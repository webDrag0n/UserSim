# ARCHITECTURE.md — UserSim 架构总览（当前态）

> 本文是全系统架构的速览与决策记录，面向刚接手的人。
> 逐模块的深入设计在 `docs/`（唯一方案来源）；协作边界与命令在 `AGENT.md`。
> 本文只讲三件事：**系统怎么分层、组件怎么通信、关键决策为什么这么做**。

## 一句话定位

UserSim 是一个**长程用户–手机助手模拟与 Benchmark 系统**：纯规则世界模拟器产生
确定轨迹，世界里只放两个 LLM（用户模拟 agent + 被测助手 agent），评估器把
"维持用户内心平和"当作闭环控制问题，用控制论指标离线打分。

## 分层与目录映射

```
┌─────────────────────────────────────────────────────────┐
│ agents/（可插拔实现目录：与外部 agent 同协议接入）           │
│   user/       config.toml + profiles/ + standard/（标准 LLM 用户）│
│   assistant/  config.toml + profiles/ + reference/ + reference_nomem/ + stub/  │
│   */profiles/*.toml  可插拔实现（增删文件即增删）               │
├─────────────────────────────────────────────────────────┤
│ usersim/（benchmark 核心，不依赖 agents/）                 │
│   agents/      接口框架层（Harness 协议 + CLI 驱动 + 轮询装配）│
│   runner.py    唯一编排者：转发消息、结算、落盘             │
│   gateway.py   AgentBroker + /api/agent/*（agent 接入面）  │
│   world/       时钟、事件、状态动力学、结算（0 LLM）         │
│   evaluator/   控制论指标、滑窗、报告（0 LLM）              │
│   contracts/   全部跨组件消息 schema（pydantic）            │
│   llm/         LLM 客户端（唯一允许联网处）                 │
│   bench/       多 seed 批量 + 置信区间 + 已知组效度检验      │
│   server/      FastAPI 后端（运行控制 + WebSocket）         │
├─────────────────────────────────────────────────────────┤
│ skills/      外部 agent 接入 skill（agentskills 格式）     │
│ web/         React + Vite + Tailwind + Recharts 前端      │
│ config/      llm.toml（密钥注册表）+ system.toml（系统参数）│
└─────────────────────────────────────────────────────────┘
```

## 数据流（一个 slot）

1. World 推进时钟，产生事件与语义化感受（felt_state，状态–表达解耦：
   原始数值 `x` 只有 World/Evaluator 可见，agent 只拿到自然语言摘要）；
2. Runner 经 **AgentBroker** 向用户 agent 提交 `plan_slot → decide_open → speak`
   请求序列（`agents/user/standard/agent.py` 里 = LLM 意图规划（plan，prompt v6）
   + LLMUserAgent + UserMemory）；
3. 有 session 时，Runner 向助手 agent 提交 `on_turn`（payload = `HarnessObs`，
   被测件可见信息的全部），助手必须回 `AssistantTurn`（`reply` + 必填 `user_belief`
   + `tool_calls`）；
4. Runner 执行工具调用（World 产生结果，下轮回传）、结算状态动力学、
   把整轮写入 append-only JSONL；
5. 离线阶段 Evaluator 只消费结构化日志（**从不读对话文本**），
   计算 e_ss / t_s / M_p / IAE / ISE / ITAE / σ² / ‖x−x̂‖ / 画像误差。

## agent 接口（benchmark 与 agent 的边界）

物理形态：agent 侧长轮询 `GET /api/agent/pending`，处理后 `POST /api/agent/respond`。
demo agent 与外部 agent（OpenClaw、Hermes 等）走**完全相同的协议**，只是 transport
不同：demo 在本进程走 ASGI 回环（不开端口），外部 agent 走真实 HTTP。

- 信封：`AgentRequest{request_id, run_id, role, type, payload, agent_state}` /
  `AgentResponse{request_id, result, agent_state, persona_hat?, error?}`；
- **agent_state**：benchmark 对 agent 无状态的钥匙——每 `(run_id, role)` 一份不透明
  JSON blob，请求带回、响应更新、run 结束存档、续跑回灌。外部 agent 可以零本地状态；
- 失败语义：超时/异常/schema 不符按角色记 degraded 或契约违约，**世界推进从不
  因 agent 失败而中断**；
