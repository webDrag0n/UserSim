# 15 · Agent 接入接口（agent API）与接入 Skill

> ⚠️ 注：replay 模式已于 R4 下线（已知组效度检验 known-groups validity 迁移至 live 对照组 reference vs stub），文中 replay/脚本三档内容为历史记录。

状态: 已实现

> benchmark 系统与 agent 的解耦层：一组 HTTP 接口 + 两个接入 skill。
> 用户 agent 与助手 agent（被测件）都经本接口接入；OpenClaw、Hermes 等外部 agent
> 装载 skill 后即可直接接入；仓库自带的 LLM 用户/参考助手是 **demo agent**——
> 与外部 agent 走完全相同的协议，充当第一方参考实现与回归基线。

## 1. 架构

```text
┌─ benchmark 核心 ─────────────────────────────────────────────┐
│  World → Runner（编排，0 live-agent import）→ Evaluator       │
│              │ broker.submit(role, run_id, type, payload)     │
│         AgentBroker（usersim/gateway.py：pending 队列 + 响应事件）│
│              │ GET /api/agent/pending（长轮询）                │
│              │ POST /api/agent/respond                        │
│              │ GET /api/agent/skill/{role}                    │
└──────────────┬───────────────────────────────┬───────────────┘
               │ HTTP（外部 agent）             │ ASGI 回环（demo，不开端口）
        OpenClaw / Hermes / 任意 agent    python -m usersim agent user|assistant
        （装载 skills/usersim-*/SKILL.md） （CLI run/bench/serve 内嵌同路径线程）
```

- Runner 线程在 `broker.submit()` 上阻塞等待；agent 侧长轮询取请求、处理后回传响应。
- 依赖边界由 `tests/test_dependency_rules.py` 强制：`runner.py` 禁止 import 任何
  live agent 实现（顶层 `agents` 包；replay 的 `usersim/scripted.py` 属仿真逻辑，豁免）；
  `gateway.py` 只依赖 contracts（+config 取 PROJECT_ROOT）。
- 消息契约的权威定义在 `usersim/contracts/agent_api.py`（pydantic），本文件是语义说明。

## 2. 传输与信封

### 端点

| 端点 | 说明 |
|---|---|
| `GET /api/agent/pending?role=user\|assistant&timeout=30&run_id=...` | 长轮询取下一个请求；无请求返回 204。`run_id` 可选：只取该 run 的请求（demo agent 按 run 过滤，外部 agent 通常不过滤） |
| `POST /api/agent/respond` | 交付响应；`request_id` 未知（已超时/重复）返回 404 |
| `GET /api/agent/skill/{role}` | 返回接入 skill 原文（自举：agent 可先拉 skill 再接入） |

### AgentRequest（pending 响应体）

```json
{
  "request_id": "a1b2c3d4e5f6",
  "run_id": "live_42_20260807T120000",
  "role": "assistant",
  "type": "on_turn",
  "payload": { "..." : "typed payload（见下）" },
  "agent_state": { "..." : "agent 侧不透明状态" }
}
```

### AgentResponse（respond 请求体）

```json
{
  "request_id": "<原样带回>",
  "result": { "..." : "typed result" },
  "agent_state": { "...": "非空则覆盖该 (run_id, role) 的存档状态" },
  "persona_hat": { "...": "assistant/on_turn 专用：累积画像快照（可选）" },
  "error": "TypeName: message（agent 侧处理失败；与 result 互斥）"
}
```

### agent_state：对 benchmark 无状态的钥匙

每个 `(run_id, role)` 维护一份不透明 JSON blob：请求携带当前值，agent 回传更新值，
Runner 在 run 结束时写入 `run_state.json`（`agent_state: {"user": ..., "assistant": ...}`），
续跑时回灌。外部 agent 因此可以不在本地保存任何会话记忆（也可以自己按 `run_id`
维护记忆，把 agent_state 留空）。旧存档的 `harness_state` 读取兼容（映射为 assistant 桶）。

### 超时与失败语义

