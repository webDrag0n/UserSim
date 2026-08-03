"""拟人化引擎测试：习惯化曲线、需求动力学、人格调节、峰终、快照。"""

import math

from usersim.config import load_system_config
from usersim.world import World
from usersim.world.anthro import Needs, hab_weight, persona_modifiers


def _world(seed=1, days=10, archetype=None):
    return World(seed=seed, days=days, cfg=load_system_config(), archetype=archetype)


def test_hab_weight_curves():
    # dt=0 → w_min；dt→∞ → 1；曲线非直线且形状不同
    for curve in ("exp", "sqrt", "s"):
        assert abs(hab_weight(0, 0.3, 6, curve) - 0.3) < 1e-9
        assert hab_weight(60, 0.3, 6, curve) > 0.75  # 长尾恢复（sqrt 较慢）
    assert hab_weight(60, 0.3, 6, "exp") > 0.9
    a, b, c = (hab_weight(4, 0.2, 10, k) for k in ("exp", "sqrt", "s"))
    assert len({round(a, 3), round(b, 3), round(c, 3)}) >= 2  # 不同曲线不同形状
    assert all(0.2 < v < 1.0 for v in (a, b, c))


def test_repetition_diminishes_and_recovers():
    w = _world()
    # 第一次出门走走：满效果
    w.add_event_todo("出门走走", 0, 0, "回血", {}, location="楼下公园")
    s1 = w.step_slot()
    first = s1.control_effects["stress"]
    # 紧接着下一时段再做：效果明显变差（习惯化）
    w.add_event_todo("出门走走", 0, 1, "回血", {}, location="楼下公园")
    s2 = w.step_slot()
    second = s2.control_effects["stress"]
    assert abs(second) < abs(first) * 0.6
    # 隔 8 个时段再做：效果恢复大部分
    for _ in range(7):
        w.step_slot()
    w.add_event_todo("出门走走", 0, w.slot, "回血", {}, location="楼下公园")
    s3 = w.step_slot()
    assert abs(s3.control_effects["stress"]) > abs(second) * 1.5


def test_stimulation_inverted_u():
    n = Needs()
    n.n["stimulation"] = 0.1
    u_low = n.urges()["stimulation"]
    n.n["stimulation"] = 0.5
    u_mid = n.urges()["stimulation"]
    n.n["stimulation"] = 0.95
    u_high = n.urges()["stimulation"]
    # 倒 U：两端都低于中点（无聊与过载都想寻求变化）
    assert u_mid > u_low and u_mid > u_high
    assert abs(u_mid - 1.0) < 1e-9
    assert u_high < 0.2


def test_needs_social_and_hunger():
    n = Needs()
    s0 = n.n["social"]
    n.update(satiety=0.3, active_names=[], extraversion=80, exam_active=False, deadline_disturbance=False)
    assert n.n["social"] > s0  # 外向者累积更快
    assert n.urges()["hunger"] > 0  # 低饱腹产生饥饿驱动
    n.update(satiety=0.9, active_names=["朋友小聚"], extraversion=50, exam_active=False, deadline_disturbance=False)
    assert n.n["social"] <= 0.1 + 1e-9  # 社交后释放


def test_persona_social_battery():
    big5_intro = {"外向性": 10, "神经质": 50, "开放性": 50}
    big5_extro = {"外向性": 90, "神经质": 50, "开放性": 50}
    eff = {"valence": 0.10, "energy": -0.03}
    intro = persona_modifiers(big5_intro, "朋友小聚", eff)
    extro = persona_modifiers(big5_extro, "朋友小聚", eff)
    assert intro["energy"] < eff["energy"]  # 内向者社交更耗电
    assert extro["energy"] > intro["energy"]  # 外向者耗电少甚至回血
    assert extro["valence"] > intro["valence"]


def test_satisfaction_curve_hungry_eats_better():
    n = Needs()
    n.n["hunger"] = 0.9
    hungry = n.satisfaction("吃好吃的")
    n.n["hunger"] = 0.1
    full = n.satisfaction("吃好吃的")
    assert hungry > full > 1.0  # 越饿吃得越香，且都有基础效果


def test_anthro_survives_snapshot():
    w = _world()
    w.add_event_todo("出门走走", 0, 0, "回血", {}, location="楼下公园")
    w.step_slot()
    assert "出门走走" in w._last_done
    snap = w.to_snapshot()
    from usersim.world.world import World as W2
    w2 = W2.from_snapshot(snap, w.cfg, extra_days=0)
    assert w2._last_done.get("出门走走") == w._last_done["出门走走"]
    assert w2.needs.to_dict() == w.needs.to_dict()
