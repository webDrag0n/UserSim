"""系列事件（Series Events）：类型定义、行程单生成、日程覆盖。

见 docs/09-series-events.md。物化原则：系列创建时行程单一次生成，世界保持确定。
"""

from __future__ import annotations

import numpy as np

from usersim.contracts import Event

# ---------------------------------------------------------------
# 系列类型定义
# ---------------------------------------------------------------

SERIES_TYPES: dict[str, dict] = {
    "grand_trip": {
        "name": "长途旅行", "icon": "🏝", "duration_range": (5, 14),
        "suppress_work": True, "suppress_income": True,
        "source": "planned",  # 助手规划
        "sleep": {"name": "酒店睡眠", "cost": 200, "effect": {"energy": {"pull": [0.72, 0.50]}}, "note": "认床，不如家里"},
        "meal": {"name": "旅行餐食", "slot": 0, "span": 3, "cost": 95,
                 "effect": {"satiety": {"pull": [0.80, 0.75]}, "valence": 0.12},
                 "note": "异地特色三餐（合并计价 35+60；心情加成按时段摊销）"},
        "daily_pool": [
            {"name": "雪山湖泊", "cost": 180, "effect": {"valence": 0.20, "stress": -0.15, "energy": -0.08}},
            {"name": "人文古迹", "cost": 120, "effect": {"valence": 0.14, "stress": -0.10, "energy": -0.06}},
            {"name": "市集商圈", "cost": 100, "effect": {"valence": 0.12, "satiety": 0.10, "energy": -0.05}},
            {"name": "主题乐园", "cost": 260, "effect": {"valence": 0.25, "stress": -0.12, "energy": -0.12}},
            {"name": "海边发呆", "cost": 0, "effect": {"valence": 0.10, "stress": -0.18, "energy": 0.03}},
            {"name": "温泉疗养", "cost": 220, "effect": {"stress": -0.20, "energy": 0.08, "valence": 0.06}},
        ],
        "evening_pool": [
            {"name": "夜市小吃", "cost": 40, "effect": {"valence": 0.08, "satiety": 0.15}},
            {"name": "酒店休息", "cost": 0, "effect": {"energy": 0.08, "stress": -0.05}},
        ],
        "transit": {"name": "长途交通", "effect": {"energy": -0.10, "stress": 0.04}},
        "aftereffect": {"name": "旅行回味", "days": 3, "effect": {"valence": 0.04}, "per": "day"},
    },
    "business_trip": {
        "name": "出差", "icon": "💼", "duration_range": (2, 7),
        "suppress_work": False, "suppress_income": False,  # 异地工作：收入照发
        "daily_income_bonus": 100,  # 出差补贴
        "extra_work_stress": 0.02,  # 异地工作额外压力
        "source": "forced",  # 强制扰动
        "sleep": {"name": "酒店睡眠", "cost": 0, "effect": {"energy": {"pull": [0.70, 0.50]}}, "note": "更差的认床"},
        "meal": {"name": "酒店餐", "slot": 0, "span": 3, "cost": 0, "income": 100,
                 "effect": {"satiety": {"pull": [0.76, 0.75]}, "stress": 0.03},
                 "note": "含出差补贴（首日早餐时段入账）"},
        "daily_pool": [
            {"name": "客户会议", "cost": 0, "effect": {"stress": 0.08, "energy": -0.04}},
            {"name": "商务应酬", "cost": 0, "effect": {"stress": 0.10, "satiety": 0.15, "energy": -0.06}, "note": "公司报销但状态受损"},
            {"name": "深夜赶材料", "cost": 0, "effect": {"energy": -0.08, "stress": 0.06}},
        ],
        "evening_pool": [],
        "transit": {"name": "差旅交通", "effect": {"energy": -0.08, "stress": 0.03}},
        "aftereffect": {"name": "差旅疲惫与回家踏实", "days": 2, "effect": {"energy": -0.06, "valence": 0.05}, "per": "day"},
    },
    "staycation": {
        "name": "宅家休假", "icon": "🛋", "duration_range": (3, 10),
        "suppress_work": True, "suppress_income": True,
        "source": "planned",
        "sleep": {"name": "懒觉自然醒", "cost": 0, "effect": {"energy": {"pull": [0.85, 0.55]}, "valence": 0.03}},
        "meal": {"name": "家常三餐", "slot": 0, "span": 3, "cost": 20,
                 "effect": {"satiety": {"pull": [0.73, 0.75]}, "valence": 0.04}},
        "daily_pool": [
            {"name": "周边一日游", "cost": 150, "span": 2, "effect": {"valence": 0.15, "stress": -0.12, "energy": -0.06}},
            {"name": "看展", "cost": 80, "effect": {"valence": 0.10, "stress": -0.06}},
            {"name": "朋友聚会", "cost": 100, "effect": {"valence": 0.12, "satiety": 0.10}},
            {"name": "纯宅", "cost": 0, "effect": {"valence": 0.04, "stress": -0.06}},
        ],
        "evening_pool": [],
        "boredom": {"from_day": 4, "effect": {"valence": -0.03}, "note": "假期空虚：连续无活动则心情衰减"},
        "aftereffect": None,
    },
    "exam_crunch": {
        "name": "备考冲刺", "icon": "📚", "duration_range": (7, 14),
        "suppress_work": True, "suppress_income": True,
        "source": "forced", "forced_archetype": "备考研究生",
        "sleep": {"name": "正常睡眠", "cost": 0, "effect": {"energy": {"pull": [0.78, 0.50]}, "stress": -0.01}},
        "meal": {"name": "备考三餐", "slot": 0, "span": 3, "cost": 30,
                 "effect": {"satiety": {"pull": [0.70, 0.75]}}},
        "daily_pool": [
            {"name": "刷题", "slot": 0, "span": 2, "cost": 0, "effect": {"stress": 0.06, "energy": -0.08, "valence": -0.02}},
            {"name": "网课", "slot": 2, "span": 1, "cost": 0, "effect": {"stress": 0.02, "energy": -0.02}},
        ],
        "evening_pool": [],
        "final_event": {"name": "大考结束", "effect": {"stress": -0.35, "valence": 0.20}},
        "aftereffect": {"name": "释放后空虚", "days": 2, "effect": {"valence": -0.02}, "per": "day"},
    },
}


