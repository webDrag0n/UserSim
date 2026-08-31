"""消融对照 Harness：reference v5 同模型同 prompt，但删掉跨 session 记忆。

实验语义（与 stub 的分工）：
- stub 是失能下界锚点（不调 LLM、恒定 x̂=0.5、零干预）——量程守护；
- 本件是**消融件**：与 reference 唯一的差异是记忆系统在 session 边界被清空
  （ProfileTracker 画像累积 / recent_arrangements / BookingMemory / StateTracker
  全部重置），LLM 与 prompt 完全一致。reference vs reference_nomem 的分差
  即"跨 session 记忆"的单变量贡献。

实现要点：
- session 边界检测：Runner 每开新 session 重建 history，故 obs.history≤1 即首轮；
- 画像增量在出口被剥掉（persona_belief=None）：否则 Runner 侧的 EMA 退化路径
  会替 harness 累积画像，消融就失效了（runner.py persona_hat 回退逻辑）；
- persona_belief() 恒返回 None → 落盘 None（吃画像组缺省罚，与"无记忆"语义一致）。
"""

from __future__ import annotations

from usersim.contracts import HarnessObs
from usersim.llm import LLMClient

from agents.assistant.reference.harness import ReferenceHarness
from agents.assistant.reference.harness import PROMPT_VERSION as _V5

PROMPT_VERSION = f"{_V5}-nomem"


class NoMemHarness(ReferenceHarness):
    """每个 session 边界重置全部 harness 状态的 reference v5。"""

    def __init__(self, client: LLMClient):
        super().__init__(client)
        self._saw_turn = False

    def on_turn(self, obs: HarnessObs):
        if len(obs.history) <= 1:
            if self._saw_turn:
                self._reset_memory()  # session 边界：清空跨 session 记忆
            self._saw_turn = True
        turn = super().on_turn(obs)
        # 画像记忆已删：剥掉本轮增量，阻止 Runner 侧 EMA 兜底累积
        turn.user_belief = turn.user_belief.model_copy(update={"persona_belief": None})
        return turn

    def persona_belief(self):
        """从不形成跨 session 画像（消融语义；区别于 reference 的累积快照）。"""
        return None

    def snapshot(self) -> dict:
        return {}  # 无记忆可存：续跑也不恢复（消融语义）

    def restore(self, state: dict) -> None:
        pass
