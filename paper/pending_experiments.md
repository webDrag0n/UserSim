# UserSim 论文待补充实验文档

> 配套 `paper/full_draft_v3.md` §3 Experiments：正文中所有 `[·]` 占位与"待补充"小节的数据产出实验均在此定义。
> 每个实验给出：目标 / 对应论文小节与表图 / 设计（组、seed、天数、命令）/ 预期产物 / 成功判据（预先注册断言）/ 依赖与成本。
> 数据卫生规则见文末，任何批次进论文前必须逐条核对。

## E0 · v4 口径阴性对照与 known-groups 效度检验重跑

- **目标**：补齐 v4 评分口径下的 stub 阴性对照，完成完整的已知组效度检验（margin_good / margin_poor / Cohen's d）。
- **对应论文位置**：§3.2 末尾声明、§3.4 表 5 stub 行、§2.5.5 效度协议的实证闭环。
- **设计**：

```bash
python -m usersim bench --groups reference,stub --seeds 42-46 --days 30 --max-episodes 10 --concurrency 5
```

- 组：reference（阳性对照）+ stub（阴性对照，无 LLM、恒定估计、零干预）；5 seeds × 30 天，共 10 episodes（reference 组命中断点续跑则实际只烧 stub 的 5 个）。
- **预期产物**：`runs/_bench/bench_live_<ts>/{episodes.jsonl, aggregate.json, discriminability.json}`。
- **成功判据**（预注册）：margin_poor > 0；margin_good > 0（跨阈记 borderline 时应加 seed 而非挪阈值）；separation Cohen's d > 1.5。历史参照（0823 批次、v4.1 重算口径）：margin_good=+0.005、margin_poor=+0.157、d=3.96。
- **成本**：stub 无 LLM 调用，仅用户侧 token（≈18 万 tokens × 5 episodes）。

## E1a · 模型主榜（W1 旗舰波）

- **目标**：产出表 4 主榜 S 档 9 模型数据，检验 H4（主榜区分度）/H5（档位单调性）。
- **对应论文位置**：§3.3 表 4、图 6（帕累托）、图 7（职业热力图）。
- **设计**：名单冻结于 `paper/design/model_selection.md` v1.0（S 档：Claude Fable 5 / Opus 5 / GPT-5.5 / Gemini 3.1 Pro / Kimi K3 / DeepSeek V4 Pro / Qwen3.8 Max / GLM 5.2 Max / Grok 4.6）。每模型 6 职业 × 3 seeds = 18 episodes；harness 固定 reference，每模型一个 profile（复制 `reference.toml`，`[llm] provider/model` 钉具体快照版本）。
- **工程前置**（model_selection.md §4）：`config/llm.toml` 逐模型加 provider；榜单元数据（家族/档位/价格带/快照日期）随 artifact 哈希登记。
- **成功判据**：H4 首尾 Tier 不重叠、相邻名次对分差 > MDE 的比例 ≥ 预设值；H5 四档均分单调不减；CI 重叠归入同一 Tier。
- **成本**：162 episodes ≈ 58M tokens，估算 $160–550。
- **注意事项**：① 一律使用钉版模型名（别名会被供应商静默换血）；② 批量前后做余额探针（0823 批次 402 余额耗尽污染 5 个 episode 的教训）；③ 逐批跑 `test_bench_integrity` 同款 turns 跨组 sha256 校验。

## E1b · 相邻档位可靠性检验扩样

- **目标**：坐实/推翻 3.2 节发现 2（pro vs flash 差异在方差而非均值）。
- **对应论文位置**：§3.2 发现 2。
- **设计**：reference 与 reference_pro 各补 3 个 seed（seeds 47–49），合计 n=8/组；命令同 E0 模式，`--groups reference,reference_pro --seeds 47-49`。
- **成功判据**：n=8 下重算配对 t 与方差比 F（历史参照：0823 批次 F(4,4)=8.11 vs 临界 9.6，边缘）。

## E2 · 用户仪器模型横评（测量仪器研究）

- **目标**：回答"评测结论对用户模型选择是否稳健"。
- **对应论文位置**：§3.6 表 7 扩展、§3.8 表 9"用户仪器模型"行。
- **设计**：user impl 固定 standard（prompt/机制不变），assistant 固定 reference + DeepSeek V4 Flash，只换 user 驱动模型（6 款：DeepSeek V4 Flash 基线 / Qwen3.7 Plus / GPT-5.4 mini / Kimi K3-256k / Claude Sonnet 5 / Qwen3.6 27B）；抽样 2 职业（高压互联网从业者、倒班护士）× 3 seeds，约 36 episodes ≈ 13M tokens。
- **产出**：① 各用户模型的 M1–M5 得分与拟人性指标（不合格仪器标记阈值：操纵检验显著低于基线）；② **关键有效性证据**——更换用户模型后 assistant 排名的 Spearman ρ（ρ 高 → 主榜结论对仪器选择不敏感）。

## E3 · 外部 Harness 横评（openclaw / hermes）

- **目标**：填表 5 的 openclaw/hermes 行，检验 H6（harness 间可分）。
- **对应论文位置**：§3.4 表 5。
- **设计**：`--groups openclaw,openclaw_pro,hermes,hermes_pro --seeds 42-46 --days 30`（profile 已就绪，CLI 整机接入、原生 session 记忆）；assistant 模型 flash/pro 两档 × 5 seeds = 20 episodes。
- **成功判据**：openclaw/hermes 落位与 reference 的差超过 MDE（方向不限——高于或低于参考线均有信息量）；stub 显著低于一切正常实现（与 E0 联动）。
- **依赖**：本机已装对应 agent CLI；每轮消息携带 Runner 注入的 recovery_catalog（信息对等约定）。

