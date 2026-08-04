"""状态动力学：纯规则差分方程（0 LLM）。

每 slot 结算顺序（顺序即语义）：
1. 自然漂移（进餐/工作/休息/睡眠的基线作用）
2. 反弹检查（压力被压过低 → 积压工作反弹）
3. 事件效果（按 span 摊销；recovery 类计入 control_effects）
4. 心情耦合（valence 向准稳态漂移）
5. 限幅 [0,1]
"""

from __future__ import annotations

from usersim.contracts import DIMS, Event, StateVec, dim_error, total_error

# dim_error / total_error / DIMS 的权威定义已下移至 contracts.metrics
# （world / evaluator / agents 三方共用，见 docs/00 依赖表）。
# 此处 re-export 保持既有 import 路径可用。
__all__ = ["DIMS", "dim_error", "total_error", "settle_slot"]


def _clip01(v: float) -> float:
    return min(1.0, max(0.0, v))


def settle_slot(
    x: StateVec,
    day: int,
    slot: int,
    is_workday: bool,
    active_events: list[Event],
    dyn,  # Namespace: config [dynamics]
    reversion_mult: float = 1.0,  # 人格调节（神经质越高越慢），由 world 传入
) -> tuple[StateVec, dict[str, float], dict[str, float], dict[str, float]]:
    """返回 (x_after, natural_drift, event_effects, control_effects)。"""
    d = x.model_dump()
    before = dict(d)
    natural: dict[str, float] = {k: 0.0 for k in DIMS}
    event_fx: dict[str, float] = {k: 0.0 for k in DIMS}
    control_fx: dict[str, float] = {k: 0.0 for k in DIMS}

    def add(bucket: dict[str, float], k: str, v: float) -> None:
        d[k] += v
        bucket[k] += v

    # 1) 自然漂移（新陈代谢与工作基线；进餐/睡眠已移入事件配表，不在此结算）
    add(natural, "satiety", -dyn.satiety_drain_per_slot)
    # 2) 反弹检查（影响本时段工作效果倍率）
    rebound = d["stress"] < dyn.rebound_threshold
    mult = dyn.rebound_multiplier if rebound else 1.0

    if slot == 0:  # 上午
        if is_workday:
            add(natural, "energy", -dyn.work_energy_drain * (1.5 if rebound else 1.0))
            add(natural, "stress", dyn.work_stress_per_slot * mult)
        else:
            add(natural, "energy", -0.03)
    elif slot == 1:  # 下午
        if is_workday:
            add(natural, "energy", -dyn.work_energy_drain * (1.5 if rebound else 1.0))
            add(natural, "stress", dyn.work_stress_per_slot * mult)
        else:
            add(natural, "energy", -0.03)
            add(natural, "valence", 0.03)
            add(natural, "stress", -dyn.rest_stress_relief)
    elif slot == 2:  # 晚上
        add(natural, "stress", -dyn.rest_stress_relief)
        add(natural, "energy", -(0.04 if is_workday else 0.03))
    # 深夜无自然漂移：睡眠恢复由"睡眠事件"（配表档位）结算

    # 压力均值回归：自然心理调适（O1——防止慢性压力无限累积，保留扰动冲击）
    # 神经质调节（docs/11 第 4 节）：神经质越高，压力回落越慢
    if hasattr(dyn, "stress_mean_reversion"):
        rate = dyn.stress_mean_reversion * reversion_mult
        add(natural, "stress", (dyn.stress_reversion_target - d["stress"]) * rate)

    # 3) 事件效果（数值按 span 摊销；pull 类拉向准稳态，不摊销）
    for e in active_events:
        if not e.effect:
            continue
        bucket = control_fx if e.kind == "recovery" else event_fx
        for k, v in e.effect.items():
            if k not in d:
                continue
            if isinstance(v, dict) and "pull" in v:
                target, rate = float(v["pull"][0]), float(v["pull"][1])
                add(bucket, k, (target - d[k]) * rate)
            else:
                add(bucket, k, float(v) / e.span_slots)

    # 4) 心情耦合（消极偏向：变差快 ×1.5，变好慢 ×0.7）
    v_eq = (
        0.75
        + 0.35 * (d["energy"] - 0.68)
        - 0.55 * (d["stress"] - 0.30)
        + 0.10 * (d["satiety"] - 0.60)
    )
    delta = v_eq - d["valence"]
    rate = dyn.valence_coupling_rate * (1.5 if delta < 0 else 0.7)
    dv = rate * delta
    d["valence"] += dv
    natural["valence"] += dv

    # 5) 限幅
    for k in DIMS:
        d[k] = _clip01(d[k])
    # 漂移量修正为实际生效量（限幅会截断）
    x_after = StateVec(**d)
    return x_after, natural, event_fx, control_fx
