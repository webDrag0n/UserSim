"""LLMClient.chat_json 空响应重试（推理模型预算耗尽）回归测试（0 token）。"""

from __future__ import annotations

from types import SimpleNamespace

from usersim.config import LLMRole, Namespace
from usersim.llm.client import LLMClient


class _StubCompletions:
    """第一次返回空 content（模拟推理模型耗尽预算），第二次返回合法 JSON。"""

    def __init__(self) -> None:
        self.budgets: list[int] = []

    def create(self, model, messages, temperature, max_tokens, response_format):
        self.budgets.append(max_tokens)
        content = "" if len(self.budgets) == 1 else '{"say": "好"}'
        msg = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                               model=model, system_fingerprint=None)


def _client(stub: _StubCompletions) -> LLMClient:
    role = LLMRole({"provider": "stub", "base_url": "http://127.0.0.1:9", "api_key": "k",
                    "model": "stub-model", "temperature": 0.5, "max_tokens": 4096})
    c = LLMClient(role, Namespace({"timeout_s": 1, "max_retries": 3, "log_prompts": False}))
    c.client = SimpleNamespace(chat=SimpleNamespace(completions=stub))
    return c


def test_empty_content_retries_with_doubled_budget(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)  # 退避不等
    stub = _StubCompletions()
    out = _client(stub).chat_json([{"role": "user", "content": "hi"}])
    assert out == {"say": "好"}
    assert stub.budgets == [4096, 8192], "空响应应触发预算翻倍重试"
