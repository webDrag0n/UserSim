"""Agent 接入 wire 协议：benchmark 核心与 agent（demo / 外部）之间的请求-响应契约。

外部 agent（OpenClaw、Hermes 等）通过 HTTP 轮询接入（见 skills/usersim-*/SKILL.md）：
- GET  /api/agent/pending?role=...&timeout=...  → AgentRequest（长轮询，无请求时 204）
- POST /api/agent/respond                        → AgentResponse
- GET  /api/agent/skill/{role}                   → 接入 skill 原文

`agent_state` 是 agent 侧的不透明状态 blob（记忆 / harness 快照）：每个请求携带
当前值，agent 可在响应里回传更新值，benchmark 负责随 run 存档并在续跑时回灌。
因此外部 agent 对 benchmark 可以保持无状态（也可自行按 run_id 维护记忆）。

字段只加不删、不改语义；新增字段必须有默认值（同 contracts 规约）。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from usersim.contracts.models import (
    AssistantTurn,
    DialogueTurn,
    PersonaBelief,
    UserAction,
    UserContext,
)

# ---------------------------------------------------------------
# 用户侧意图（wire 类型；规则版规划器已废除，意图由用户侧 LLM 生成）
# ---------------------------------------------------------------

INTENT_EAT = "eat"                # 进餐
INTENT_SOCIAL = "social"          # 社交
INTENT_STIMULATE = "stimulate"    # 寻求刺激/娱乐
INTENT_RECOVER = "recover"        # 休息恢复
INTENT_SLEEP = "sleep"            # 睡眠
INTENT_ACHIEVE = "achieve"        # 成就/学习
INTENT_CHAT = "chat"              # 闲聊/分享/吐槽（无恢复目标，非事务性）
INTENT_EMERGENCY = "emergency"    # 世界注入的紧急意图（高压/扰动）


class Intent(BaseModel):
    """用户侧意图规划结果（plan_slot 的输出单元）。"""

    type: str
    priority: float = 0.0
    event_name: str = ""   # 匹配到的事件名（可空）
    location: str = ""
    description: str = ""


# ---------------------------------------------------------------
# 请求类型与 typed payload（payload 在 AgentRequest.payload 中以 dict 承载）
# ---------------------------------------------------------------


class PlanSlotRequest(BaseModel):
    """user/plan_slot：一个 slot 的规划输入（用户=本人，可看到自己的需求数值）。

    状态-表达解耦只约束"用户 LLM 的台词"（felt_state 语义摘要），规划器作为
    用户的"潜意识"本就按真实驱动力工作——这些数值只流向用户侧，永不进助手侧。

    规则版规划器废除后，意图由用户侧 LLM 生成：demo 实现只用 `context`
    （felt_state 语义摘要 + 人格 + 记忆，不含数值），数值字段保留给
    规则/混合实现与外部用户 agent。
    """

    urges: dict[str, float]        # {hunger, social, stimulation, achievement}
    stress: float = Field(ge=0, le=1)
    energy: float = Field(ge=0, le=1)
    slot: int                      # 当前时段序号（0=上午 …）
    day: int = 0
    money: float = 0.0
    event_library: list[dict] = []  # 个性化事件库
    assist_prompt: str | None = None  # 世界注入的紧急介入点提示（→ emergency 意图）
    max_intents: int = 5           # 本 slot 的 session 容量上限
    context: UserContext | None = None  # LLM 规划的语义输入（只加不删；规则实现可忽略）


class PlanSlotResult(BaseModel):
    intents: list[Intent] = []     # 0~max_intents 个，按优先级排序


class DecideOpenRequest(BaseModel):
    """user/decide_open：带着某个意图，决定是否真的开 session。"""

    context: UserContext
    intent: Intent


class DecideOpenResult(BaseModel):
    open: bool
    reason: str = ""


class SpeakRequest(BaseModel):
    """user/speak：session 内生成一轮发言。"""

    context: UserContext
    history: list[DialogueTurn] = []  # 本 session 已有的对话（不含本轮）
    intent_description: str = ""      # 意图描述（可含 runner 注入的收尾提示）


# speak 的响应载荷即 contracts.UserAction（say / end_session / tool_calls）；
# on_turn 的响应载荷即 contracts.AssistantTurn（reply / user_belief / tool_calls）。


class SessionClosedNotice(BaseModel):
    """user/session_closed：session 结束通知（agent 据此更新自己的记忆）。"""

    session_id: str
    intent_type: str
    turns: int = 0
    day: int = 0
    # 本 session 实际落单的事件名（runner 从工具执行结果收集，只加不删）：
    # 用户记忆需要"具体做过什么"而不是只有意图标签——否则 LLM 不知道自己刚去过
    # livehouse，下周又提同一个安排（真人会腻，R5 实测重复任务根因）
    activities: list[str] = []


# ---------------------------------------------------------------
# 信封
# ---------------------------------------------------------------


class AgentRequest(BaseModel):
    """benchmark → agent 的请求信封（GET /api/agent/pending 的响应体）。"""

    request_id: str
    run_id: str
    role: Literal["user", "assistant"]
    type: str                      # plan_slot / decide_open / speak / session_closed / on_turn
    payload: dict = {}             # 上述 typed payload 的 dict 形态
    agent_state: dict = {}         # agent 侧不透明状态（续跑回灌 / 跨请求记忆）


class AgentResponse(BaseModel):
    """agent → benchmark 的响应信封（POST /api/agent/respond 的请求体）。"""

    request_id: str
    result: dict = {}              # typed result 的 dict 形态（PlanSlotResult / UserAction / AssistantTurn …）
    agent_state: dict | None = None   # 非空时覆盖该 (run_id, role) 的存档状态
    persona_hat: PersonaBelief | None = None  # assistant/on_turn 专用：累积画像快照
    error: str | None = None       # agent 侧处理失败（"TypeName: message"），benchmark 记违约/降级


# UserContext 内引用 TurnRecord，确保前向引用已解析
PlanSlotRequest.model_rebuild()
DecideOpenRequest.model_rebuild()
SpeakRequest.model_rebuild()

__all__ = [
    "INTENT_EAT", "INTENT_SOCIAL", "INTENT_STIMULATE", "INTENT_RECOVER",
    "INTENT_SLEEP", "INTENT_ACHIEVE", "INTENT_CHAT", "INTENT_EMERGENCY",
    "Intent",
    "PlanSlotRequest", "PlanSlotResult",
    "DecideOpenRequest", "DecideOpenResult",
    "SpeakRequest", "SessionClosedNotice",
    "AgentRequest", "AgentResponse",
    # 复用的载荷模型（便于接入方从一处取齐）
    "AssistantTurn", "UserAction", "UserContext", "DialogueTurn",
]
