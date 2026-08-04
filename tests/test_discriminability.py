"""量程守护回归：世界必须能分辨好助手与差助手。

背景（docs/10 的教训）：R1/R2 调参把 poor 档 ess 压到接近 diverged 阈值，
当时只在文档里记"记录观察"，没有任何机制阻止量程继续被压缩。本测试把它变成红灯。

阈值来自 8 seed 实测分布（good ess≈0.011±0.005 / poor≈0.124±0.061，separation≈2.2），
留出裕度而非卡在观测值上。慢测试（27 个 30 天回放 episode），标记 slow。
"""

from __future__ import annotations

import pytest

from usersim.bench.discriminability import compute
from usersim.bench.suite import BenchSpec, run_suite
from usersim.config import load_system_config

SEEDS = [1, 2, 3, 4, 5, 6, 7, 8]


@pytest.fixture(scope="module")
def bench_result(tmp_path_factory):
    cfg = load_system_config()
    spec = BenchSpec(seeds=SEEDS, days=30, mode="replay",
                     groups=["good", "mid", "poor"], concurrency=4)
    out = tmp_path_factory.mktemp("bench")
    return run_suite(spec, out_root=out, bench_id="guard"), cfg


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


@pytest.mark.slow
def test_poor_harness_stays_above_diverged_threshold(bench_result) -> None:
    """失能助手必须确实被判发散——且留有裕度，不能刚好卡线。"""
    result, cfg = bench_result
    disc = compute(result["episodes"], cfg.eval)
    assert disc["margin_poor"] is not None
    assert disc["margin_poor"] > 0.02, (
        f"poor 档 ess={disc['ess_poor_mean']:.4f} 距发散阈值 "
        f"{cfg.eval.diverged_ess_min} 仅 {disc['margin_poor']:.4f}——量程被压缩了"
    )


@pytest.mark.slow
def test_good_harness_stays_below_converged_threshold(bench_result) -> None:
    result, cfg = bench_result
    disc = compute(result["episodes"], cfg.eval)
    assert disc["margin_good"] is not None
    assert disc["margin_good"] > 0.005, (
        f"good 档 ess={disc['ess_good_mean']:.4f} 已逼近收敛阈值上限"
    )


@pytest.mark.slow
def test_good_and_poor_are_statistically_separated(bench_result) -> None:
    """Cohen's d > 1.5：两档必须是清晰可分的两个分布，而非重叠的噪声。"""
    result, cfg = bench_result
    disc = compute(result["episodes"], cfg.eval)
    assert disc["separation"] is not None
    assert disc["separation"] > 1.5, (
        f"good/poor 分离度仅 {disc['separation']:.2f}——世界失去了对助手质量的分辨力"
    )


@pytest.mark.slow
def test_verdict_modes_are_ordered(bench_result) -> None:
    """三档的判定众数必须单调恶化（收敛 → 振荡 → 发散）。"""
    result, _ = bench_result
    groups = result["aggregate"]["groups"]
    assert groups["good"]["verdict_mode"] in ("converged", "oscillating")
    assert groups["poor"]["verdict_mode"] == "diverged"
    # good 的带内驻留必须显著高于 poor
    good_band = groups["good"]["metrics"]["in_band_ratio"]["mean"]
    poor_band = groups["poor"]["metrics"]["in_band_ratio"]["mean"]
    assert good_band > poor_band + 0.3, f"带内驻留未分离: good={good_band:.2f} poor={poor_band:.2f}"


@pytest.mark.slow
def test_disabled_harness_is_penalized_by_health_score(bench_result) -> None:
    """健康分必须惩罚失能助手：poor 明显低于 good。"""
    result, _ = bench_result
    groups = result["aggregate"]["groups"]
    good_h = groups["good"]["metrics"]["health_score"]["mean"]
    poor_h = groups["poor"]["metrics"]["health_score"]["mean"]
    assert good_h - poor_h > 15, (
        f"健康分对助手质量不敏感: good={good_h:.1f} poor={poor_h:.1f}"
    )
