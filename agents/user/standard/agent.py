"""demo 用户 Agent：经统一 agent 接口（broker / HTTP）接入的用户模拟器。

组合 LLM 意图规划（plan，prompt v3）+ UserMemory（跨 session 记忆）+ LLMUserAgent（表演），
处理 plan_slot / decide_open / speak / session_closed 四种请求。它是"通过同一
接口与 skill 接入"的参考实现——外部用户 agent 只需实现同样的请求语义
（skills/usersim-user/SKILL.md）。

记忆存于 agent_state（benchmark 随 run 存档、续跑回灌），因此 demo 进程重启不丢记忆。
意图与表达完全由 LLM 驱动：plan_slot 契约里的 urges/money 等数值不进 prompt
（状态-表达解耦）；emergency 意图注入与 max_intents 截断与重构前 runner 内联逻辑一致。

plan_slot 契约可携带 UserContext（context 字段，只加不删）：demo 优先使用请求
携带的新鲜 context，缺省时回退到最近一次 decide_open / speak 的缓存（至多才一个
slot 旧）；run 的首个 slot 无缓存，plan 退化为无人格的通用规划。
"""

from __future__ import annotations

from agents.user.standard.llm_user import LLMUserAgent
from agents.user.standard.memory import UserMemory
from usersim.contracts.agent_api import (
    INTENT_EMERGENCY,
    INTENT_RECOVER,
    AgentRequest,
    AgentResponse,
    DecideOpenRequest,
    Intent,
    PlanSlotRequest,
    PlanSlotResult,
    SessionClosedNotice,
    SpeakRequest,
    UserAction,
)
from usersim.llm import LLMClient

# speak 时按意图表达模式拼入 intent_description 的指导前缀（契约无 mode 字段，demo 内部传递）
_MODE_PREFIX = {
    "explicit": "你想做的事：{want}（可以直接说想做什么，但具体地点、价位让助手想办法）",
    "vague": "你的感受：{want}（只说感受和需求，让助手帮你想办法）",
}


class DemoUserAgent:
    """demo 用户模拟 Agent（LLM 意图规划 + memory + LLM 表演）。"""

    def __init__(self, client: LLMClient, memory_capacity: int = 8):
        self.user = LLMUserAgent(client)
        self.memory_capacity = memory_capacity
        self.memory = UserMemory(capacity=memory_capacity)
        self._loaded_run: str | None = None
        self._last_ctx = None            # 最近一次 decide_open/speak 的 UserContext（供 plan）
        self._want_modes: dict[str, str] = {}  # 本 slot 的 {want: mode}（plan → speak 传递）

    def _maybe_restore(self, req: AgentRequest) -> None:
        """新 run / 进程重启后的首个请求：从 agent_state 回灌记忆。"""
        if self._loaded_run == req.run_id:
            return
        self._loaded_run = req.run_id
        self._last_ctx = None
        self._want_modes = {}
        if req.agent_state:
            self.memory = UserMemory.from_dict(req.agent_state.get("memory", {}),
                                               capacity=self.memory_capacity)

    def handle(self, req: AgentRequest) -> AgentResponse:
        self._maybe_restore(req)
        if req.type == "plan_slot":
            result = self._plan_slot(PlanSlotRequest(**req.payload))
        elif req.type == "decide_open":
            result = self._decide_open(DecideOpenRequest(**req.payload))
        elif req.type == "speak":
            result = self._speak(SpeakRequest(**req.payload))
        elif req.type == "session_closed":
            result = self._session_closed(SessionClosedNotice(**req.payload))
        else:
            raise ValueError(f"demo user 未知请求类型 {req.type!r}")
        return AgentResponse(
            request_id=req.request_id,
            result=result,
            agent_state={"memory": self.memory.to_dict()},
        )

    # ---- 四类请求 ----

    def _plan_slot(self, p: PlanSlotRequest) -> dict:
        # 优先用请求携带的新鲜 context（runner 每 slot 组装），缺省回退缓存
        ctx = p.context or self._last_ctx
        planned = self.user.plan(p, ctx=ctx,
                                 memory_block=self.memory.prompt_block())
        intents = []
        self._want_modes = {}
        for i, item in enumerate(planned):
            intents.append(Intent(type=item["type"], priority=1.0 - 0.2 * i,
                                  description=item["want"]))
            self._want_modes[item["want"]] = item["mode"]
        # 世界补充触发（扰动/高压注入紧急意图）——与重构前 runner 内联逻辑一致
        if p.assist_prompt:
            has_emergency = any(i.type in (INTENT_RECOVER, INTENT_EMERGENCY) for i in intents)
            if not has_emergency and len(intents) < p.max_intents:
                intents.insert(0, Intent(
                    type=INTENT_EMERGENCY, priority=1.0, description=p.assist_prompt,
                ))
        intents = intents[: p.max_intents]
        return PlanSlotResult(intents=intents).model_dump()

    def _decide_open(self, p: DecideOpenRequest) -> dict:
        self._last_ctx = p.context
        open_it = self.user.decide_open(p.context, memory_block=self.memory.prompt_block(),
                                        want=p.intent.description)
        return {"open": bool(open_it)}

    def _speak(self, p: SpeakRequest) -> dict:
        self._last_ctx = p.context
        intent_description = p.intent_description
        if intent_description:
            # runner 组装的是 description + "\n" + 收尾 hint——拆出 want 查 mode，拼上指导前缀
            want, sep, rest = intent_description.partition("\n")
            mode = self._want_modes.get(want.strip())
            prefix = _MODE_PREFIX.get(mode or "", "").format(want=want) if mode else ""
            if prefix:
                intent_description = prefix + (f"\n{rest}" if sep else "")
        ua = self.user.speak(
            p.context, p.history,
            memory_block=self.memory.prompt_block(),
            intent_description=intent_description,
        )
        return UserAction(say=ua["say"], end_session=ua["end_session"]).model_dump()

    def _session_closed(self, n: SessionClosedNotice) -> dict:
        self.memory.add(n.session_id, n.intent_type, n.turns, day=n.day,
                        activities=n.activities)
        return {"ack": True}
