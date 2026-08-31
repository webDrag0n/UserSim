# 02 · 用户模拟 Agent

> ⚠️ 注：replay 模式已于 R4 下线（已知组效度检验 known-groups validity 迁移至 live 对照组 reference vs stub），文中 replay/脚本三档内容为历史记录。

用户 Agent 的职责是把"真实的人"演出来：基于状态、人格与事件上下文，生成对话、情绪化表达、求助决策，以及 session 的开启与结束。它是世界的"感受器官"，不是世界的"手"——任何输出都不会直接改变状态向量 `x`。

用户 Agent 经统一 **agent 接口**接入（docs/15-agent-api.md）：benchmark 发
`plan_slot / decide_open / speak / session_closed` 请求，agent 回传响应。
仓库自带的 LLM 用户是 **demo agent**（`agents/user/standard/agent.py`），与外部用户 agent
（装载 `skills/usersim-user/SKILL.md`）走完全相同的协议。demo 用户实现是可插拔的
配置文件：`agents/user/profiles/*.toml`（`--impl <name>` 选择，增删文件即
增删实现）；角色级 LLM 绑定在 `agents/user/config.toml`。

---

## 两种模式

### LLM 驱动模式（live）

实现：`agents/user/standard/llm_user.py`（prompt v6）+ `agents/user/standard/agent.py`（接入壳）。

将 30 个人格细分面、结构化喜好、表达直白度档位、当前感受、活跃事件全部编码进 prompt，由 LLM 推理出意图、对话与决策（plan/decide_open/speak 全流程 LLM 驱动）。每个 slot：

1. `plan_slot`：LLM 生成意图（见下节；世界补充触发的 emergency 意图由接入壳注入）
2. `decide_open()` 判断本 slot 是否对每个意图开 session
3. `speak()` 在 session 内生成对话
4. `session_closed`：session 结束，更新自己的 UserMemory

LLM 失败时记 `degraded=true` 并跳过该 turn，用户说"（沉默）"。

### 脚本模式（replay）

实现：`usersim/scripted.py`。

0 LLM，确定性，用于验证世界动力学、CI、调参。三档脚本用户（good / mid / poor）模拟不同质量的对话，使用模板库（`OPENERS / EVENT_LINES / ACK`）按 `felt_state` 与活跃事件填充，求助决策由压力阈值 + 随机概率控制。

---

## LLM 意图规划（prompt v6）

每个 slot，意图由用户侧 LLM 直接生成（`llm_user.py` 的 `plan()`，PLAN_TEMPLATE）。
规则版 UserPlanner 已废除（v2 时代的"按 urges 阈值确定性选意图"不再存在）。
**规划仍在用户 agent 侧**（agent 接口的 `plan_slot` 请求处理器）：它扮演的是本人的
"想要什么"，因此请求 payload 仍携带 urges/stress/energy/money 等数值（只流向用户侧，
助手侧不可见）——但 demo 实现**不消费这些数值**（状态-表达解耦：数值不进 prompt，
LLM 只看到 persona、felt_state、时段、事件、天气、记忆与 assist_prompt）；数值字段
保留给规则/混合实现与外部用户 agent。需求驱动力公式本身仍是世界机制的一部分
（见 docs/01-world.md；replay 脚本用户仍由 urges 驱动）。
`Intent` 类型与意图常量的权威定义在 `contracts/agent_api.py`（wire 契约）。

### plan() 输出契约

```json
{"intents": [{"type": "eat|social|stimulate|recover|sleep|achieve|chat",
              "mode": "explicit|vague",
              "want": "一句口语化的需求或感受"}]}
```

0–3 条，按想要的强烈程度排序；真的没什么想要就输出空列表（本 slot 无 session）。
`chat`（v4 新增）是无恢复目标的闲聊/分享/吐槽——真人不是每句话都"要办成什么事"，
缺这个通道时 LLM 会把一切寒暄硬塞进事务意图，助手也跟着落任务单，形成复读死循环。
type 不允许 emergency——它只能由世界注入：`assist_prompt` 非空且无 recover 类意图时，
接入壳（`agent.py`）把 emergency 意图插入意图列表居首，再按 max_intents 截断，
规则与旧 runner 内联逻辑逐条一致。LLM 失败/解析失败 → 空列表，runner 记 degraded。

