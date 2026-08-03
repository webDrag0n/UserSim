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
| 画像精度 | — | x̂ 冻结维度与角色卡匹配度 | 长程画像能力 |
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
diverged    ⇐  e_ss > diverged_ess_min  ∨  后10天日均误差斜率 > diverged_slope_min
oscillating ⇐  其余（能回稳但反复过冲，存在极限环）
```

所有阈值集中在 `config/system.toml [eval]`。

## 4. 滑动窗口与 episode 报告

- 生成器无限延展 → 评估按 `[eval].window_days` 滑窗持续输出窗口指标序列（用于超长 run 的健康监控）；
- benchmark 对比报告按 `run.days` 的 episode 为单位产出。

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
