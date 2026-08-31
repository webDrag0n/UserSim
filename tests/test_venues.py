"""venues 统一地点表测试：加载、flatten、查找命中、数值裁决、模板餐抑制、餍足提示。

数据模型：事件（recovery_actions A1-A6）只带元信息；一次"在某地点做某事件"的
价格/时长/效果由 venue.supports 条目自带；vid = f"{事件id}@{地点id}"。
"""

import json

import pytest

from usersim.config import load_system_config
from usersim.contracts.persona import PREF_CATEGORIES
from usersim.runner import _recovery_catalog
from usersim.world import World
from usersim.world.balance import get_config_dir
from usersim.world.catalog import VENUES, all_variants, find_variant, get_venues

REQUIRED_FIELDS = ("id", "name", "category", "cuisine", "aliases", "supports", "design_intent")
EVENT_IDS = {f"A{i}" for i in range(1, 7)} | {f"C{i}" for i in range(0, 7)}


def _world(seed=1, days=5):
    return World(seed=seed, days=days, cfg=load_system_config())


def test_venues_json_loaded_and_wellformed():
    venues = get_venues()
    assert 40 <= len(venues) <= 50  # 30 场所 + 15 旧档位地点（家合并 3 条）
    food_costs = []
    supported_events = set()
    for vn in venues:
        for f in REQUIRED_FIELDS:
            assert f in vn, f"{vn.get('id')} 缺字段 {f}"
        assert vn["category"] in PREF_CATEGORIES, f"{vn['id']} 类目越界：{vn['category']}"
        assert isinstance(vn["aliases"], list) and vn["aliases"]
        assert isinstance(vn["supports"], list) and vn["supports"], f"{vn['id']} 无支持条目"
        for s in vn["supports"]:
            assert s["event"] in EVENT_IDS, f"{vn['id']} 引用未知事件 {s['event']}"
            supported_events.add(s["event"])
            assert s["cost"] >= 0 and s["span"] >= 1
            # 单次事件单维效果量级（旧档位合计最大 0.27 = 远方城市心情；pull 类目标/速率 ∈ [0,1]）
            for dim, v in s["effect"].items():
                if isinstance(v, dict) and "pull" in v:
                    assert 0.0 <= v["pull"][0] <= 1.0 and 0.0 < v["pull"][1] <= 1.0
                else:
                    assert abs(v) <= 0.30, f"{vn['id']} 的 {dim} 超幅：{v}"
        if vn.get("replaces_meal"):
            assert vn["category"] == "饮食" and vn["cuisine"], f"{vn['id']} 替代餐须为带菜系餐饮场所"
            food_costs.append(vn["supports"][0]["cost"])
    # 六个恢复事件都至少有一个支持地点
    assert {f"A{i}" for i in range(1, 7)} <= supported_events
    # 餐饮价位覆盖 ¥15–¥500
    assert min(food_costs) >= 15 and max(food_costs) <= 500
    assert min(food_costs) <= 30 and max(food_costs) >= 400  # 跨度确实拉开


def test_venues_constant_matches_json():
    """代码内联副本（无配表时的回退）必须与 venues.json 内容一致。"""
    raw = json.loads((get_config_dir() / "venues.json").read_text(encoding="utf-8"))
    assert VENUES == raw


def test_all_variants_is_venue_flatten_plus_pseudo():
    """all_variants = 地点支持表 flatten + 进餐/睡眠伪动作；vid 规则 f"{事件}@{地点}"。"""
    av = all_variants()
    n_supports = sum(len(vn["supports"]) for vn in get_venues())
    assert len(av) == n_supports + 2  # + MEAL/SLEEP 伪动作
    vids = [v["vid"] for _, v in av]
    assert len(vids) == len(set(vids)), "vid 不得重复"
    assert "A1@V001" in vids and "M2" in vids and "S2" in vids
    # 同一 venue 同事件多条目按序加 #n（家的两条 A6）
    assert "A6@V034#1" in vids and "A6@V034#2" in vids
    assert not any(a.get("id") == "VENUE" for a, _ in av)  # 旧伪动作已拆除