| 情况 | 用户侧 | 助手侧 |
|---|---|---|
| 响应超时（`config/system.toml [agent_api] response_timeout_sec`，默认 120s） | 记 degraded system turn，跳过该意图/中止该 session | 记契约违约（`assistant_timeout`），session 中止 |
| 响应带 `error` | 同上（degraded） | 记契约违约（`LLMError/ValidationError` → `contract_or_llm_error`，其余 → `harness_crash`） |
| result 不符合契约 schema | 同上 | 记契约违约 |

世界推进**从不**因 agent 失败而中断（与重构前口径一致）。
`session_closed` 通知失败仅静默丢弃（记忆损失不影响世界）。

## 3. 助手侧协议（被测件）

只有一个请求类型 `on_turn`：

- payload = `contracts.HarnessObs`（被测件可见信息的全部：`user_say / history /
  tool_results / balance / schedule_hint / recovery_catalog / slot_names / day / slot`）；
- result = `contracts.AssistantTurn`（`reply` + **每轮必填** `user_belief` + `tool_calls`）；
- `persona_hat`（可选）：累积画像快照。缺失时 Runner 把本轮
  `user_belief.persona_belief` 增量按 EMA 合并进 Runner 侧累积器后落盘
  （`contracts.merge_persona_delta`，与 agents.ProfileTracker 同一实现来源；
  `persona_notes` 作为 notes 一并并入）；agent 回快照时以快照为新基线。
  续跑时累积器从 turns.jsonl 最后一条 assistant 的 persona_hat 重建。

工具集不变：`view_event_todos / add_event_todo / plan_series / set_reminder`，
由 Runner 执行、world 产生结果，下一轮经 `tool_results` 返回。

## 4. 用户侧协议

四个请求类型（demo 实现见 `agents/user/standard/agent.py`）：

| type | payload | result | 说明 |
|---|---|---|---|
| `plan_slot` | `PlanSlotRequest`：urges/stress/energy/slot/day/money/event_library/assist_prompt/max_intents/context | `PlanSlotResult.intents`（0~max_intents 个 `Intent`） | 意图规划（用户的"潜意识"，可见自身需求数值）。`assist_prompt` 非空且无 recover 类意图时插入 emergency 意图居首，再按 max_intents 截断。`context`（可空，只加不删）：LLM 规划的语义输入——runner 每 slot 组装的 UserContext（persona + felt_state + 餍足提示，不含数值）；规则/混合实现可忽略 |
| `decide_open` | `{context: UserContext, intent: Intent}` | `{open: bool, reason}` | 带意图决定是否开 session |
| `speak` | `{context: UserContext, history: [DialogueTurn], intent_description}` | `UserAction`（`say` + `end_session`） | session 内发言；`end_session` 是唯一结束标准（另有 runner 的轮数硬上限） |
| `session_closed` | `{session_id, intent_type, turns, day}` | `{ack: true}` | 结束通知，agent 据此更新自身记忆 |

UserContext 故意**不含**原始状态数值——只有 `felt_state` 语义摘要（状态-表达解耦，
对助手侧保持估计难度）。`plan_slot` 的 urges/money 等数值只流向用户侧（本人）；
demo 实现（prompt v3）意图由用户侧 LLM 生成，只用 `context` 语义上下文，
数值字段保留给规则/混合实现与外部用户 agent。

## 5. demo agent（第一方参考实现）

| 组件 | 位置 | 说明 |
|---|---|---|
| `AgentClient` | `usersim/agents/client.py` | 长轮询循环；`base_url`（真实 HTTP）或 `app`（ASGI 回环）两种 transport |
| `DemoUserAgent` | `agents/user/standard/agent.py` | LLM 意图规划（plan，prompt v3）+ UserMemory + LLMUserAgent；记忆存 agent_state；实现配置在 `agents/user/profiles/*.toml`（`--impl` 选择） |
| `DemoAssistantAgent` | `usersim/agents/demo.py` | 包装 registry 扫描到的 Harness（`agents/assistant/profiles/*.toml`：reference / stub / openclaw / hermes / …）；snapshot/restore ↔ agent_state；`--harness` 选择 |
| `spawn_demo_agents` | `usersim/agents/client.py` | 组装点：为本进程 broker 起 mini ASGI app + 回环 demo 线程 |

