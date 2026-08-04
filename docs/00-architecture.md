# 00 · 总体架构

UserSim = **纯规则世界** + **两个 LLM Agent**（用户模拟 + 被测助手）+ **纯规则控制论评估器**，用控制论指标评测「助手能否让用户的心理状态收敛到内心平和」。

---

## 四个组件

```text
            ┌──────────────────────── World（0 LLM）────────────────────────┐
            │  时钟  事件引擎  状态动力学  结算器  天气  需求  日志写入       │
            └───────▲───────────────────────────────────────────▲──────────┘
                    │ UserContext / ToolResult                   │ TurnLog（落盘）
                    │                                            │
   UserAgent（LLM）─┘                                            └──── Evaluator（0 LLM）
        ▲  SessionChannel 消息                                        离线读取 runs/*.jsonl
        ▼                                                              输出报告，永不回写世界
   AssistantAgent（LLM，被测件）

              以上四者由 Runner（编排器）组装，Runner 是唯一的组装点
```

### World（纯规则）

维护用户状态向量 `x = [valence, energy, satiety, stress] ∈ [0,1]⁴`，按时段（slot）结算。包含：

- 双层时钟（外层 slot、内层 session turn）
- 天气系统（马尔可夫链，5 种天气，每天转移）
- 需求动力学（4 个需求 + 生物钟调制）
- 事件引擎（模板/扰动/恢复三类事件）
- 习惯化曲线（重复事件效果递减）
- `felt_state` 翻译器（数值 → 语义摘要）

### UserAgent（LLM 驱动）

把"真实的人"演出来。每个 slot 由 UserPlanner 根据需求 urges 选出意图，再带着意图找助手开 session。收到的是 `felt_state` 语义摘要，看不到原始数值。

### AssistantAgent（LLM，被测件）

通过 Harness 接入，每轮回复必须同时给出估计向量 `x̂`（`user_belief`）。被测件通过消息协议接入，不感知 World 的存在。

### Evaluator（纯规则）

离线读取 `runs/<run_id>/` 下的日志，计算控制论指标并输出报告。不含 LLM 调用，不回写 World。

---

## 每个 Slot 的执行流程

Runner 每推进一个 slot，按以下顺序执行：

```text
1. 天气转移（每天 slot 0 执行一次，马尔可夫链）
2. 环境熵增（satiety 衰减、energy 消耗）
3. 需求更新（4 个需求 + 生物钟调制：饭点/晚间加强）
4. UserPlanner 根据 urges 选出意图事件列表（0–3 个意图）
5. World 补充触发（扰动/高压注入紧急意图）
6. 逐个意图开 session：
      a. Runner 把 UserContext 注入 UserAgent
      b. UserAgent 带着意图找 AssistantAgent 对话
      c. Session 任意长度，唯一结束标准是用户调用 end_session
      d. Session 结束后记录到 UserMemory
7. step_slot() 结算状态、写日志、推进时钟
```

---

## 依赖规则

各包的 import 边界由 `tests/test_dependency_rules.py` 静态扫描强制：

| 包 | 允许 import | 禁止 import |
|---|---|---|
| `contracts` | 仅 pydantic / 标准库 | 一切业务包 |
| `world` | contracts | agents、evaluator、llm |
| `agents/*` | contracts、llm | world、evaluator |
| `evaluator` | contracts | world、agents、llm |
| `server` / `bench` / `runner` / `cli` | world、agents、evaluator、contracts | —（组装点） |

共享纯函数（`DIMS`、`dim_error`、`total_error`、`belief_error`）的权威定义在 `contracts/metrics.py`，三方必须引用同一份，避免评分标准漂移。

---

## 关键架构决策

### 编排者模式

World 不调用 Agent，Agent 不知道 World 的存在。Runner 是唯一的组装点，负责在组件之间转发消息。好处：被测 AssistantAgent 的接入面只有一个消息协议；World 可在无 LLM 的环境下做单测。

### 状态–表达解耦

状态向量 `x` 的唯一写入方是 World 的结算器。UserAgent 接收的是语义化摘要（如"你现在很疲惫、压力大"），而非原始数值。这防止用户 LLM 精确"报数"，也防止它反推并篡改状态。

### 助手契约：user_belief

AssistantAgent 每轮回复必须同时输出估计向量：

```json
{ "reply": "...", "user_belief": { "valence": 0.4, "energy": 0.25, "satiety": 0.3, "stress": 0.75 } }
```

缺字段的 turn 记为契约违约，计入行为指标。

### 意图驱动 session

Session 的触发由用户侧 UserPlanner 主导（而非 World 强制触发）。UserPlanner 每个 slot 根据需求 urges 进行多目标优化，选出 0–3 个意图事件，用户带着意图找助手对话。World 只在高压场景下注入紧急意图作为补充。

---

## 两种运行模式

| 模式 | 触发方式 | 用途 |
|------|----------|------|
| **Replay（规则回放）** | 0 LLM，三档脚本用户（good/mid/poor）| 验证世界动力学、CI、调参 |
| **Live（真实 LLM）** | UserAgent + AssistantAgent 均调用 LLM | 完整 benchmark |

Replay 模式确定性：同 seed 逐字节复现。

---

## 技术选型

| 层 | 选型 | 理由 |
|---|---|---|
| 语言 | Python ≥ 3.11 | 生态 + `tomllib` 标准库读配置 |
| 契约 | pydantic v2 | schema 校验 + JSON Schema 导出 |
| LLM 客户端 | `openai` SDK（OpenAI 兼容协议） | Moonshot / DeepSeek / vLLM 均兼容 |
| 后端 | FastAPI + WebSocket | 运行控制 + 实时 turn 推送 |
| 前端 | React + Vite + Tailwind + Recharts | Cockpit 全景 + 双主题 |
| 测试 | pytest | 确定性测试（同 seed 同轨迹） |

---

## 实现备注

- Runner 位于 `usersim/runner.py`，`run_replay` 与 `run_live` 两种模式均已落地。
- 离线评估：`python -m usersim eval <run_dir>` 可用。
- 依赖规则已 CI 化（`tests/test_dependency_rules.py`），用 `ast` 静态扫描全部 import，含函数内延迟 import。
- `contracts/metrics.py` 是"偏离平和"定义的权威位置，`world/dynamics.py` 保留 re-export。