def test_find_variant_hits_venue_by_cuisine():
    found = find_variant("想吃日料")
    assert found is not None
    action, variant = found
    assert action["id"] == "A1" and variant["vid"] == "A1@V005"
    assert action["action"] == "吃好吃的" and action["category"] == "饮食"
    assert variant["location"] == "鮨·omakase（主厨发办）"

    found = find_variant("寿司")
    assert found is not None and found[1]["vid"] == "A1@V004"

    # 场所 id 精确匹配（取其首个支持条目；harness 回传 variant_id 的路径）
    found = find_variant("V001")
    assert found is not None and found[1]["vid"] == "A1@V001"
    assert found[1]["location"] == "川渝老火锅（巷子里店）"
    # vid 精确匹配
    assert find_variant("A1@V001")[1]["location"] == "川渝老火锅（巷子里店）"


def test_old_tier_locations_still_hittable():
    """旧 17 个档位地点迁移后都能经 find_variant 命中（数值逐字沿用原合计效果）。"""
    cases = {
        "楼下快餐": ("A1@V031", 30), "商场餐厅": ("A1@V032", 120),
        "收藏多年的小店": ("A1@V033", 200),
        "温泉": ("A2@V036", 400), "按摩": ("A2@V035", 150),
        "楼下公园": ("A3@V037", 0), "近郊徒步": ("A3@V039", 80),
        "邻市一日": ("A4@V040", 300), "远方城市": ("A4@V042", 1200),
        "小区跑步": ("A5@V043", 0), "私教": ("A5@V045", 200),
    }
    for key, (vid, cost) in cases.items():
        found = find_variant(key)
        assert found is not None, f"{key} 未命中"
        assert found[1]["vid"] == vid and found[1]["cost"] == cost, f"{key} → {found[1]['vid']}"
    # 效果逐字沿用：温泉酒店 = 原 A2-3 合计（精力0.25 压力-0.20 心情0.10）
    eff = find_variant("温泉")[1]["effect"]
    assert eff["energy"] == pytest.approx(0.25) and eff["stress"] == pytest.approx(-0.20)


def test_home_venue_multiple_supports():
    """"家"同一 venue 支持多事件多条目：补觉/看电影/做顿好的都能命中且 vid 不同。"""
    nap = find_variant("家里补觉")
    movie = find_variant("看电影")
    cook = find_variant("做顿好的")
    assert nap[1]["vid"] == "A2@V034" and nap[1]["cost"] == 0
    assert movie[1]["vid"] == "A6@V034#1" and movie[1]["cost"] == 0
    assert cook[1]["vid"] == "A6@V034#2" and cook[1]["cost"] == 40
    assert nap[0]["action"] == "好好休息" and movie[0]["action"] == "宅家回血"
    # 数值沿用原合计：补觉 精力0.20；做顿好的 饱腹0.25
    assert nap[1]["effect"]["energy"] == pytest.approx(0.20)
    assert cook[1]["effect"]["satiety"] == pytest.approx(0.25)


def test_event_name_only_picks_cheapest_venue():
    """只给事件名时选最便宜的支持场所。"""
    found = find_variant("吃好吃的")
    assert found[1]["vid"] == "A1@V010" and found[1]["cost"] == 18  # 兰州牛肉面
    found = find_variant("好好休息")
    assert found[1]["vid"] == "A2@V034" and found[1]["cost"] == 0  # 家里补觉
    # 带地点关键词则选该地点
    found = find_variant("吃好吃的", "商场")
    assert found[1]["vid"] == "A1@V032" and found[1]["cost"] == 120


