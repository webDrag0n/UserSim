"""跨 episode 聚合与统计量（0 LLM，纯统计；只依赖标准库）。

存在理由：此前所有结论都来自 seed=42 单角色单跑，统计效力为零——
无法区分"助手 A 比 B 好"与"这个 seed 恰好对 A 友好"。
"""

from __future__ import annotations

import math
from statistics import fmean, stdev

# t 分布 97.5% 分位（双尾 95%），索引 = 自由度 n-1；n>30 用正态近似 1.96
_T975 = {
    1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
    8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145,
    15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
    21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056,
    27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
}

# 参与聚合的标量指标（daily_* 序列不聚合）
METRIC_KEYS = [
    "ess", "settling_time_days", "overshoot", "iae", "ise", "itae",
    "variance", "in_band_ratio", "est_err_final", "est_err_slope_per_day",
    "health_score",
    # 画像精度（冻结维度：人格 facet + 喜好）
    "persona_err_final", "persona_err_slope_per_day", "persona_coverage",
    "prefs_err_final", "prefs_tag_f1",
]


# 判定严重度（众数平票时取更差的那个：benchmark 不能替被测件往好处圆）
_SEVERITY = {"converged": 0, "oscillating": 1, "diverged": 2}


def _t_crit(n: int) -> float:
    if n <= 1:
        return float("nan")
    return _T975.get(n - 1, 1.96)


def summarize(values: list[float]) -> dict:
    """一个指标的 mean / std / n / ci95（小样本用 t 分布）。"""
    vals = [float(v) for v in values if v is not None and not _isnan(v)]
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": None, "std": None, "ci95": None, "lo": None, "hi": None}
    mean = fmean(vals)
    if n == 1:
        return {"n": 1, "mean": mean, "std": 0.0, "ci95": None, "lo": mean, "hi": mean}
    sd = stdev(vals)
    half = _t_crit(n) * sd / math.sqrt(n)
    return {"n": n, "mean": mean, "std": sd, "ci95": half,
            "lo": mean - half, "hi": mean + half}


def _isnan(v) -> bool:
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return True


def aggregate(episodes: list[dict]) -> dict:
    """episodes: [{"group": str, "metrics": {...}, ...}] → 分组聚合。

    `settling_time_days` 为 None 表示"从未回带"——不能当缺失值丢掉（会让最差的
    助手看起来最好）。单独统计 never_settled 计数，并在均值中排除。
    """
    groups: dict[str, list[dict]] = {}
    for ep in episodes:
        groups.setdefault(ep["group"], []).append(ep)

    out: dict = {"groups": {}, "n_episodes": len(episodes)}
    for name, eps in sorted(groups.items()):
        metrics: dict = {}
        for key in METRIC_KEYS:
            metrics[key] = summarize([ep["metrics"].get(key) for ep in eps])
        verdicts = [ep["metrics"].get("verdict") for ep in eps]
        n = len(eps)
        out["groups"][name] = {
            "n": n,
            "metrics": metrics,
            "verdict_share": {
                v: round(verdicts.count(v) / n, 3)
                for v in ("converged", "oscillating", "diverged")
            },
            # 众数：平票时取**更差**的判定。此前顺序是 converged→oscillating→diverged，
            # max() 在平票时返回第一个最大值，即最讨好被测件的那个判定——对 benchmark
            # 来说方向正好错了（4 票发散 / 4 票振荡会被报成"振荡"）。
            "verdict_mode": max(("converged", "oscillating", "diverged"),
                                key=lambda v: (verdicts.count(v), _SEVERITY[v])),
            "never_settled": sum(
                1 for ep in eps if ep["metrics"].get("settling_time_days") is None
            ),
        }
    return out


def cohens_d(a: list[float], b: list[float]) -> float | None:
    """效应量（pooled std）。用于量程守护：good 与 poor 必须被清晰分开。"""
    a = [float(v) for v in a if not _isnan(v)]
    b = [float(v) for v in b if not _isnan(v)]
    if len(a) < 2 or len(b) < 2:
        return None
    na, nb = len(a), len(b)
    va, vb = stdev(a) ** 2, stdev(b) ** 2
    pooled = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    if pooled < 1e-12:
        return float("inf") if fmean(a) != fmean(b) else 0.0
    return (fmean(b) - fmean(a)) / pooled
