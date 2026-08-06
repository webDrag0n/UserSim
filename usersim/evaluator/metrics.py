"""评估器：控制论指标 + 三级判定 + 报告（0 LLM，只读 runs/ 日志）。"""

from __future__ import annotations

import json
from pathlib import Path

from usersim.contracts import (
    DIMS,
    Persona,
    SlotSettlement,
    StateVec,
    TurnRecord,
    dim_error,
    facet_coverage,
    facet_error,
    prefs_error,
    tag_hit_rate,
    total_error,
)


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
    persona: dict | Persona | None = None,
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

    # 带内驻留比（后 window_days 天）
    window_days = int(getattr(eval_cfg, "window_days", 10) or 10)
    tail_pts = xs[-window_days * slots_per_day:]
    in_band_ratio = sum(1 for x in tail_pts if in_band(x)) / len(tail_pts) if tail_pts else float("nan")

    # 滑动窗口指标序列（docs/04 第 4 节：无限延展的 run 用滑窗做健康监控）
    windows = _sliding_windows(xs, targets, band, slots_per_day, window_days, in_band)

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

    # 画像精度（冻结维度：人格 30 facet + 结构化喜好）
    profile = _profile_metrics(turns, persona, slots_per_day)

    # 行为一致性（用户 Agent 作为 reward 信号的可信度）
    from usersim.evaluator.consistency import compute_consistency
    p_data = persona if isinstance(persona, dict) else (persona.model_dump() if persona else {})
    consistency = compute_consistency(turns, p_data)
    consistency_metrics = consistency.get("metrics", {})

    return {
        **profile,
        "ess": ess,
        "settling_time_days": settling_time,
        "overshoot": overshoot,
        "iae": iae,
        "ise": ise,
        "itae": itae,
        "variance": variance,
        "in_band_ratio": in_band_ratio,
        "window_days": window_days,
        "windows": windows,
        "est_err_final": est_err_final,
        "est_err_slope_per_day": est_err_slope,
        "daily_est_err": [{"day": d, "err": e} for d, e in daily_est_err],
        "daily_err": [{"day": d, "e": e} for d, e in enumerate(daily_e)],
        "verdict": verdict,
        # 行为一致性指标
        "pac_conflict_rate": consistency_metrics.get("pac_conflict_rate"),
        "pac_conflict_count": consistency_metrics.get("pac_conflict_count"),
        "pac_severity": consistency_metrics.get("pac_severity"),
        "wsc_coherence_score": consistency_metrics.get("wsc_coherence_score"),
        "wsc_incoherent_sessions": consistency_metrics.get("wsc_incoherent_sessions"),
        "pra_misaligned_requests": consistency_metrics.get("pra_misaligned_requests"),
        "pba_correlation": consistency_metrics.get("pba_correlation"),
        "csps_stability_score": consistency_metrics.get("csps_stability_score"),
    }


def _profile_metrics(turns: list[TurnRecord], persona, slots_per_day: int) -> dict:
    """画像精度：人格 facet 误差 + 喜好类目误差 + loves/hates 命中率（含学习曲线）。

    真值来自 meta.json 的角色卡（冻结维度）；估计来自每个助手 turn 落盘的
    `persona_hat`。**没有估计的 turn 不参与**——不作为不能等于零误差，覆盖率
    单独报告（`persona_coverage`）。

    返回全 None 表示本 run 没有任何画像估计（如 stub 下界锚点、或旧日志）。
    """
    empty = {
        "persona_err_final": float("nan"), "persona_err_slope_per_day": 0.0,
        "persona_coverage": 0.0, "prefs_err_final": float("nan"),
        "prefs_tag_f1": float("nan"), "daily_persona_err": [],
    }
    if persona is None:
        return empty
    p = persona if isinstance(persona, dict) else persona.model_dump()
    true_facets = {k: int(v) for k, v in (p.get("facets") or {}).items()}
    true_prefs = p.get("prefs") or {}
    true_cats = {k: float(v) for k, v in (true_prefs.get("categories") or {}).items()}
    true_loves = list(true_prefs.get("loves") or [])
    true_hates = list(true_prefs.get("hates") or [])
    if not true_facets and not true_cats:
        return empty  # 旧存档没有冻结维度真值，无法评分

    hats = [t for t in turns if t.persona_hat is not None]
    if not hats:
        return empty

    by_day: dict[int, list[float]] = {}
    for t in hats:
        err = facet_error(true_facets, t.persona_hat.facets)
        if err is not None:
            by_day.setdefault(t.t_logical // slots_per_day, []).append(err)
    daily = sorted((d, sum(v) / len(v)) for d, v in by_day.items())

    last = hats[-1].persona_hat
    return {
        "persona_err_final": daily[-1][1] if daily else float("nan"),
        "persona_err_slope_per_day": (
            _slope([d for d, _ in daily], [e for _, e in daily]) if len(daily) > 1 else 0.0),
        "persona_coverage": round(facet_coverage(last.facets), 3),
        "prefs_err_final": _nan(prefs_error(true_cats, last.categories)),
        "prefs_tag_f1": _nan(_tag_f1(true_loves, true_hates, last)),
        "daily_persona_err": [{"day": d, "err": round(e, 4)} for d, e in daily],
    }


def _tag_f1(true_loves: list[str], true_hates: list[str], hat) -> float | None:
    """loves 与 hates 的 F1 均值（两者都有真值时取均值，否则取存在的那个）。"""
    scores = [s for s in (tag_hit_rate(true_loves, hat.loves),
                          tag_hit_rate(true_hates, hat.hates)) if s is not None]
    return sum(scores) / len(scores) if scores else None


def _nan(v: float | None) -> float:
    return float("nan") if v is None else float(v)


def _infer_slots_per_day(slots: list[SlotSettlement], eval_cfg) -> int:
    """从结算单读取时钟刻度（world 写入）；旧日志缺省 4。

    此前这里硬编码 return 4——改 [clock].slots_per_day 会让所有按天归一的指标
    静默算错（IAE/ITAE/调节时间/学习曲线）。
    """
    if slots:
        spd = getattr(slots[0], "slots_per_day", 0) or 0
        if spd > 0:
            return int(spd)
    return int(getattr(eval_cfg, "slots_per_day", 4) or 4)


def _sliding_windows(xs: list[StateVec], targets: dict[str, float], band: float,
                     slots_per_day: int, window_days: int, in_band) -> list[dict]:
    """按 window_days 逐日滑动输出窗口指标（长 run 的健康监控曲线）。

    此前 [eval].window_days 是死配置——文档承诺了滑窗结算但从未实现。
    """
    win = window_days * slots_per_day
    if win <= 0 or len(xs) < win:
        return []
    out: list[dict] = []
    for start in range(0, len(xs) - win + 1, slots_per_day):
        chunk = xs[start:start + win]
        errs = [total_error(x, targets) for x in chunk]
        out.append({
            "start_day": start // slots_per_day,
            "end_day": (start + win) // slots_per_day,
            "mean_err": sum(errs) / len(errs),
            "max_err": max(errs),
            "in_band_ratio": sum(1 for x in chunk if in_band(x)) / len(chunk),
        })
    return out


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
