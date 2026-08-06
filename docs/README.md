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

> 只想验证世界动力学、不调 LLM？直接：
> `python -m usersim run --mode replay --days 30`（0 token，秒级出结果）

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
4. UserPlanner 根据 urges 选出意图事件列表（0–3 个）
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

所有 provider 走 OpenAI 兼容协议（`/v1/chat/completions`）。内置 moonshot / openai / deepseek / local 四个示例端点，默认 `deepseek`：

```toml
default_provider = "deepseek"

[providers.deepseek]
base_url = "https://api.deepseek.com/v1"
api_key  = "sk-在此填入你的-DeepSeek-Key"
model    = "deepseek-chat"

[roles.user_agent]       # 用户模拟 Agent
provider = "deepseek"
[roles.assistant_agent]  # 被测助手 Agent
provider = "deepseek"
[roles.reference_user]   # 参考对照用户（建议低温）
provider    = "deepseek"
temperature = 0.3
```

密钥也可以用同名环境变量覆盖（优先级高于文件）：`USERSIM_DEEPSEEK_API_KEY` 等。

本地模型（vLLM / Ollama / LMStudio）用 `[providers.local]`，指向本地端点即可。

### 系统参数配置

| 文件 | 管什么 |
|------|--------|
| `config/llm.toml` | 模型端点、密钥、角色绑定（含密钥，不提交，从 `.example` 复制） |
| `config/system.toml` | 时钟、状态动力学、设定点、评估阈值、服务端口 |
| `balance-sheet/UserSim数值配表.xlsx` | 事件、需求、习惯化的数值配表（Web 配表编辑器的数据源） |

`system.toml` 关键段：`[run]`（seed/天数/输出目录）、`[clock]`（每天时段数）、`[state]`（四维设定点 + 平和带半宽）、`[dynamics]`（动力学系数）、`[score]`（健康分权重）。

---

## 常见工作流

### A. 验证世界动力学（不花钱）

```bash
python -m usersim run --mode replay --days 30
./start.sh   # 开界面回放刚才的 run
```

### B. 评测一个真实助手模型

```bash
# 1. 配 LLM
cp config/llm.toml.example config/llm.toml
# 编辑 [roles.assistant_agent] 填入要测的模型

# 2. 单次跑，先看对话质量
python -m usersim run --mode live --days 30

# 3. 多 seed 批量统计
python -m usersim bench --mode live --groups reference --seeds 1-8 --max-episodes 24

# 4. Web「批量评测」看均值 ± CI 与量程守护
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
python -m usersim run --mode replay --days 30          # 规则回放，0 LLM
python -m usersim run --mode live   --days 30          # 真实 LLM
python -m usersim run --mode live   --harness stub --days 5
```

| 参数 | 说明 |
|------|------|
| `--mode {replay,live}` | `replay`=纯规则回放（0 LLM）；`live`=真实 LLM |
| `--days N` | episode 天数 |
| `--seed N` | 全局种子（同 seed 同轨迹） |
| `--quality {good,mid,poor}` | 回放助手档位（仅 `replay`） |
| `--harness NAME` | 被测 Harness 名（仅 `live`，默认 `reference`） |

产物写入 `runs/<run_id>/`：`meta.json`、`slots.jsonl`、`turns.jsonl`、`report.json`。

### `bench` — 多 seed 批量评测

```bash
python -m usersim bench --seeds 1-8 --days 30 --mode replay
python -m usersim bench --seeds 1-8 --days 30 --mode live --groups reference --max-episodes 24
```

输出多 seed 均值 ± 95% CI、判定众数、量程守护（good 档需收敛、poor 档需发散）。

### `eval` — 离线重算指标

```bash
python -m usersim eval runs/<run_id>
```

改了评估器或权重后，不必重跑 LLM，直接对历史 run 重算。

### `continue` — 续跑

```bash
python -m usersim continue runs/<run_id> --extra-days 10
```

### `serve` — 仅启动后端

```bash
python -m usersim serve
USERSIM_PORT=8620 python -m usersim serve
```

---

## 测试

```bash
pytest -q            # 快速测试（排除 slow）
pytest -q -m slow    # 量程守护慢测试（27 个 30 天回放 episode）
```

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

| # | 文档 | 内容 | 状态 |
|---|------|------|------|
| 00 | [architecture](00-architecture.md) | 四组件架构、依赖规则、编排流程、技术选型 | 已实现 |
| 01 | [world](01-world.md) | 世界模拟器：状态向量、天气、需求动力学、事件引擎、结算器 | 已实现 |
| 02 | [user-agent](02-user-agent.md) | 用户 Agent：LLM 驱动 / 脚本模式、规划器、记忆、prompt 结构 | 已实现 |
| 03 | [assistant-agent](03-assistant-agent.md) | 助手 Agent / Harness 契约、user_belief 输出、接入规范 | 已实现 |
| 04 | [evaluator](04-evaluator.md) | 评估方法论：三层解耦（世界仿真/用户Agent/助手Agent）、控制论指标、行为一致性M1-M5、画像精度、健康分与判定规则、模型对比协议 | 已实现 |
| 05 | [contracts](05-contracts.md) | 跨组件数据契约（消息 schema 全集） | 已实现 |
| 06 | [frontend](06-frontend.md) | 前端页面结构、后端 API / WebSocket、可视化设计 | 已实现 |
| 08 | [event-catalog](08-event-catalog.md) | 事件配表（动作×地点×时长）与经济系统 | 已实现 |
| 09 | [series-events](09-series-events.md) | 系列事件（旅行/出差/休假/备考）：行程单物化、后效 | 已实现 |
| 11 | [anthropomorphism](11-anthropomorphism.md) | 习惯化曲线、需求动力学、人格调节、Excel 单一数据源 | 已实现 |
| 12 | [benchmark](12-benchmark.md) | 被测件可插拔、可复现性凭证、多 seed 统计、量程守护 | 已实现 |
| 13 | [persona-model](13-persona-model.md) | 大五 30 facet + 结构化喜好 + 画像精度指标 | 已实现 |
