# 05 · 数据契约（contracts）

> ⚠️ 注：replay 模式已于 R4 下线（已知组效度检验 known-groups validity 迁移至 live 对照组 reference vs stub），文中 replay/脚本三档内容为历史记录。

状态: 草稿

> contracts 是唯一允许被所有包 import 的层。所有跨组件消息在此定义（pydantic v2），
> 任何字段变更必须向后兼容：只加不删、不改语义；schema 变更同步更新本文档。

## 1. 基础模型

### StateVec — 状态向量

```python
class StateVec(BaseModel):
    valence: float = Field(ge=0, le=1)   # 心情
    energy: float = Field(ge=0, le=1)    # 精力
    satiety: float = Field(ge=0, le=1)   # 饱腹
    stress: float = Field(ge=0, le=1)    # 压力
```

### Persona — 角色卡

```python
class Persona(BaseModel):
    name: str
    archetype: str
    big5: dict[str, int]          # 5 域聚合分, 0-100, frozen（由 facets 派生）
    facets: dict[str, int]        # 大五 30 细分面, 0-100, frozen
    likes: str                    # 喜好自我陈述, frozen
    prefs: Preferences            # 结构化喜好, frozen
    routine: str                  # 作息模板标识
    x0: StateVec                  # 初始状态
    income_per_slot: int = 200

class Preferences(BaseModel):     # 结构化喜好（冻结特质）
    categories: dict[str, float] = {}   # 11 类目 → 偏好分 [-1,1]
    loves: list[str] = []; hates: list[str] = []
    interruption_tolerance: float = 0.5 # 越低越讨厌计划被打断
    planning_style: str = "看心情"       # 提前规划 | 随遇而安 | 看心情
    social_recharge: str = "独处"        # 独处 | 找人
```

人格/喜好四个字段为 pydantic `frozen=True`：**冻结维度运行期不可改写**（此前只是
口头约定，`world.py` 曾直接改 `archetype`）。facet 词表与画像度量在
`contracts/persona.py`（三方共用的唯一数据源），详见 `docs/13-persona-model.md`。
`facets` 缺省为空 dict——旧存档仍可读，读取时经 `trait()` 回退到域分。

### Event — 事件（六字段）

```python
class Event(BaseModel):
    id: str
    kind: Literal["template", "disturbance", "recovery"]
    name: str
    start_slot: int               # t_logical 起点
    span_slots: int
    location: str
    goal: str
    effect: dict[str, float]      # Δx，结算时按 span 摊销
    progress: float = 0
    caused_by_session_id: str | None = None   # 因果链（哪次对话促成了它）
    replaces_meal: bool = False   # 餐饮场所事件：活跃时段抑制当日模板"三餐"在同 slot 的效果
```

## 2. 世界 ↔ Runner 消息

```python
class EventContext(BaseModel):        # world → Runner：一个时段的上下文
    t_logical: int
    day: int
    slot_name: str
    active_events: list[Event]
    assist_prompt: str | None         # 助手介入点提示
    schedule_view: list[Event]
    satiation_note: str | None = None  # 餍足提示：最近重复的恢复动作已腻（习惯化权重 < 0.6）
    utility_menu: list[str] = []       # 各恢复活动的边际效用档位（R7，语义行，无数值）

class SlotSettlement(BaseModel):      # world → 日志：一次状态推进
    t_logical: int
    x_before: StateVec
    x_after: StateVec
    natural_drift: dict[str, float]
    event_effects: dict[str, float]
    control_effects: dict[str, float]
    active_event_ids: list[str]
```

## 3. Agent 侧消息

```python
class UserContext(BaseModel):         # Runner → user_agent（注意：无原始数值 x）
    persona: Persona
    felt_state: str                   # world 规则翻译器产出的语义化状态摘要
    active_events: list[Event]
    assist_prompt: str | None
    schedule_view: list[Event]
    dialogue_history: list["TurnRecord"]
    satiation_note: str | None = None  # 餍足提示（world 裁决，供用户表达"吃腻了"）
    utility_menu: list[str] = []       # 各活动边际效用档位（R7：规划权衡与拒绝重复安排的依据）

class UserAction(BaseModel):          # user_agent → Runner
    say: str
    tool_calls: list[ToolCall] = []   # open_session / close_session / request_assistant
    end_session: bool = False

class AssistantTurn(BaseModel):       # assistant → Runner（每轮必填 user_belief）
    reply: str
    user_belief: UserBelief
    tool_calls: list[ToolCall] = []   # view_event_todos / add_event_todo / set_reminder

class UserBelief(BaseModel):
    valence: float = Field(ge=0, le=1)
    energy: float = Field(ge=0, le=1)
    satiety: float = Field(ge=0, le=1)
    stress: float = Field(ge=0, le=1)
    persona_notes: str = ""                          # 画像笔记（自由文本）
    persona_belief: PersonaBeliefDelta | None = None  # 冻结维度估计**增量**

class PersonaBeliefDelta(BaseModel):  # 每轮只填有新证据的项（留空 > 瞎猜）
    facets: dict[str, int] = {}           # facet key → 0-100
    categories: dict[str, float] = {}     # 类目 → [-1,1]
    loves: list[str] = []; hates: list[str] = []
    interruption_tolerance: float | None = None
    planning_style: str | None = None
    social_recharge: str | None = None
    confidence: float | None = None
    notes: str = ""

class PersonaBelief(BaseModel):  # Harness 合并后的完整信念（落盘用，同形但 confidence 必填）
    ...  # 字段同上；未估计过的 facet 直接缺席，不填 50 占位

class ToolCall(BaseModel):
    name: str
    args: dict = {}

class ToolResult(BaseModel):
    name: str
    ok: bool
    payload: dict = {}
```