- 契约权威定义：`usersim/contracts/agent_api.py`；语义说明：`docs/15-agent-api.md`；
  接入教学：`skills/usersim-*/SKILL.md`（可运行时经 `GET /api/agent/skill/{role}` 自举拉取）。

## 不可违背的依赖方向

```
contracts ← world / evaluator / agents / llm
contracts + world + evaluator ← runner（禁 agents）
contracts + llm + config + gateway ← agents（禁 world/evaluator/server/bench/runner）
一切 ← server / bench / cli（组装点）
```

由 `tests/test_dependency_rules.py` 用 AST 静态扫描强制（含函数内延迟 import）。
world 与 evaluator **0 LLM**；评分器只消费结构化日志。

## 运行模式：live 唯一

R4 起系统只有 **live** 一种运行模式：用户与助手都是经 agent 接口接入的真实
agent（demo 或外部实现）。曾经的 replay 模式（`usersim/scripted.py` 三档脚本
good/mid/poor，0 LLM，同 seed 逐字节复现）已彻底下线——0-token 回归手段改为
pytest（纯函数 / 合成 fixture / World 直驱单测）；已知组效度检验（known-groups
validity）迁移到 live 阳性/阴性对照
**reference vs stub**（见 `docs/12-benchmark.md` 第 4 节）。

## 关键决策与理由

1. **编排者模式**：World 不调 Agent，Agent 不知道 World；Runner 是唯一组装点。
   被测件接入面因此只有一个消息协议，World 可在无 LLM 环境单测。
2. **状态–表达解耦**：`x` 的唯一写入方是 World 结算器；agent 收语义摘要。
   防止用户 LLM "报数"，也防止它反推篡改状态；对助手保持估计难度。
3. **agent 接口外置（2026-08 两轮重构）**：
   - 第一轮：live agent 接入从"runner 进程内 import Harness"改为 AgentBroker +
     HTTP 轮询，runner 不再 import 任何 live agent 实现 → benchmark 与 agent 解耦，
     OpenClaw/Hermes 等可直接接入；
   - 第二轮：demo agent 从 `usersim/agents/` 迁出为顶层独立 `agents/` 包，
     agent 自己的 LLM 绑定与行为参数随包走（`agents/<role>/config.toml`），
     `config/llm.toml` 退化为纯 provider 端点/密钥注册表；随后接口框架层
     （Harness 协议 / CLI 驱动 / 轮询客户端 / registry）回迁 `usersim/agents/`，
     顶层 `agents/` 只保留可插拔实现（`profiles/*.toml` + 实现包）→ usersim
     核心不再携带任何 agent 实现与 agent 配置。
   - 例外（已随 R4 消失）：当时 replay 的 `scripted.py` 是 0-LLM 仿真逻辑
     （三档对照组是实验设计的一部分），留在 usersim 内；R4 replay 模式下线后
     该文件已删除，usersim 核心不再携带任何 agent 实现或仿真脚本。
4. **Harness 仍是进程内抽象**：demo assistant 包装 registry 里的 Harness
   （reference/reference_nomem/stub），跨进程/跨语言的接入面是 agent 接口；`HarnessObs` 是
   被测件可见信息的封闭集，需要世界信息时由 Runner 注入（如恢复动作目录）。
5. **实现即配置文件（可插拔）**：`agents/<role>/profiles/*.toml` 是可选
   agent 实现的全部清单——reference/reference_nomem/stub 是 `type=package` 的实现包
   （importlib 导入 `agents/assistant/<name>/` 调 `create(client)`），
   openclaw/hermes 等 `type=cli` 走通用 CLI 驱动（argv 模板 + key/resume 会话策略 +
   输出提取，全部在 toml 里声明）。增删一个 toml 就增删一个可选实现；
   assistant 与 user 两侧对称。
6. **评估 = 控制论**：不评对话"好不好"，评"有没有把用户控制在设定点容差带内"——
   指标、滑窗结算、报告全部离线、纯规则、可复现。
7. **可复现性凭证**：每次 run 落 `meta.json`（seed、config_hash、prompt_versions、
   harness 接入方式）；随机性一律来自 world 的种子流，agent 侧不得自行 `random.*`。

## 深入阅读顺序

`docs/00-architecture.md`（总）→ `docs/15-agent-api.md`（接入）→
`docs/01-world.md` / `docs/02-user-agent.md` / `docs/03-assistant-agent.md` /
`docs/04-evaluator.md`（分模块）→ `docs/05-contracts.md`（消息 schema）。
