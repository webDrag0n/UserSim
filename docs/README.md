# UserSim 使用指南

> UserSim = **纯规则世界** + **两个 LLM Agent**（用户模拟 + 被测助手）+ **纯规则控制论评估器**，
> 用控制论指标评测「助手能否让用户的生活收敛到内心平和」。项目定位与边界见 [AGENT.md](../AGENT.md)，
> 架构见 [00-architecture](00-architecture.md)。本页讲**怎么用**；实现方案文档地图在最后一节。

---

## 1. 快速开始（一键启动）

已装好 [uv](https://astral.sh/uv) 和 Node.js（≥ 20）后，在仓库根目录：

```bash
./start.sh                 # 自动备环境 + 装依赖 + 构建前端 + 起后端 + 开浏览器
```

脚本会依次：创建 `.venv`、装 Python 依赖、`npm install`、`npm run build`、启动后端并托管前端，
最后自动打开 `http://127.0.0.1:8610/`。按 `Ctrl+C` 停止。

```bash
./start.sh --rebuild       # 强制重新构建前端（改了 web/ 后用）
./start.sh --port 8620     # 换端口（默认 8610）
```

macOS 上也可直接**双击 `start.command`**（等效于 `./start.sh`）。

> 只想跑纯规则模拟、完全不调 LLM？跳过配置直接：
> `python -m usersim run --mode replay --days 30`（0 token，见 §4）。

---

## 2. 配置 LLM（只有 live 模式和真人被测才需要）

真实 LLM 模式（`--mode live`）需要配 `config/llm.toml`。仓库只提供模板，首次使用先复制：

```bash
cp config/llm.toml.example config/llm.toml
```

然后编辑 `config/llm.toml`，填入 provider 的密钥。所有 provider 走 OpenAI 兼容协议
（`/v1/chat/completions`），内置 moonshot / openai / deepseek / local 四个示例端点，
默认 provider 是 `deepseek`：

```toml
default_provider = "deepseek"

[providers.deepseek]
base_url    = "https://api.deepseek.com/v1"
api_key     = "sk-在此填入你的-DeepSeek-Key"
model       = "deepseek-chat"

# 角色绑定：谁用哪个 provider
[roles.user_agent]        # 用户模拟 Agent
provider = "deepseek"
[roles.assistant_agent]   # 被测助手 Agent
provider = "deepseek"
[roles.reference_user]    # 对照用参考实现（建议低温）
provider = "deepseek"
temperature = 0.3
```

安全约定（详见模板注释与 [AGENT.md](../AGENT.md) 配置规约）：

- **密钥只进 `config/llm.toml`**（已在 `.gitignore`），代码里禁止硬编码。
- 每个 `api_key` 都能用**同名环境变量覆盖**，优先级高于文件，适合 CI / 不落盘：
  `USERSIM_DEEPSEEK_API_KEY`、`USERSIM_OPENAI_API_KEY`、`USERSIM_MOONSHOT_API_KEY`…
- 本地模型（vLLM / Ollama / LMStudio）用 `[providers.local]`，指到你的本地端点即可。

世界/动力学/评估参数不在这里，在 `config/system.toml`（见 §7）。

---

## 3. 三种使用方式

| 方式 | 命令 | 适合 |
|------|------|------|
| **Web 界面**（推荐） | `./start.sh` | 交互式跑模拟、看同时刻全景、回放、批量对比、编辑配表 |
| **命令行 CLI** | `python -m usersim <子命令>` | 脚本化、批量评测、CI、无头环境 |
| **前端开发模式** | `cd web && npm run dev` | 改前端时热更新（代理到 8610 后端，需另起 `python -m usersim serve`） |

CLI 前先激活虚拟环境：`source .venv/bin/activate`（或用 `uv run python -m usersim …`）。

---

## 4. 命令行（CLI）详解

入口是 `python -m usersim`，五个子命令：

### `run` — 跑一次模拟

```bash
# 规则回放：0 LLM、0 token，秒级出结果，用于验证世界/调参/冒烟
python -m usersim run --mode replay --days 30

# 真实 LLM：用户 Agent + 助手 Agent 真实对话（需先配 llm.toml）
python -m usersim run --mode live --days 30

# 指定被测 Harness（仅 live；默认 reference）
python -m usersim run --mode live --harness stub --days 5
```

常用参数：

| 参数 | 说明 |
|------|------|
| `--mode {replay,live}` | `replay`=纯规则回放（0 LLM）；`live`=真实 LLM |
| `--days N` | episode 天数（评估窗口长度），覆盖 `system.toml` |
| `--seed N` | 全局种子：角色卡、事件流、扰动流全部由它派生（同 seed 同轨迹） |
| `--quality {good,mid,poor}` | 回放助手档位（仅 `replay`，用于调世界分辨力） |
| `--archetype NAME` | 指定职业（收入随之改变） |
| `--harness NAME` | 被测 Harness 名（仅 `live`，默认 `reference`） |

产物写到 `runs/<run_id>/`：`meta.json`（可复现凭证）、`slots.jsonl`（逐时段结算）、
`turns.jsonl`（逐 turn 对话 + 真实状态 x + 助手估计 x̂）、`report.json`（控制论指标）。

### `bench` — 多 seed 批量评测（带置信区间）

```bash
# 三档回放批量（good/mid/poor），0 token，验证「世界能否分辨好差助手」
python -m usersim bench --seeds 1-8 --days 30 --mode replay

# live 批量：显式上限成本（会真实计费）
python -m usersim bench --seeds 1-8 --days 30 --mode live --groups reference --max-episodes 24
```

| 参数 | 说明 |
|------|------|
| `--seeds` | 种子范围，如 `1-20` 或 `1,4,7` |
| `--groups` | replay：`good,mid,poor`（默认三档）；live：harness 名列表（默认 reference） |
| `--archetypes` | 职业列表或 `all`（默认 `auto`＝由 seed 决定） |
| `--concurrency` | 并行度 |
| `--max-episodes` | **live 模式的显式 episode 上限**（成本闸门，防止跑飞） |

输出多 seed 均值 ± 95% CI、判定众数、**量程守护**（good 档需收敛、poor 档需发散、两档需清晰分离）。

### `eval` — 对既有 run 离线重算指标

```bash
python -m usersim eval runs/<run_id>
```

改了评估器或权重后，无需重跑模拟即可重新打分（评估器只读日志、0 LLM）。

### `continue` — 续跑（追加天数）

```bash
python -m usersim continue runs/<run_id> --extra-days 10
```

从既有 run 的末状态接着跑，用于观察长期行为。

### `serve` — 仅启动后端

```bash
python -m usersim serve            # 托管 web/dist，默认端口 8610
USERSIM_PORT=8620 python -m usersim serve
```

`./start.sh` 内部最终就是调它。前端需已构建（`cd web && npm run build`）。

---

## 5. Web 界面导览

顶部导航三大页面 + 右上角 **☀/☾ 主题切换**（浅色/深色，记忆到本地；默认跟随系统）。

### 运行控制台

打开后先看**运行列表**：卡片展示每个存档的 seed / 天数 / 职业 / 判定，运行中的有实时进度条。
「启动新运行」填职业 / 被测 Harness / seed / 天数即可开跑；也可多选删除旧存档。点开一个 run 进入详情：

- **同时刻全景（Cockpit）** — 本平台的核心。一条**时间游标**驱动三栏同步：
  **系统·世界**（时间/系列/余额/进行中事件/本时段状态结算分解）→ **用户 Agent**（真实状态 x
  四维条 + 世界翻译给用户的感受 `felt_state` + 用户台词）→ **助手 Agent**（估计 x̂ 与逐维偏差 +
  助手回复 + 行动卡）。三栏间有**因果箭头**，一眼看清「世界事件→用户感受→用户台词→助手估计→助手行动」这条链。
- **统一时间线** — 日程记录图（甘特）+ 状态轨迹曲线，共享同一游标；点击任意位置跳转回放。
- **对话记录** — 逐 turn 气泡，用户气泡带 `felt_state` 副标题，当前 turn 高亮。
- **回放控制条** — 播放/暂停、单步、拖动进度、1×/2×/4× 变速、「回到最新」。拖动游标 1:1 跟手。
- **分析面板** — 经济 / 人格画像 / 估计误差 / 指标 / 事件统计 / 洞察 / 世界图谱，切 Tab 查看。

### 批量评测

跑三档回放（0 token）后展示：**量程守护**卡（是否能分辨好差助手）、**分档均值柱状对比**
（三档并排，一眼看分离度）、聚合表（mean ± 95% CI）、episode 明细。live 批量需走 CLI 显式确认成本。

### 配表编辑器

直接查看/编辑数值配表（习惯化曲线、需求参数、事件表等），点单元格改、回车保存，**热加载生效**；
习惯化曲线和需求参数带实时函数曲线预览。数据源是 `balance-sheet/UserSim数值配表.xlsx`。

---

## 6. 常见工作流

### A. 只想看世界怎么运转（不花钱）

```bash
python -m usersim run --mode replay --days 30
./start.sh          # 再开界面回放刚才的 run
```

### B. 评测一个真实助手模型

1. `cp config/llm.toml.example config/llm.toml`，在 `[roles.assistant_agent]` 配上要测的模型；
2. `python -m usersim run --mode live --days 30`（先跑单个看对话质量）；
3. `python -m usersim bench --mode live --groups reference --seeds 1-8 --max-episodes 24`（多 seed 统计）；
4. 开 Web「批量评测」看均值 ± CI 与量程守护。

### C. 开发前端

```bash
python -m usersim serve            # 终端 1：后端
cd web && npm run dev              # 终端 2：前端热更新（代理到 8610）
```

### D. 改了评估指标，想重算旧数据

```bash
python -m usersim eval runs/<run_id>
```

---

## 7. 配置文件

| 文件 | 管什么 | 备注 |
|------|--------|------|
| `config/llm.toml` | 模型从哪来（端点/密钥/角色绑定） | 含密钥，不提交；从 `.example` 复制 |
| `config/system.toml` | 世界怎么运转（时钟/动力学/状态设定点/评估阈值/服务） | 所有项都有代码默认值，只写要覆盖的 |
| `balance-sheet/UserSim数值配表.xlsx` | 事件/需求/习惯化的数值配表 | Web 配表编辑器的单一数据源 |

`system.toml` 关键段：`[run]`（seed/天数/输出目录）、`[clock]`（每天时段数）、
`[state]`（四维设定点 + 平和带半宽）、`[dynamics]`（状态动力学系数）、`[score]`（健康分权重）。

---

## 8. 测试

```bash
pytest -q            # 快测试（默认排除 slow）
pytest -q -m slow    # 量程守护慢测试（27 个 30 天回放 episode）
```

测试分层：`tests/world`（同 seed 同轨迹的确定性）、`tests/evaluator`（指标对拍）、
`tests/contracts`（schema 向后兼容）、`tests/test_dependency_rules.py`（组件依赖边界的静态强制）。

---

## 9. 故障排查

| 现象 | 处理 |
|------|------|
| `未找到 uv / npm` | 装 uv（`curl -LsSf https://astral.sh/uv/install.sh \| sh`）和 Node ≥ 20 |
| `端口 8610 已被占用` | `pkill -f 'usersim serve'`，或 `./start.sh --port 8620` |
| live 模式报鉴权/超时 | 检查 `config/llm.toml` 的 `api_key` 与 `base_url`；可调 `[runtime] timeout_s / max_retries` |
| 界面是旧版 / 改了前端不生效 | `./start.sh --rebuild` 重新构建 |
| 想看完整 prompt 调试 | `config/llm.toml` 里 `[runtime] log_prompts = true`（日志体积会变大） |
| 老存档打不开某字段 | 日志向后兼容（字段只加不删），缺失字段前端会回退或隐藏，不报错 |

---

## 实现方案文档地图

> 规约：先设计后编码。每篇文档头部标注状态；实现完成后回填"实现备注"。

| # | 文档 | 内容 | 状态 |
|---|------|------|------|
| 00 | [architecture](00-architecture.md) | 总体架构、四组件解耦、依赖规则、技术选型 | 已实现 |
| 01 | [world](01-world.md) | 世界模拟器：双层时钟、事件引擎、状态动力学、结算器、无限生成 | 已实现 |
| 02 | [user-agent](02-user-agent.md) | 用户模拟 Agent：人格注入、状态→表达、求助决策、工具集 | 已实现 |
| 03 | [assistant-agent](03-assistant-agent.md) | 助手 Agent / Harness 契约、user_belief 输出、记忆抽象、接入规范 | 已实现 |
| 04 | [evaluator](04-evaluator.md) | 评估器：控制论指标、滑窗、判定规则、报告产物 | 已实现（report.json；HTML 报告由 web 前端承担） |
| 05 | [contracts](05-contracts.md) | 跨组件数据契约（消息 schema 全集） | 已实现 |
| 06 | [frontend](06-frontend.md) | 前端页面结构、后端 API / WebSocket、可视化设计 | 已实现（Apple 风重设计：Cockpit 全景 + 双主题） |
| 07 | [roadmap](07-roadmap.md) | 里程碑 M0–M4 与验收标准 | M0–M4 已完成 |
| 08 | [event-catalog](08-event-catalog.md) | 事件配表（动作×地点×时长）与经济系统、Excel 导出 | 已实现 |
| 09 | [series-events](09-series-events.md) | 长时间系列事件（旅行/出差/休假/备考）：行程单物化、日程覆盖、后效 | 已实现 |
| 10 | [optimization-round1](10-optimization-round1.md) | 优化轮次 R1/R2（基于 100 天运行洞察） | 已实现（x̂ 数值属刻度泄漏期，见 04 §4c） |
| 11 | [anthropomorphism](11-anthropomorphism.md) | 习惯化曲线 + 需求动力学 + 人格调节 + Excel 单一数据源 | 已实现 |
| 12 | [benchmark](12-benchmark.md) | 被测件可插拔、可复现性凭证、多 seed 统计、量程守护 | 已实现（第三轮 Phase 1） |
| 13 | [persona-model](13-persona-model.md) | 大五 30 facet + 结构化喜好 + 逐 turn 画像估计与精度指标 | 已实现 |

## 迭代历史

- 第一轮：两份配置 + AGENT.md + 全部方案草稿。
- 第二轮：contracts + world 实现（01/05）。
- 第三轮：两个 Agent + 端到端冒烟（02/03）。
- 第四轮：evaluator + 报告（04）。
- 第五轮：server + web 前端联调（06）。
- 第六轮：事件配表/系列事件/拟人化（08/09/11）+ 优化轮次 R1/R2（10）。
- **第七轮 · Phase 1**：Benchmark 骨架（12）——被测件可插拔、可复现性凭证、
  多 seed 置信区间、量程守护、依赖规则 CI 化。
- **第七轮 · Phase 2（待做）**：双层 Agent（规则规划器 + LLM 对话）、去刻度泄漏、
  求助决策权从 world 移交用户 Agent、世界拟真度残留项。
