"""stub 实现包：失能对照（恒定 x̂=0.5、零干预、零画像，benchmark 下界锚点）。

框架（usersim.agents.registry）按 profiles/stub.toml（type=package）导入本包，
调用 create(client) 构造 Harness。
"""

from agents.assistant.stub.stub import StubHarness

__all__ = ["StubHarness", "create"]


def create(client=None) -> StubHarness:
    return StubHarness(client)
