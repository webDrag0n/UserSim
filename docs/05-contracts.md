# 05 · 数据契约（contracts）

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
    big5: dict[str, int]          # 开放性/尽责性/外向性/宜人性/神经质, 0-100, 冻结
    likes: str                    # 喜好自我陈述, 冻结
    routine: str                  # 作息模板标识
    x0: StateVec                  # 初始状态
```

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
    persona_notes: str = ""           # 画像笔记（冻结维度评估素材）

class ToolCall(BaseModel):
    name: str
    args: dict = {}

class ToolResult(BaseModel):
    name: str
    ok: bool
    payload: dict = {}
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
    contract_violation: str | None = None
    degraded: bool = False
```

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
