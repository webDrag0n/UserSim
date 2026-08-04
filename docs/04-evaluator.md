# 04 · 评估器（evaluator）

状态: 草稿

> 约束：0 次 LLM 调用；只读 `runs/` 日志；可离线重放，与世界迭代解耦。

## 1. 输入与输出

- 输入：`runs/<run_id>/` 下的 `slots.jsonl`（含每时段 x_true）、`turns.jsonl`（含每 turn 的 x_hat 与工具调用）、`meta.json`（seed、配置快照、角色卡）；
- 输出：`report.json`（机读）+ `report.html`（人读，内嵌图表）+ 可选 `summary.csv`（跨 run 对比）。

## 2. 指标体系（全部为轨迹的确定性函数）

| 指标 | 符号 | 定义 | 回答的问题 |
|---|---|---|---|
| 稳态误差 | e_ss | 末端 `tail_slots_for_ess` 个时段 mean e(t) | 最终收敛还是发散 |
| 调节时间 | t_s | 首次大扰动后连续 `settle_band_slots` 个时段入带所需天数 | 恢复速度 |
| 超调量 | M_p | 冲出带外后被反向压过目标的最大深度（带前置条件窗口） | 干预过猛 |
| 积分指标 | IAE / ISE / ITAE | ∫\|e\|、∫e²、∫t·\|e\|（按天归一） | 全程 / 大误差 / 晚期误差 |
| 状态方差 | σ² | e(t) 全轨迹方差 | 平稳性 |
| 带内驻留比 | ρ | 窗口内处于平和带的时段占比 | 生活质量 |
| 估计误差 | ‖x−x̂‖₂ | 每日均值 + 时间斜率（学习曲线） | Harness 是否越用越懂用户 |
| 画像精度 | `persona_err` | 末日逐 facet MAE/100 + 每日斜率 + 覆盖率 | 是否越聊越懂用户的**人格** |
| 喜好精度 | `prefs_err` | 类目 MAE/2 + loves/hates 的 F1 | 是否摸清了**喜好** |
| 行为指标 | — | 契约违约率、降级率、求助及时性、打扰率 | 协议遵守与分寸感 |

其中逐维误差为**单侧误差**：健康维低于目标才算偏差，压力高于目标才算偏差（"过度开心"不算失控）：

```
e_i(t) = max(0, r_i − x_i(t))   对 good=high 维
e_i(t) = max(0, x_i(t) − r_i)   对 good=low 维（stress）
e(t)   = mean_i e_i(t)
```

## 3. 收敛判定（三级）

```
converged   ⇐  e_ss ≤ converged_ess_max
            ∧  t_s  ≤ converged_settle_max（且存在）
            ∧  M_p  < converged_overshoot_max
diverged    ⇐  e_ss > diverged_ess_min  ∨  worsening
oscillating ⇐  其余（能回稳但反复过冲，存在极限环）
```

其中 `worsening` = 后 5 天日均误差 > 前 5 天 × 1.5 + 0.02（**窗口均值对比**，比端点斜率抗振荡
噪声）。原 `diverged_slope_min` 配置项已删除——它被窗口均值法取代后成了死配置，留着会让人以为
斜率判据仍在生效。

所有阈值集中在 `config/system.toml [eval]`。

## 4. 滑动窗口与 episode 报告

- 生成器无限延展 → 评估按 `[eval].window_days` 滑窗持续输出窗口指标序列（用于超长 run 的健康监控）。
  已实现：`report.windows` 为逐日滑动的 `{start_day, end_day, mean_err, max_err, in_band_ratio}` 序列。
- benchmark 对比报告按 `run.days` 的 episode 为单位产出；跨 seed 聚合见 `docs/12-benchmark.md`。

**时钟刻度**：所有按天归一的指标从 `SlotSettlement.slots_per_day` 读取刻度（world 写入），
不再硬编码 4——此前改 `[clock].slots_per_day` 会让 IAE/ITAE/调节时间/学习曲线全部静默算错。

