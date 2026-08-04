"""assistant 包：助手 Agent 抽象与参考 Harness 实现。"""

from usersim.agents.assistant.base import Harness
from usersim.agents.assistant.reference import ReferenceHarness
from usersim.agents.assistant.registry import DEFAULT_HARNESS, REGISTRY, available, resolve
from usersim.agents.assistant.stub import StubHarness

__all__ = [
    "Harness",
    "ReferenceHarness",
    "StubHarness",
    "REGISTRY",
    "DEFAULT_HARNESS",
    "resolve",
    "available",
]
