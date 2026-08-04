# 12 · Benchmark 执行协议（可插拔被测件 · 多 seed 统计 · 量程守护）

状态: 已实现（第三轮迭代 Phase 1）

> 本文档回答：怎么把 UserSim 当 benchmark 用，而不只是当仿真工作台看。

## 0. 为什么需要这一层

第三轮迭代前的实际状况：

| 问题 | 后果 |
|---|---|
| Runner 硬编码 `ReferenceHarness` | E1/E2 评测矩阵在代码层无处落脚，"被测件"名不副实 |
| 全部结论来自 seed=42 单角色单跑 | 无法区分"助手 A 比 B 好"与"这个 seed 恰好对 A 友好" |
| `config_hash` 只哈希 `system.toml` | 改 Excel 配表/catalog/prompt 都不反映在凭证里，两个"同 hash"的 run 其实不可比 |
| 调参压缩了 good/poor 的分辨率且无守护 | poor 档 ess 距发散阈值仅剩 0.004 裕度（docs/10 记录） |

## 1. 被测件接入（Harness 协议）

```python
class Harness(Protocol):
    def on_turn(self, obs: HarnessObs) -> AssistantTurn: ...
    def snapshot(self) -> dict: ...          # 续跑用
    def restore(self, state: dict) -> None: ...
```

- 落位 `agents/assistant/base.py`；注册表 `agents/assistant/registry.py`。
- 内置两个：`reference`（及格线）与 `stub`（失能下界：恒定 x̂=0.5、零干预）。
- 被测件**只能看到 `HarnessObs`**：`user_say / history / tool_results / balance /
  schedule_hint / recovery_catalog / slot_names / day / slot`。真实状态 `x`、world 的翻译
  词典、`runs/` 日志都不在其中。需要世界信息时由 Runner 注入。
- 选择方式：CLI `--harness NAME`、`POST /api/runs {"harness": ...}`、或前端启动表单下拉。
  所用 harness 名写入 `meta.json`。
- **异常隔离**：被测件是第三方代码，`on_turn` 抛任何异常都记为契约违约并继续，不会让整个
  episode 丢失（此前只捕获 `LLMError`/`ValidationError`，其他异常会终止长 run）。

### 评测矩阵

| 矩阵 | 固定 | 变化 |
|---|---|---|
| E1（测 Model） | `--harness reference` | `config/llm.toml [roles.assistant_agent]` 的 provider/model |
| E2（测 Harness） | 参考 provider | `--harness <你的实现>` |

## 2. 可复现性凭证

`meta.json` 新增三个字段（均有默认值，旧 run 仍可读）：

- `harness`：被测件名（replay 模式记 `scripted:<档位>`）；
- `artifact_hashes`：`system / llm / balance / catalog / prompts / combined` 逐项哈希；
- `prompt_versions`：各 agent 的 `PROMPT_VERSION`（此前定义了但从不落盘）。

**密钥安全**：`llm.toml` 的哈希先剔除所有含 `api_key` 的行再计算，密钥不作为哈希前像进入产物。
已有测试验证"改密钥不改哈希、改端点改哈希"。

**跨 run 可比性判据**：仅当 `artifact_hashes.combined` 相同时，两个 run 的指标才严格可比。

## 3. 多 seed 批量与置信区间

```bash
python -m usersim bench --seeds 1-8 --days 30 --mode replay          # 0 token
python -m usersim bench --seeds 1-20 --archetypes all --mode replay  # 全职业
python -m usersim bench --mode live --seeds 1-3 --max-episodes 3     # 需显式确认成本
```

- 每个标量指标输出 `mean / std / n / ci95`（n≤30 用 t 分布，>30 用正态近似；只依赖标准库）。
- `verdict` 输出三档占比与众数。
- **`settling_time_days = None` 单独计为 `never_settled`，不当缺失值丢弃**——否则从未回带的
  最差助手会因为样本被丢掉而看起来最好。
- 产物：`runs/_bench/<bench_id>/{episodes.jsonl, aggregate.json, discriminability.json}`。
- 成本闸门：live 模式硬上限 20 episode，且必须显式 `--max-episodes`；replay 全量免费。
  live 走串行（避免多进程同时打同一 provider 触发限流），replay 走进程池。

## 4. 量程守护（本轮新增的核心机制）

把"世界能否分辨好助手与差助手"变成可断言的量：

```
margin_poor = mean(ess_poor) - diverged_ess_min     > 0.02   才算差助手确实被判差
margin_good = converged_ess_max - mean(ess_good)    > 0.005  才算好助手确实被判好
separation  = Cohen's d(ess_good, ess_poor)         > 1.5    两档必须清晰可分
```

`tests/test_discriminability.py`（8 seed × 三档，标记 `slow`）额外断言带内驻留分离
（good − poor > 0.30）与健康分敏感度（good − poor > 15）。

**作用**：以后任何调参（含 Excel 热编辑）压缩了量程会立刻红灯，而不是像 R1/R2 那样事后在
文档里记一句"记录观察"。

### 实测基线（8 seed × 30 天，规则回放）

| 档位 | ess | 带内驻留 | ‖x−x̂‖ 终值 | 健康分 | 判定众数 |
|---|---|---|---|---|---|
| good | 0.0107 ± 0.0054 | 88.8% | 0.0127 | 96.9 | converged |
| mid | 0.0407 ± 0.0305 | 41.3% | 0.0953 | 82.9 | oscillating |
| poor | 0.1237 ± 0.0605 | 5.9% | 0.2728 | 71.0 | diverged |

守护指标：`margin_good=+0.0193`、`margin_poor=+0.0437`、`separation=2.20` — 全部通过。

## 5. 前端

顶级页面「批量评测」：分组聚合表（mean ± 95% CI）、量程守护红绿灯卡、按 episode 明细。
启动按钮只跑 replay（零成本）；live 批量刻意只留 CLI 入口，强制人显式确认成本。

## 6. 实现备注

- `bench/` 是新的组装点，已登记进 `docs/00` 依赖表与依赖规则测试。
- `evaluate_run` 现在一并落盘 `insights.json`（此前 insights 只由 API 按需计算、从不持久化，
  导致批量拿不到 health_score、同一 run 的诊断结论也无法归档比对）。
- 健康分权重外置到 `config/system.toml [score]`，`stats.score_deductions` 输出逐项扣分明细
  （此前是 `insights.py` 里的一串魔数，主 KPI 不可审计）。
- 修掉一个假通过的测试：`test_same_seed_same_trajectory` 原先两次 run 落到同一个时间戳目录，
  实际是"文件与自己比较"而恒真；现在显式指定不同 `run_id` 并归一化 `run_id` 字段后比较。
