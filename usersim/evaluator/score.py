"""Benchmark 分数：把一个存档的全部指标折算成单一百分制得分（被测 assistant 的主 KPI）。

公式（v2）：

    B = max(0, 100 − Σₖ min(capₖ, wₖ · xₖ))

每个存档指标先归一为"越大越差"的观测量 xₖ，乘系数 wₖ、封顶 capₖ 后从 100 扣减。
权重可用 config/system.toml [benchmark] 覆盖（[系数, 上限] 对，与 [score] 同构）。
设计理由（为何扣分制/封顶/线性/这组权重/缺失处理）见 docs/04-evaluator.md 第 8 节。

与 insights 的 health_score 分工：health_score 诊断**仿真本身**是否健康
（用户复读、状态饱和、行为一致性占大头）；benchmark 分给**被测 assistant** 打分，
以控制回路表现与画像精度为主体，契约违约与仿真有效性只作门槛项（上限合计有限）。
v3 起，归因混杂的仿真健康指标（user_dup/clamp_ratio/wsc_incoherent）不再从
benchmark 扣分——它们度量的是用户 LLM 与世界动力学，不是被测件能力。
"""

from __future__ import annotations

import math
from typing import Any

FORMULA_VERSION = "v3"  # v3：混杂指标移出（user_dup/clamp_ratio/wsc 归 health_score）+ 终值改末端 5 天窗；与 v2 分数不可直接比
FORMULA_TEXT = "B = max(0, 100 − Σₖ min(capₖ, wₖ·xₖ))"

# key → (组, 展示标签, 默认 (系数 w, 封顶 cap))
_TERMS: dict[str, tuple[str, str, tuple[float, float]]] = {
    # ---- 控制表现（report.json 控制回路指标，权重主体）----
    "ess": ("control", "稳态误差 e_ss", (200.0, 30.0)),
    "settle_frac": ("control", "未稳定时间占比", (12.0, 10.0)),
    "overshoot": ("control", "超调量 M_p", (40.0, 8.0)),
    "iae_daily": ("control", "日均误差总量 IAE/d", (100.0, 10.0)),
    "variance": ("control", "状态方差 σ²", (100.0, 6.0)),
    "band_deficit": ("control", "带外时间占比 1−ρ", (16.0, 8.0)),
    # ---- 状态估计与画像（第二公理：理解用户）----
    "est_err": ("belief", "状态估计终值误差 ‖x−x̂‖", (40.0, 8.0)),
    "est_slope": ("belief", "估计误差正斜率", (1000.0, 4.0)),
    "persona_err": ("belief", "画像误差", (40.0, 8.0)),
    "coverage_deficit": ("belief", "画像覆盖缺口", (8.0, 4.0)),
    "prefs_err": ("belief", "喜好数值误差", (20.0, 4.0)),
    "f1_deficit": ("belief", "爱憎命中缺口 1−F1", (6.0, 3.0)),
    # ---- 契约与仿真有效性（门槛项；只保留 agent 归因清晰的指标）----
    "violations": ("contract", "契约违约率/百turn", (5.0, 15.0)),  # v4：按助手话务量归一
    "no_recover": ("contract", "扰动无响应次数", (2.0, 6.0)),
    "pac_conflict": ("contract", "偏好-行动冲突率", (25.0, 6.0)),
    "pra_misaligned": ("contract", "喜好-请求不对齐占比", (10.0, 3.0)),
    # v3 移除（归因混杂，归 health_score 诊断仿真健康而非给被测件打分）：
    # - user_dup：度量用户 LLM 台词多样性，同 harness 跨轮漂移数倍（噪声主导）
    # - clamp_ratio：世界动力学饱和分辨力，惩罚"把用户状态调满格"的强控制 agent
    # - wsc_incoherent：用户台词情感摆荡，用户 LLM 属性为主
}

_GROUP_LABELS = {"control": "控制表现", "belief": "状态估计与画像", "contract": "契约与有效性"}

# 契约有效性观测量的键：来自 insights 的 score_observations（单一数据源，不重复计算）
_INSIGHT_KEYS = ("violations", "no_recover", "pac_conflict", "pra_misaligned")

_FULL_ERR = 0.5  # 无估计时的满误差（与 insights 同规约：不作为不能免罚，否则 stub 反而占便宜）


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
    d = max(1, days)
    st = report.get("settling_time_days")
    return {
        "ess": _nan(report.get("ess"), 1.0),
        # 未稳定 = 全程未回带（1.0）；已稳定 = 调节时间占全程比例
        "settle_frac": 1.0 if st is None else min(1.0, float(st) / d),
        "overshoot": _nan(report.get("overshoot"), 1.0),
        # iae 是按天累计总量，除天数 ≈ mean|e|，与 run 长短无关才可横向比较
        "iae_daily": _nan(report.get("iae"), float(d)) / d,
        "variance": _nan(report.get("variance"), 1.0),
        "band_deficit": 1.0 - _nan(report.get("in_band_ratio"), 0.0),
        "est_err": _nan(report.get("est_err_final"), _FULL_ERR),
        "est_slope": max(0.0, _nan(report.get("est_err_slope_per_day"), 0.0)),
        "persona_err": _nan(report.get("persona_err_final"), _FULL_ERR),
        "coverage_deficit": 1.0 - _nan(report.get("persona_coverage"), 0.0),
        "prefs_err": _nan(report.get("prefs_err_final"), _FULL_ERR),
        "f1_deficit": 1.0 - _nan(report.get("prefs_tag_f1"), 0.0),
    }


def compute_benchmark(report: dict, insight_obs: dict[str, float], days: int,
                      cfg=None) -> dict:
    """算分主入口：report 指标 + insights 观测量 → 得分与逐项明细（落 report.json）。"""
    w = _weights(cfg)
    obs = report_observations(report, days)
    for k in _INSIGHT_KEYS:
        obs[k] = float(insight_obs.get(k, 0.0) or 0.0)
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
