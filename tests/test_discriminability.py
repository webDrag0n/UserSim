"""量程守护回归：世界必须能分辨好助手与差助手。

背景（docs/10 的教训）：R1/R2 调参把 poor 档 ess 压到接近 diverged 阈值，
当时只在文档里记"记录观察"，没有任何机制阻止量程继续被压缩。本测试把它变成红灯。

replay 模式下线后不再真跑批量 episode（原 slow 集成 fixture 已删除）：
改为合成 episodes 直喂 discriminability.compute 的纯函数测试，断言语义不变——
  margin_poor = mean(ess[poor]) - diverged_ess_min   > 0 差助手才确实被判差
  margin_good = converged_ess_max - mean(ess[good])  > 0 好助手才确实被判好
  separation  = Cohen's d(good, poor)                > 1.5 两组才可区分
（live 实测锚点对的量程校验由 bench 管线在真跑时落盘 discriminability.json。）
"""

from __future__ import annotations

from usersim.bench.discriminability import compute
from usersim.config import load_system_config


def _eps(group: str, ess_values: list) -> list[dict]:
    return [{"group": group, "metrics": {"ess": v}} for v in ess_values]


def _eval_cfg():
    return load_system_config().eval


def test_verdict_mode_breaks_ties_toward_worse_verdict() -> None:
    """平票时众数必须取**更差**的判定（快测试，不跑 episode）。

    回归：原实现是 `max(("converged","oscillating","diverged"), key=count)`，
    max 在平票时返回第一个最大值——即最讨好被测件的判定。4 票发散 / 4 票振荡
    会被报成"振荡"，benchmark 于是替失能助手往好处圆。
    """
    from usersim.bench.aggregate import aggregate

    def eps(verdicts):
        return [{"group": "poor", "metrics": {"ess": 0.1, "verdict": v}} for v in verdicts]

    tie = aggregate(eps(["diverged"] * 4 + ["oscillating"] * 4))
    assert tie["groups"]["poor"]["verdict_mode"] == "diverged"

    tie2 = aggregate(eps(["converged"] * 3 + ["oscillating"] * 3))
    assert tie2["groups"]["poor"]["verdict_mode"] == "oscillating"

    # 非平票时仍是真正的众数
    clear = aggregate(eps(["oscillating"] * 5 + ["diverged"] * 2))
    assert clear["groups"]["poor"]["verdict_mode"] == "oscillating"


def test_well_separated_groups_pass() -> None:
    """好组 ess 低、差组 ess 高且分布不重叠 → 三项检查全绿。"""
    cfg = _eval_cfg()
    episodes = _eps("reference", [0.010, 0.012, 0.011, 0.009]) \
        + _eps("stub", [0.12, 0.13, 0.14, 0.15])
    disc = compute(episodes, cfg)
    assert disc["groups"] == {"good": "reference", "poor": "stub"}
    assert disc["margin_good"] > 0
    assert disc["margin_poor"] > 0.02, "差组距发散阈值应留裕度，不能刚好卡线"
    assert disc["separation"] is not None and disc["separation"] > 1.5
    assert disc["checks"] == {"margin_poor_positive": True,
                              "margin_good_positive": True,
                              "separation_large": True}
    assert disc["ok"] is True


def test_poor_below_diverged_threshold_lights_margin_poor() -> None:
    """差组 ess 均值低于发散阈值 → margin_poor 红灯（量程被压缩的回归形态）。"""
    cfg = _eval_cfg()
    episodes = _eps("reference", [0.010, 0.012, 0.011, 0.009]) \
        + _eps("stub", [0.050, 0.060, 0.055, 0.052])
    disc = compute(episodes, cfg)
    assert disc["margin_poor"] is not None and disc["margin_poor"] < 0
    assert disc["checks"]["margin_poor_positive"] is False
    assert disc["ok"] is False


def test_good_above_converged_threshold_lights_margin_good() -> None:
    """好组 ess 均值高于收敛阈值 → margin_good 红灯。"""
    cfg = _eval_cfg()
    # 取值须高于当前 converged_ess_max（0.060，v4.1 live 标定）
    episodes = _eps("reference", [0.070, 0.080, 0.075, 0.072]) \
        + _eps("stub", [0.20, 0.22, 0.21, 0.19])
    disc = compute(episodes, cfg)
    assert disc["margin_good"] is not None and disc["margin_good"] < 0
    assert disc["checks"]["margin_good_positive"] is False
    assert disc["ok"] is False


def test_overlapping_groups_light_separation() -> None:
    """两组分布重叠 → Cohen's d 小 → separation 红灯。"""
    cfg = _eval_cfg()
    episodes = _eps("reference", [0.05, 0.06, 0.07]) \
        + _eps("stub", [0.055, 0.06, 0.065])
    disc = compute(episodes, cfg)
    assert disc["separation"] is not None and disc["separation"] <= 1.5
    assert disc["checks"]["separation_large"] is False
    assert disc["ok"] is False


def test_missing_group_yields_none_without_crashing() -> None:
    """缺任一分组：对应字段为 None、ok=False，且不抛异常。"""
    cfg = _eval_cfg()
    disc = compute(_eps("reference", [0.010, 0.012]), cfg)
    assert disc["ess_poor_mean"] is None
    assert disc["margin_poor"] is None
    assert disc["separation"] is None
    assert disc["ok"] is False

    disc2 = compute(_eps("stub", [0.12, 0.13]), cfg)
    assert disc2["ess_good_mean"] is None
    assert disc2["margin_good"] is None
    assert disc2["ok"] is False


