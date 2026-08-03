"""evaluator 测试：合成轨迹对拍判定 + 三档回放集成测试。"""

from usersim.config import load_system_config
from usersim.contracts import SlotSettlement, StateVec
from usersim.evaluator.metrics import compute_metrics
from usersim.runner import run_replay

TARGETS = {"valence": 0.72, "energy": 0.70, "satiety": 0.65, "stress": 0.30}
BAND = 0.10


def _synthetic(kind: str, days: int = 30) -> list[SlotSettlement]:
    """构造三种理想轨迹：线性收敛 / 正弦振荡 / 线性发散。"""
    slots = []
    n = days * 4
    for t in range(n):
        if kind == "converged":
            stress = 0.30 + 0.5 * (0.75 ** t)
        elif kind == "oscillating":
            import math
            stress = 0.30 + 0.25 * math.sin(t / 2.0)
        else:  # diverged
            stress = min(1.0, 0.30 + 0.006 * t)
        x = StateVec(valence=0.72, energy=0.70, satiety=0.65, stress=max(0.0, stress))
        slots.append(SlotSettlement(t_logical=t, x_before=x, x_after=x))
    return slots


def _eval(slots):
    cfg = load_system_config()
    return compute_metrics(slots, [], TARGETS, BAND, cfg.eval)


def test_verdict_on_synthetic():
    assert _eval(_synthetic("converged"))["verdict"] == "converged"
    assert _eval(_synthetic("oscillating"))["verdict"] == "oscillating"
    assert _eval(_synthetic("diverged"))["verdict"] == "diverged"


def test_three_quality_replay_verdicts(tmp_path):
    """集成：三档规则回放 30 天 → 收敛 / 振荡 / 发散。"""
    cfg = load_system_config()
    expected = {"good": "converged", "mid": "oscillating", "poor": "diverged"}
    for quality, want in expected.items():
        run_dir = run_replay(seed=42, days=30, quality=quality, cfg=cfg, out_root=tmp_path)
        from usersim.evaluator.report import evaluate_run
        report = evaluate_run(run_dir, cfg)
        assert report["verdict"] == want, f"{quality}: {report['verdict']} != {want} (e_ss={report['ess']:.3f})"


def test_metrics_monotonic_across_qualities(tmp_path):
    """IAE 应随助手品质下降而增大。"""
    cfg = load_system_config()
    iaes = {}
    for quality in ("good", "mid", "poor"):
        run_dir = run_replay(seed=42, days=30, quality=quality, cfg=cfg, out_root=tmp_path)
        from usersim.evaluator.report import evaluate_run
        iaes[quality] = evaluate_run(run_dir, cfg)["iae"]
    assert iaes["good"] < iaes["poor"]
