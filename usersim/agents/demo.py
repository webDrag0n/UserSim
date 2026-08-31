"""demo 助手 Agent：把 registry 里的 Harness（reference / stub）经统一 agent 接口接入。

它是"被测助手如何接入 benchmark"的第一方参考实现（skills/usersim-assistant/SKILL.md）：
- 输入即 `HarnessObs`（被测件可见信息的全部）；
- 输出即 `AssistantTurn`，外加可选的累积画像快照 `persona_hat`；
- harness 的 snapshot()/restore() 经 agent_state 对接 run 存档与续跑。

persona_hat 语义与重构前 runner._persona_hat 完全一致：
Harness 实现 persona_belief() 就用它的累积快照（可为 None = 不做画像）；
未实现则退化为"本轮 user_belief.persona_belief 增量"。
"""

from __future__ import annotations

from usersim.agents.base import Harness
from usersim.contracts import HarnessObs, PersonaBelief
from usersim.contracts.agent_api import AgentRequest, AgentResponse


class DemoAssistantAgent:
    """demo 助手 Agent（包装一个 Harness 协议实现）。"""

    def __init__(self, harness: Harness):
        self.harness = harness
        self._loaded_run: str | None = None

    def _maybe_restore(self, req: AgentRequest) -> None:
        """新 run / 进程重启后的首个请求：从 agent_state 恢复 harness 记忆。"""
        if self._loaded_run == req.run_id:
            return
        self._loaded_run = req.run_id
        if req.agent_state:
            self.harness.restore(req.agent_state)

    def handle(self, req: AgentRequest) -> AgentResponse:
        if req.type != "on_turn":
            raise ValueError(f"demo assistant 未知请求类型 {req.type!r}")
        self._maybe_restore(req)
        obs = HarnessObs(**req.payload)
        turn = self.harness.on_turn(obs)  # 抛错由 client 包装为 error 响应，runner 记违约

        getter = getattr(self.harness, "persona_belief", None)
        if callable(getter):
            try:
                hat = getter()  # 可为 None（如 stub：从不形成画像）
            except Exception:  # noqa: BLE001 — 被测件的 bug 不能中断 episode
                hat = None
        else:
            delta = turn.user_belief.persona_belief
            hat = PersonaBelief(**delta.model_dump()) if delta is not None else None

        return AgentResponse(
            request_id=req.request_id,
            result=turn.model_dump(),
            agent_state=self.harness.snapshot(),
            persona_hat=hat,
        )
