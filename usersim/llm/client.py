"""LLM 客户端：OpenAI 兼容协议 + JSON 模式 + 重试。

唯一允许联网的包。密钥来自 config/llm.toml（或环境变量覆盖），禁止硬编码。
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from openai import OpenAI

from usersim.config import LLMRole, Namespace


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

    def set_log_dir(self, run_dir: Path) -> None:
        """由 Runner 指定 prompt 日志位置（仅 log_prompts=true 时生效）。"""
        if self.log_prompts:
            self._log_path = run_dir / "prompts.jsonl"

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
        for attempt in range(self.max_retries):
            try:
                resp = self.client.chat.completions.create(
                    model=self.role.model,
                    messages=messages,
                    temperature=float(self.role.temperature),
                    max_tokens=max_tokens or int(self.role.max_tokens),
                    response_format={"type": "json_object"},
                )
                content = resp.choices[0].message.content or ""
                self._log(messages, content)
                return _extract_json(content)
            except Exception as e:  # 网络错误 / 限流 / JSON 解析失败
                last_err = e
                time.sleep(min(2 ** attempt * 2, 20))
        raise LLMError(f"LLM 调用失败（重试 {self.max_retries} 次）: {last_err}")
