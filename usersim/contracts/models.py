"""跨组件数据契约全集。

唯一允许被所有包 import 的层。字段只加不删、不改语义；新增字段必须有默认值。
对应文档：docs/05-contracts.md
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------
# 基础模型
# ---------------------------------------------------------------


class StateVec(BaseModel):
    """用户状态向量 x ∈ [0,1]⁴（唯一写入方是 world 的结算器）。"""

    valence: float = Field(ge=0, le=1)  # 心情
    energy: float = Field(ge=0, le=1)  # 精力
    satiety: float = Field(ge=0, le=1)  # 饱腹
    stress: float = Field(ge=0, le=1)  # 压力

    def as_dict(self) -> dict[str, float]:
        return self.model_dump()


class Persona(BaseModel):
    """角色卡：seed 派生，人格/喜好冻结（不参与动力学，参与画像精度评估）。"""

    name: str
    archetype: str
    big5: dict[str, int]  # 开放性/尽责性/外向性/宜人性/神经质, 0-100
    likes: str
    routine: str
    x0: StateVec
    income_per_slot: int = 200  # 职业收入（每个工作时段）


class Event(BaseModel):
    """事件六字段结构：类型/起止/地点/目标/效果/进度。"""

    id: str
    kind: Literal["template", "disturbance", "recovery", "series"]
    name: str
    start_slot: int  # t_logical 起点
    span_slots: int
    location: str
    goal: str
    effect: dict = {}  # Δx：数值（按 span 摊销）或 {"pull": [目标, 速率]}（拉向准稳态，不摊销）
    cost: float = 0.0  # 金钱消耗（在首个活跃时段扣除）
    income: float = 0.0  # 金钱收入（如加班）
    progress: float = 0.0
    caused_by_session_id: str | None = None  # 因果链
    series_id: str | None = None  # 所属系列事件
    note: str = ""


class Series(BaseModel):
    """系列事件实例：跨越多天的剧情块（旅行/出差/休假/备考）。"""

    id: str
    type: str
    name: str
    icon: str = ""
    start_day: int
    end_day: int


class ToolCall(BaseModel):
    name: str
    args: dict = {}


class ToolResult(BaseModel):
    name: str
    ok: bool
    payload: dict = {}


# ---------------------------------------------------------------
# 世界 ↔ Runner 消息
# ---------------------------------------------------------------


class EventContext(BaseModel):
    """world → Runner：一个时段的上下文（推进前的快照）。"""

    t_logical: int
    day: int
    slot: int
    slot_name: str
    active_events: list[Event] = []
    assist_prompt: str | None = None  # 助手介入点提示
    schedule_view: list[Event] = []  # 可见日程（未来事件）


class SlotSettlement(BaseModel):
    """world → 日志：一次状态推进的完整结算单。"""

    t_logical: int
    x_before: StateVec
    x_after: StateVec
    natural_drift: dict[str, float] = {}
    event_effects: dict[str, float] = {}
    control_effects: dict[str, float] = {}
    active_event_ids: list[str] = []
    money_before: float = 0.0
    money_after: float = 0.0
    active_series: str | None = None  # 当前活跃的系列事件名


# ---------------------------------------------------------------
# Agent 侧消息
# ---------------------------------------------------------------


class UserContext(BaseModel):
    """Runner → user_agent。注意：故意不含原始数值 x（状态-表达解耦）。"""

    persona: Persona
    felt_state: str  # world 规则翻译器产出的语义化状态摘要
    active_events: list[Event] = []
    assist_prompt: str | None = None
    schedule_view: list[Event] = []
    dialogue_history: list[TurnRecord] = []


class UserAction(BaseModel):
    """user_agent → Runner。"""

    say: str
    tool_calls: list[ToolCall] = []  # open_session / close_session / request_assistant
    end_session: bool = False


class UserBelief(BaseModel):
    """助手对用户的估计（观测器输出），每轮必填。"""

    valence: float = Field(ge=0, le=1)
    energy: float = Field(ge=0, le=1)
    satiety: float = Field(ge=0, le=1)
    stress: float = Field(ge=0, le=1)
    persona_notes: str = ""  # 画像笔记（冻结维度评估素材）

    def to_statevec(self) -> StateVec:
        return StateVec(valence=self.valence, energy=self.energy, satiety=self.satiety, stress=self.stress)


class AssistantTurn(BaseModel):
    """assistant → Runner（结构化输出 schema 直接下发给 LLM）。"""

    reply: str
    user_belief: UserBelief
    tool_calls: list[ToolCall] = []  # view_event_todos / add_event_todo / set_reminder


# ---------------------------------------------------------------
# 日志模型（append-only JSONL）
# ---------------------------------------------------------------


class TurnRecord(BaseModel):
    """turns.jsonl 一行。评估器的主要输入。"""

    run_id: str
    t_logical: int
    session_id: str | None = None
    turn_id: int
    speaker: Literal["user", "assistant", "system"]
    text: str
    tool_calls: list[ToolCall] = []
    tool_results: list[ToolResult] = []
    x_true: StateVec  # world 提供（对用户 LLM 不可见）
    x_hat: StateVec | None = None  # assistant 提供
    contract_violation: str | None = None
    degraded: bool = False


class RunMeta(BaseModel):
    """meta.json：一次 run 的完整快照（可复现性凭证）。"""

    run_id: str
    seed: int
    started_at: str
    days: int
    mode: Literal["replay", "live"] = "replay"
    assistant_quality: str | None = None  # replay 模式的档位
    config_hash: str
    persona: Persona
    llm_roles: dict = {}  # 各角色 provider/model（不含密钥）


UserContext.model_rebuild()