def test_add_event_todo_venue_arbitration():
    w = _world()
    r = w.add_event_todo("寿喜烧", 0, 2, "改善伙食", {})
    assert r.ok
    e = r.payload["event"]
    # 效果/价格/时长以配表为准（寿喜烧专门店 V003，事件名为「动作 · 地点」）
    assert e["name"] == "吃好吃的 · 寿喜烧专门店（和牛放题）"
    assert e["cost"] == 180
    assert e["effect"]["satiety"] == pytest.approx(0.16)
    assert e["effect"]["valence"] == pytest.approx(0.14)
    assert e["span_slots"] == 1
    assert e["replaces_meal"] is True


def test_unaffordable_venue_rejected():
    w = _world()
    w.money = 100
    r = w.add_event_todo("海鲜大酒楼", 0, 1, "请客", {})
    assert not r.ok and "金钱不足" in r.payload["error"]


def test_template_meal_suppressed_per_slot():
    """晚餐安排了餐饮场所 → 该 slot 模板"三餐"不生效；未覆盖的 slot 照常。"""
    w_venue = _world(seed=2, days=2)
    w_ctrl = _world(seed=2, days=2)
    r = w_venue.add_event_todo("川渝老火锅", 0, 2, "聚餐", {})
    assert r.ok

    s1 = [w_venue.step_slot() for _ in range(3)]  # 第 0 天 slot 0/1/2
    s2 = [w_ctrl.step_slot() for _ in range(3)]

    # slot 0/1：场所事件尚未活跃，模板餐照常生效（slot 粒度抑制，不删事件）
    assert s1[1].event_effects["satiety"] != 0.0
    # slot 2：场所晚餐活跃 → 模板餐该 slot 的 satiety 完全抑制，只有场所的一份生效
    assert s1[2].event_effects["satiety"] == 0.0
    assert s1[2].control_effects["satiety"] > 0.0
    # 对照组：无场所 → 模板餐 pull 生效，且无恢复事件效果
    assert s2[2].event_effects["satiety"] != 0.0
    assert s2[2].control_effects["satiety"] == 0.0


def test_venue_restaurant_habituates_but_template_meal_exempt():
    """venue 餐厅（名字含"餐"）照常习惯化（按店跟踪）；模板"三餐"仍在豁免名单。"""
    w = _world(seed=4, days=2)
    r = w.add_event_todo("粤式茶餐厅", 0, 2, "午饭", {})
    assert r.ok
    for _ in range(3):
        w.step_slot()
    assert "粤式茶餐厅" in w._last_done  # 含"餐"的 venue 不再被豁免，按店名习惯化
    assert "三餐" not in w._last_done    # 模板餐不进入习惯化


def test_satiation_note_after_repeated_action():
    w = _world(seed=3, days=3)
    assert w.current_context().satiation_note is None  # 尚无执行记录

    r1 = w.add_event_todo("出门走走", 0, 2, "散步", {})
    r2 = w.add_event_todo("出门走走", 1, 2, "散步", {})
    assert r1.ok and r2.ok
    for _ in range(7):  # 推进到第 1 天 slot 3（第二次散步刚结束）
        w.step_slot()

    note = w.current_context().satiation_note
    assert note is not None and "腻" in note and "出门走走" in note


def test_recovery_catalog_includes_venues_with_category_cuisine():
    w = _world()
    cat = _recovery_catalog(w)
    assert cat and all("category" in c and "cuisine" in c for c in cat)

    venues = [c for c in cat if "@" in c["vid"]]
    assert venues, "地点支持条目未并入 recovery_catalog"
    v001 = next(c for c in venues if c["vid"] == "A1@V001")
    assert v001["action"] == "吃好吃的"  # action 用事件名，地点在 location
    assert v001["location"] == "川渝老火锅（巷子里店）"
    assert v001["category"] == "饮食" and v001["cuisine"] == "火锅"
    # 非餐饮场所（livehouse → C3 音乐放松）cuisine 为空字符串
    v025 = next(c for c in venues if c["vid"] == "C3@V025")
    assert v025["action"] == "音乐放松"
    assert v025["category"] == "音乐" and v025["cuisine"] == ""
