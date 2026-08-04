"""量程守护：世界能否分辨好助手与差助手。

动机（docs/10 的教训）：R1/R2 调参把 poor 档 ess 从 0.31 压到 0.084，而
diverged_ess_min = 0.080——失能助手距"发散"判定只剩 0.004 裕度。当时只在文档里
记了一句"记录观察"，没有任何机制阻止量程继续被压缩。

本模块把"分辨力"变成可断言的量：
  margin_poor = mean(ess_poor) - diverged_ess_min    > 0 才说明差助手确实被判差
  margin_good = converged_ess_max - mean(ess_good)   > 0 才说明好助手确实被判好
  separation  = Cohen's d(good, poor)                大效应才说明两档可区分
"""

from __future__ import annotations

from usersim.bench.aggregate import cohens_d


def compute(episodes: list[dict], eval_cfg) -> dict:
    """episodes 需含 group ∈ {good, mid, poor}（回放三档）。"""
    by_group: dict[str, list[float]] = {}
    for ep in episodes:
        by_group.setdefault(ep["group"], []).append(ep["metrics"].get("ess"))

    good = [v for v in by_group.get("good", []) if v is not None]
    poor = [v for v in by_group.get("poor", []) if v is not None]

    diverged_min = float(eval_cfg.diverged_ess_min)
    converged_max = float(eval_cfg.converged_ess_max)

    mean_good = sum(good) / len(good) if good else None
    mean_poor = sum(poor) / len(poor) if poor else None

    margin_poor = (mean_poor - diverged_min) if mean_poor is not None else None
    margin_good = (converged_max - mean_good) if mean_good is not None else None
    sep = cohens_d(good, poor) if good and poor else None

    checks = {
        "margin_poor_positive": bool(margin_poor is not None and margin_poor > 0),
        "margin_good_positive": bool(margin_good is not None and margin_good > 0),
        "separation_large": bool(sep is not None and sep > 1.5),
    }
    return {
        "thresholds": {"diverged_ess_min": diverged_min, "converged_ess_max": converged_max},
        "ess_good_mean": mean_good,
        "ess_poor_mean": mean_poor,
        "margin_poor": margin_poor,
        "margin_good": margin_good,
        "separation": sep,
        "checks": checks,
        "ok": all(checks.values()),
    }
