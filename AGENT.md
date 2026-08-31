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
   该规则由 `tests/test_dependency_rules.py` 静态检查强制（含函数内延迟 import）。
   共享的纯函数（如 `dim_error`）下移进 `contracts/metrics.py`，而不是放宽规则。
4. **live agent 只经 agent 接口接入（docs/15-agent-api.md）。** `runner.py` 不得 import
   任何 live agent 实现（顶层 `agents` 包）；demo agent 与外部 agent
   （OpenClaw、Hermes 等）都经 AgentBroker + `/api/agent/*` 轮询接入，同一协议。
   （R4 起 replay 模式与 `usersim/scripted.py` 已彻底删除，本条边界不再有例外。）
5. **被测 Harness 只能看到 `contracts.HarnessObs`。** 不得读取 `runs/` 日志、不得访问用户侧
   prompt、不得 import world/evaluator；需要世界信息时由 Runner 注入（如恢复动作目录）。

## 仓库结构（目标态）

```
usersim/
  AGENT.md                ← 本文件
  .claude/skills/         ← vendor 进来的外部 skill（见"Skills"一节，来源记录在其 README.md）
  config/
    llm.toml              ← LLM provider 端点/密钥注册表（含密钥，禁止外传；角色绑定在各 agent 文件夹）
    system.toml           ← 世界/动力学/评估/服务参数
  docs/                   ← 实现方案文档（先设计后编码，持续补写）
  agents/                 ← 可插拔实现插件目录（usersim 外的实现；与外部 agent 同协议接入）
    user/                 ← config.toml（default + [llm] 绑定）+ profiles/（一个 .toml 一个实现）
      standard/           ← 标准 LLM 用户实现包（agent.py 接入壳 + llm_user.py 规划/表演 + expression.py 表达直白度 + memory）
    assistant/            ← config.toml + profiles/（reference/reference_nomem/stub/openclaw/hermes.toml）
      reference/          ← 参考实现包（ReferenceHarness，prompt v5.4：状态跟踪+日程记忆+多变量带中心控制+私信腔/助手身份条款）
      reference_nomem/    ← 消融对照包（NoMemHarness：与 reference 同 prompt 减跨 session 记忆）
      stub/               ← 失能对照实现包（StubHarness）
  usersim/                ← Python 包（benchmark 核心）
    agents/               ← agent 接口框架层：base（Harness 协议）、profile（ProfileTracker）、
                            cli_agent（通用 CLI 驱动）、demo/client（装配与轮询）、
                            config/registry（profiles 加载与注册）、__main__（standalone 入口）
    contracts/            ← 全部跨组件消息 schema（pydantic；含 agent_api wire 协议）
    world/                ← 时钟、事件引擎、状态动力学、结算器（0 LLM）
    evaluator/            ← 控制论指标、滑窗结算、报告（0 LLM）
    bench/                ← 多 seed 批量、置信区间、量程守护（0 LLM，组装点）
    gateway.py            ← AgentBroker + /api/agent/* 端点（仅依赖 contracts）
    llm/                  ← LLM 客户端（唯一允许联网处）
    server/               ← FastAPI 后端（运行控制 + WebSocket 推送 + agent 接入端点）
    cli.py                ← python -m usersim 入口
  skills/                 ← 外部 agent 接入 skill（usersim-assistant / usersim-user）
  web/                    ← React + Vite 前端
  runs/                   ← 运行产物（JSONL 轨迹 + 报告，gitignore）
  tests/
```

## 配置规约

- **密钥只进 `config/llm.toml`**（或同名环境变量覆盖）；代码里禁止硬编码任何 token。
- 系统行为参数只进 `config/system.toml`；代码内默认值与文件注释保持一致。
- **agent 自身的参数进 `agents/<role>/config.toml`**：LLM 绑定（`[llm] provider` 引用
  llm.toml 的 provider 注册表，密钥仍只在 llm.toml/环境变量）与顶层 `default` 默认实现。
- **agent 实现是可插拔的配置文件**：`agents/<role>/profiles/*.toml`，一个文件
  一个实现（含 type 与实现自有参数，如 cli 驱动的 argv/会话/输出描述、用户的行为参数，
  或覆盖角色默认的 `[llm]` 绑定）。增删文件即增删可供选择的实现，无需改代码。
- 两个文件都用 TOML：Python 3.11+ 可用标准库 `tomllib` 直接读取，不引第三方依赖。

## 运行命令