接入方式记录进 `meta.json` 的 `harness` 字段：`demo:reference` / `external`
（旧格式 `reference` 按 demo 读取）。

### 三种用法

```bash
# 1) CLI 一把梭（内部自动起 ASGI 回环 demo，行为与旧版一致）
python -m usersim run --mode live --days 30

# 2) serve + standalone demo agent（与外部 agent 完全同路径）
python -m usersim serve                                   # 终端 1
python -m usersim.agents user --server http://127.0.0.1:8610        # 终端 2（standalone 入口）
python -m usersim.agents assistant --server http://127.0.0.1:8610 --harness reference   # 终端 3
#   （`python -m usersim agent user|assistant` 是等价的委托入口）
curl -X POST localhost:8610/api/runs -H 'Content-Type: application/json' \
  -d '{"mode":"live","days":30,"user_agent":"external","assistant_agent":"external"}'

# 3) 外部 agent（OpenClaw / Hermes）：装载 skills/usersim-assistant/SKILL.md，
#    按 skill 中的轮询范式直接对接；skill 也可运行时拉取：
curl localhost:8610/api/agent/skill/assistant
```

## 6. 接入 skill

`skills/usersim-assistant/SKILL.md` 与 `skills/usersim-user/SKILL.md`
（agentskills 格式，YAML frontmatter + Markdown）：角色定位、轮询范式（curl/python 示例）、
全部请求/响应 schema、契约要点（user_belief 必填、persona_belief 增量"留空优于瞎猜"、
超时与违约语义）、agent_state 用法与自举方式。server 经
`GET /api/agent/skill/{role}` 实时下发最新版本。

## 7. 测试钩子

`broker.register_local(role, fn)` 注册进程内响应函数（`fn(AgentRequest) -> AgentResponse`），
与 HTTP 路径同一份请求语义——`tests/test_runner.py` 用它替代了原先的
`harness_factory` / monkeypatch 注入。`tests/test_gateway.py` 覆盖 broker 往返、
超时僵尸清理、run_id 过滤、HTTP 端点与 ASGI 回环端到端。

## 8. 实现备注

- httpx 0.28 的 `ASGITransport` 只有异步接口，故 `AgentClient` 用 `AsyncClient`
  实现轮询循环，同步 handler 经 `asyncio.to_thread` 执行。
- broker 提交超时会把仍挂在队列里的请求作废，避免下一个 run 的 agent 捡到无法交付的
  僵尸请求（响应返回 404，agent 继续轮询即可）。
- demo agent 的 restore 策略：同一 run 内以进程内状态为准；run_id 变化（新 run /
  进程重启后首请求）时从请求的 agent_state 回灌。
- 外部模式下的 bench 批量未在本次范围内扩展（episode 请求带 run_id，
  外部 agent 可自行多路复用）。
- 2026-08-12 接口完善（源于 live_42_20260811T172044 复盘）：
  - 画像退化路径此前对**外部 HTTP agent 是空承诺**——增量无人合并即被丢弃；
    现由 Runner 侧累积器（`merge_persona_delta`）真正生效，合并语义从
    `agents/profile.py` 下移到 `contracts/models.py`（第一公理第 3 条的共享纯函数先例），
    `ProfileTracker.update` 改为委托，行为不变。
  - CLI 整机接入（openclaw/hermes）此前只在首轮发 bootstrap，长 session 遗忘后
    画像增量/校准刻度/行动要求全部失联（该 run 117 个 assistant turn 零结构化画像）；
    现 TURN_TEMPLATE 每轮注入 ProfileTracker 画像反馈块与"每轮必做"提醒，
    bootstrap 的 persona_belief schema 与【行动要求】对齐 reference（prompt v2）。
