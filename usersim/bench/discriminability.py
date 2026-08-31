"""量程守护：世界能否分辨好助手与差助手（live 锚点对口径）。

动机（docs/10 的教训）：R1/R2 调参把 poor 档 ess 从 0.31 压到 0.084，而
diverged_ess_min = 0.080——失能助手距"发散"判定只剩 0.004 裕度。当时只在文档里
记了一句"记录观察"，没有任何机制阻止量程继续被压缩。

本模块把"分辨力"变成可断言的量（replay 三档下线后，锚点改为 live 的
reference（好锚点）vs stub（失能下界），分组键由参数给出）：
  margin_poor = mean(ess[poor_group]) - diverged_ess_min    > 0 才说明差助手确实被判差
  margin_good = converged_ess_max - mean(ess[good_group])   > 0 才说明好助手确实被判好
  separation  = Cohen's d(good, poor)                       大效应才说明两档可区分

黄灯（borderline）：ess 均值 ±SEM 跨阈时记 borderline——margin 虽然仍为正，
但抽样噪声足以把均值推过阈值（刀沿）。status 汇总：fail > borderline > ok。
`checks`/`ok` 保持原二值语义不变（borderline 仍算通过），黄灯只体现在
check_status/status 字段，供前端与报告提示"结论在统计噪声刀沿上"。
"""

from __future__ import annotations

from statistics import stdev

from usersim.bench.aggregate import cohens_d


def _sem(vals: list[float]) -> float | None:
    n = len(vals)
    if n == 0:
        return None
    if n == 1:
        return 0.0
    return stdev(vals) / n ** 0.5


def compute(episodes: list[dict], eval_cfg,
            good_group: str = "reference", poor_group: str = "stub") -> dict:
    """episodes 需含 good_group / poor_group 两个分组的记录（live 锚点对）。"""
    by_group: dict[str, list[float]] = {}
    for ep in episodes:
        by_group.setdefault(ep["group"], []).append(ep["metrics"].get("ess"))

    good = [v for v in by_group.get(good_group, []) if v is not None]
    poor = [v for v in by_group.get(poor_group, []) if v is not None]

    diverged_min = float(eval_cfg.diverged_ess_min)
    converged_max = float(eval_cfg.converged_ess_max)

    mean_good = sum(good) / len(good) if good else None
    mean_poor = sum(poor) / len(poor) if poor else None
    sem_good = _sem(good)
    sem_poor = _sem(poor)

    margin_poor = (mean_poor - diverged_min) if mean_poor is not None else None
    margin_good = (converged_max - mean_good) if mean_good is not None else None
    sep = cohens_d(good, poor) if good and poor else None

    checks = {
        "margin_poor_positive": bool(margin_poor is not None and margin_poor > 0),
        "margin_good_positive": bool(margin_good is not None and margin_good > 0),
        "separation_large": bool(sep is not None and sep > 1.5),
    }
    # 黄灯区间判定：CI（均值 ±SEM）跨阈 → borderline（非 fail，但不可作为强结论）
    check_status = {
        "margin_poor": (
            "fail" if not checks["margin_poor_positive"]
            else "borderline" if (sem_poor or 0.0) > 0 and mean_poor - sem_poor <= diverged_min
            else "pass"
        ),
        "margin_good": (
            "fail" if not checks["margin_good_positive"]
            else "borderline" if (sem_good or 0.0) > 0 and mean_good + sem_good >= converged_max
            else "pass"
        ),
        "separation": "pass" if checks["separation_large"] else "fail",
    }
    if any(s == "fail" for s in check_status.values()):
        status = "fail"
    elif any(s == "borderline" for s in check_status.values()):
        status = "borderline"
    else:
        status = "ok"
    return {
        "groups": {"good": good_group, "poor": poor_group},
        "thresholds": {"diverged_ess_min": diverged_min, "converged_ess_max": converged_max},
        "ess_good_mean": mean_good,
        "ess_poor_mean": mean_poor,
        "ess_good_sem": sem_good,
        "ess_poor_sem": sem_poor,
        "margin_poor": margin_poor,
        "margin_good": margin_good,
        "separation": sep,
        "checks": checks,
        "check_status": check_status,
        "status": status,
        "ok": all(checks.values()),
    }
