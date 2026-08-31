"""LLM 客户端：OpenAI 兼容协议 + JSON 模式 + 重试。

唯一允许联网的包。密钥来自 config/llm.toml（或环境变量覆盖），禁止硬编码。
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path

from openai import OpenAI

from usersim.config import LLMRole, Namespace

# reported_models.json 的写锁：user/assistant 两个 demo agent 线程共享同一 run_dir
_REPORTED_LOCK = threading.Lock()

# 进程级 LLM 并发上限（惰性初始化，多 LLMClient 实例共享单例）：
# bench 默认全并发启动 episode，真正打到 provider 的并发由这里按
# llm.toml [runtime].concurrency 限流
_LLM_SEM: threading.BoundedSemaphore | None = None
_LLM_SEM_LOCK = threading.Lock()


def _llm_semaphore() -> threading.BoundedSemaphore:
    global _LLM_SEM
    if _LLM_SEM is None:
        with _LLM_SEM_LOCK:
            if _LLM_SEM is None:
                from usersim.config import load_llm_runtime
                try:
                    limit = int(load_llm_runtime().get("concurrency", 8))
                except Exception:  # noqa: BLE001 — 配置缺失时退回默认
                    limit = 8
                _LLM_SEM = threading.BoundedSemaphore(max(1, limit))
    return _LLM_SEM


class LLMError(Exception):
    pass


def _extract_json(text: str) -> dict:
    """容错提取：优先直接解析，其次抓第一个 {...} 块。"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


class LLMClient:
    def __init__(self, role: LLMRole, runtime: Namespace):
        self.role = role
        self.client = OpenAI(
            base_url=role.base_url,
            api_key=role.api_key,
            timeout=float(runtime.get("timeout_s", 60)),
        )
        self.max_retries = int(runtime.get("max_retries", 3))
        # [runtime].log_prompts：调试用完整 prompt 落盘（体积大，默认关）
        self.log_prompts = bool(runtime.get("log_prompts", False))
        self._log_path: Path | None = None
        self._run_dir: Path | None = None
        # provider 实际应答的模型版本（滚动别名如 deepseek-chat 的真实落点），用于溯源
        self.reported_models: set[str] = set()

    def set_log_dir(self, run_dir: Path) -> None:
        """由 Runner 指定 run 目录：reported_models.json 总是落盘（溯源凭证），
        prompt 日志仍仅 log_prompts=true 时写。"""
        self._run_dir = run_dir
        if self.log_prompts:
            self._log_path = run_dir / "prompts.jsonl"

    def _record_reported_model(self, resp) -> None:
        """捕获响应里的实际模型名/指纹，与配置名不同也照记（provider 端漂移不进配置 hash）。"""
        model = getattr(resp, "model", None)
        fingerprint = getattr(resp, "system_fingerprint", None)
        changed = False
        for v in (model, fingerprint):
            if v and v not in self.reported_models:
                self.reported_models.add(v)
                changed = True
        if changed and self._run_dir is not None:
            try:
                path = self._run_dir / "reported_models.json"
                with _REPORTED_LOCK:  # 两个 agent 线程共享该文件，读-改-写需互斥
                    data = {}
                    if path.exists():
                        try:
                            data = json.loads(path.read_text(encoding="utf-8"))
                        except json.JSONDecodeError:
                            data = {}
                    key = f"{getattr(self.role, 'provider', '?')}/{self.role.model}"
                    entry = data.get(key, {"provider": getattr(self.role, "provider", "?"),
                                           "configured_model": self.role.model,
                                           "reported": []})
                    entry["reported"] = sorted(set(entry["reported"]) | self.reported_models)
                    data[key] = entry
                    path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
            except OSError:
                pass  # 溯源落盘失败不阻断 episode

    def _log(self, messages: list[dict], content: str) -> None:
        if not self.log_prompts or self._log_path is None:
            return
        rec = {
            "ts": time.time(),
            "role": getattr(self.role, "provider", "?"),
            "model": self.role.model,
            "messages": messages,
            "response": content,
        }
        with self._log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def chat_json(self, messages: list[dict], max_tokens: int | None = None) -> dict:
        """JSON 模式调用，带指数退避重试；返回解析后的 dict。"""
        last_err: Exception | None = None
        budget = max_tokens or int(self.role.max_tokens)
        sem = _llm_semaphore()
        for attempt in range(self.max_retries):
            try:
                with sem:  # 进程级 LLM 并发上限：只圈 HTTP 请求，退避等待不占额度
                    resp = self.client.chat.completions.create(
                        model=self.role.model,
                        messages=messages,
                        temperature=float(self.role.temperature),
                        max_tokens=budget,
                        response_format={"type": "json_object"},
                    )
                content = resp.choices[0].message.content or ""
                if not content.strip():
                    # 推理模型（如 deepseek-v4-flash）会把 max_tokens 预算耗在
                    # reasoning_content 上，content 返回空串——预算翻倍重试（封顶 16k）
                    budget = min(budget * 2, 16384)
                    raise ValueError(f"空响应（推理预算耗尽？），max_tokens 提升至 {budget} 重试")
                self._record_reported_model(resp)
                self._log(messages, content)
                return _extract_json(content)
            except Exception as e:  # 网络错误 / 限流 / JSON 解析失败 / 空响应
                last_err = e
                time.sleep(min(2 ** attempt * 2, 20))
        raise LLMError(f"LLM 调用失败（重试 {self.max_retries} 次）: {last_err}")
