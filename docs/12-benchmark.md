# 12 · Benchmark 执行协议（可插拔被测件 · 多 seed 统计 · 已知组效度检验）

状态: 已实现（第四轮迭代，live-only）

> 本文档回答：怎么把 UserSim 当 benchmark 用，而不只是当仿真工作台看。

## 0. 为什么需要这一层

第三轮迭代前的实际状况：

| 问题 | 后果 |
|---|---|
| Runner 硬编码 `ReferenceHarness` | E1/E2 评测矩阵在代码层无处落脚，"被测件"名不副实 |
| 全部结论来自 seed=42 单角色单跑 | 无法区分"助手 A 比 B 好"与"这个 seed 恰好对 A 友好" |
| `config_hash` 只哈希 `system.toml` | 改 Excel 配表/catalog/prompt 都不反映在凭证里，两个"同 hash"的 run 其实不可比 |
| 调参压缩了 good/poor 的分辨率且无守护 | poor 档 ess 距发散阈值仅剩 0.004 裕度（docs/10 记录） |

## 1. 被测件接入（agent 接口 + Harness 协议）

被测件的接入面是统一 **agent 接口**（docs/15-agent-api.md）：benchmark 暴露
`GET /api/agent/pending`（长轮询）+ `POST /api/agent/respond`，被测件装载
`skills/usersim-assistant/SKILL.md` 即可接入——OpenClaw、Hermes 等外部 agent 直接可用。
进程内被测件仍实现 Harness 协议：

```python
class Harness(Protocol):
    def on_turn(self, obs: HarnessObs) -> AssistantTurn: ...
    def snapshot(self) -> dict: ...          # 续跑用（经 agent_state 存档）
    def restore(self, state: dict) -> None: ...
```

- Harness 协议落位 `usersim/agents/base.py`；注册表 `usersim/agents/registry.py` 扫描
  `agents/assistant/profiles/*.toml`——**实现即配置文件，增删文件即增删可选实现**。
