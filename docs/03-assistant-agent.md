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
    "persona_notes": "高压工作，喜欢寿喜烧和独处回血",
    "persona_belief": {
      "facets": { "神经质.焦虑": 75, "外向性.群居性": 30 },
      "categories": { "饮食": 0.8, "社交": -0.6 },
      "loves": ["寿喜烧"], "hates": ["应酬"],
      "planning_style": "提前规划", "social_recharge": "独处",
      "confidence": 0.45
    }
  },
  "tool_calls": [
    { "name": "add_event_todo", "args": { "title": "吃好吃的·寿喜烧", "day_offset": 1, "slot": 2 } }
  ]
}
```

- `user_belief` 每轮必填——**估计精度本身就是考点**；缺字段 = 契约违约，计入行为指标；
- `persona_belief` 是**冻结维度（人格 30 facet + 喜好）的估计增量**：只填本轮真正有
  新证据的项，Harness 侧累积成完整信念。**留空优于瞎猜**——未估计的 facet 不计误差，
  但覆盖率会低；瞎猜则直接拉高画像误差。详见 `docs/13-persona-model.md`。
- 数值域 [0,1]，schema 由 `contracts/` 导出 JSON Schema，直接喂给支持 structured output 的 provider；不支持时退化为"JSON 模式 + 校验重试"。

## 3. 助手侧工具集（手机操作执行者）

| 工具 | 语义 | 结果来源 |
|---|---|---|
| `view_event_todos` | 查看日程 | world 日程视图（规则查询） |
| `add_event_todo` | 新增日程事件 | world 合法性校验后入队 |
| `set_reminder` | 设提醒 | 日程元数据 |

工具结果由 world 产生、Runner 转发；助手无法触碰世界其他任何部分。

## 4. Harness 抽象（实际结构）

```text
agents/assistant/
  base.py       # Harness 协议：on_turn(obs) / snapshot() / restore() / persona_belief()
  registry.py   # 名 → 类的注册表（可插拔被测件）
  reference.py  # 参考 Harness：naive memory（profile_notes 累积）+ 工具执行
  profile.py    # ProfileTracker：人格/喜好信念的增量累积器（滑动平均）
  stub.py       # 失能对照：恒定 x̂=0.5、零干预、零画像（benchmark 下界）
```

`persona_belief()` 是协议的**可选**方法：返回当前累积的冻结维度信念，由 Runner 每轮
落盘为 `TurnRecord.persona_hat`。未实现时 Runner 退化为"只用本轮增量"，老 Harness
不改也能跑（只是画像学习曲线更抖）。

参考 Harness 的策略刻意朴素（被动响应、按需建议），作为评测矩阵 E1 的固定底座；它的指标分数构成 benchmark 的"及格线"。`stub` 则是下界锚点——一个合格的评估器必须把它判为 diverged。

> 早期草稿曾规划 `memory/base.py`、`memory/naive.py`、`user_model.py` 三个文件的拆分，实际实现
> 中记忆策略简单到不值得单独成包（就是一段跨 session 累积的 `profile_notes`）。Phase 2 引入
> 规划器分层时会重新划分为 `planner/` 与 `dialogue/`。

## 5. 被测 Harness / Model 接入规范

- **E1（测 Model）**：`--harness reference` 固定，只换 `config/llm.toml [roles.assistant_agent]` 的 provider/model；
- **E2（测 Harness）**：实现 `base.Harness` 协议并在 `registry.py` 登记，Model 固定为参考 provider；
- 被测件**只能看到 `contracts.HarnessObs`**：不得读取 `runs/` 日志、不得访问用户侧 prompt、
  不得 import world/evaluator（依赖规则测试强制）。需要世界信息（如恢复动作目录）时由 Runner 注入。
- 选择方式：CLI `--harness`、`POST /api/runs`、前端下拉；所用名写入 `meta.json`。
- **异常隔离**：`on_turn` 抛任何异常都记为契约违约并继续，不会终止整个 episode。

详见 `docs/12-benchmark.md`。

## 6. 主动干预与打扰率

- 助手只能在 session 内说话（假设① session-based）；
- Harness 可以选择"主动建议结束 session"（通过回复暗示），是否结束由用户 Agent 决定；
- 无关建议、过度安排会在评估中体现为**打扰率**与**超调量 M_p**——控制器增益过大的可观测症状。

## 7. 实现备注

- 参考 Harness 落位于 `agents/assistant/reference.py`（prompt **v2**）：每轮 JSON 输出 `reply + user_belief + tool_calls`，契约违约自动修复重试一次，再失败由 Runner 记违约。
- `profile_notes` 跨 session 积累（naive memory），注入系统提示；续跑通过协议的
  `snapshot()`/`restore()` 恢复（此前 Runner 里是 `harness_notes` 专用分支，假设记忆一定是一段文本）。
- prompt v2 新增冻结维度画像：可估计的 30 个 facet 键名清单（含语义）+ 11 个喜好类目，
  并强调"增量输出、没证据就留空、不要每轮重报 30 项"。画像会**反过来影响建议质量**
  （安排用户偏爱的类目回血更多），因此摸清喜好不是附加题。
- `ProfileTracker` 用滑动平均（新证据权重 0.6）合并增量：偏向新证据以修正第一印象的
  锚定问题，但保留 40% 已有认识避免被单句话带跑；未知 facet 名静默丢弃，
  loves/hates 各截断 12 个（防堆词刷命中率）。
- **已知问题（Phase 2 处理）**：`reference.py` 提示词中的「估计校准刻度」与 `world/felt.py` 的
  分档词典互为逆映射，助手做字符串查表即可拿到高 x̂ 分，`‖x−x̂‖` 因此不再度量真实观测能力。
  Phase 2 改为 LLM 只输出定性方向、由规划器积分出数值，从结构上消除该泄漏。
- 实测：工具调用率合理（view_event_todos / add_event_todo / set_reminder 均已接通世界端）；‖x−x̂‖ 约 0.26——朴素观测器的基线水平，构成 benchmark "及格线"。
- `set_reminder` 为世界端日程元数据（无状态效果）。
