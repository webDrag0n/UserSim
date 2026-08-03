# AGENT.md — UserSim 项目协作规约

> 本文件面向在本仓库中工作的 AI 编码 Agent 与人类开发者。
> 读完本文件再动手；其中"不可违背的边界"一节优先级高于一切临时需求。

## 项目是什么

UserSim 是一个**长程用户–手机助手模拟与 Benchmark 系统**：

- 一个**纯规则的世界模拟器**按确定规则运转（时钟 / 事件 / 状态动力学 / 结算），可由 seed 无限生成轨迹；
- 世界里只放两个 LLM：**用户模拟 Agent**（把真实状态表达为对话与求助）和**助手 Agent**（被测件，对话 + 维护对用户的估计）；
- 每个 turn 全量记录：对话、真实状态向量 `x`、助手估计向量 `x̂`、工具调用；
- **评估器**把"维持内心平和"当作闭环控制问题，用控制论指标（e_ss / t_s / M_p / IAE / ISE / ITAE / σ² / ‖x−x̂‖）离线评估轨迹。

设计背景见 `docs/00-architecture.md`，前身设计稿见仓库外 `../DESIGN.md`。

## 不可违背的边界（第一公理）

1. **`world/` 与 `evaluator/` 禁止任何 LLM 调用、禁止 import agents 包。**
   需要"理解语言"的逻辑一律不得进入这两个包；评分器从不阅读对话文本，只消费结构化日志。
2. **用户 Agent 不能改写自己的状态向量。** 状态转移只发生在 `world/`（差分方程 + 事件效果表）。
3. **四个组件（world / user_agent / assistant_agent / evaluator）只能通过 `contracts/` 中的消息 schema 通信。**
   禁止跨包直接 import 实现类；新增跨组件字段必须先改 `contracts/` 与 `docs/05-contracts.md`。

## 仓库结构（目标态）

```
usersim/
  AGENT.md                ← 本文件
  config/
    llm.toml              ← LLM 端点/密钥/角色绑定（含密钥，禁止外传）
    system.toml           ← 世界/动力学/评估/服务参数
  docs/                   ← 实现方案文档（先设计后编码，持续补写）
  usersim/                ← Python 包
    contracts/            ← 全部跨组件消息 schema（pydantic）
    world/                ← 时钟、事件引擎、状态动力学、结算器（0 LLM）
    agents/
      user/               ← 用户模拟 Agent（LLM × 1）
      assistant/          ← 助手 Agent 抽象 + 参考 Harness（LLM × 1）
    evaluator/            ← 控制论指标、滑窗结算、报告（0 LLM）
    llm/                  ← LLM 客户端（读 config/llm.toml，唯一允许联网处）
    server/               ← FastAPI 后端（运行控制 + WebSocket 推送）
    cli.py                ← python -m usersim 入口
  web/                    ← React + Vite 前端
  runs/                   ← 运行产物（JSONL 轨迹 + 报告，gitignore）
  tests/
```

## 配置规约

- **密钥只进 `config/llm.toml`**（或同名环境变量覆盖）；代码里禁止硬编码任何 token。
- 系统行为参数只进 `config/system.toml`；代码内默认值与文件注释保持一致。
- 两个文件都用 TOML：Python 3.11+ 可用标准库 `tomllib` 直接读取，不引第三方依赖。

## 运行命令

```bash
./start.sh                                    # 一键启动（自动备环境+构建前端+开浏览器），Ctrl+C 停止
python -m usersim run --mode replay --days 30 # 规则回放
python -m usersim run --mode live --days 30   # 真实 LLM
python -m usersim continue runs/<run_id> --extra-days 10   # 续跑
python -m usersim eval runs/<run_id>          # 离线重算指标
python -m usersim serve                       # 仅启动后端（托管 web/dist）
cd web && npm run dev                         # 前端开发模式（代理到 8610）
```

## 编码约定

- Python ≥ 3.11；类型注解全覆盖；跨组件数据一律用 `contracts/` 的 pydantic 模型。
- 随机性一律来自 `world` 的种子流（`numpy.random.Generator` 派生），agents 侧不得自行 `random.*`。
- 日志为 append-only JSONL，一行一个 turn 事件；schema 变更必须向后兼容（加字段，不改语义）。
- 测试分层：`tests/world`（确定性：同 seed 同轨迹）、`tests/evaluator`（指标对拍）、`tests/contracts`（schema 兼容）。

## 文档规约

- `docs/` 是唯一的方案来源；先写/改文档，再实现对应代码。
- 每篇文档头部维护 `状态: 草稿 | 已定稿 | 已实现`；实现完成后回填"实现备注"一节。
- 新文档加入 `docs/README.md` 的地图与进度表。