## 4b. 健康分权重（主 KPI，可审计）

扣分 = `min(上限, 观测量 × 系数)`，权重在 `config/system.toml [score]`，
逐项扣分明细输出在 `insights.stats.score_deductions`。

| 项 | 系数 | 上限 | 依据 |
|---|---|---|---|
| `ess` | 200 | 40 | 稳态误差即控制目标本身，权重最重 |
| `violations` | 5 | 15 | 协议遵守是硬要求，但单次违约不应主导总分 |
| `xhat_bias` | 80 | 10 | 观测器系统性偏移（0.125 的偏差即扣满） |
| `user_dup` | 1.5 | 10 | 拟人性：台词复读 |
| `clamp_ratio` | 80 | 10 | 世界分辨力：状态顶到边界即损失信息 |
| `no_recover` | 2 | 10 | 干预覆盖：扰动是最明确的介入时机 |
| `persona_err` | 40 | 10 | 画像精度：人格/喜好估计偏差（0.25 即扣满）。**没有估计按 0.5 满误差计**——不作为不能免罚，否则 stub 反而占便宜 |

## 4c. x̂ 指标的基线断代声明

`docs/10`（R1/R2）记录的 `x̂` 偏差数值属**刻度泄漏期数据**：当时 `reference.py` 提示词里的
逐维校准刻度与 `world/felt.py` 的分档词典互为逆映射，助手做字符串查表即可压低偏差。
这些数值**不可与 Phase 2 去泄漏之后的数值比较**。

去泄漏后 `est_err_final` 预期会变差，这是真实基线而非退步。观测器能力应改看
`est_err_slope_per_day`（是否为负 = 是否越用越懂用户）。

## 4d. 画像精度（冻结维度）

`persona_err` / `prefs_err` 度量助手对**人格 30 facet 与结构化喜好**的估计准确度，
真值取 `meta.json` 的角色卡，估计取每个助手 turn 的 `persona_hat`。三个设计取舍：

1. **取末期而非全程均值**——画像是学习任务，"最后学没学会"才是考点；全程均值会
   惩罚"一开始不懂"这件必然的事；
2. **没有估计 ≠ 零误差**——未估计的 facet 不参与误差，覆盖率单独报告
   （`persona_coverage`）；健康分里则按满误差计罚；
3. **标签命中双向包含**——真值"寿喜烧"与估计"喜欢吃寿喜烧"算命中，不要求复现原文。

与 `x̂` 不同，这里**不存在刻度泄漏**：facet 真值从不出现在任何对话文本里，助手只能
从用户的言行推断。详见 `docs/13-persona-model.md`。

## 5. 报告内容（report.html 章节）

1. 运行元信息（seed / 配置快照哈希 / 角色卡）；
2. 状态轨迹图（四维 + 综合误差，扰动标注，平和带）；
3. 判定徽章与指标卡；
4. 估计误差学习曲线；
5. 事件统计（三类事件计数、恢复事件响应时延）；
6. 行为指标表（违约/降级/打扰）；
7. 附：轨迹文件清单与复算命令。

## 6. 评估器自身的测试

- 构造合成轨迹（线性收敛/正弦振荡/线性发散）→ 三个 verdict 必须分别命中；
- 指标对拍：与 `scripts/` 中的独立参考实现（numpy 直算）交叉验证；
- 配置变更测试：阈值改动只影响 verdict，不影响轨迹。

## 7. 实现备注

- 落位于 `evaluator/metrics.py`（指标）+ `evaluator/report.py`（report.json + 终端摘要）。
- 合成轨迹对拍（线性收敛/正弦振荡/线性发散）三个 verdict 全部命中；三档回放集成测试通过（tests/test_evaluator.py，14/14 全绿）。
- report.html 未单独产出——人读报告由 web 前端报告视图承担（轨迹图/指标卡/学习曲线），数据来自 report.json。
