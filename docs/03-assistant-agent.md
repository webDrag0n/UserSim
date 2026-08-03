# 03 · 助手 Agent 与 Harness 契约（agents/assistant）

状态: 草稿

> 助手是**被测件**。本包提供：契约定义、参考 Harness 实现、被测 Harness 的接入规范。
> 助手 = Model（LLM）+ Harness（记忆结构 / 用户建模 / 工具执行 / 输出组装）。

## 1. 助手在控制回路中的位置

- **观测器**：从对话历史估计用户状态 `x̂`（含冻结维度画像）；
- **控制器**：决定回复内容与工具调用（写日程/提醒），间接驱动用户执行恢复行为 `u`；
- 助手**看不到**真实 `x`，也看不到 world 的语义化摘要翻译表——只能凭对话推断。

## 2. 每轮输出契约（contracts.AssistantTurn，强制 JSON Schema 校验）

```json
{
  "reply": "辛苦啦！今晚先喝点粥垫垫，明晚给你安排那家寿喜烧？",
  "user_belief": {
    "valence": 0.4, "energy": 0.25, "satiety": 0.3, "stress": 0.75,
    "persona_notes": "高压工作，喜欢寿喜烧和独处回血"
  },
  "tool_calls": [
    { "name": "add_event_todo", "args": { "title": "吃好吃的·寿喜烧", "day_offset": 1, "slot": 2 } }
  ]
}
```

- `user_belief` 每轮必填——**估计精度本身就是考点**；缺字段 = 契约违约，计入行为指标；
- 数值域 [0,1]，schema 由 `contracts/` 导出 JSON Schema，直接喂给支持 structured output 的 provider；不支持时退化为"JSON 模式 + 校验重试"。

## 3. 助手侧工具集（手机操作执行者）

| 工具 | 语义 | 结果来源 |
|---|---|---|
| `view_event_todos` | 查看日程 | world 日程视图（规则查询） |
| `add_event_todo` | 新增日程事件 | world 合法性校验后入队 |
| `set_reminder` | 设提醒 | 日程元数据 |

工具结果由 world 产生、Runner 转发；助手无法触碰世界其他任何部分。

## 4. Harness 内部抽象（参考实现）

```
agents/assistant/
  harness_base.py    # Harness 协议类：on_turn(history, tool_results) -> AssistantTurn
  memory/
    base.py          # Memory 协议：read(query) / write(turn) / consolidate()
    naive.py         # 参考实现：滑动窗口 + 追加式用户档案
  user_model.py      # 参考观测器：从 memory 提炼 x̂（LLM 结构化输出）
  reference.py       # 参考 Harness = naive memory + user_model + 工具执行
```

参考 Harness 的策略刻意朴素（被动响应、按需建议），作为评测矩阵 E1 的固定底座；它的指标分数构成 benchmark 的"及格线"。

## 5. 被测 Harness / Model 接入规范

- **E1（测 Model）**：Harness 固定为 `reference.py`，只换 `config/llm.toml [roles.assistant_agent]` 的 provider/model；
- **E2（测 Harness）**：实现 `Harness` 协议（单一方法 `on_turn`），Model 固定为参考 provider；
- 两类被测件都不得读取 `runs/` 日志、不得访问用户侧 prompt——Runner 在进程边界上就不提供这些对象。

## 6. 主动干预与打扰率

- 助手只能在 session 内说话（假设① session-based）；
- Harness 可以选择"主动建议结束 session"（通过回复暗示），是否结束由用户 Agent 决定；
- 无关建议、过度安排会在评估中体现为**打扰率**与**超调量 M_p**——控制器增益过大的可观测症状。

## 7. 实现备注

- 参考 Harness 落位于 `agents/assistant/reference.py`（prompt v1）：每轮 JSON 输出 `reply + user_belief + tool_calls`，契约违约自动修复重试一次，再失败由 Runner 记违约。
- `profile_notes` 跨 session 积累（naive memory），注入系统提示。
- 实测：工具调用率合理（view_event_todos / add_event_todo / set_reminder 均已接通世界端）；‖x−x̂‖ 约 0.26——朴素观测器的基线水平，构成 benchmark "及格线"。
- `set_reminder` 为世界端日程元数据（无状态效果）。
