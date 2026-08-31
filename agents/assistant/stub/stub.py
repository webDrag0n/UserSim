"""失能对照 Harness：恒定估计 x̂=0.5、从不安排任何恢复事件。

用途：benchmark 的下界锚点。一个合格的评估器必须把它判为 diverged——
若它也能拿到好分数，说明指标或世界失去了分辨力（量程守护的反向验证）。
不调用 LLM，因此可在无 API key 的环境下验证 live 编排链路。
"""

from __future__ import annotations

from usersim.contracts import AssistantTurn, HarnessObs, UserBelief

PROMPT_VERSION = "stub"


class StubHarness:
    """恒定估计、零干预的失能助手（benchmark 下界）。"""

    def __init__(self, client=None):
        self.client = client  # 刻意不用
        self.n_turns = 0

    def on_turn(self, obs: HarnessObs) -> AssistantTurn:
        self.n_turns += 1
        return AssistantTurn(
            reply="嗯嗯，我知道了。",
            user_belief=UserBelief(
                valence=0.5, energy=0.5, satiety=0.5, stress=0.5,
                persona_notes="（stub 不建立画像）",
                persona_belief=None,  # 刻意不估计人格/喜好：画像精度的下界锚点
            ),
            tool_calls=[],
        )

    def persona_belief(self) -> None:
        """stub 从不形成画像——Runner 因此落盘 None（区别于"估计了但估错"）。"""
        return None

    def snapshot(self) -> dict:
        return {"n_turns": self.n_turns}

    def restore(self, state: dict) -> None:
        self.n_turns = int(state.get("n_turns", 0))