## E4 · 真人对照研究

- **目标**：① 轨迹拟真度人类标注（§3.6 表 8）；② 人类成对排序一致性（§3.5 表 6 第一行）。
- **设计**：
  - **拟真度**：抽 [100] 条轨迹片段（UserSim 用户 vs 真实陪伴型对话摘录混洗），n=[·] 名标注者打拟真度分；同批片段交强 LLM 打分，先算人类 vs LLM 的 Spearman ρ 确立 LLM 代理合法性，再 LLM 全量打分。
  - **成对排序**：同 seed 不同助手的 trace 对 [·] 组，标注者判断"哪个助手更好"，度量 Krippendorff's α / pairwise 一致率。预期（experiment-validity-notes.md 模块 B）：人类排序方差大 → "与人工排序算 Kendall τ"的传统效度路径根基是噪声。
- **注意**：目的是证明人类标注方差，不是建立金标准；小样本即可。拟真度与排序可复用同一批标注资源。

## E5 · LLM Judge 稳定性对比

- **目标**：§3.5 表 6 第二行，检验 H8/H9。
- **设计**：同批 trace（沿用 E4 的 trace 池）交 Claude Fable 5（及 [·] 个对照 judge）评分：每 trace 重复 [5] 次 × 2 种 prompt 措辞 × 顺序翻转。度量：组内方差、重采样排名变动率、顺序偏置幅度、冗长偏置（回复长度与得分相关）。
- **成功判据**：H8——judge 重采样排名变动率显著 > 0 且存在显著顺序/冗长偏置（p < 0.05）；规则评分重算方差 = 0（构造保证）。H9——强信号 trace 对（reference vs stub）三方一致，弱信号对上人类与 judge 分歧放大。

## E6 · 鲁棒性扰动矩阵

- **目标**：填 §3.8 表 9，检验 H10。
- **设计**：逐项扰动重跑小规模 bench（reference + stub 各 3 seeds）：
  1. Episode 长度 7/14/30/60 天（已有 10 天与 2 天历史 run 可作趋势参照，但口径需统一到 v4 重评估）；
  2. 容差带半宽 β ±25%（改 `config/system.toml [state] band`，离线重评估即可，无需重跑）；
  3. 扰动强度（`disturbance_prob_per_day`）±[·]%；
  4. 职业原型留一法（`--archetypes` 子集）；
  5. Seed 数 4/8/16（复用存量 + 补跑）；
  6. 用户温度 ±[·]（`[llm]` user temperature）。
- **成功判据**：H10——全部扰动下主榜 Tier 结构与基线秩相关 ρ > [·]，known-groups 三判据保持成立；不满足则在 Discussion 如实划定结论有效域。
- **注意**：β 与评分权重扰动可纯离线重评估（评估器确定性）；世界动力学参数扰动必须重跑且会产生新 artifact 哈希，结论只在同哈希内可比。

## E7 · 成本核算

- **目标**：填 §3.9。
- **设计**：从各 run `meta.json` / turns.jsonl 与 provider 账单统计单 episode token 与美元成本（按模型分列）；规则评分边际成本（≈0）vs LLM judge / 人工标注单价对比；断点续跑的增量成本实测。
- **参照基线**：≈12k tokens/天（双侧合计），单 episode ≈ 36 万 tokens；W1 旗舰波 162 episodes ≈ 58M tokens。

## E8 · 失败案例研究与图表绘制

- **目标**：§3.7 失败案例 + 图 3/4/5/8 绘制。
- **设计**：
  - 从 0830 批次选 3 个典型失败 trace（候选：reference_nomem seed44 得 0.0 分 episode；reference seed43 得 44.1 的两极分化低位 episode；任一 diverged episode），做维度 × 时段 × 事件的时空归因叙述；
  - 图 4/图 5：从各 run `report.json` 的 `daily_persona_err` / `daily_est_err` 序列直接绘制（数据已落盘，参考 `paper/figures/gen_figures.py` 的既有绘图约定）；
  - 图 8：三族指标归一化后雷达图；图 3：从 slots.jsonl 取一条代表性状态轨迹（如 reference seed42）叠加稳态带绘制。

## 数据卫生规则（进论文前逐条核对）

1. **不可引用批次**：`runs_archive/_bench/bench_live_v56full_20260827`（pro 与 nomem 组 turns.jsonl 逐字节相同，输出复制 bug，由 `tests/test_bench_integrity.py` 防复发）；`runs_archive/_bench/_quarantine_402/`（provider 余额耗尽污染，轨迹退化为纯世界漂移）。
2. **口径纪律**：benchmark score 的 v3 / v4.1 重算 / v4 三套数值不可混排进同一张表；正文统一使用 v4（`bench_live_20260830T164021` 及之后的批次）。历史 replay 三档基线（good/mid/poor）仅作开发史参照，不进论文。
3. **模型归属**：以各 run `reported_models.json`（provider 实际应答模型）为准；`meta.json` 的 `llm_roles` 不反映 profile 的模型覆盖，勿引用。
4. **可比性判据**：跨 run 比较仅当 `artifact_hashes.combined` 相同才严格成立；任何配置/配表/prompt 变更后跑的批次必须标注新哈希。
5. **never_settled 语义**：出带后从未回归单独计数，不当缺失值丢弃；全程未出带记 t_s=0 且不计入 never_settled。
6. **阈值冻结**：eval 阈值（converged_ess_max=0.060 等）已按 v4.1 标定冻结；触刀沿时加 seed 或采用 borderline 区间判定，不得向单批数据再拟合阈值（自适应偏差教训，见 docs/12 §4）。
