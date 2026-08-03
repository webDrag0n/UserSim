"""评估器：控制论指标 + 三级判定 + 报告（0 LLM，只读 runs/ 日志）。"""

from __future__ import annotations

import json
from pathlib import Path

from usersim.contracts import SlotSettlement, StateVec, TurnRecord
from usersim.world.dynamics import DIMS, dim_error, total_error


def load_run(run_dir: Path) -> tuple[list[SlotSettlement], list[TurnRecord], dict]:
    slots = [SlotSettlement(**json.loads(l)) for l in (run_dir / "slots.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    turns_file = run_dir / "turns.jsonl"
    turns = [TurnRecord(**json.loads(l)) for l in turns_file.read_text(encoding="utf-8").splitlines() if l.strip()] if turns_file.exists() else []
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    return slots, turns, meta


def compute_metrics(
    slots: list[SlotSettlement],
    turns: list[TurnRecord],
    targets: dict[str, float],
    band: float,
    eval_cfg,
) -> dict:
    xs = [s.x_after for s in slots]
    n = len(xs)
    slots_per_day = _infer_slots_per_day(slots, eval_cfg)

    def in_band(x: StateVec) -> bool:
        return all(dim_error(x, d, targets) <= band for d in DIMS)

    es = [total_error(x, targets) for x in xs]

    # 稳态误差（末端若干时段）
    tail = es[-eval_cfg.tail_slots_for_ess:]
    ess = sum(tail) / len(tail) if tail else float("nan")

    # 积分指标（按天归一）
    iae = sum(es) / slots_per_day
    ise = sum(e * e for e in es) / slots_per_day
    itae = sum((i / slots_per_day) * e for i, e in enumerate(es)) / slots_per_day
    mean_e = sum(es) / n
    variance = sum((e - mean_e) ** 2 for e in es) / n

    # 调节时间：首次压力冲出带外后，连续 settle_band_slots 个时段回带
    settle_band = eval_cfg.settle_band_slots
    settling_time = None
    d0 = next((i for i, x in enumerate(xs) if dim_error(x, "stress", targets) > band), None)
    if d0 is not None:
        run = 0
        for i in range(d0, n):
            run = run + 1 if in_band(xs[i]) else 0
            if run >= settle_band:
                settling_time = (i - d0 - settle_band + 1) / slots_per_day
                break

    # 超调量：冲出带外后（前置窗口）被反向压到目标以下的最大深度。
    # 排除"大考结束"等事件巨量释放造成的下冲（那是事件效果，不是控制器过校正）。
    overshoot = 0.0
    hot = 0
    release_cooldown = 0
    for s in slots:
        x = s.x_after
        if s.event_effects.get("stress", 0.0) <= -0.08:
            release_cooldown = 8
            hot = 0
            continue
        if x.stress > targets["stress"] + band:
            hot = 10
        else:
            hot = max(0, hot - 1)
        if release_cooldown > 0:
            release_cooldown -= 1
        elif hot > 0:
            overshoot = max(overshoot, max(0.0, targets["stress"] - x.stress))

    # 带内驻留比（后 10 天）
    tail_pts = xs[-10 * slots_per_day:]
    in_band_ratio = sum(1 for x in tail_pts if in_band(x)) / len(tail_pts) if tail_pts else float("nan")

    # 估计误差学习曲线（每日 mean ‖x−x̂‖₂）
    daily_est_err = _daily_est_err(turns, slots_per_day)
    est_err_final = daily_est_err[-1][1] if daily_est_err else float("nan")
    est_err_slope = _slope([p[0] for p in daily_est_err], [p[1] for p in daily_est_err]) if len(daily_est_err) > 1 else 0.0

    # 后 10 天误差趋势：窗口均值对比（比端点斜率抗振荡噪声）
    daily_e = _daily_mean_err(xs, targets, slots_per_day)
    if len(daily_e) >= 10:
        last5 = sum(daily_e[-5:]) / 5
        prev5 = sum(daily_e[-10:-5]) / 5
        worsening = last5 > prev5 * 1.5 + 0.02
        late_slope = (daily_e[-1] - daily_e[-11]) / 10 if len(daily_e) > 10 else 0.0
    else:
        worsening = False
        late_slope = 0.0

    verdict = _verdict(ess, settling_time, overshoot, worsening, eval_cfg)

    return {
        "ess": ess,
        "settling_time_days": settling_time,
        "overshoot": overshoot,
        "iae": iae,
        "ise": ise,
        "itae": itae,
        "variance": variance,
        "in_band_ratio": in_band_ratio,
        "est_err_final": est_err_final,
        "est_err_slope_per_day": est_err_slope,
        "daily_est_err": [{"day": d, "err": e} for d, e in daily_est_err],
        "daily_err": [{"day": d, "e": e} for d, e in enumerate(daily_e)],
        "verdict": verdict,
    }


def _infer_slots_per_day(slots: list[SlotSettlement], eval_cfg) -> int:
    # slots.jsonl 不存 spd；与 run 配置一致（本系统固定 4）。优先从 t 序列推断最大值+1。
    return 4


def _daily_est_err(turns: list[TurnRecord], slots_per_day: int) -> list[tuple[int, float]]:
    by_day: dict[int, list[float]] = {}
    for t in turns:
        if t.x_hat is None:
            continue
        d = t.t_logical // slots_per_day
        err = (
            (t.x_true.valence - t.x_hat.valence) ** 2
            + (t.x_true.energy - t.x_hat.energy) ** 2
            + (t.x_true.satiety - t.x_hat.satiety) ** 2
            + (t.x_true.stress - t.x_hat.stress) ** 2
        ) ** 0.5
        by_day.setdefault(d, []).append(err)
    return sorted((d, sum(v) / len(v)) for d, v in by_day.items())


def _daily_mean_err(xs: list[StateVec], targets: dict[str, float], slots_per_day: int) -> list[float]:
    days = (len(xs) + slots_per_day - 1) // slots_per_day
    out = []
    for d in range(days):
        chunk = xs[d * slots_per_day:(d + 1) * slots_per_day]
        out.append(sum(total_error(x, targets) for x in chunk) / len(chunk))
    return out


def _slope(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    sx, sy = sum(xs), sum(ys)
    sxy = sum(x * y for x, y in zip(xs, ys))
    sxx = sum(x * x for x in xs)
    denom = n * sxx - sx * sx
    return (n * sxy - sx * sy) / denom if abs(denom) > 1e-12 else 0.0


def _verdict(ess: float, settling_time, overshoot: float, worsening: bool, eval_cfg) -> str:
    """三级判定：收敛看稳态/调节/超调；发散看持续恶化（窗口均值对比）或大稳态误差；其余振荡。"""
    if (
        ess <= eval_cfg.converged_ess_max
        and settling_time is not None
        and settling_time <= eval_cfg.converged_settle_max
        and overshoot < eval_cfg.converged_overshoot_max
    ):
        return "converged"
    if worsening or ess > eval_cfg.diverged_ess_min:
        return "diverged"
    return "oscillating"
