# DEVELOPMENT.md — 开发指南与经验沉淀

> 面向在本仓库写代码的人：环境、日常命令、配置与测试约定，以及踩过的坑。
> 架构看 `ARCHITECTURE.md`，不可违背的边界看 `AGENT.md`（优先级高于本文）。

## 环境

- Python ≥ 3.11（依赖 `tomllib` 标准库读 TOML，不引第三方 TOML 包）；
- 虚拟环境在 `.venv/`，用 `.venv/bin/python -m ...` 或先 `source .venv/bin/activate`；
- 依赖见 `pyproject.toml`（pydantic / numpy / fastapi / uvicorn / httpx / openai），
  dev 组只有 pytest；前端在 `web/`（React 18 + Vite + Tailwind + Recharts）。

## 日常命令

```bash
./start.sh                                    # 一键启动（备环境+构建前端+开浏览器）
python -m usersim run --days 30               # live：真实 LLM（demo agent ASGI 回环接入）
python -m usersim bench --groups reference,stub --seeds 1-8 --days 30 --max-episodes 16
python -m usersim continue runs/<run_id> --extra-days 10
python -m usersim eval runs/<run_id>          # 离线重算指标（不烧 token）
python -m usersim serve                       # 仅后端（托管 web/dist + /api/agent/*）
python -m usersim agent user|assistant --server http://127.0.0.1:8610  # standalone demo agent
pytest -q            # 全部测试（0 token：纯函数 / 合成 fixture / World 直驱）
```

> **R4 起只有 live 一种运行模式（replay 已删除）：所有 `run` / `bench` 都烧 token。**
> 0-token 回归手段是 pytest（合成 fixture）与 World 单测；已知组效度检验
> （known-groups validity）的实测（reference vs stub × 多 seed）是手动 live 流程，不进 CI（见 `docs/12-benchmark.md` 第 4 节）。

## 配置约定（三类文件，各管各的）

| 文件 | 管什么 | 注意 |
|---|---|---|
| `config/llm.toml` | LLM provider 端点/密钥**注册表** | 含密钥，不提交；从 `.example` 复制；密钥可被 `USERSIM_<PROVIDER>_API_KEY` 环境变量覆盖 |
| `agents/<role>/config.toml` | 角色级默认：`[llm]` provider 绑定 + 顶层 `default` 默认实现 | agent 自己的参数跟 agent 走，不进 llm.toml / system.toml |
| `agents/<role>/profiles/*.toml` | 一个文件 = 一个可供选择的 agent 实现 | 增删文件即增删实现；type 分派（assistant: package/cli，user: package）；cli 型自带 argv/会话/输出描述；可含 `[llm]` 覆盖角色绑定 |
| `config/system.toml` | 世界/时钟/动力学/经济/评估/服务参数 | 所有参数有代码内默认值，文件只写覆盖项，注释与默认值保持一致 |

判断一个参数该放哪：影响**世界怎么运转/指标怎么算** → system.toml；
影响**某个 agent 实现怎么表演** → 该实现的 profiles/<name>.toml；
角色级默认（provider、默认实现）→ agents/<role>/config.toml；
**密钥** → 只在 llm.toml 或环境变量，代码里禁止硬编码。

### 新增一个 agent 实现（三步，零 Python）

1. 在 `agents/assistant/profiles/`（或 `user/`）放 `<name>.toml`：
   进程内型写 `type = "package"`（在同名文件夹提供 Python 包，暴露 `create(...)`；
   可用 `impl = "<文件夹>"` 另指实现文件夹）；
   本机 CLI 型写 `type = "cli"` + `[cli] argv` 模板（占位符 `{message}` `{timeout}`
   `{session}` `{uid}`）+ `[cli.session]`（`mode = key|resume|none`）+ `[cli.output]`
   （`format = json|text`，json 用 `text_path` 点路径、`*` 展开列表）——照抄
   `openclaw.toml` / `hermes.toml` 改即可；
2. `python -m usersim run --harness <name>`（用户侧用 `--user-impl <name>`）即选即用；
   想变默认就改角色 config.toml 的 `default`；
3. 下线 = 删文件。`/api/harnesses` / `/api/user-impls` 清单随扫描自动更新。

## 测试分层

