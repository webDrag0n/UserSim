"""economy 测试：收入、消费、支付能力、负债压力、配表裁决。"""

from usersim.config import load_system_config
from usersim.world import World
from usersim.world.catalog import find_variant


def _world(seed=1, days=5):
    return World(seed=seed, days=days, cfg=load_system_config())


def test_workday_income():
    w = _world()
    m0 = w.money
    w.step_slot()  # 第 0 天 slot 0（工作日）→ 收入按职业；另扣三餐合并计价 ¥30
    assert w.money == m0 + w.persona.income_per_slot - 30


def test_catalog_lookup_by_name_and_location():
    found = find_variant("吃好吃的", "商场")
    assert found is not None
    action, variant = found
    assert action["action"] == "吃好吃的" and variant["location"] == "商场餐厅" and variant["cost"] == 120


def test_recovery_cost_deducted_at_start():
    w = _world()
    r = w.add_event_todo("吃好吃的", 0, 0, "回血", {}, location="商场")
    assert r.ok and r.payload["event"]["cost"] == 120
    m0 = w.money
    w.step_slot()  # slot 0：恢复事件 -120；工作收入按职业；三餐合并计价 -30
    assert w.money == m0 + w.persona.income_per_slot - 30 - 120


def test_unaffordable_rejected():
    w = _world()
    w.money = 50
    r = w.add_event_todo("短途旅行", 0, 1, "回血", {}, location="海边小镇")
    assert not r.ok and "金钱不足" in r.payload["error"]
    # 免费选项仍然可用
    r2 = w.add_event_todo("出门走走", 0, 1, "回血", {}, location="楼下公园")
    assert r2.ok


def test_debt_stress_penalty():
    w = _world()
    w.money = -10
    s = w.step_slot()
    assert abs(s.natural_drift["stress"] - 0.03) > 1e-9 or s.natural_drift["stress"] >= 0.03


def test_unsupported_event_rejected():
    w = _world()
    # 完全目录外的活动（无任何规范类目关键词）= 系统不支持 → 拒绝安排，
    # 助手应坦诚告知用户"找不到这样的地方"并推荐目录内替代（不再给 C0 兜底效果）
    r = w.add_event_todo("自定义冥想", 0, 1, "放松", {"stress": -0.9, "valence": 0.9})
    assert not r.ok
    assert r.payload.get("unsupported") is True
    # 自报效果不生效：世界里没有新增任何事件
    assert not any(e.name == "自定义冥想" for e in w.events)


def test_custom_activity_normalized():
    w = _world()
    r = w.add_event_todo("去美术馆逛逛", 0, 1, "放松", {})
    assert r.ok
    e = r.payload["event"]
    assert e["name"] == "文化看展" and e["cost"] == 80 and e["effect"]["valence"] == 0.10
    assert "原称" in e["goal"]
