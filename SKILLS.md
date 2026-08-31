# SKILLS.md — Skill 体系与设计经验

> 本仓库有两类 skill：**给外部 agent 装载的接入 skill**（`skills/`）和
> **给编码 agent 用的开发 skill**（`.claude/skills/`，vendor 而来）。
> 本文记录两者的定位、机制，以及从"让任意智能体接入 benchmark"中沉淀的设计经验。

## 一、接入 skill（`skills/usersim-*`）——本项目的核心交付物

| skill | 角色 | 请求类型 |
|---|---|---|
| `skills/usersim-assistant/SKILL.md` | 被测助手（OpenClaw、Hermes 等直接接入） | 仅 `on_turn` |
| `skills/usersim-user/SKILL.md` | 模拟用户 | `plan_slot / decide_open / speak / session_closed` |

设计目标：**benchmark 系统不认识任何具体 agent**。assistant 与 user 两侧都是
"接口集合 + skill 文档"：接口集合 = `contracts/agent_api.py` 的四个/一个请求类型 +
`/api/agent/*` 端点，skill 文档 = 本目录的两份 SKILL.md。一个从未见过本项目的智能体，
装载对应 skill 后应当无需阅读任何源码就能正确接入、正确履约、正确理解失败语义。

第一方实现同样遵守这个约束：demo agent 只是"预先装好 skill 的参考 agent"，而且
**实现本身也是可插拔的配置文件**——`agents/<role>/profiles/*.toml`，
增删一个 toml 就增删一个可供选择的实现（含本机 CLI 整机接入的 openclaw/hermes），
选择用 `--harness` / `--impl` 或 config.toml 的 `default`。

### 接入机制（自举闭环）

```
agent 拿到 skill（本地装载，或运行时 GET /api/agent/skill/{role} 拉取最新版）
  → 按 skill 发起 run（assistant_agent=external / user_agent=external）
  → 长轮询 GET /api/agent/pending?role=...&timeout=30
  → 处理 → POST /api/agent/respond
```

server 实时下发 skill 原文这一点很关键：**skill 即协议文档，且永远是最新版**，
不存在"agent 手里一份过期的接入文档"。

### 一份合格接入 skill 的要素（经验清单）

1. **角色定位先行**：第一段就让 agent 入戏（"你是被测件"/"你演一个真实的人"），
   并说明它**看不见什么**（真实状态 `x`、词典、日志）——信息边界比接口字段更重要。
2. **最小可运行范式**：curl 轮询循环 5 行内能跑起来，再给一个 Python 参考实现
   指针（`usersim/agents/client.py`——demo agent 与外部 agent 同一路径，可作行为参照）。
3. **完整信封与 schema**：每种请求类型的 payload/result 字段逐个列出，标明必填
   （如助手每轮必出 `user_belief`）与可选（`persona_hat`、`agent_state`）。
4. **契约要点用"为什么"写**：如画像增量"留空优于瞎猜"——告诉 agent 违约的代价
   是什么，它才会做出正确取舍。
5. **失败语义成文**：超时、error 字段、schema 不符各自记什么、世界是否继续——
   agent 需要知道"挂了会发生什么"才能写出健壮的循环（响应 404 就继续轮询）。
6. **状态管理说明**：`agent_state` 的带回/更新/存档/回灌语义，让外部 agent 可以
   零本地状态接入（也可以自己按 run_id 记，二选一，写清楚）。

### demo agent 的双重身份

`agents/user/standard/agent.py`、`usersim/agents/demo.py` 既是第一方参考实现，也是
"skill 是否正确"的活体验证：它们与外部 agent 走**完全相同**的轮询协议，
`python -m usersim agent user|assistant --server <url>` 即可观察标准行为。
改协议时：先改 `contracts/agent_api.py`，同步改两个 SKILL.md 和 demo agent，
再改 runner——skill 与代码漂移等于协议说谎。

## 二、开发 skill（`.claude/skills/`）——vendor 的编码助手能力

9 个项目级 skill，从外部仓库**逐字节 vendor** 而来，随仓库提交、离线可用。
来源、commit SHA、license 见 `.claude/skills/README.md`；
重新拉取上游：`bash scripts/update-skills.sh`。

- `karpathy-guidelines`：LLM 编码行为约束（先思考再编码/简单优先/外科手术式改动/
  目标驱动），与 AGENT.md "先设计后编码" 同向；
- 前端设计工程 8 个（emilkowalski/skills）：只在动 `web/` 时有意义——
  `apple-design`、`emil-design-eng`、`animation-vocabulary`、
  `find-animation-opportunities`、`improve-animations`（自动触发），
  `pick-ui-library`、`prototype`、`review-animations`（手动 `/` 调用）。

使用纪律（经验）：

- **不要就地编辑 `.claude/skills/`**，会被同步脚本覆盖；项目专属规约写 `AGENT.md`；
- vendor 而非 marketplace 安装的取舍：换来离线可用、clone 即得、版本随 git 锁定，
  代价是要自己跑脚本追上游——对本项目值得；
- `improve-animations` 会往仓库根写 `plans/`，那是过程文件，不进 `docs/`。

## 三、什么时候该写新 skill

- 新的**接入方**出现（新角色、新协议面）→ 写接入 skill，并挂到
  `/api/agent/skill/{role}` 的下发逻辑里；
- 重复出现三次以上的**开发操作**（如"更新 vendor skill"、"导出配表"）→
  考虑写成脚本或 skill，别靠口口相传；
- skill 写完的验收标准：拿一个**没有本仓库上下文**的 agent，只给 skill，
  能独立完成接入/操作，才算合格。
