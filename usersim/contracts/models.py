"""跨组件数据契约全集。

唯一允许被所有包 import 的层。字段只加不删、不改语义；新增字段必须有默认值。
对应文档：docs/05-contracts.md
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from usersim.contracts.persona import (
    FACET_KEYS,
    PREF_CATEGORIES,
    domains_from_facets,
)

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


class Preferences(BaseModel):
    """结构化喜好（冻结特质）：类目偏好 + 明确的爱憎 + 打扰容忍度。

    与 world/catalog 的类目对齐（contracts.persona.PREF_CATEGORIES），因此
    "助手估计得多准"可以逐类目量化——这是 likes 自由文本做不到的。
    """

    categories: dict[str, float] = {}  # 类目 → 偏好分 ∈ [-1,1]
    loves: list[str] = []              # 明确偏爱的具体事物（"寿喜烧"/"爵士乐"）
    hates: list[str] = []              # 明确反感的（"临时邀约"/"油腻食物"）
    interruption_tolerance: float = Field(default=0.5, ge=0, le=1)  # 越低越讨厌计划被打断
    planning_style: str = "看心情"      # 提前规划 | 随遇而安 | 看心情
    social_recharge: str = "独处"       # 独处 | 找人 —— 状态差时怎么回血

    def pref_of(self, category: str) -> float:
        return float(self.categories.get(category, 0.0))


class Persona(BaseModel):
    """角色卡：seed 派生，人格/喜好**冻结**（frozen 字段禁止运行期改写）。

    人格现在是 30 个 facet 的完整大五（contracts.persona.FACET_KEYS）：
    - world 用 facet 粒度调节动力学（比域粒度更细的行为差异）；
    - 用户 Agent 据此表演；
    - 助手估计它，evaluator 逐 facet 比对算画像精度。

    `big5`（5 域）保留为 facets 的聚合视图，旧存档/旧日志因此仍可读。
    """

    name: str
    archetype: str
    big5: dict[str, int] = Field(frozen=True)  # 5 域聚合分, 0-100（由 facets 派生）
    facets: dict[str, int] = Field(default_factory=dict, frozen=True)  # 30 facet, 0-100
    likes: str = Field(frozen=True)  # 自陈述喜好（prompt 表演用）
    prefs: Preferences = Field(default_factory=Preferences, frozen=True)  # 结构化喜好
    routine: str
    x0: StateVec
    income_per_slot: int = 200  # 职业收入（每个工作时段）
    event_library: list[dict] = Field(default_factory=list)  # 个性化事件库（不冻结，可由 world 运行时填充）

    def facet(self, key: str, default: int = 50) -> int:
        """读一个人格分：facet 优先、缺失回退域分（旧存档兼容）。"""
        from usersim.contracts.persona import trait

        return trait(self.big5, self.facets, key, default)

    def domains(self) -> dict[str, int]:
        """5 域分：有 facets 时由其聚合，否则用 big5 原值。"""
        return domains_from_facets(self.facets) if self.facets else dict(self.big5)


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
    replaces_meal: bool = False  # 餐饮场所事件：活跃时段抑制当日模板"三餐"在同 slot 的效果


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
    weather: str | None = None  # 当前天气（晴/多云/阴/小雨/暴雨）
    satiation_note: str | None = None  # 餍足提示：最近重复执行的恢复动作已腻（习惯化权重过低）
    utility_menu: list[str] = []  # 各恢复活动的边际效用档位（R7，只加不删；语义行，无数值）


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
    # 时钟刻度：评估器据此换算天，不再假设固定为 4（旧日志缺省 4 保持兼容）
    slots_per_day: int = 4
    weather: str | None = None  # 当前天气


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
    weather: str | None = None  # 当前天气
    satiation_note: str | None = None  # 餍足提示（world 裁决，供用户表达"吃腻了"）
    utility_menu: list[str] = []  # 各活动边际效用档位（R7：用户规划/拒绝重复安排的依据）


class UserAction(BaseModel):
    """user_agent → Runner。"""

    say: str
    tool_calls: list[ToolCall] = []  # open_session / close_session / request_assistant
    end_session: bool = False


class PersonaBelief(BaseModel):
    """助手对用户**冻结维度**（人格 + 喜好）的估计快照。

    与 StateVec 的估计不同，这是**累积**的：Harness 每轮只需给出本轮有新证据的
    增量（PersonaBeliefDelta），由 Harness 合并进这里再整体落盘。未被估计过的
    facet 直接缺席（不填 50 占位）——evaluator 才能区分"猜错了"与"还没看出来"。
    """

    facets: dict[str, int] = {}          # facet key → 0-100 估计
    categories: dict[str, float] = {}    # 偏好类目 → [-1,1] 估计
    loves: list[str] = []
    hates: list[str] = []
    interruption_tolerance: float | None = None
    planning_style: str | None = None
    social_recharge: str | None = None
    confidence: float = Field(default=0.0, ge=0, le=1)  # 助手自评置信度
    notes: str = ""                       # 自由画像笔记（沿用 persona_notes 语义）

    def coverage(self) -> float:
        from usersim.contracts.persona import facet_coverage

        return facet_coverage(self.facets)


class PersonaBeliefDelta(BaseModel):
    """Harness 每轮输出的画像**增量**（只填本轮真正有证据的项）。

    刻意与 PersonaBelief 同形但全部可空：LLM 每轮重写 30 个 facet 既费 token
    又会随机抖动，增量式更贴近"从对话里一点点认识一个人"。
    """

    facets: dict[str, int] = {}
    categories: dict[str, float] = {}
    loves: list[str] = []
    hates: list[str] = []
    interruption_tolerance: float | None = None
    planning_style: str | None = None
    social_recharge: str | None = None
    confidence: float | None = None
    notes: str = ""


# ---------------------------------------------------------------
# 画像增量合并（共享纯函数：agents.ProfileTracker 与 Runner 退化路径同一语义）
# ---------------------------------------------------------------

# 新证据权重：0.6 表示"以新观察为主，但保留 40% 已有认识"。
# 偏高是有意的——助手应该敢于修正错误的第一印象（docs/03 的锚定问题）。
PERSONA_BLEND_NEW = 0.6
PERSONA_MAX_TAGS = 12  # loves/hates 各自的上限（防止 Harness 无节制堆词刷命中率）


def _blend(old: float, new: float, w: float = PERSONA_BLEND_NEW) -> float:
    return old * (1.0 - w) + new * w


def merge_persona_delta(base: PersonaBelief, delta: PersonaBeliefDelta) -> PersonaBelief:
    """把一轮画像增量合并进累积快照（EMA 吸收新证据），返回新的 PersonaBelief。

    语义与 agents.ProfileTracker.update 完全一致（同一实现来源）：
    - 未知 facet 键名 / 未知偏好类目静默丢弃（被测件可能瞎编，不能污染信念）；
    - 数值域裁剪：facet 0-100、category [-1,1]、interruption_tolerance [0,1]；
    - loves/hates 去重保序、新标签靠前、各截断 PERSONA_MAX_TAGS 条。
    """
    facets = dict(base.facets)
    for key, val in (delta.facets or {}).items():
        if key not in FACET_KEYS:
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        v = max(0.0, min(100.0, v))
        facets[key] = int(round(_blend(facets[key], v) if key in facets else v))

    categories = dict(base.categories)
    for cat, val in (delta.categories or {}).items():
        if cat not in PREF_CATEGORIES:
            continue
        try:
            v = float(val)
        except (TypeError, ValueError):
            continue
        v = max(-1.0, min(1.0, v))
        categories[cat] = round(_blend(categories[cat], v) if cat in categories else v, 3)

    def merge_tags(existing: list[str], incoming: list[str]) -> list[str]:
        out: list[str] = []
        for tag in list(incoming) + list(existing):
            t = str(tag).strip()
            if t and t not in out:
                out.append(t)
        return out[:PERSONA_MAX_TAGS]

    interruption = base.interruption_tolerance
    if delta.interruption_tolerance is not None:
        v = max(0.0, min(1.0, float(delta.interruption_tolerance)))
        interruption = round(_blend(interruption, v) if interruption is not None else v, 3)

    return PersonaBelief(
        facets=facets,
        categories=categories,
        loves=merge_tags(base.loves, delta.loves) if delta.loves else list(base.loves),
        hates=merge_tags(base.hates, delta.hates) if delta.hates else list(base.hates),
        interruption_tolerance=interruption,
        planning_style=str(delta.planning_style) if delta.planning_style else base.planning_style,
        social_recharge=str(delta.social_recharge) if delta.social_recharge else base.social_recharge,
        confidence=(max(0.0, min(1.0, float(delta.confidence)))
                    if delta.confidence is not None else base.confidence),
        notes=str(delta.notes) if delta.notes else base.notes,
    )


class UserBelief(BaseModel):
    """助手对用户的估计（观测器输出），每轮必填。"""

    valence: float = Field(ge=0, le=1)
    energy: float = Field(ge=0, le=1)
    satiety: float = Field(ge=0, le=1)
    stress: float = Field(ge=0, le=1)
    persona_notes: str = ""  # 画像笔记（冻结维度评估素材）
    # 冻结维度的结构化估计增量：本轮新学到的人格/喜好（详见 PersonaBeliefDelta）
    persona_belief: PersonaBeliefDelta | None = None

    def to_statevec(self) -> StateVec:
        return StateVec(valence=self.valence, energy=self.energy, satiety=self.satiety, stress=self.stress)


class AssistantTurn(BaseModel):
    """assistant → Runner（结构化输出 schema 直接下发给 LLM）。"""

    reply: str
    user_belief: UserBelief
    tool_calls: list[ToolCall] = []  # view_event_todos / add_event_todo / set_reminder


class DialogueTurn(BaseModel):
    """对话历史中的一条（Harness 输入用，不含任何真实状态）。"""

    speaker: Literal["user", "assistant"]
    text: str


class HarnessObs(BaseModel):
    """Runner → Harness：被测助手在一个 turn 能看到的全部信息。

    刻意收敛为单一对象：此前这些是 on_turn 的一串位置参数，每加一个字段都要
    同时改 reference.py 与 runner.py（跨组件耦合）。被测件只看得到这里的东西——
    真实状态 x、world 的翻译词典、runs/ 日志都不在其中（docs/03 第 5 节）。
    """

    user_say: str
    history: list[DialogueTurn] = []
    tool_results: list[ToolResult] = []
    balance: float | None = None
    schedule_hint: str = ""
    # 可安排的恢复动作候选（由 Runner 从世界目录注入；agents 不直连 world）
    recovery_catalog: list[dict] = []
    slot_names: list[str] = []
    day: int = 0
    slot: int = 0


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
    # 助手在本轮结束时对用户人格/喜好的**累积**估计（Harness 合并后的完整快照）。
    # 每个助手 turn 都落盘一份，因此前端可以逐 turn 回放"画像是怎么长出来的"。
    persona_hat: PersonaBelief | None = None
    contract_violation: str | None = None
    degraded: bool = False
    # world 规则翻译器把真实状态 x 翻译成的语义化"感受"（只有用户开口的 turn 有）。
    # 落盘后前端可展示"世界 x → 用户感受 → 用户台词 → 助手 x̂"的完整因果链；
    # 旧 run 缺省 None（向后兼容），evaluator 不消费它（0 LLM 边界不变）。
    felt_state: str | None = None


class RunMeta(BaseModel):
    """meta.json：一次 run 的完整快照（可复现性凭证）。"""

    run_id: str
    seed: int
    started_at: str
    days: int
    # legacy 读取兼容：replay 模式已下线（R4），新 run 只会是 "live"；
    # 旧存档的 "replay" 仍需能被解析（前端回放/离线 eval 只读不验模式）。
    mode: Literal["replay", "live"] = "live"
    assistant_quality: str | None = None  # legacy：已下线的 replay 档位字段
    config_hash: str
    persona: Persona
    llm_roles: dict = {}  # 各角色 provider/model（不含密钥，来自配置）
    # provider 实际应答的模型版本（滚动别名漂移溯源；demo agent 侧 LLMClient 落盘，
    # run 结束时由 Runner 合并进来）。形如 {"<provider>/<配置模型>": {"reported": [...]}}
    llm_reported: dict = {}
    # ---- 可复现性凭证（新增字段均有默认值，旧 run 仍可读）----
    harness: str = "reference"  # 被测 Harness 名（registry 键）
    artifact_hashes: dict = {}  # system/llm/balance/catalog/prompts/combined
    prompt_versions: dict = {}  # 各 agent 的 PROMPT_VERSION
    profiles: dict = {}  # 各角色选用的 profile：{"user": "standard", "assistant": "openclaw"}
                         # legacy replay 存档为 {"user": "scripted", "assistant": "scripted:<quality>"}


UserContext.model_rebuild()
