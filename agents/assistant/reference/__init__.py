"""reference 实现包：naive memory + 每轮必填 user_belief 的参考 Harness（benchmark 及格线）。

框架（usersim.agents.registry）按 profiles/reference.toml（type=package）导入本包，
调用 create(client) 构造 Harness。
"""

from agents.assistant.reference.harness import PROMPT_VERSION, ReferenceHarness

__all__ = ["PROMPT_VERSION", "ReferenceHarness", "create"]


def create(client=None) -> ReferenceHarness:
    return ReferenceHarness(client)