`PlanSlotRequest` 新增 `context: UserContext | None` 字段（只加不删）：runner 每 slot
组装语义化上下文（persona + felt_state + 事件 + 天气 + satiation_note）传入；demo 无
context 时回退最近一次 decide_open/speak 的缓存（至多才一个 slot 旧），run 首个 slot
无缓存则退化为无人格的通用规划（表达习惯按中档默认）。

### 表达直白度：explicit / vague 两种模式

用户不再总是"点名方案"——有时明确说想做的事（explicit：说想做什么，但不说地点、
价位等实现细节），有时只说感受（vague：只描述感受和需求，让助手猜、由助手给方案）。
倾向由人格确定性分档（`agents/user/standard/expression.py` 的 `explicitness_tier()`，
0 LLM 纯函数）：

```text
score = 外向性.果断 + 宜人性.直率 + 开放性.情感丰富 − 神经质.自我意识（缺失按 50）
score < 100   → 含蓄：只绕着说感受，想要什么让别人猜
100 ≤ score < 180 → 中等：有时直接说想做什么，有时只描述感受
score ≥ 180   → 直白：想做什么通常直接说出来
```

档位文案注入 sys prompt 的【你的表达习惯】，指导 LLM 选择表达模式；plan 产出的
mode 经接入壳暂存，speak 时拼入 intent_description 的指导前缀。

### 真实反馈与餍足通道

对助手的安排，用户按冻结喜好给出真实反馈：喜欢就开心接受，讨厌或腻了就按顺从度
自然抗拒（顺从高勉强接受、低直接拒绝）。餍足通道让"腻了"可表达：world 在最近一次
执行的恢复动作习惯化权重 < 0.6 时产出 `satiation_note`（"最近总是{动作}，感觉有点
腻了"），经 `UserContext` 注入 sys prompt 的【最近的感觉】段落（venue 餐厅同样参与
习惯化，模板三餐豁免——见 docs/08-event-catalog.md）。

世界在高压场景下的紧急意图（如"解压"）仍经 `assist_prompt` 传入 `plan_slot` 请求，
由用户侧接入壳注入意图列表（作为对 LLM 规划的补充）。

---

## UserMemory：滚动记忆

实现：`agents/user/standard/memory.py`。

- 保留最近 8 个 session 的摘要（标题 + 关键结果 + 情绪标注）
- 每个 session 结束后（`session_closed` 通知）自动摘要写入
- 注入 prompt 时作为"记忆"段落，让用户 Agent 的决策有历史感
- 记忆随 `agent_state` 存档/续跑回灌（demo 进程重启不丢）

---

## Prompt 结构

