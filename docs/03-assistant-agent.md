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

## 7. 驱动机制：大模型 vs 规则规划器

助手 Agent 的驱动机制涉及**观测器**（估计 `x̂`）与**控制器**（决定干预策略）两个子系统，可采用不同的实现路径：

### 7.1 大模型驱动（LLM-driven，当前实现）

**机制**：将对话历史、工具结果、经济状态全部编码进 prompt，由 LLM 一次性输出 `reply + user_belief + tool_calls`。

**优势**：

- 上下文整合能力强：LLM 能从碎片化对话中推断用户状态（如"又加班"→ 压力高、"没吃晚饭"→ 饱腹低）；
- 自然语言交互：回复语气自适应用户情绪，共情表达由模型隐式建模；
- 快速原型：无需手写观测/控制规则，prompt 迭代即可调整策略。

**劣势**：

- 估计不稳定：同一对话不同采样可能给出不同的 `user_belief`（即使温度低）；
- 过度拟合 prompt：当前「估计校准刻度」实际上给了 LLM 查表捷径（**已知泄漏**，Phase 2 修复）；
- 控制策略隐式：增益 K、干预阈值等控制参数埋在 prompt 文本里，无法像规则系统那样做参数化调优；
- 成本：每轮都需要推理（虽然可用 prompt cache 优化）。

**当前实现**（[reference.py](../usersim/agents/assistant/reference.py)）：

- `ReferenceHarness` 每轮调用 `client.chat_json()`，输出 JSON 经 schema 校验；
- 观测器：LLM 直接输出 4 维状态估计 + 人格画像增量（`persona_belief`）；
- 控制器：LLM 根据压力档位从【干预决策规则】选择恢复动作（prompt 中硬编码的规则）；
- 记忆：`profile_notes` 跨 session 累积，`ProfileTracker` 用滑动平均合并画像增量。

### 7.2 规则规划器驱动（Rule-based planner，脚本助手）

**机制**：用确定性规则实现观测（带噪声估计）与控制（按增益 K 计算恢复量，选择最佳变体）。

**优势**：

- 完全确定：同 seed 可复现轨迹，适合验证世界动力学与评估器逻辑；
- 参数化控制：增益 K、噪声 σ、滞后 delay 等参数显式可调，便于做控制论实验；
- 0 LLM 成本：可在 CI 中高速运行三档回放（good/mid/poor）。

**劣势**：

- 对话机械：回复从模板库抽取（`ASSISTANT_REPLIES`），缺乏 LLM 的共情能力；
- 观测器简化：只能按预设噪声模型估计，无法从对话细节推断（如"语气低落"→ valence 更低）；
- 画像学习受限：按概率揭示 facet（`facets_per_obs`），无法像 LLM 那样从"拒绝应酬"推断"社交偏负"。

**当前实现**（[scripted.py](../usersim/agents/scripted.py)）：

- 三档预设（good/mid/poor）对应不同的观测噪声、控制增益、响应概率；
- 观测器：`observe()` 在真值 `x_true` 上叠加高斯噪声（σ 随 day 衰减），`delayed_estimate()` 模拟滞后；
- 控制器：`choose_recovery()` 按估计误差选择恢复变体（good 档做最优一拍控制，mid 档超调，poor 档控制不足）；
- 画像学习：`observe_persona()` 每次随机揭示若干 facet 与类目偏好（带噪声，多次观察收敛）。

### 7.3 混合路径：规则规划器 + LLM 表达（Phase 2 方向）

**提议架构**：

```text
对话历史 → LLM 观测器 → 定性判断（"压力在上升" / "精力很低"）
                ↓
        规则积分器 → 数值状态 x̂（消除校准刻度泄漏）
                ↓
        规则控制器 → 恢复动作意图（"需要中档减压，预算 ¥150"）
                ↓
        LLM 执行器 → 自然语言回复 + 工具调用
```

**优势**：

- 观测可验证：数值估计由规则积分，LLM 只负责定性判断（难以作弊）；
- 控制可调优：增益 K 等参数显式可调，不依赖 prompt 隐式编码；
- 表达保留自然性：LLM 仍负责共情回复，只是控制决策从 prompt 剥离。

**Graph 结构**（规划器的执行流程）：

Phase 2 的规则规划器可以形式化为**有向无环图（DAG）**：

