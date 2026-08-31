"""world 测试：确定性、单调性、边界、合法性校验。"""

import json

from usersim.config import load_system_config
from usersim.world import World


def _cfg():
    return load_system_config()


def _trajectory(seed: int, days: int = 10) -> list[dict]:
    """直驱 World 推进完整 episode，返回逐 slot 结算单（含事件流引用）。"""
    w = World(seed=seed, days=days, cfg=_cfg())
    out = []
    while not w.done:
        s = w.step_slot()
        d = s.model_dump()
        # 快照级别的上下文也纳入比对：事件流/天气/需求驱动量都必须确定
        d["_ctx"] = w.current_context().model_dump()
        out.append(d)
    return out


def test_same_seed_same_trajectory():
    """同 seed 两次直驱 World，逐 slot 结算单与最终快照完全一致。"""
    t1 = _trajectory(seed=7)
    t2 = _trajectory(seed=7)
    assert json.dumps(t1, sort_keys=True, ensure_ascii=False) == \
        json.dumps(t2, sort_keys=True, ensure_ascii=False)

    # 最终快照（含 RNG 流状态）也必须一致——否则续跑会分叉
    w1 = World(seed=7, days=10, cfg=_cfg())
    w2 = World(seed=7, days=10, cfg=_cfg())
    while not w1.done:
        w1.step_slot()
        w2.step_slot()
    assert json.dumps(w1.to_snapshot(), sort_keys=True, default=str) == \
        json.dumps(w2.to_snapshot(), sort_keys=True, default=str)


def test_different_seed_diverges():
    """对偶断言：不同 seed 必须产出不同轨迹（防"恒真比较"退化）。"""
    assert json.dumps(_trajectory(seed=7), sort_keys=True, ensure_ascii=False) != \
        json.dumps(_trajectory(seed=8), sort_keys=True, ensure_ascii=False)


def test_state_always_bounded():
    cfg = _cfg()
    w = World(seed=3, days=30, cfg=cfg)
    while not w.done:
        s = w.step_slot()
        for v in s.x_after.model_dump().values():
            assert 0.0 <= v <= 1.0


def test_sleep_restores_energy():
    cfg = _cfg()
    w = World(seed=5, days=3, cfg=cfg)
    # 推进到第 0 天深夜（slot 3）
    for _ in range(3):
        w.step_slot()
    s = w.step_slot()
    # 睡眠恢复已移入事件配表（S1 正常睡眠 pull(0.78, 0.5)），计入事件效果
    assert s.event_effects["energy"] > 0


def test_disturbance_effect_applied():
    cfg = _cfg()
    w = World(seed=42, days=30, cfg=cfg)
    applied = 0
    while not w.done:
        t = w.t
        has_dist = any(e.kind == "disturbance" for e in w.active_events())
        s = w.step_slot()
        if has_dist and any(abs(v) > 1e-9 for v in s.event_effects.values()):
            applied += 1
        assert t == s.t_logical
    assert applied > 0  # 30 天内必有扰动事件结算


def test_recovery_event_validation_conflict():
    cfg = _cfg()
    w = World(seed=9, days=5, cfg=cfg)
    r1 = w.add_event_todo("吃好吃的", 0, 1, "回血", {"valence": 0.2})
    assert r1.ok
    r2 = w.add_event_todo("短途旅行", 0, 1, "回血", {"valence": 0.3})
    assert not r2.ok  # 同一时段恢复事件冲突


def test_felt_state_is_text():
    cfg = _cfg()
    w = World(seed=11, days=2, cfg=cfg)
    assert isinstance(w.felt_state(), str) and "，" in w.felt_state()
