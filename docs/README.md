# UserSim 使用指南

UserSim 是一个**用户行为仿真平台**，通过纯规则世界 + LLM 用户 Agent + 被测助手 Agent + 控制论评估器，评测「AI 助手能否让用户的心理状态收敛到平和」。

---

## 快速开始

已装好 [uv](https://astral.sh/uv) 和 Node.js（≥ 20）后，在仓库根目录执行：

```bash
./start.sh
```

脚本会自动创建虚拟环境、安装依赖、构建前端、启动后端，最后打开 `http://127.0.0.1:8610/`。按 `Ctrl+C` 停止。

```bash
./start.sh --rebuild       # 重新构建前端（改了 web/ 后使用）
./start.sh --port 8620     # 换端口（默认 8610）
```

macOS 上也可双击 `start.command`。

> 只想验证世界动力学、不烧 token？跑 0-LLM 测试套件：`pytest -q`
> （纯函数 / 合成 fixture / World 直驱。replay 模式已于 R4 删除，
> 所有 `run` / `bench` 都是 live、都消耗 LLM token。）

---

## 系统架构

```text
                ┌─────────────── World（0 LLM）───────────────┐
                │  时钟 · 事件引擎 · 状态动力学 · 结算器       │
                └───────▲─────────────────────────▲──────────┘
                        │ EventContext              │ TurnLog（落盘）
                        │                          │
         UserAgent（LLM）│                          └── Evaluator（0 LLM）
              ▲  对话消息 │                               离线读取日志，输出报告
              │          │
              ▼          │
         AssistantAgent（LLM，被测件）
                         │
                   Runner（编排器）
```

Runner 是唯一的组装点，负责在 World、UserAgent、AssistantAgent 之间传递消息。World 和 Evaluator 不含任何 LLM 调用。

每个 slot（时段）的执行顺序：

1. 天气转移（每天一次，马尔可夫链驱动）
2. 环境熵增（satiety 衰减、energy 消耗）
3. 需求更新（生物钟调制）
4. 用户侧 LLM 生成意图事件列表（0–3 个；数值不进 prompt，状态-表达解耦）
5. World 补充触发（扰动/高压注入紧急意图）
6. 逐个意图开 session：用户带着意图找助手对话
7. Session 由用户主动调用 `end_session` 结束
8. Session 结束后记录到用户记忆
9. `step_slot()` 推进时间

---

## 三种使用方式

| 方式 | 入口 | 适合场景 |
|------|------|----------|
| Web 界面（推荐） | `./start.sh` | 交互查看、回放、批量对比、配表编辑 |
| 命令行 CLI | `python -m usersim <子命令>` | 脚本化、批量评测、CI、无头环境 |
| 前端开发模式 | `cd web && npm run dev` | 改前端时热更新（需另起后端） |

CLI 前请先激活虚拟环境：`source .venv/bin/activate`，或使用 `uv run python -m usersim …`。

---

## 配置说明

### LLM 配置（live 模式必需）

```bash
cp config/llm.toml.example config/llm.toml
# 编辑 config/llm.toml，填入 provider 密钥
```

所有 provider 走 OpenAI 兼容协议（`/v1/chat/completions`）。`config/llm.toml` 只是
provider 端点/密钥注册表（内置 moonshot / openai / deepseek / local 四个示例端点）：

```toml
[providers.deepseek]
base_url = "https://api.deepseek.com/v1"
api_key  = "sk-在此填入你的-DeepSeek-Key"
model    = "deepseek-chat"
```

**角色绑定在各 agent 自己的配置里**（不属于 llm.toml）：

- `agents/user/config.toml [llm]`：demo 用户 agent 的 provider 引用（默认 `deepseek`）；
- `agents/assistant/config.toml [llm]`：demo 助手 agent 的 provider 引用（默认 `deepseek`）。

密钥也可以用同名环境变量覆盖（优先级高于文件）：`USERSIM_DEEPSEEK_API_KEY` 等。

本地模型（vLLM / Ollama / LMStudio）用 `[providers.local]`，指向本地端点即可。

### 系统参数配置

| 文件 | 管什么 |
|------|--------|
| `config/llm.toml` | LLM provider 端点与密钥注册表（含密钥，不提交，从 `.example` 复制） |
| `agents/<role>/config.toml` | 各 agent 的 LLM 绑定（provider 引用）与行为参数 |
| `config/system.toml` | 时钟、状态动力学、设定点、评估阈值、服务端口 |
| `balance-sheet/UserSim数值配表.xlsx` | 事件、需求、习惯化的数值配表（Web 配表编辑器的数据源） |

`system.toml` 关键段：`[run]`（seed/天数/输出目录）、`[clock]`（每天时段数）、`[state]`（四维设定点 + 容差带半宽）、`[dynamics]`（动力学系数）、`[score]`（健康分权重）。

---

## 常见工作流

### A. 验证世界动力学（不花钱）

```bash
pytest -q    # 0 token：纯函数 / 合成 fixture / World 直驱单测
```

要端到端看轨迹只能跑 live（烧 token）：`python -m usersim run --days 30`，
然后 `./start.sh` 开界面回放该存档。

### B. 评测一个真实助手模型

```bash
# 1. 配 LLM
cp config/llm.toml.example config/llm.toml   # 填 provider 密钥
# 编辑 agents/assistant/config.toml [llm] 选择要测的 provider

# 2. 单次跑，先看对话质量
python -m usersim run --days 30

# 3. 多 seed 批量统计
python -m usersim bench --groups reference --seeds 1-8 --max-episodes 8

# 4. Web「批量评测」看均值 ± CI 与已知组效度检验
./start.sh
```

### C. 前端开发

```bash
python -m usersim serve       # 终端 1：启动后端
cd web && npm run dev         # 终端 2：前端热更新（代理到 8610）
```

### D. 改了评估指标，重算旧数据

```bash
python -m usersim eval runs/<run_id>
```

---

## CLI 子命令

### `run` — 跑一次模拟

```bash
python -m usersim run --days 30                    # live：真实 LLM（烧 token）
python -m usersim run --harness stub --days 5      # 指定被测 Harness
```

| 参数 | 说明 |
|------|------|
| `--days N` | episode 天数 |
| `--seed N` | 全局种子（同 seed 同轨迹） |
| `--harness NAME` | 被测 Harness 名（默认取 `agents/assistant/config.toml` 的 default，当前为 `openclaw`） |
| `--user-impl NAME` | demo 用户实现名（默认取 `agents/user/config.toml` 的 default） |

> R4 起只有 live 一种运行模式：replay 与 `--mode` / `--quality` 已删除，所有 run 都烧 token。

产物写入 `runs/<run_id>/`：`meta.json`、`slots.jsonl`、`turns.jsonl`、`report.json`。
`meta.json` 的 `profiles` 记录本 run 各角色选用的实现（如 `{"user": "standard", "assistant": "openclaw"}`）；
`report.json` 的 `benchmark` 是存档综合分（公式与设计理由见 [04-evaluator](04-evaluator.md) 第 8 节）。

### `bench` — 多 seed 批量评测

```bash
python -m usersim bench --groups reference,stub --seeds 1-8 --days 30 --max-episodes 16
```

恒为 live（烧 token）、按 `--concurrency` 并发（默认取 llm.toml 配置）；必须显式
`--max-episodes` 确认成本（硬上限 20 个**待跑** episode/次——断点续跑/重评估的存量
不计）。已有 `report.json` 的 episode 断点续跑自动跳过（重评估不重复烧 token），
`--bench-id` 复用目录合并多批结果。也可在前端「批量评测」页填参数组合一键启动，
页面实时显示总进度与每个 episode 的天数进度。
输出多 seed 均值 ± 95% CI、判定众数；`--groups` 同时含 reference 与 stub 时产出已知组效度检验
断言（阳性对照 reference 需落在收敛一侧、阴性对照 stub 需落在发散一侧，详见
[12-benchmark](12-benchmark.md) 第 4 节）。

### `eval` — 离线重算指标

```bash
python -m usersim eval runs/<run_id>
```

改了评估器或权重后，不必重跑 LLM，直接对历史 run 重算。

### `continue` — 续跑

```bash
python -m usersim continue runs/<run_id> --extra-days 10
```

仅限 live 存档；旧 replay 存档仍可回放与 eval，但续跑会收到 400。

### `serve` — 仅启动后端

```bash
python -m usersim serve
USERSIM_PORT=8620 python -m usersim serve
```

### `agent` — demo agent 接入运行中的 server

```bash
python -m usersim agent user                             # demo 用户 agent
python -m usersim agent assistant --harness reference    # demo 助手 agent
# 等价 standalone 入口（usersim.agents 包，与外部 agent 完全同路径）：
python -m usersim.agents user --server http://127.0.0.1:8610
python -m usersim.agents assistant --server http://127.0.0.1:8610 --harness reference
```

---

## 测试

```bash
pytest -q            # 全部测试（0 token：纯函数 / 合成 fixture / World 直驱）
```

已知组效度检验的实测（reference vs stub × 多 seed）是手动 live 流程——烧 token、不进 CI，
见 [12-benchmark](12-benchmark.md) 第 4 节。

测试分层：`tests/world`（确定性）、`tests/evaluator`（指标对拍）、`tests/contracts`（schema 向后兼容）、`tests/test_dependency_rules.py`（依赖边界静态扫描）。

---

## 故障排查

| 现象 | 处理 |
|------|------|
| `未找到 uv / npm` | 装 uv（`curl -LsSf https://astral.sh/uv/install.sh \| sh`）和 Node ≥ 20 |
| 端口 8610 已被占用 | `pkill -f 'usersim serve'`，或 `./start.sh --port 8620` |
| live 模式报鉴权/超时 | 检查 `config/llm.toml` 的 `api_key` 与 `base_url` |
| 界面是旧版 | `./start.sh --rebuild` |
| 想看完整 prompt 调试 | `config/llm.toml` 里 `[runtime] log_prompts = true` |
| 老存档字段缺失 | 日志向后兼容（字段只加不删），前端会回退显示，不报错 |

---

## 文档索引

> Agent 接入（demo / 外部 agent 如 OpenClaw、Hermes）见
> [15-agent-api](15-agent-api.md) 与 `skills/usersim-*/SKILL.md`：
> `python -m usersim serve` 后，agent 轮询 `GET /api/agent/pending`、
> 回传 `POST /api/agent/respond` 即可接入。

| # | 文档 | 内容 | 状态 |
|---|------|------|------|
| 00 | [architecture](00-architecture.md) | 四组件架构、依赖规则、编排流程、技术选型 | 已实现 |
| 01 | [world](01-world.md) | 世界模拟器：状态向量、天气、需求动力学、事件引擎、结算器 | 已实现 |
| 02 | [user-agent](02-user-agent.md) | 用户 Agent：LLM 驱动、意图规划、记忆、prompt 结构（脚本模式已随 replay 下线，见文内注记） | 已实现 |
| 03 | [assistant-agent](03-assistant-agent.md) | 助手 Agent / Harness 契约、user_belief 输出、接入规范 | 已实现 |
| 04 | [evaluator](04-evaluator.md) | 评估方法论：三层解耦（世界仿真/用户Agent/助手Agent）、控制论指标、行为一致性M1-M5、画像精度、健康分与判定规则、模型对比协议 | 已实现 |
| 05 | [contracts](05-contracts.md) | 跨组件数据契约（消息 schema 全集） | 已实现 |
| 06 | [frontend](06-frontend.md) | 前端页面结构、后端 API / WebSocket、可视化设计 | 已实现 |
| 08 | [event-catalog](08-event-catalog.md) | 事件配表（事件表 + 统一地点表）与经济系统 | 已实现 |
| 09 | [series-events](09-series-events.md) | 系列事件（旅行/出差/休假/备考）：行程单物化、后效 | 已实现 |
| 11 | [anthropomorphism](11-anthropomorphism.md) | 习惯化曲线、需求动力学、人格调节、Excel 单一数据源 | 已实现 |
| 12 | [benchmark](12-benchmark.md) | 被测件可插拔、可复现性凭证、多 seed 统计、已知组效度检验 | 已实现 |
| 13 | [persona-model](13-persona-model.md) | 大五 30 facet + 结构化喜好 + 画像精度指标 | 已实现 |
| 15 | [agent-api](15-agent-api.md) | Agent 接入接口（HTTP 轮询 + broker）、接入 skill、demo agent、外部 agent（OpenClaw/Hermes）接入 | 已实现 |
