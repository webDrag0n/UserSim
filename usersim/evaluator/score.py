"""Benchmark 分数：把一个存档的全部指标折算成单一百分制得分（被测 assistant 的主 KPI）。

公式（v4）：

    B = max(0, 100 − Σₖ min(capₖ, wₖ · xₖ))

每个存档指标先归一为"越大越差"的观测量 xₖ，乘系数 wₖ、封顶 capₖ 后从 100 扣减。
权重可用 config/system.toml [benchmark] 覆盖（[系数, 上限] 对，与 [score] 同构）。
设计理由（为何扣分制/封顶/线性/这组权重/缺失处理）见 docs/04-evaluator.md 第 8 节。

与 insights 的 health_score 分工：health_score 诊断**仿真本身**是否健康
（用户复读、状态饱和、行为一致性占大头）；benchmark 分给**被测 assistant** 打分，
只保留与被测件能力因果清晰的指标。

v4 起精简为 3 个扣分项（ess / band_deficit / coverage_deficit）：历史 bench 数据的
known-groups 区分度分析显示，仅 ess、in_band_ratio、persona_coverage 与模型强弱
显著相关；其余指标或冗余（iae/variance/ise/itae 与 ess 同轨迹）、或无区分力
（est_err/est_slope/persona_err/prefs_err/f1）、或归因混杂（overshoot 反向、
violations 恒 0、pac_conflict/pra_misaligned 度量用户模拟器保真度）、或不稳定
（settle_frac CV 0.90）。与 v3 分数不可直接比。
"""

from __future__ import annotations

import math
from typing import Any

FORMULA_VERSION = "v4"  # v4：精简为 ess/band_deficit/coverage_deficit 三项（bench 区分度分析）；与 v3 分数不可直接比
FORMULA_TEXT = "B = max(0, 100 − Σₖ min(capₖ, wₖ·xₖ))"

# key → (组, 展示标签, 默认 (系数 w, 封顶 cap))
_TERMS: dict[str, tuple[str, str, tuple[float, float]]] = {
    # ---- 控制表现（report.json 控制回路指标）----
    "ess": ("control", "稳态误差 e_ss", (200.0, 40.0)),
    "band_deficit": ("control", "带外时间占比 1−ρ", (30.0, 30.0)),
    # ---- 画像覆盖（第二公理：理解用户）----
    "coverage_deficit": ("belief", "画像覆盖缺口", (30.0, 30.0)),
    # v4 移除（依据见模块 docstring）：
    # - 冗余：settle_frac/overshoot/iae_daily/variance/est_err/est_slope/persona_err/prefs_err/f1_deficit
    # - 归因混杂：violations/no_recover/pac_conflict/pra_misaligned（pac/pra 仍作 consistency
    #   指标与 health_score 项保留，只从 benchmark 计分移除）
}

_GROUP_LABELS = {"control": "控制表现", "belief": "画像覆盖"}


def _nan(value: Any, default: float) -> float:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return default
    return float(value)


def _weights(cfg) -> dict[str, tuple[float, float]]:
    """默认权重 ← config/system.toml [benchmark] 覆盖（缺项/畸形项忽略）。"""
    w = {k: v[2] for k, v in _TERMS.items()}
    if cfg is None:
        return w
    raw = cfg.to_dict() if hasattr(cfg, "to_dict") else dict(cfg)
    for k, pair in raw.items():
        if k in w and isinstance(pair, (list, tuple)) and len(pair) == 2:
            w[k] = (float(pair[0]), float(pair[1]))
    return w


def report_observations(report: dict, days: int) -> dict[str, float]:
    """report.json 指标 → "越大越差"观测量（缺失按满误差/满占比计）。"""
    return {
        "ess": _nan(report.get("ess"), 1.0),
        "band_deficit": 1.0 - _nan(report.get("in_band_ratio"), 0.0),
        "coverage_deficit": 1.0 - _nan(report.get("persona_coverage"), 0.0),
    }


def compute_benchmark(report: dict, days: int, cfg=None) -> dict:
    """算分主入口：report 指标 → 得分与逐项明细（落 report.json）。"""
    w = _weights(cfg)
    obs = report_observations(report, days)
    terms: list[dict[str, Any]] = []
    groups: dict[str, dict[str, Any]] = {}
    for key, (group, label, _default) in _TERMS.items():
        coef, cap = w[key]
        deduct = min(cap, obs[key] * coef)
        terms.append({"key": key, "group": group, "label": label,
                      "obs": round(obs[key], 4), "coef": coef, "cap": cap,
                      "deduct": round(deduct, 2)})
        g = groups.setdefault(group, {"label": _GROUP_LABELS[group], "deduct": 0.0})
        g["deduct"] = round(g["deduct"] + deduct, 2)
    score = max(0.0, round(100.0 - sum(t["deduct"] for t in terms), 1))
    return {"version": FORMULA_VERSION, "formula": FORMULA_TEXT,
            "score": score, "groups": groups, "terms": terms}
