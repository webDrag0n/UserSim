"""事件引擎：日程模板 ⊕ 泊松扰动 ⊕ 用户新增恢复事件。

约定：
- 模板事件 effect 为空——其作用体现在自然动力学中（工作/睡眠/进餐是漂移的一部分），
  它们在此只是上下文与日程视图；显式效果只挂在扰动与恢复事件上，避免双重计数。
"""

from __future__ import annotations

import numpy as np

from usersim.contracts import Event, ToolResult

DISTURBANCE_TYPES: list[tuple[str, str, dict[str, float], float, float]] = [
    # (名称, 地点, Δx, 金钱消耗, 金钱收入) —— 数值以 catalog.DISTURBANCES 为准
    ("临时加班", "公司", {"energy": -0.16, "stress": 0.20, "valence": -0.08}, 0, 150),
    ("应酬饭局", "餐厅", {"energy": -0.12, "stress": 0.10, "satiety": 0.15}, 100, 0),
    ("暴雨行程受阻", "路上", {"valence": -0.12, "stress": 0.09}, 0, 0),
    ("项目截止压缩", "公司", {"stress": 0.24, "energy": -0.10, "valence": -0.06}, 0, 0),
    ("朋友临时邀约", "外面", {"valence": 0.10, "energy": -0.08, "satiety": 0.10}, 80, 0),
]

def build_template_schedule(days: int, slots_per_day: int, weekend_days: list[int]) -> list[Event]:
    """作息模板铺底（数据层无时段变体：工作/三餐/睡眠各为一个事件，时间只是参数）。

    语义说明：三餐为跨 3 时段的单事件——pull 效果在每个活跃时段各作用一次，
    与原"早餐/午餐/晚餐三个事件"逐时段作用完全等价；费用 30 一次性扣除（= 10×3）。
    """
    from usersim.world.catalog import get_meal_tiers, get_sleep_tiers

    # 经 getter 取档位：config/balance/*.json 覆盖才生效（直接 import 常量会绕过配表）
    default_meal = get_meal_tiers()[1]   # M1 日常家常（pull 在每时段各作用一次）
    default_sleep = get_sleep_tiers()[1]  # S1 正常睡眠
    events: list[Event] = []
    eid = 0
    for d in range(days):
        is_weekend = d % 7 in weekend_days
        base = d * slots_per_day

        def add(name: str, slot: int, span: int, location: str, goal: str,
                effect: dict | None = None, cost: float = 0.0) -> None:
            nonlocal eid
            events.append(
                Event(
                    id=f"T{eid:04d}", kind="template", name=name,
                    start_slot=base + slot, span_slots=span,
                    location=location, goal=goal,
                    effect=dict(effect or {}), cost=cost,
                )
            )
            eid += 1

        add("三餐", 0, 3, "家", "补充能量", default_meal["effect"], default_meal["cost"] * 3)
        add("睡眠", 3, 1, "家", "恢复精力", default_sleep["effect"], default_sleep["cost"])

        if not is_weekend:
            add("工作", 0, 2, "公司", "推进当日工作任务")
            add("晚间休整", 2, 1, "家", "休息回血")
        else:
            add("周末休闲", 1, 1, "外面", "自由安排")
    return events


def sample_disturbances(
    gen: np.random.Generator, days: int, slots_per_day: int, prob_per_day: float
) -> list[Event]:
    """泊松扰动流：每天以 prob 概率出现一次扰动，落在前三个时段之一。"""
    from usersim.world.catalog import get_disturbances
    dtypes = [(d["name"], d["location"], d["effect"], d["cost"], d["income"]) for d in get_disturbances()]
    events: list[Event] = []
    eid = 0
    for d in range(1, days):  # 第 0 天留给用户进入状态
        if gen.random() < prob_per_day:
            name, loc, effect, cost, income = dtypes[int(gen.integers(len(dtypes)))]
            events.append(
                Event(
                    id=f"D{eid:04d}", kind="disturbance", name=name,
                    start_slot=d * slots_per_day + int(gen.integers(slots_per_day - 1)),
                    span_slots=1, location=loc, goal=f"应对突发：{name}",
                    effect=dict(effect), cost=cost, income=income, note="泊松扰动流触发",
                )
            )
            eid += 1
    return events


def validate_new_event(
    event: Event, existing: list[Event], total_slots: int
) -> ToolResult:
    """新增事件（恢复类）合法性校验。"""
    if event.start_slot < 0 or event.start_slot + event.span_slots > total_slots:
        return ToolResult(name="add_event_todo", ok=False, payload={"error": "起止时段越界"})
    if event.span_slots < 1 or event.span_slots > 4:
        return ToolResult(name="add_event_todo", ok=False, payload={"error": "事件跨度需在 1-4 时段"})
    # 恢复事件需要日程空位（同一时段不重复安排恢复事件）
    for e in existing:
        if e.kind == "recovery" and not (
            event.start_slot + event.span_slots <= e.start_slot
            or e.start_slot + e.span_slots <= event.start_slot
        ):
            alt = "换到相邻空闲时段即可"
            return ToolResult(name="add_event_todo", ok=False,
                              payload={"error": f"与已有恢复事件 {e.id}（{e.name}）冲突", "suggestion": alt})
    return ToolResult(name="add_event_todo", ok=True, payload={"event_id": event.id})