def test_custom_group_names_and_none_ess_skipped() -> None:
    """分组键由参数给出；metrics.ess 为 None 的 episode 不参与统计。"""
    cfg = _eval_cfg()
    episodes = _eps("good_llm", [0.010, None, 0.012]) \
        + _eps("bad_llm", [0.12, 0.13, None])
    disc = compute(episodes, cfg, good_group="good_llm", poor_group="bad_llm")
    assert disc["groups"] == {"good": "good_llm", "poor": "bad_llm"}
    assert disc["ess_good_mean"] == 0.011
    assert disc["ess_poor_mean"] == 0.125
    assert disc["ok"] is True


def test_borderline_when_ci_crosses_threshold() -> None:
    """ess 均值 ±SEM 跨阈 → 黄灯：checks 仍 True、ok 仍 True，但 status=borderline。"""
    cfg = _eval_cfg()
    conv = float(cfg.converged_ess_max)
    # 好组均值略低于阈值但散布大：mean=0.055，mean+SEM≈0.061 跨过 converged_ess_max
    episodes = _eps("reference", [conv - 0.02, conv + 0.015, conv - 0.01, conv, conv - 0.01]) \
        + _eps("stub", [0.20, 0.22, 0.21, 0.19, 0.20])
    disc = compute(episodes, cfg)
    assert disc["checks"]["margin_good_positive"] is True
    assert disc["ok"] is True
    assert disc["check_status"]["margin_good"] == "borderline"
    assert disc["status"] == "borderline"


def test_status_fail_when_check_fails() -> None:
    """任一检查红灯 → status=fail（黄灯语义不稀释红灯）。"""
    cfg = _eval_cfg()
    episodes = _eps("reference", [0.010, 0.012, 0.011, 0.009]) \
        + _eps("stub", [0.050, 0.060, 0.055, 0.052])
    disc = compute(episodes, cfg)
    assert disc["check_status"]["margin_poor"] == "fail"
    assert disc["status"] == "fail"
    assert disc["ok"] is False


def test_status_ok_when_all_clear() -> None:
    cfg = _eval_cfg()
    episodes = _eps("reference", [0.010, 0.012, 0.011, 0.009]) \
        + _eps("stub", [0.12, 0.13, 0.14, 0.15])
    disc = compute(episodes, cfg)
    assert disc["status"] == "ok"
    assert all(s == "pass" for s in disc["check_status"].values())


def test_aggregate_verdict_consistency_and_mde() -> None:
    """aggregate 新增字段：判定一致率 + 组对 MDE（主 KPI 与 ess）。"""
    from usersim.bench.aggregate import aggregate

    eps = [
        {"group": "a", "metrics": {"ess": 0.01, "benchmark_score": 80.0,
                                   "verdict": "converged", "settling_time_days": 1.0}},
        {"group": "a", "metrics": {"ess": 0.02, "benchmark_score": 70.0,
                                   "verdict": "converged", "settling_time_days": 1.0}},
        {"group": "a", "metrics": {"ess": 0.015, "benchmark_score": 75.0,
                                   "verdict": "oscillating", "settling_time_days": 1.0}},
        {"group": "b", "metrics": {"ess": 0.10, "benchmark_score": 30.0,
                                   "verdict": "diverged", "settling_time_days": None}},
        {"group": "b", "metrics": {"ess": 0.12, "benchmark_score": 20.0,
                                   "verdict": "diverged", "settling_time_days": None}},
    ]
    agg = aggregate(eps)
    # 判定一致率：a 组众数 converged 2/3；b 组全票 diverged
    assert agg["groups"]["a"]["verdict_consistency"] == round(2 / 3, 3)
    assert agg["groups"]["b"]["verdict_consistency"] == 1.0
    # MDE：a-b 一组对，benchmark_score 均值差 MDE 应远小于实际差（50）
    mde = agg["mde"]
    assert mde["alpha"] == 0.05 and mde["power"] == 0.8
    pair = next(p for p in mde["pairs"] if {p["a"], p["b"]} == {"a", "b"})
    bs = pair["metrics"]["benchmark_score"]
    assert bs["mde_mean"] is not None and 0 < bs["mde_mean"] < 50
    assert bs["mde_var_ratio"] is not None and bs["mde_var_ratio"] > 1
    assert pair["metrics"]["ess"]["mde_mean"] is not None


def test_mde_none_when_group_too_small() -> None:
    """任一组 n<2 → 该指标 MDE 为 None（不抛异常）。"""
    from usersim.bench.aggregate import mde

    eps = [
        {"group": "a", "metrics": {"ess": 0.01, "benchmark_score": 80.0}},
        {"group": "b", "metrics": {"ess": 0.10, "benchmark_score": 30.0}},
    ]
    out = mde(eps)
    pair = out["pairs"][0]
    assert pair["metrics"]["ess"]["mde_mean"] is None
    assert pair["metrics"]["ess"]["n_a"] == 1 and pair["metrics"]["ess"]["n_b"] == 1