```text
节点：
  N1: 解析对话 → 提取关键信息（情绪词、事件提及、时间线索）
  N2: 估计状态分量 → valence / energy / satiety / stress
  N3: 更新人格信念 → 增量合并到 ProfileTracker
  N4: 检查干预条件 → 压力 > 阈值？余额充足？
  N5: 选择恢复类型 → 按需求向量与用户偏好排序
  N6: 选择时段与变体 → 日程冲突检测 + 价格筛选
  N7: 生成回复意图 → 共情语句 + 建议理由
  N8: LLM 渲染 → 自然语言输出

边（依赖关系）：
  N1 → N2（信息提取完成才能估计）
  N1 → N3（对话内容影响人格推断）
  N2 → N4（状态估计决定是否干预）
  N3 → N5（人格偏好影响恢复类型选择）
  N4 → N5（只有"需要干预"才进入选择）
  N5 → N6（类型确定后选变体）
  N6 → N7（具体方案确定后生成意图）
  N7 → N8（意图驱动 LLM 表达）

回边（重新规划）：
  N6 失败（日程冲突 / 余额不足）→ N5（换一个恢复类型）
  N5 穷尽所有类型仍失败 → N7（生成"暂时无法安排"的回复）
```

**为什么是 DAG 而非任意图**：

- 无环保证：重新规划有**退出条件**（尝试次数上限 / 可选方案耗尽），不会死循环；
- 拓扑有序：可以按依赖顺序线性执行（N1 → N2 → ... → N8），无需并发调度；
- 与 HTN（Hierarchical Task Network）的关系：可以看作简化的 HTN——每个节点是一个"方法"，边是"前置条件"，但没有多层分解（只有一层规划）。

**对比：用户侧为何也需要图结构**：

用户与助手都是**多目标优化系统**，但优化目标不同：

| 维度 | 用户 Agent | 助手 Agent |
|---|---|---|
| 目标数量 | 4 个需求（饥饿/社交/刺激/成就） | 4 个状态维度（valence/energy/satiety/stress） |
| 优化方式 | 多目标驱动力加权求和 | 最小化状态误差（控制论） |
| 非线性 | 倒 U 曲线（刺激需求） | 反弹检查、心情耦合 |
| 时间依赖 | 生物钟（饭点、睡眠时段） | 习惯化曲线（Δt 依赖） |
| 反馈回路 | 需求满足 → 状态更新 → 需求重算 | 观测 → 干预 → 再观测 |
| 图结构 | 需求汇合 + 生物钟调制 + 状态反馈 | 多步规划 + 冲突检测 + 重新规划 |

**核心区别**：

- 用户做**需求驱动的反应式决策**（多个需求汇合为求助倾向，但不做多步规划）
- 助手做**前瞻性规划**（观测 → 推理需求 → 搜索方案 → 冲突检测 → 执行）

两者都适合用图结构建模，但图的**复杂度不同**：

- 用户侧的图较浅（需求计算 → 驱动力 → 生物钟调制 → 求助决策，约 5 个节点）
- 助手侧的图较深（观测 → 估计 → 需求推理 → 方案生成 → 冲突检测 → 重新规划，约 8 个节点）

### 7.4 规则图结构的可行性分析

**结论**：助手侧的规则规划器**天然适合用图结构建模**，因为其任务本质是**多目标约束优化**：

- 节点 = 决策步骤（观测、估计、需求推理、方案生成、冲突检测）
- 边 = 数据依赖（后续步骤依赖前序步骤的输出）
- 回边 = 重新规划（冲突失败 → 回到方案选择）

**图结构的工程价值**：

1. **可测试性**：每个节点可单独测试（如"给定对话历史，N2 能否正确估计压力？"）；
2. **可组合性**：替换某个节点的实现（如 N2 从规则换成 LLM）不影响其他节点；
3. **可调试性**：执行轨迹就是图上的路径，便于定位"在哪个节点做了错误决策"；
4. **可并行化**：N2 与 N3 无依赖，可并行执行（观测状态 + 更新画像）。

**实现技术栈**（Phase 2）：

- 可用 Airflow / Prefect 等 DAG 调度框架（过重）；
- 或自定义轻量级执行器（推荐）：`Plan = List[Node]`，按拓扑序执行，节点失败时触发回边。

## 8. 实现备注

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
