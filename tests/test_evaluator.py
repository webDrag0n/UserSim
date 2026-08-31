"""evaluator 测试：合成轨迹对拍判定 + _verdict 阈值语义（0 LLM、不起 run）。

replay 模式下线后，原"三档回放集成测试"改为直喂 compute_metrics / _verdict：
轨迹是手工合成的 SlotSettlement 序列，判定意图不变（三档可分、阈值分支语义）。
"""

import math

from usersim.config import load_system_config
from usersim.contracts import SlotSettlement, StateVec
from usersim.evaluator.metrics import _verdict, compute_metrics

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
    """三档合成轨迹经完整 compute_metrics 管线必须可分。"""
    assert _eval(_synthetic("converged"))["verdict"] == "converged"
    assert _eval(_synthetic("oscillating"))["verdict"] == "oscillating"
    assert _eval(_synthetic("diverged"))["verdict"] == "diverged"


class TestVerdictThresholds:
    """_verdict 的分支语义：ess / settle / overshoot / worsening 四个门槛。"""

    def setup_method(self):
        self.cfg = load_system_config().eval

    def v(self, ess, settle, overshoot, worsening=False):
        return _verdict(ess, settle, overshoot, worsening, self.cfg)

    def test_converged_requires_all_three_gates(self):
        assert self.v(0.01, 2.0, 0.05) == "converged"
        # 任一门槛失败即掉出 converged（且未达发散条件 → 振荡）
        assert self.v(0.01, None, 0.05) == "oscillating"  # 从未回带
        assert self.v(0.01, self.cfg.converged_settle_max + 1.0, 0.05) == "oscillating"
        assert self.v(0.01, 2.0, self.cfg.converged_overshoot_max + 0.01) == "oscillating"
        assert self.v(self.cfg.converged_ess_max + 0.01, 2.0, 0.05) == "oscillating"

    def test_converged_boundary_inclusivity(self):
        # ess / settle 为 <=（含端点）；overshoot 为严格 <
        assert self.v(self.cfg.converged_ess_max,
                      self.cfg.converged_settle_max, 0.05) == "converged"
        assert self.v(0.01, 2.0, self.cfg.converged_overshoot_max) != "converged"

    def test_diverged_on_large_ess_or_worsening(self):
        assert self.v(self.cfg.diverged_ess_min + 0.01, None, 0.0) == "diverged"
        # worsening 在未满足收敛门槛时判发散（持续恶化比当前误差更危险）
        assert self.v(0.05, None, 0.0, worsening=True) == "diverged"

    def test_converged_gates_take_precedence_over_worsening(self):
        # 分支顺序语义：收敛门槛先判——ess/settle/overshoot 全达标时，
        # 末端轻微 worsening（绝对误差仍极小）不改判发散
        assert self.v(0.01, 2.0, 0.05, worsening=True) == "converged"

    def test_middle_band_is_oscillating(self):
        mid = (self.cfg.converged_ess_max + self.cfg.diverged_ess_min) / 2
        assert self.v(mid, None, 0.0) == "oscillating"


def test_metrics_monotonic_across_synthetic_qualities():
    """IAE 随（合成）控制质量下降而单调增大——替代原三档 replay 集成断言。"""
    iae = {k: _eval(_synthetic(k))["iae"] for k in ("converged", "oscillating", "diverged")}
    assert iae["converged"] < iae["oscillating"] < iae["diverged"]
