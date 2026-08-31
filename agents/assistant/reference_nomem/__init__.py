"""reference_nomem 实现包：reference v5 减去跨 session 记忆的消融对照。

框架（usersim.agents.registry）按 profiles/reference_nomem.toml（type=package）
导入本包，调用 create(client) 构造 Harness。
"""

from agents.assistant.reference_nomem.harness import PROMPT_VERSION, NoMemHarness

__all__ = ["PROMPT_VERSION", "NoMemHarness", "create"]


def create(client=None) -> NoMemHarness:
    return NoMemHarness(client)
