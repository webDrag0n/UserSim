"""Harness 协议：被测助手的唯一接入面（docs/03-assistant-agent.md 第 5 节）。

助手 = Model（LLM）+ Harness（记忆结构 / 用户建模 / 工具执行 / 输出组装）。
评测矩阵：
  E1（测 Model）  ：Harness 固定 reference，换 config/llm.toml 的 provider/model；
  E2（测 Harness）：实现本协议，Model 固定为参考 provider。

被测件只能看到 HarnessObs，不得读取 runs/ 日志、不得访问用户侧 prompt、
不得 import world/evaluator——依赖规则由 tests/test_dependency_rules.py 强制。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from usersim.contracts import AssistantTurn, HarnessObs, PersonaBelief


@runtime_checkable
class Harness(Protocol):
    """被测 Harness 协议。实现者需可用 `Harness(client)` 构造。"""

    def on_turn(self, obs: HarnessObs) -> AssistantTurn:
        """产出一轮回复。必须包含 user_belief（缺字段由 Runner 记契约违约）。"""
        ...

    def persona_belief(self) -> PersonaBelief | None:
        """（可选）当前累积的人格/喜好信念，由 Runner 每轮落盘为 `persona_hat`。

        未实现时 Runner 退化为"只用本轮 user_belief.persona_belief 增量"——
        因此老的 Harness 不实现本方法也能跑，只是画像学习曲线会更抖。
        返回 None 表示"本 Harness 不做冻结维度画像"（如 stub 下界锚点）。
        """
        ...

    def snapshot(self) -> dict:
        """导出 Harness 内部记忆，供续跑恢复。无状态实现可返回 {}。"""
        ...

    def restore(self, state: dict) -> None:
        """从 snapshot() 的产物恢复内部记忆。"""
        ...