# ---------------------------------------------------------------
# 行程单生成
# ---------------------------------------------------------------

def _mk(sid: str, idx: int, name: str, kind_slot: int, effect: dict,
        cost: float = 0.0, income: float = 0.0, span: int = 1,
        location: str = "", goal: str = "", note: str = "") -> Event:
    return Event(id=f"{sid}-{idx:02d}", kind="series", name=name, start_slot=kind_slot,
                 span_slots=span, location=location or name, goal=goal or name,
                 effect=dict(effect), cost=cost, income=income, series_id=sid, note=note)


def generate_itinerary(
    series_id: str,
    stype: str,
    start_day: int,
    duration: int,
    slots_per_day: int,
    rng: np.random.Generator,
    ticket_budget: float,
) -> list[Event]:
    """物化整个系列：每日餐宿 + 子事件 + 首尾交通 + 后效。"""
    sdef = SERIES_TYPES[stype]
    events: list[Event] = []
    idx = 0
    pool = list(sdef["daily_pool"])
    # 门票预算决定行程单里高价景点的比例（没钱就多看海发呆）
    affordable = [p for p in pool if p["cost"] <= max(0, ticket_budget)]
    if not affordable:
        affordable = [p for p in pool if p["cost"] == 0] or pool

    exam = stype == "exam_crunch"
    for i in range(duration):
        day = start_day + i
        base = day * slots_per_day

        # 三餐（单事件跨 3 时段，含补贴收入）与宿
        m = sdef["meal"]
        events.append(_mk(series_id, idx, m["name"], base + m["slot"], m["effect"],
                          m["cost"], m.get("income", 0), span=m["span"], note="系列餐食")); idx += 1
        sl = sdef["sleep"]
        events.append(_mk(series_id, idx, sl["name"], base + 3, sl["effect"], sl["cost"], note=sl.get("note", ""))); idx += 1

        # 首尾交通（并非所有系列都有）
        t = sdef.get("transit")
        if t and (i == 0 or i == duration - 1):
            events.append(_mk(series_id, idx, t["name"], base + (0 if i == 0 else 1), t["effect"])); idx += 1

        # 子事件（刷题/网课有固定 slot/span；出差与旅休按节奏生成）
        if exam:
            for p in pool:
                events.append(_mk(series_id, idx, p["name"], base + p["slot"], p["effect"], p["cost"], span=p.get("span", 1))); idx += 1
            if i >= duration - 2:  # 考前焦虑
                events.append(_mk(series_id, idx, "考前焦虑", base + 2, {"stress": 0.03}, note="临近考试")); idx += 1
            if i == duration - 1:
                f = sdef["final_event"]
                events.append(_mk(series_id, idx, f["name"], base + 2, f["effect"], note="巨量释放")); idx += 1
        elif stype == "business_trip":
            events.append(_mk(series_id, idx, "异地工作", base + 0, {"stress": sdef["extra_work_stress"] * 2, "energy": -0.04}, span=2, note="收入照发")); idx += 1
            if i % 2 == 0:
                events.append(_mk(series_id, idx, pool[0]["name"], base + 2, pool[0]["effect"])); idx += 1
            if i == 1 or i == duration - 2:
                p = pool[1]
                events.append(_mk(series_id, idx, p["name"], base + 2, p["effect"], note=p.get("note", ""))); idx += 1
        else:
            # grand_trip / staycation：每天 1~2 个子事件
            p1 = affordable[int(rng.integers(len(affordable)))]
            events.append(_mk(series_id, idx, p1["name"], base + 0, p1["effect"], p1["cost"],
                              span=p1.get("span", 1), note="行程单")); idx += 1
            if rng.random() < 0.6:
                p2 = affordable[int(rng.integers(len(affordable)))]
                if p2["name"] != p1["name"]:
                    events.append(_mk(series_id, idx, p2["name"], base + 1, p2["effect"], p2["cost"],
                                      span=p2.get("span", 1))); idx += 1
            # 晚上（旅行：夜市/休息交替）
            if sdef["evening_pool"]:
                ev = sdef["evening_pool"][i % len(sdef["evening_pool"])]
                events.append(_mk(series_id, idx, ev["name"], base + 2, ev["effect"], ev["cost"])); idx += 1

    # 后效事件
    ae = sdef.get("aftereffect")
    if ae:
        end_base = (start_day + duration) * slots_per_day
        n = ae["days"] if ae["per"] == "day" else ae["days"] * slots_per_day
        events.append(_mk(series_id, idx, ae["name"], end_base, ae["effect"], span=n,
                          note="系列后效"))

    return events


def boredom_active(stype: str, day_in_series: int, day_event_names: list[str]) -> bool:
    """宅家休假的空虚机制：第 N 天起，当天除餐宿外无任何活动 → 心情衰减。"""
    sdef = SERIES_TYPES.get(stype, {})
    b = sdef.get("boredom")
    if not b or day_in_series < b["from_day"]:
        return False
    meal_sleep_names = {sdef["meal"]["name"], sdef["sleep"]["name"]}
    return all(n in meal_sleep_names for n in day_event_names) if day_event_names else True