## 3.5 Agent 接入 wire 协议（contracts/agent_api.py，docs/15-agent-api.md）

benchmark ↔ agent（demo / 外部）的请求-响应信封与 typed payload。
`Intent` 与意图常量（INTENT_EAT 等）的权威定义也在此（最初自规则版规划器上移；
规划器废除后 wire 类型不变）。

```python
class AgentRequest(BaseModel):      # benchmark → agent（GET /api/agent/pending 响应体）
    request_id: str
    run_id: str
    role: Literal["user", "assistant"]
    type: str                       # plan_slot / decide_open / speak / session_closed / on_turn
    payload: dict = {}              # typed payload 的 dict 形态
    agent_state: dict = {}          # agent 侧不透明状态（续跑回灌）

class AgentResponse(BaseModel):     # agent → benchmark（POST /api/agent/respond 请求体）
    request_id: str
    result: dict = {}               # typed result 的 dict 形态
    agent_state: dict | None = None       # 非空覆盖 (run_id, role) 存档状态
    persona_hat: PersonaBelief | None = None  # on_turn 专用：累积画像快照
    error: str | None = None        # agent 侧失败（记违约/降级）

# 用户侧 typed payload / result
class PlanSlotRequest(BaseModel):   # urges/stress/energy/slot/day/money/event_library/
    ...                             # assist_prompt/max_intents（数值只流向用户侧）
                                    # context: UserContext | None（只加不删：LLM 规划的
                                    # 语义输入——felt_state+人格+餍足提示，不含数值；
                                    # 规则/混合实现可忽略）
class PlanSlotResult(BaseModel):    # intents: list[Intent]
class DecideOpenRequest(BaseModel): # {context: UserContext, intent: Intent}
class DecideOpenResult(BaseModel):  # {open: bool, reason: str}
class SpeakRequest(BaseModel):      # {context, history: list[DialogueTurn], intent_description}
class SessionClosedNotice(BaseModel):  # {session_id, intent_type, turns, day}

# speak 的 result 即 UserAction；on_turn 的 payload 即 HarnessObs、result 即 AssistantTurn
```

## 4. 日志模型（append-only JSONL，一行一条）

### turns.jsonl

```python
class TurnRecord(BaseModel):
    run_id: str
    t_logical: int
    session_id: str | None
    turn_id: int
    speaker: Literal["user", "assistant", "system"]
    text: str
    tool_calls: list[ToolCall]
    tool_results: list[ToolResult]
    x_true: StateVec                  # world 提供（对用户 LLM 不可见）
    x_hat: StateVec | None            # assistant 提供；user/system 行为 None
    persona_hat: PersonaBelief | None = None  # 助手对人格/喜好的累积估计（逐 turn 快照）
    contract_violation: str | None = None
    degraded: bool = False
    felt_state: str | None = None     # world 把 x 翻译成的语义化感受（仅用户开口 turn）
```

`felt_state` 是 world 规则翻译器（`world.felt_state()`）产出的自然语言感受，运行期只
经 `UserContext` 传给用户 Agent；现在同时落盘到用户开启 session 的那一 turn，前端因此
能展示「世界真实 x → 用户感受到的 → 用户说出的 → 助手估计的 x̂」四层因果链。evaluator
不消费该字段（`world/`·`evaluator/` 的 0 LLM 边界不变），旧 run 缺省 `None`。

`persona_hat` 落盘的是**合并后的完整快照**而非增量：前端因此能逐 turn 回放画像的
成长过程，评估器也无需自己重放增量。

### meta.json（每 run 一份）

```python
class RunMeta(BaseModel):
    run_id: str
    seed: int
    started_at: str
    days: int
    config_hash: str                  # system.toml 快照哈希
    persona: Persona
    llm_roles: dict                   # 各角色 provider/model（不含密钥）
```

## 5. 导出给 LLM 的 JSON Schema

`AssistantTurn.model_json_schema()` 直接作为 structured output 的 schema 下发；
`UserAction` 同理。schema 文本随 `meta.json` 快照，保证旧日志永远可解释。

## 6. 兼容性测试（tests/contracts）

- 每个模型一个 golden JSON 样例，反序列化必须成功；
- 新增字段必须有默认值；
- `contracts` 包的 import 白名单由脚本强制检查。

## 7. 实现备注

- 全部模型落位于 `contracts/models.py`（pydantic v2）；golden JSON 往返测试在 `tests/test_contracts.py`。
- `RunMeta` 增加了 `mode` 与 `assistant_quality` 字段（区分 replay/live）。
- Agent 接入 wire 协议落位于 `contracts/agent_api.py`（§3.5）：信封 + 四类用户请求 +
  on_turn；`meta.harness` 记录接入方式（`demo:reference` / `external`），
  `run_state.json` 以 `agent_state` 分角色存档（旧 `harness_state` 读取兼容）。
- prompt v3 配套新增（均为只加不删）：`PlanSlotRequest.context`（LLM 规划的语义输入，
  runner 每 slot 组装；可空——demo 回退缓存再退化通用规划）；`EventContext`/`UserContext`
  的 `satiation_note`（餍足通道）；`Event.replaces_meal`（餐饮场所抑制同 slot 模板餐效果）。
  wire 协议的请求/响应结构不变——外部 agent 无需改代码。
