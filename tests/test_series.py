"""系列事件测试：行程单物化、日程覆盖、收入抑制、空虚机制、强制系列、快照。"""

from usersim.config import load_system_config
from usersim.world import World


def _world(seed=1, days=30, archetype=None):
    return World(seed=seed, days=days, cfg=load_system_config(), archetype=archetype)


def test_grand_trip_materialized_and_overrides_schedule():
    w = _world()
    w.money = 8000
    r = w.plan_series("grand_trip", 2, 6)
    assert r.ok, r.payload
    s = w.series[0]
    assert s.type == "grand_trip" and s.end_day - s.start_day == 6
    start_slot = s.start_day * w.slots_per_day
    end_slot = s.end_day * w.slots_per_day
    # 区间内不应再有"上午工作/下午工作"模板
    assert not any(e.name in ("上午工作", "下午工作") and start_slot <= e.start_slot < end_slot
                   for e in w.events)
    # 系列子事件存在且带 series_id；有景点与合并的系列餐食
    sub = [e for e in w.events if e.series_id == s.id and start_slot <= e.start_slot < end_slot]
    names = {e.name for e in sub}
    assert any("睡眠" in n or "酒店" in n for n in names)
    assert any("餐食" in n or "特色" in n for n in names)  # 合并后的旅行餐食
    assert any(n in ("雪山湖泊", "人文古迹", "市集商圈", "主题乐园", "海边发呆", "温泉疗养") for n in names)
    # 后效事件已物化
    assert any(e.name == "旅行回味" for e in w.events)


def test_trip_suppresses_work_and_income():
    w = _world()
    w.money = 8000
    r = w.plan_series("grand_trip", 1, 5)
    s = w.series[0]
    # 快进到旅行中的一个工作日
    while w.day < s.start_day or not w.is_workday() or w.slot != 0:
        w.step_slot()
    assert w.active_series() is not None
    m0 = w.money
    st = w.step_slot()  # 旅行中的工作日上午：无工作漂移、无收入（只有消费）
    assert st.natural_drift["stress"] < 0.048  # 工作压力被抑制
    assert w.money <= m0  # 无工作收入
    assert st.active_series and "旅行" in st.active_series


def test_business_trip_keeps_income_with_bonus():
    w = _world()
    r = w.add_series("business_trip", 10, 3)
    assert r.ok
    s = w.series[0]
    while w.day < s.start_day or not w.is_workday() or w.slot != 0:
        w.step_slot()
    m0 = w.money
    w.step_slot()
    # 出差补贴来自系列餐事件的 income（酒店早餐 +¥100），工作收入照发
    assert w.money > m0


def test_staycation_boredom_replaced_by_stimulation_decay():
    """空虚机制已由刺激需求统一承担：连续无活动时刺激值回落（无聊累积）。"""
    w = _world()
    r = w.add_series("staycation", 10, 8)
    assert r.ok
    s0 = w.needs.n["stimulation"]
    # 删除系列第 4 天起的所有活动子事件（只留餐宿），模拟"躺完全程"
    s = w.series[0]
    boredom_start = (s.start_day + 4) * w.slots_per_day
    meal_sleep = {"家常三餐", "懒觉自然醒"}
    w.events = [e for e in w.events
                if not (e.series_id == s.id and e.start_slot >= boredom_start and e.name not in meal_sleep)]
    while w.day < s.start_day + 4:
        w.step_slot()
    for _ in range(4):
        w.step_slot()
    assert w.needs.n["stimulation"] < 0.5  # 无聊在累积（倒 U 左端将提升求助倾向）


def test_exam_crunch_forced_for_student():
    w = _world(days=25, archetype="备考研究生")
    assert any(s.type == "exam_crunch" for s in w.series)
    assert any(e.name == "大考结束" for e in w.events)


def test_series_activity_triggers_assist_prompt():
    """系列游玩事件应以概率触发'攻略/导航'类助手介入点。"""
    w = _world()
    w.money = 8000
    w.plan_series("grand_trip", 1, 6)
    prompts = 0
    while not w.done:
        ctx = w.current_context()
        if ctx.assist_prompt and ("游玩" in ctx.assist_prompt or "攻略" in ctx.assist_prompt):
            prompts += 1
        w.step_slot()
    assert prompts >= 1


def test_series_survives_snapshot(tmp_path):
    w = _world()
    w.money = 8000
    w.plan_series("grand_trip", 2, 6)
    for _ in range(8):
        w.step_slot()
    from usersim.world.world import World as W2
    snap = w.to_snapshot()
    w2 = W2.from_snapshot(snap, w.cfg, extra_days=2)
    assert len(w2.series) == len(w.series)
    assert w2.days == w.days + 2
    assert w2.x == w.x and w2.money == w.money
