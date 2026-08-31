"""standard 实现包：标准 LLM 用户（LLM 意图规划 + memory + 表演），demo 默认用户。

框架（usersim.agents.client）按 profiles/standard.toml（type=package）导入本包，
调用 create(client, behavior) 得到 agent 接口的请求处理函数。
"""

from agents.user.standard.agent import DemoUserAgent

__all__ = ["DemoUserAgent", "create"]


def create(client, behavior: dict | None = None):
    """构造请求处理函数（behavior 来自 profiles/standard.toml 的 [behavior] 节）。"""
    behavior = behavior or {}
    capacity = int(behavior.get("memory_capacity", 8))
    return DemoUserAgent(client, memory_capacity=capacity).handle
