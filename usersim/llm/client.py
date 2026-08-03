"""LLM 客户端：OpenAI 兼容协议 + JSON 模式 + 重试。

唯一允许联网的包。密钥来自 config/llm.toml（或环境变量覆盖），禁止硬编码。
"""

from __future__ import annotations

import json
import re
import time

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
                return _extract_json(content)
            except Exception as e:  # 网络错误 / 限流 / JSON 解析失败
                last_err = e
                time.sleep(min(2 ** attempt * 2, 20))
        raise LLMError(f"LLM 调用失败（重试 {self.max_retries} 次）: {last_err}")