```bash
./start.sh                                    # 一键启动（自动备环境+构建前端+开浏览器），Ctrl+C 停止
python -m usersim run --days 30               # live：真实 LLM（demo agent 经 ASGI 回环接入；烧 token）
python -m usersim run --harness stub --days 5 # 指定被测 Harness
python -m usersim bench --groups reference,stub --seeds 1-8 --days 30 --max-episodes 16  # 批量评测（恒 live，需显式确认成本）
python -m usersim continue runs/<run_id> --extra-days 10   # 续跑（仅 live 存档；旧 replay 存档返回 400）
python -m usersim eval runs/<run_id>          # 离线重算指标（不烧 token）
python -m usersim serve                       # 仅启动后端（托管 web/dist + /api/agent/*）
python -m usersim agent user                  # demo 用户 agent 接入运行中的 server
python -m usersim agent assistant --harness reference  # demo 助手 agent（与外部 agent 同路径）
python -m usersim.agents user --server http://127.0.0.1:8610   # 等价 standalone 入口（独立进程）
python -m usersim.agents assistant --server http://127.0.0.1:8610 --harness reference
cd web && npm run dev                         # 前端开发模式（代理到 8610）
```

外部 agent（OpenClaw、Hermes 等）接入：装载 `skills/usersim-*/SKILL.md`，
以 `user_agent`/`assistant_agent=external` 发起 run 后轮询 `/api/agent/pending`
（详见 `docs/15-agent-api.md`）。

测试全部为 0-token：纯函数、合成 fixture 与 World 直驱单测，无任何 LLM 调用。

```bash
pytest -q            # 全部测试（0 token）
```

量程守护的实测（live 锚点对 reference vs stub × 多 seed）是**手动 live 流程**——
烧 token、不进 CI：
`python -m usersim bench --groups reference,stub --seeds 1-8 --days 30 --max-episodes 16`
（断言与产物见 `docs/12-benchmark.md` 第 4 节）。

## 编码约定

- Python ≥ 3.11；类型注解全覆盖；跨组件数据一律用 `contracts/` 的 pydantic 模型。
- 随机性一律来自 `world` 的种子流（`numpy.random.Generator` 派生），agents 侧不得自行 `random.*`。
- 日志为 append-only JSONL，一行一个 turn 事件；schema 变更必须向后兼容（加字段，不改语义）。
- 测试分层：`tests/world`（确定性：同 seed 同轨迹）、`tests/evaluator`（指标对拍）、`tests/contracts`（schema 兼容）。

## Skills

`.claude/skills/` 下有 9 个从外部仓库 vendor 进来的项目级 skill，随仓库提交。
来源仓库、commit SHA、license 与逐个说明见 `.claude/skills/README.md`；
重新拉取上游用 `bash scripts/update-skills.sh`。

- **`karpathy-guidelines`** —— LLM 编码行为约束（先思考再编码 / 简单优先 / 外科手术式改动 /
  目标驱动执行）。与本文件"先设计后编码"同向，写 Python 侧代码时也适用。
- **前端设计工程（8 个，来自 emilkowalski/skills）** —— 只在动 `web/` 时有意义，
  与"`world/` 与 `evaluator/` 禁止 LLM 调用"等 Python 侧边界互不干扰。
  自动触发：`apple-design`、`emil-design-eng`、`animation-vocabulary`、
  `find-animation-opportunities`、`improve-animations`。
  仅手动 `/` 调用：`pick-ui-library`、`prototype`、`review-animations`。

两点注意：

- **不要就地编辑 `.claude/skills/` 下的文件**，会被同步脚本覆盖；项目专属规约写进本文件。
- `improve-animations` 会往仓库根的 `plans/` 写实施计划（目前无此目录，首次使用会新建）。
  这类产物是过程文件，不属于 `docs/`；`docs/` 仍是唯一的方案来源。

## 文档规约

- `docs/` 是唯一的方案来源；先写/改文档，再实现对应代码。
- 仓库根另有四份入口文档：本文件（协作边界）、`ARCHITECTURE.md`（架构速览与决策）、
  `DEVELOPMENT.md`（开发指南与踩坑记录）、`SKILLS.md`（skill 体系与设计经验）——
  它们是导航与经验沉淀，不替代 `docs/` 的方案细节。
- 每篇文档头部维护 `状态: 草稿 | 已定稿 | 已实现`；实现完成后回填"实现备注"一节。
- 新文档加入 `docs/README.md` 的地图与进度表。
