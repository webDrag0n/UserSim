# 02 · 用户模拟 Agent

用户 Agent 的职责是把"真实的人"演出来：基于状态、人格与事件上下文，生成对话、情绪化表达、求助决策，以及 session 的开启与结束。它是世界的"感受器官"，不是世界的"手"——任何输出都不会直接改变状态向量 `x`。

---

## 两种模式

### LLM 驱动模式（live）

实现：`usersim/agents/user/llm_user.py`，prompt v2。

将 30 个人格细分面、结构化喜好、当前感受、活跃事件、意图全部编码进 prompt，由 LLM 推理出对话与决策。每个 slot：

1. UserPlanner 计算意图（见下节）
2. `decide_open()` 判断本 slot 是否对每个意图开 session
3. `speak()` 在 session 内生成对话

LLM 失败时记 `degraded=true` 并跳过该 turn，用户说"（沉默）"。

### 脚本模式（replay）

实现：`usersim/agents/scripted.py`。

0 LLM，确定性，用于验证世界动力学、CI、调参。三档脚本用户（good / mid / poor）模拟不同质量的对话，使用模板库（`OPENERS / EVENT_LINES / ACK`）按 `felt_state` 与活跃事件填充，求助决策由压力阈值 + 随机概率控制。

---

## UserPlanner：意图规划

每个 slot，UserPlanner 根据需求 urges 进行多目标优化，选出 0–3 个意图事件。

### 四个需求

| 需求 | 驱动力公式 | 触发的意图 |
|------|-----------|-----------|
| hunger | `u = [(1-x)/0.6]^1.5`（低饱腹加速） | eat |
| social | `u = x²`（平方增长） | social |
| stimulation | `u = 1 - (2x-1)²`（倒 U 曲线：中等最强） | stimulate |
| achievement | `u = x^2.5`（后期陡增） | achieve |

### 生物钟调制

| 时段 | 调制规则 |
|------|---------|
| slot 1（下午，饭点）| hunger 驱动力 × 生物钟因子 |
| slot 3（深夜）| 疲劳驱动力上升，sleep 意图优先 |
| 工作日 vs 周末 | 不同的需求基线 |

### 规划输出

```python
# 选出驱动力超过阈值的意图，最多 3 个
intents = planner.select(urges, persona, slot)
# intents: List[Intent]，每个 Intent 包含类型和目标描述
```

World 在高压场景下可以向意图列表注入紧急意图（如"解压"），作为对规划器的补充。

---

## UserMemory：滚动记忆

实现：`usersim/agents/user/memory.py`。

- 保留最近 8 个 session 的摘要（标题 + 关键结果 + 情绪标注）
- 每个 session 结束后自动摘要写入
- 注入 prompt 时作为"记忆"段落，让用户 Agent 的决策有历史感

---

## Prompt 结构

```text
你是 {persona.name}，{persona.archetype}。

【性格（大五 · 30 个细分特质，0-100）】
  按域分组，每项附语义注释
  · 开放性：想象力 82（爱做白日梦…）；审美 63（对美有感知）；…（共 6 项）
  · 尽责性 / 外向性 / 宜人性 / 神经质 同上
  怎么用：分数是行为的内在原因；>65 明显外显、<35 相反；
  绝不报出分数、不提"大五"或特质名——要让人从语气与决定里看出来。

【喜好】
  自陈述文本 + 结构化偏好
  （偏爱/排斥的类目、明确爱憎、打扰容忍度、做事风格、回血方式）

【记忆】
  近期 session 摘要（最多 8 条）

【铁律】
  你不是 AI，你就是这个人本人。
  只能表达感受与做出现实决策，不能篡改或预言状态数值。
  性格与喜好固定，不为迎合助手而改变。

【当前感受】{felt_state}
【正在发生】{active_events}
【本次意图】{intent}     ← 由 UserPlanner 注入
{assist_prompt}          ← 介入点提示，可空
```

用户 Agent **看不到原始数值 x**。数值→语言的翻译在 World 侧用分档词典完成（如 stress > 0.7 →"快崩溃了"），这有三重作用：
1. 防止用户 LLM 精确报数，使助手的估计任务保持难度
2. 表达风格由人格调制（高神经质者把 0.6 说成"糟透了"）
3. 从结构上杜绝"用户 LLM 篡改状态"的通道

---

## 工具集

用户侧只有三个工具：

| 工具 | 语义 |
|------|------|
| `open_session` | 主动找助手（被测行为之一）|
| `close_session` | 结束对话（session 的唯一结束标准）|
| `request_assistant` | 请助手代为操作手机（查/写日程、设提醒）|

写日程等手机操作一律不在用户侧——假设用户不能自己操作手机，只能通过助手代操作。

---

## 行为调制参数

位于 `config/system.toml [user_agent]`：

| 参数 | 说明 |
|------|------|
| `help_seek_stress_threshold` | felt_state 档位超过阈值时，在 prompt 中强化"考虑找助手"的倾向（不强制，决策仍由 LLM 做）|
| `max_turns_per_session` | 防死循环，达到上限由 Runner 强制结算 session |

---

## 实现备注

- prompt v2 相比 v1：大五由 5 域升级为 30 细分面全量注入（含语义注释），喜好增加结构化偏好段落，显式要求"人格固定不可为迎合助手而改变"。
- 实测（DeepSeek）：对话自然、人格稳定；偶见连续两轮重复措辞，可在 prompt 加"不要重复上一句"。
- `decide_open()` 与 `speak()` 是两次独立 LLM 调用，前者决策是否求助，后者生成对话内容。
