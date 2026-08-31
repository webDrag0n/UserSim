# 16. 模型能力分级实验（deepseek v4-flash / v4-pro）

> 状态：设计已定稿并执行（R6 之后）。约束：当前只用 deepseek 家族的钉版模型
> （别名会被供应商静默换血，一律用具体版本名）。

## 1. 研究问题

在**用户模型固定**（deepseek-v4-flash，测量仪器不变）的前提下：

- **Q1（能力分级）**：助手 LLM 从 v4-flash 换成 v4-pro，benchmark 各层指标
  （控制/估计/画像/契约）提升多少？benchmark 能否分辨同家族相邻档位？
- **Q2（机制 × 能力交互）**：记忆消融（reference_nomem）对不同档位模型的伤害
  是否相同——强模型能否靠上下文内推理弥补无记忆？
- **Q3（已知组效度检验）**：reference 与 stub（阴性对照）的可分辨性在钉版模型下是否成立。

## 2. 因子设计（2×2 + 对照组）

| 组（profile） | harness | 助手模型 | 角色 |
|---|---|---|---|
| reference | reference | deepseek-v4-flash | 基线 |
| reference_pro | reference | deepseek-v4-pro | Q1 处理 |
| reference_nomem | reference_nomem | deepseek-v4-flash | 消融基线 |
| reference_nomem_pro | reference_nomem | deepseek-v4-pro | Q2 处理 |
| stub | stub | 无 LLM | Q3 负对照 |

- 模型差异**只**经 profiles 的 `[llm] model` 覆盖实现，prompt/代码完全相同——
  差异可归因于模型能力。
- 用户侧固定：standard（prompt v6）+ deepseek-v4-flash + temperature 0.5。
- 复本：seed ∈ {42, …, 46}（每格 5 个；首跑 42-44 后证实 flash 组内 sd≈12.4，
  n=3 功效不足，扩到 5 以支撑 H1/H2 检验）。
- 时长：30 天/episode（与 benchmark 阈值标定尺度一致；调节时间/斜率类指标需要跑道）。
- 共 5 组 × 5 seed = **25 episodes**（实际烧 token 的 todo ≤ 硬上限 20，存量断点续跑
  自动跳过/重评估零成本），按 `--concurrency` 并发（防限流靠 chat_json 指数退避兜底）。
- 评分口径 v4：收敛阈值按首轮 15 episode 重标定（converged_ess_max 0.030→0.050），
  违约按话务量归一（详见 12-benchmark 第 4 节）；全部存档经离线重评估统一到 v4。

## 3. 假设

- H1：pro 的 benchmark 总分显著高于 flash（主效应），主要来自画像学习与契约稳定。
- H2：nomem 对两档都降分，但 pro 的降幅更小（交互效应）。
- H3：reference 组与 stub 组在控制/估计指标上显著分离（对照分离成立）。

## 4. 观测指标（每 episode 落盘 report.json / insights.json）

- 总分：benchmark score（v3 公式，见 docs/04 第 8 节）
- 控制：e_ss / t_s / M_p / 带内驻留比
- 估计：‖x−x̂‖ 终值与斜率
- 画像：persona_err / prefs F1
- 行为：contract_violations、dialogue 形态指标（复读率/口癖率/熔断数）

## 5. 执行与分析

```bash
python -m usersim bench --groups reference,reference_pro,reference_nomem,reference_nomem_pro,stub \
  --seeds 42-46 --days 30 --max-episodes 25 --concurrency 5
```

产物：`runs/_bench/bench_live_<ts>/`（episodes.jsonl / aggregate.json /
discriminability.json + 每格完整 run 存档）。分析时按组聚合 mean±sd，
对照 H1-H3；已知组效度检验要求 reference vs stub 显著分离，否则本轮数据不可用于模型比较。

## 6. 结果（bench_live_20260823T175134，25 episodes 全矩阵，评分口径 v4.1）

| 组 | n | benchmark mean±CI95 | ess mean | 违约率/turn | 判定众数 |
|---|---|---|---|---|---|
| reference（flash+记忆） | 5 | 19.8 ± 16.2 | 0.0548 | 12.5% | oscillating |
| reference_pro（pro+记忆） | 5 | 20.0 ± 5.7 | 0.0450 | 15.7% | oscillating |
| reference_nomem | 5 | 11.6 ± 10.7 | 0.0937 | 1.4% | oscillating |
| reference_nomem_pro | 5 | 8.9 ± 5.6 | 0.0535 | 7.0% | oscillating |
| stub | 5 | 4.8 ± 3.7 | 0.2373 | 0% | diverged |

已知组效度检验 ✅：margin_good=+0.005、margin_poor=+0.157、separation=3.96。

- **H1 不成立（均值层面）**：同种子配对差 t(4)=0.04，pro 与 flash 的 benchmark
  水平无差异；ess 配对差 t(4)=-0.92 亦不显著。pro 的差异体现在**方差**：
  benchmark 方差比 F(4,4)=8.11（临界 9.6，边缘）——pro 稳定、flash 两极
  （39.1 与 4.5 同组并存）。结论：该档差在此 benchmark 上是"可靠性差异"而非"能力水平差异"。
- **H2 不成立且方向反转**：记忆消融 flash Δ=-8.2、pro Δ=-11.1，pro 并未更抗消融。
  机理：nomem_pro 的 ess（0.0535）远好于 nomem flash（0.0937）且 100% 判 oscillating，
  但 benchmark 反而更低——pro 在无记忆长输出下契约违约率 7.0%（vs 1.4%），
  超时/违约扣分吃掉了控制优势。
- **H3 成立**：对照组分离近 4 个标准差，stub 全程发散、带内驻留 0%。
- 事故记录：补种子期间 provider 余额耗尽（402）污染 5 个 episode
  （大面积降级 → 轨迹退化为纯世界漂移，与 stub 逐位一致）；已隔离并重跑补齐。
  教训：批量前后应做余额探针；stub 同种子轨迹完全可复现（重跑 ess 逐位相同），
  反向验证了世界确定性。

## 7. 已知局限

- 单家族（deepseek）两档，结论不外推跨家族；接入新 provider 时按同矩阵复跑。
- 用户仪器本身也是 LLM（flash），其噪声是两组共享的背景——组间差仍是有效对比。
- n=5/格对方差比的检验功效有限（F=8.11 vs 临界 9.6）；要坐实"pro 更稳"需 n≥8。
- 3 复本只够粗估方差，显著性解读保持保守。
