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
              Runner 不直连 agent（live 是唯一运行模式）：所有 agent 调用经
              AgentBroker + HTTP agent 接口（docs/15-agent-api.md），
              demo agent 与外部 agent（OpenClaw、Hermes 等）走同一协议
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

把"真实的人"演出来。经统一 agent 接口接入（demo 或外部实现）：每个 slot 由用户侧
LLM 生成意图（`plan_slot` 请求；状态-表达解耦——需求数值不进 prompt，意图由人格与
felt_state 直接产出），再带着意图找助手开 session（`decide_open` / `speak`）。
收到的是 `felt_state` 语义摘要，看不到原始数值。

### AssistantAgent（LLM，被测件）

经同一 agent 接口接入（`on_turn` 请求，payload 即 HarnessObs），每轮回复必须同时给出
估计向量 `x̂`（`user_belief`）。被测件通过消息协议接入，不感知 World 的存在；
OpenClaw、Hermes 等外部 agent 装载 `skills/usersim-assistant/SKILL.md` 即可接入。

### Evaluator（纯规则）

离线读取 `runs/<run_id>/` 下的日志，计算控制论指标并输出报告。不含 LLM 调用，不回写 World。

---

## 每个 Slot 的执行流程

Runner 每推进一个 slot，按以下顺序执行：

```text
1. 天气转移（每天 slot 0 执行一次，马尔可夫链）
2. 环境熵增（satiety 衰减、energy 消耗）
3. 需求更新（4 个需求 + 生物钟调制：饭点/晚间加强）
4. Runner 向用户 agent 发 plan_slot 请求（携带 urges 等数值 + context 语义上下文），
   用户侧 LLM 生成意图事件列表（0–3 个意图；世界补充触发的紧急意图由用户侧注入）
5. 逐个意图开 session：
      a. Runner 把 UserContext 注入 decide_open / speak 请求
      b. UserAgent 带着意图找 AssistantAgent 对话（on_turn 请求）
      c. Session 任意长度，唯一结束标准是用户调用 end_session
      d. Session 结束后 Runner 发 session_closed 通知，用户 agent 记入自己的记忆
6. step_slot() 结算状态、写日志、推进时钟
```

---

## 依赖规则

各包的 import 边界由 `tests/test_dependency_rules.py` 静态扫描强制：

| 包 | 允许 import | 禁止 import |
|---|---|---|
| `contracts` | 仅 pydantic / 标准库 | 一切业务包 |
| `world` | contracts | agents、evaluator、llm |
| `agents`（顶层独立包） | contracts、llm、config、gateway（+httpx：agent client 轮询） | world、evaluator、server、bench、runner |
| `evaluator` | contracts | world、agents、llm |
| `server` / `bench` / `cli` | world、agents、evaluator、contracts | —（组装点） |
| `runner` | world、evaluator、contracts | agents（live agent 只经 AgentBroker 接入） |

单文件级补充边界（同由依赖测试强制）：

- **`runner.py` 禁止 import 任何 live agent 实现**（顶层 `agents` 包）——live agent
  只经 `AgentBroker` 接入；R4 起 replay 与 `usersim/scripted.py`（0 LLM 脚本）已删除，无例外。
- **`gateway.py`（AgentBroker + agent 端点）只依赖 contracts**（+config 取 PROJECT_ROOT），
  不得 import world / agents / evaluator / llm。

共享纯函数（`DIMS`、`dim_error`、`total_error`、`belief_error`）的权威定义在 `contracts/metrics.py`，三方必须引用同一份，避免评分标准漂移。

---

## 关键架构决策

### 编排者模式

World 不调用 Agent，Agent 不知道 World 的存在。Runner 是唯一的组装点，负责在组件之间转发消息。好处：被测 AssistantAgent 的接入面只有一个消息协议；World 可在无 LLM 的环境下做单测。

live（唯一运行模式）下该协议物理化为 **agent 接口**（docs/15-agent-api.md）：Runner 经
AgentBroker 提交 `plan_slot / decide_open / speak / on_turn` 等请求，agent 侧以
HTTP 长轮询接入（demo agent 走 ASGI 回环，外部 agent 走真实 HTTP，同一份协议）。
Runner 因此不再 import 任何 live agent 实现，benchmark 与 agent 完全解耦。

### 状态–表达解耦

状态向量 `x` 的唯一写入方是 World 的结算器。UserAgent 接收的是语义化摘要（如"你现在很疲惫、压力大"），而非原始数值。这防止用户 LLM 精确"报数"，也防止它反推并篡改状态。

### 助手契约：user_belief

AssistantAgent 每轮回复必须同时输出估计向量：

```json
{ "reply": "...", "user_belief": { "valence": 0.4, "energy": 0.25, "satiety": 0.3, "stress": 0.75 } }
```

缺字段的 turn 记为契约违约，计入行为指标。

### 意图驱动 session

Session 的触发由用户侧意图主导（而非 World 强制触发）。每个 slot 由用户侧 LLM
生成 0–3 个意图（prompt v3：意图由人格与 felt_state 直接产出，需求数值不进
prompt——状态-表达解耦），用户带着意图找助手对话。World 只在高压场景下注入紧急
意图作为补充。

---

## 运行模式：live 唯一

R4 起系统只有 **Live** 一种运行模式：UserAgent 与 AssistantAgent 均调用真实 LLM，
经 agent 接口接入（demo 或外部实现）。原 Replay 模式（0 LLM、三档脚本用户/助手
good/mid/poor，`usersim/scripted.py`，同 seed 逐字节复现）已彻底删除；验证世界
动力学与 CI 回归改由 pytest（纯函数 / 合成 fixture / World 直驱，0 token）承担，
量程守护迁移至 live 锚点对 reference vs stub（见 docs/12-benchmark.md 第 4 节）。

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

- Runner 位于 `usersim/runner.py`（R4 起仅 live 编排；原 `run_replay` 已随 replay 模式一并删除）。
- live 模式的 agent 接入已解耦（docs/15-agent-api.md）：`usersim/gateway.py`
  AgentBroker + `/api/agent/*` 端点；demo agent 的装配与轮询在接口框架层
  `usersim/agents/`（`usersim/agents/demo.py / usersim/agents/client.py`），可插拔实现
  在顶层 `agents/`（如 `agents/user/standard/agent.py`），与外部
  agent 同一协议；`skills/usersim-*/SKILL.md` 是外部 agent（OpenClaw、Hermes 等）的接入说明。
- 离线评估：`python -m usersim eval <run_dir>` 可用。
- 依赖规则已 CI 化（`tests/test_dependency_rules.py`），用 `ast` 静态扫描全部 import，含函数内延迟 import；含 runner/gateway 的单文件级边界。
- `contracts/metrics.py` 是"偏离平和"定义的权威位置，`world/dynamics.py` 保留 re-export。