```text
你是 {persona.name}，{persona.archetype}。

【你的性格（大五 · 30 个细分特质，0-100）】
  按域分组，每项附语义注释
  · 开放性：想象力 82（爱做白日梦…）；审美 63（对美有感知）；…（共 6 项）
  · 尽责性 / 外向性 / 宜人性 / 神经质 同上
  怎么用：分数是行为的内在原因；>65 明显外显、<35 相反；
  绝不报出分数、不提"大五"或特质名——要让人从语气与决定里看出来。

【你的喜好】
  自陈述文本 + 结构化偏好
  （偏爱/排斥的类目、明确爱憎、打扰容忍度、做事风格、回血方式）

【你的表达习惯】          ← explicitness_tier 档位文案（含蓄/中等/直白）

【铁律】
  第一人称口语化（≤60 字）；只表达感受与现实决策，不能篡改或预言状态数值；
  不能自己操作手机（日程/提醒一律请助手代劳）；输出必须是 JSON；
  严禁重复自己说过的话；
  性格与喜好固定，不为迎合助手而改变——对助手的安排给出真实反馈，
  讨厌或腻了就按顺从度自然抗拒；
  不是规划器——具体去哪儿、怎么实现、花多少钱交给助手想办法；
  表达模式按【你的表达习惯】——点名不说实现细节、只说感受不自己给方案。

【当前感受】{felt_state}
【最近的感觉】{satiation_note}   ← 餍足提示（"最近总是X，感觉有点腻了"），可空
【今日天气】{weather}            ← 可空
【记忆】
  近期 session 摘要（最多 8 条）
【提示】{assist_prompt}          ← 介入点提示，可空
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
- prompt v3 相比 v2：**意图规划纯 LLM 化**（废除规则版 UserPlanner）——`plan()` 让人格与
  当前感受直接产出 0~3 条 {"type", "mode", "want"}；新增表达直白度调制
  （`expression.py` 的 `explicitness_tier`：果断 + 直率 + 情感丰富 − 自我意识，
  阈值 100/180 分含蓄/中等/直白三档，注入【你的表达习惯】）；【铁律】新增第 7 条
  （你不是规划器——实现细节交给助手）与第 8 条（点名不说地点价位、只说感受不给方案）；
  新增餍足通道【最近的感觉】（`satiation_note`）。`PlanSlotRequest` 新增 `context`
  字段承载 LLM 规划的语义输入（可空，只加不删）。
- prompt v6 相比 v5（R7 边际效用感知）：`EventContext`/`UserContext` 新增 `utility_menu`
  通道（world 用习惯化裁决同一公式把各活动当前 hab_weight 翻译成语义档位，外加
  "还没试过的"候选清单，只加不删）；铁律 9 重写为效用版（腻了的事不提也不接受、
  明确说"对我已经没什么用了"、做完效果差如实反馈）；PLAN 模板引导从"新鲜/没试过"
  里选、全腻了就 vague 说感受。satiation_note 保留兼容。
- prompt v5 相比 v4（R6 拟人度修复）：**记忆带具体活动名**——`SessionClosedNotice` 新增
  `activities` 字段（runner 从工具执行结果收集本 session 成功落单的事件名），
  `UserMemory.prompt_block` 显示"找乐子：livehouse · 地下现场"而非只有意图标签；
  此前 LLM 不知道自己刚去过哪，重复提同一安排（真人会腻）。铁律第 1 条语域修正：
  对**手机助手**说话（有事说事、简短直接、少语气词网络梗），不是朋友微信闲聊腔；
  新增第 9 条（刚做过的乐事会腻、短期内换花样，助手重复推荐就按性格表达腻烦）；
  SPEAK/PLAN 模板同步引导"说完事就结束""刚做过的活动别再提"。
- prompt v4 相比 v3（R4 对话质量修复）：新增 `chat` 闲聊意图通道（见上）；铁律第 5 条
  升级为"用生活细节表现状态，而非复述状态词"（配合 felt_state 同义变体池 3→5 扩容）；
  采样温度 0.25→0.5（0.25 实测把用户压成复读机）。配套机制：runner 复读熔断
  （相邻发言相似度 > 0.75 连续计数，用户 2 次注入收尾提示 / 3 次强制收尾，
  助手 2 次即强制收尾，熔断落盘 system 记录供 evaluator 统计）。用户模型钉版
  `deepseek-v4-flash`（滚动别名 deepseek-chat 实测被供应商静默换血，毁掉跨天可比性）；
  该模型是推理模型，`LLMClient.chat_json` 新增空响应预算翻倍重试
  （max_tokens 4096→8192→16384，封顶 16k）——推理会把预算耗在 reasoning_content 上
  导致 content 空串，实测曾造成 64% session 含降级记录；三处调用的 max_tokens 地板同步
  抬高（plan 256→2048 / decide_open 128→1024 / speak 256→2048，上限语义不影响非推理模型）。
- 实测（DeepSeek，v2 时代）：对话自然、人格稳定；偶见连续两轮重复措辞——v3 已将
  "严禁重复自己说过的话"写入铁律第 5 条。
- `plan()` / `decide_open()` / `speak()` 是三次独立 LLM 调用：前者生成意图列表，
  中者决策是否求助，后者生成对话内容。
