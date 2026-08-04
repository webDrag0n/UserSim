# 00 · 总体架构

状态: 已实现

## 1. 一句话定义

UserSim = **纯规则世界** + **两个 LLM Agent** + **纯规则评估器**，用控制论指标评测"助手能否让用户的生活收敛到内心平和"。

## 2. 组件拓扑与依赖规则

```
            ┌──────────────────────── world（0 LLM）────────────────────────┐
            │  时钟  事件引擎  状态动力学  结算器  日程生成器  轨迹日志写入   │
            └───────▲───────────────────────────────────────────▲──────────┘
                    │ EventContext / ToolResult                  │ TurnLog（落盘）
                    │                                            │
   user_agent（LLM）┘                                            └──── evaluator（0 LLM）
        ▲  对话消息                                                 离线读取 runs/*.jsonl
        │ SessionChannel（contracts 定义的消息通道）               输出报告，永不回写世界
        ▼
   assistant_agent（LLM，被测件）
```

依赖规则（由 CI import 检查强制）：

| 包 | 允许 import | 禁止 import |
|---|---|---|
| `contracts` | 仅 pydantic/标准库 | 一切业务包 |
| `world` | contracts | agents、evaluator、llm |
| `agents/*` | contracts、llm | world、evaluator（运行时由编排器注入上下文） |
| `evaluator` | contracts | world、agents、llm |
| `server` / `bench` / `runner` / `cli` | world、agents、evaluator、contracts | —（登记在册的组装点） |

**强制方式**：`tests/test_dependency_rules.py` 用 `ast` 静态扫描全部 import（含函数内延迟
import），并额外断言 world/evaluator 中不存在 LLM 痕迹、不存在未登记的跨包组装者。

共享的纯函数下沉而非放宽规则：`DIMS / dim_error / total_error / belief_error` 的权威定义在
`contracts/metrics.py`——"什么叫偏离内心平和"是契约的一部分，三方必须一致，否则世界的动力学
目标、助手的控制目标、评估器的打分标准会各自漂移。`world/dynamics.py` 保留 re-export。

## 3. 关键架构决策

### 3.1 编排者模式（Orchestrator）

世界不"调用"Agent，Agent 也不知道世界的存在。`server`（或 CLI）中的 **Runner** 是唯一的组装点：

1. Runner 从 world 取下一个 `EventContext`（当前时段、活跃事件、用户真实状态摘要——**只给用户 Agent 该看的部分**）；
2. Runner 把上下文交给 user_agent，收集其输出（对话 / 工具调用 / 是否开 session）；
3. 若开启 session，Runner 在 user 与 assistant 之间转发消息，直到用户调用"结束 Session"或达到轮数上限；
4. Runner 将 turn 记录（含 world 提供的 `x_true` 与 assistant 提供的 `x_hat`）写入日志；
5. 时段结束，world 结算状态，推进时钟。

**好处**：被测 assistant 的接入面只有一个消息协议；world 可以在完全没有 LLM 的环境下做单测（规则回放模式）；evaluator 可以在没有 world 的环境下重放旧日志。

### 3.2 状态–表达解耦

- 状态向量 `x` 的唯一写入方是 world 的结算器；
- user_agent 接收 `x` 的**语义化摘要**（如"你现在很疲惫、压力大、有点饿"）而非原始数值——数值表达由 world 的规则翻译器生成，防止用户 LLM 精确"报数"，也防止它反推并篡改状态；
- user_agent 的输出只有：对话文本、工具调用、求助/结束决策。**任何输出都不会直接改变 x**。

### 3.3 助手契约：user_belief

assistant 每产生一轮回复，必须在同一个结构化输出中给出：

```json
{ "reply": "...", "user_belief": { "valence": 0.4, "energy": 0.25, "satiety": 0.3, "stress": 0.75 } }
```

- `user_belief` 即估计向量 `x̂`，是观测器考点；
- 该要求写进 assistant 的系统提示词与 JSON Schema 校验；缺字段 = 该 turn 记为契约违约（计入行为指标）；
- 评测矩阵 E2（测 Harness）时，参考 Model 固定， Harness 的记忆/估计策略自由发挥，但输出通道不变。

### 3.4 无限生成与有限评估

- world 的事件流是 seed 派生的确定性随机流，可无限延展；
- 评估按 `system.toml [eval].window_days` 滑动窗口持续结算；
- 跨系统对比时截取 `run.days` 长度的 episode。

## 4. 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 语言 | Python ≥ 3.11 | 生态 + `tomllib` 标准库读配置 |
| 契约 | pydantic v2 | schema 校验 + JSON Schema 导出（喂给 LLM 的结构化输出） |
| LLM 客户端 | `openai` SDK（OpenAI 兼容协议） | Moonshot/DeepSeek/vLLM 均兼容 |
| 后端 | FastAPI + WebSocket | 运行控制 + 实时 turn 推送 |
| 前端 | React + Vite + Tailwind + Recharts | 沿用已验证的 demo 设计语言 |
| 测试 | pytest | 确定性测试（同 seed 同轨迹） |

## 5. 运行模式

1. **规则回放模式**（无 LLM）：world 用规则脚本扮演用户与助手（三档 quality），用于世界/评估器开发与 CI。
2. **真实运行模式**：两个 LLM 上线，完整 benchmark。
3. **离线评估模式**：`eval` 子命令对历史 runs 重算指标（评估器迭代不必重跑 LLM，省钱）。

## 6. 实现备注

- 依赖规则已 CI 化（`tests/test_dependency_rules.py`）。第三轮迭代前该规则实际已被违反：
  `agents/scripted.py` 与 `evaluator/*` 都直接 import 了 `world.dynamics`，`scripted.py` 还在
  函数内延迟 import `world.catalog`。修复方式是把共享纯函数下移进 contracts，并让 Runner
  注入恢复目录（而非让 agents 自己去世界里取）。
- Runner 位于 `usersim/runner.py`，是组装点之一（其余为 server / bench / cli）。
- 规则回放（`run_replay`）与真实运行（`run_live`）两种模式均已落地；离线评估 `python -m usersim eval <run_dir>` 可用。
- 编排中发现并解决的一个语义问题：恢复事件在"当时段即时生效"（一个时段长达数小时，助手建议在此时段内落地），与动力学即时控制语义一致。