- `tests/test_world.py` 等：确定性测试（同 seed 同轨迹）；
- `tests/test_contracts.py`：schema 兼容（加字段可、改语义不可）；
- `tests/test_dependency_rules.py`：import 边界的 AST 静态扫描（含函数内延迟 import）——
  改包结构后第一件事是跑它；
- `tests/test_runner.py` / `test_gateway.py`：agent 接口用 `broker.register_local()`
  进程内钩子打桩，不起 HTTP；
- 已知组效度检验（known-groups validity；reference vs stub 阳性/阴性对照 + 区分度断言）是**手动 live 流程**——烧 token、
  不进 CI：`python -m usersim bench --groups reference,stub --seeds 1-8 --days 30 --max-episodes 16`，
  动数值后才需要跑（见 `docs/12-benchmark.md` 第 4 节）。

## 工作流约定

- **先文档后编码**：方案进 `docs/`，头部标 `状态: 草稿|已定稿|已实现`，完成后回填"实现备注"；
- 日志 append-only JSONL，schema 向后兼容（加字段，不改语义）；
- 随机性只来自 world 的种子流（`numpy.random.Generator` 派生），agent 侧不得 `random.*`；
- 改动最小化；跨组件新字段先改 `contracts/` + `docs/05-contracts.md`。

## 踩坑记录（都是实际趟过的）

1. **shell 代理会搞崩 openai 客户端**：本机 shell 若带了 `http_proxy/https_proxy/all_proxy`，
   openai SDK 会尝试走 socks 代理并因缺 `socksio` 崩溃。跑 live 前一律：
   ```bash
   env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY -u all_proxy -u ALL_PROXY \
     python -m usersim run ...
   ```
2. **httpx 0.28 的 `ASGITransport` 只有异步接口**：`AgentClient` 因此用 `AsyncClient`
   实现轮询循环，同步 handler 经 `asyncio.to_thread` 执行。别再尝试同步调用它。
3. **FastAPI `include_router` 的路由在 `app.routes` 里是 `_IncludedRouter`，没有 `.path`
   属性**——按 path 枚举路由做自检会漏判。验证端点用 TestClient 实测，别靠 routes 内省。
4. **函数内的延迟 import 只有真正执行到那条路径才暴露**：`bench/suite.py` 曾在子进程
   worker 里 `from usersim.config import prompt_versions`，快测试全绿、slow 测试才炸。
   教训：移动/删除公开函数后，除 grep 调用点外，**必须跑一遍全量测试**再收工
   （R4 起 slow 回放套件随 replay 移除，全量 pytest 即 0-token 全量）。
5. **进程池 worker 的 import 必须可 pickle 路径可达**（历史记录）：bench 曾用
   `ProcessPoolExecutor`（R4 起 bench 恒 live、恒串行，进程池已移除），
   worker 入口只传基本类型；在 worker 里 import 什么，什么就必须在子进程里独立可用。
6. **零 turn ≠ 挂了**：1 天短 live run 可能全天 planner 无意图或 `decide_open` 全否，
   turns.jsonl 不存在是合法结果。判断真伪看 slots.jsonl 是否正常推进、report 是否产出，
   必要时开 `log_prompts` 或换 seed 复跑对照。
7. **TOML 就用标准库 `tomllib`**（3.11+）；配置默认值在代码里，toml 文件是覆盖层——
   改默认值时同步改文件注释，两边漂移已经咬过人。
8. **文档里的文件路径会烂**：两轮重构后 docs/ 里残留了一串 `usersim/agents/...` 旧路径。
   改结构后统一 `grep -rn "<旧路径>" docs/ skills/ AGENT.md` 清一遍，别只改代码。
9. **接本机 agent CLI（openclaw/hermes，见 `usersim/agents/cli_agent.py`）的实测坑**：
   - CLI 的信息流分通道：hermes 的 `session_id:` 打在 **stderr**（要 `--pass-session-id`），
     reasoning 框混在 **stdout** 正文里（用 `--reasoning none` 抑制，否则污染 reply）；
     合并 2>&1 调试会掩盖这一点，接输出时务必 stdout/stderr 分开看。
   - openclaw 不带会话参数时落到用户默认主会话——会污染用户自己的聊天记录。
     每个 harness 实例生成专属 `--session-key agent:main:usersim-<hex>` 做隔离。
   - 每轮一个子进程、原生 session 做跨 turn 记忆，是"整机当被测件"的最简方案：
     记忆、工具习惯全是被测对象，benchmark 侧零假设。