- 内置两类 type：`package` 导入 `agents/assistant/<name>/` 实现包（`reference` 参考线、
  `reference_nomem` 减记忆消融、`stub` 阴性对照）；`cli` 走通用 CLI 驱动（`usersim/agents/cli_agent.py`）：openclaw.toml /
  hermes.toml 把本机 agent CLI
  整机包装为 Harness——跨 turn 记忆用各 CLI 原生 session（key / resume 两种模式由
  配置声明），输出契约 = 正文 + 末尾 ```json 块；每轮消息携带 Runner 注入的动态
  recovery_catalog（cli_agent v3 起，与 reference 每轮所见目录一致——信息对等约定）。
  新增任何"一条消息进、回复出"的 agent CLI 只需再放一个 toml，无需写 Python。
- **demo assistant**（`usersim/agents/demo.py`）把 registry 内 Harness 包装成
  agent 接口的 on_turn 处理器，与外部 agent 走完全相同的 HTTP 协议——第一方参照实现。
- 被测件**只能看到 `HarnessObs`**（on_turn 的 payload）：`user_say / history / tool_results / balance /
  schedule_hint / recovery_catalog / slot_names / day / slot`。真实状态 `x`、world 的翻译
  词典、`runs/` 日志都不在其中。需要世界信息时由 Runner 注入。
- 选择方式：CLI `--harness NAME`、`POST /api/runs {"harness": ..., "assistant_agent": "demo"|"external"}`、
  或前端启动表单下拉。接入方式写入 `meta.json`（`demo:reference` / `external`）。
- **异常隔离**：`on_turn` 抛任何异常、响应超时、schema 不符都记为契约违约并继续，
  不会让整个 episode 丢失。

### 评测矩阵

| 矩阵 | 固定 | 变化 |
|---|---|---|
| E1（测 Model） | `--harness reference`（demo 接入） | `agents/assistant/config.toml [llm]` 的 provider/model |
| E2（测 Harness） | 参考 provider（demo 接入） | `--harness <你的实现>` |
| E3（测外部 Agent） | `user_agent=demo` | 两种接法：① 本机已装的 CLI 整机接入 `--harness openclaw\|hermes`（`cli_agent.py`，原生 session 记忆）；② `assistant_agent=external`，任意 agent 装载 skill 轮询接入 |

## 2. 可复现性凭证

`meta.json` 新增三个字段（均有默认值，旧 run 仍可读）：

- `harness`：接入方式 + 被测件名（live：`demo:reference` / `external`；旧值 `reference`
  按 demo 读取；replay 时代的 `scripted:<档位>` 仅见于历史存档）；
- `artifact_hashes`：`system / llm / balance / catalog / prompts / combined` 逐项哈希；
- `prompt_versions`：各 agent 的 `PROMPT_VERSION`（此前定义了但从不落盘）。
- `llm_reported`（R4 新增）：provider 实际应答的模型版本——demo agent 侧 LLMClient
  把响应里的 model/system_fingerprint 落盘 `reported_models.json`，run 结束合并进 meta；
  外部/CLI agent 可经 agent_state 自报 `reported_model`。堵住滚动别名
  （如 `deepseek-chat`）的漂移洞。

**密钥安全**：`llm.toml` 的哈希先剔除所有含 `api_key` 的行再计算，密钥不作为哈希前像进入产物。
已有测试验证"改密钥不改哈希、改端点改哈希"。

**跨 run 可比性判据**：仅当 `artifact_hashes.combined` 相同时，两个 run 的指标才严格可比。

## 3. 多 seed 批量与置信区间

```bash
python -m usersim bench --groups reference,stub --seeds 1-8 --days 30 --max-episodes 16   # 已知组效度检验对照组
python -m usersim bench --groups reference --seeds 1-8 --days 30 --max-episodes 8         # 单组统计
python -m usersim bench --groups openclaw --seeds 1-20 --archetypes all --max-episodes 20 # 全职业
```

- 每个标量指标输出 `mean / std / n / ci95`（n≤30 用 t 分布，>30 用正态近似；只依赖标准库）。
- `verdict` 输出三档占比与众数，另有**判定一致率**（`verdict_consistency`：与众数一致的
  episode 占比——组内分歧本身就是信号，H1 教训：模型差异可能在方差）。
- **`settling_time_days = None` 单独计为 `never_settled`，不当缺失值丢弃**——否则出带后
  从未回归带内（never settled）的最差助手会因为样本被丢掉而看起来最好。（v5 起"全程未出带"记 $t_s=0$，
  不再计入 never_settled——从未失控不等于从未稳定。）
- **MDE（最小可检测效应）**：`aggregate.json` 顶层 `mde` 字段给出每组对在当前 n 下、
  α=0.05/power=80% 可检测的最小均值差（两样本 t）与最小方差比（对数方差正态近似），
  覆盖 benchmark_score 与 ess。差值小于 MDE 的"无差异"结论不具统计效力；前端聚合表
  表尾逐组对列出。
- 产物：`runs/_bench/<bench_id>/{episodes.jsonl, aggregate.json, discriminability.json}`
  （bench_id 前缀 `bench_live_`）。
- benchmark_score 采用 v4 三项扣分公式（`ess` / `in_band_ratio` / `persona_coverage`，
  公式与精简依据见 `docs/04-evaluator.md` 第 8 节）；被移除指标仍全部落盘供诊断。
- 成本闸门：bench 恒为 live（烧 token）；episode 按 `--concurrency` 并发
  （默认取 `llm.toml` 的 concurrency，防限流靠 chat_json 指数退避重试兜底）；
  硬上限 20 episode/次，且必须显式 `--max-episodes` 确认成本。
- 断点续跑：run 目录已有 `report.json` 的 episode 直接复用存档重评估，
  重跑 bench 不重复烧已完成 episode 的 token。

## 4. 已知组效度检验（known-groups validity；live 对照组：reference vs stub）

把"世界能否分辨好助手与差助手"变成可断言的量。R4 起对照从 replay 三档脚本迁移到
**live 对照组**：`reference`（阳性对照，参考实现）vs `stub`（阴性对照）。当 bench 的
`--groups` 同时包含 reference 与 stub 时自动触发，结果写入 `discriminability.json`：

```
margin_poor = mean(ess_stub) − diverged_ess_min        > 0    差助手确实被判差
margin_good = converged_ess_max − mean(ess_reference)  > 0    好助手确实被判好
separation  = Cohen's d(ess_reference, ess_stub)       > 1.5  两对照必须清晰可分
```

v5 起增加**黄灯（borderline）区间判定**：ess 均值 ±SEM 跨阈时对应检查记
`borderline`（`check_status` 字段），整体 `status` 汇总为 ok / borderline / fail。
`checks`/`ok` 保持二值语义不变（borderline 仍算通过），黄灯的含义是"margin 虽为正，
但抽样噪声足以把均值推过阈值"——结论在刀沿上，应加 seed 而不是强下结论。

实现：`bench/discriminability.py`（分组键参数化，默认 good=reference / poor=stub）。
实测是**手动 live 流程**（烧 token，不进 CI）：

```bash
python -m usersim bench --groups reference,stub --seeds 1-8 --days 30 --max-episodes 16
```

**作用**：以后任何调参（含 Excel 热编辑）压缩了量程会立刻红灯，而不是像 R1/R2 那样事后在
文档里记一句"记录观察"。

### eval 阈值（R4 重校准）

旧阈值按 replay 脚本锚点校准，对 LLM 被测件过严（replay good 自身只有 50% 判
converged；live reference 收敛 run 实测 settle=4.5 天 / overshoot=0.177）。R4 起
（`config/system.toml [eval]`）：

| 键 | 旧值（replay 口径） | 新值（live 口径） |
|---|---|---|
| `converged_settle_max` | 2.5 天 | **5.0 天** |
| `converged_overshoot_max` | 0.15 | **0.20** |
| `converged_ess_max` | 0.030 | **0.060**（v4.1 终标定） |
| `diverged_ess_min` | 0.080 | 不变 |

v4 重标定过程与教训：首轮按 15 episode 阳性对照 P75 拟合 0.050，补种子后新样本落入
分布右尾，margin_good 再度转负（-0.005，≈0.4 SEM 刀沿）——**向单批数据拟合阈值是
自适应偏差**。v4.1 终值 0.060 取全部 20 个干净 live episode 阳性对照 5-seed 均值
（0.0548）+ 微裕度，margin_good=+0.005、separation=5.75。后续若再触刀沿，应改
区间判定（ess ± SEM 跨阈记 borderline）而非继续挪阈值——**该区间判定已在 v5 落地**
（见上节黄灯语义）。

v4 起契约违约观测量改为**违约率**（每 100 个助手 turn 的违约数，insights/score
同一键位 `violations`）：原始计数随话务量漂移（30 天 run 的 turn 数 348-1286），
session 多的 run 被冤枉；归一化后跨 run 可比。report.json 顶层同时保留原始计数
`contract_violations` 与比率 `contract_violation_rate`（0-1，入聚合口径）。

注意：用新阈值重新 eval 旧存档，verdict 可能与存档时不同。

### 实测基线（历史 replay 口径，待 live 重测）

> ⚠️ 下表为 replay 时代基线（8 seed × 30 天，三档脚本 good/mid/poor），仅作历史
> 参照；live 对照组（reference vs stub）的基线尚待重测。

| 档位 | ess | 带内驻留 | ‖x−x̂‖ 终值 | 健康分 | 判定众数 |
|---|---|---|---|---|---|
| good | 0.0107 ± 0.0054 | 88.8% | 0.0127 | 96.9 | converged |
| mid | 0.0407 ± 0.0305 | 41.3% | 0.0953 | 82.9 | oscillating |
| poor | 0.1237 ± 0.0605 | 5.9% | 0.2728 | 71.0 | diverged |

守护指标（历史 replay 口径）：`margin_good=+0.0193`、`margin_poor=+0.0437`、`separation=2.20`。

## 5. 前端

顶级页面「批量评测」：参数组合表单（组/seeds/天数/并发/max_episodes，默认即模型天梯
实验 5 组 × seeds 42-46 × 30 天）+ 一键启动（POST /api/bench，恒 live 烧 token，
max_episodes 为成本确认闸门）、总进度条与进行中 episode 逐个进度（slots.jsonl 推导）、
分组聚合表（mean ± 95% CI，含违约次数与违约率两列）、已知组效度检验红绿灯卡、episode 明细。
运行控制台中 bench 以文件夹分组呈现、内部 run 可下钻回放；进行中的 bench 文件夹
实时显示各 run 天数进度。也仍可经 CLI 发起（`python -m usersim bench …`）。

## 6. 实现备注

- `bench/` 是新的组装点，已登记进 `docs/00` 依赖表与依赖规则测试。
- `evaluate_run` 现在一并落盘 `insights.json`（此前 insights 只由 API 按需计算、从不持久化，
  导致批量拿不到 health_score、同一 run 的诊断结论也无法归档比对）。
- 健康分权重外置到 `config/system.toml [score]`，`stats.score_deductions` 输出逐项扣分明细
  （此前是 `insights.py` 里的一串魔数，主 KPI 不可审计）。
- 修掉一个假通过的测试：`test_same_seed_same_trajectory` 原先两次 run 落到同一个时间戳目录，
  实际是"文件与自己比较"而恒真；现在显式指定不同 `run_id` 并归一化 `run_id` 字段后比较。
