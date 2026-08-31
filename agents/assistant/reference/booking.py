"""日程记忆与冲突避让：消灭"与已有恢复事件冲突"这个最大失分根因。

实测基线（live_42_20260814T031317）：201 次 add_event_todo 中 156 次因同槽位
冲突失败（75%）——harness 不记得自己订过什么，也不解析失败建议重试。本模块：
- 记录自己**成功**订下的 (day, slot) → 事件名（绝对日，跨 session 有效）；
  span>1 的事件登记其覆盖的**全部**槽位（世界按 span 占满，只记起点的
  v5.2 在第五轮实测引发 17 次连续撞单风暴）；
- 解析 schedule_hint 里今日已被世界占用（recovery/series/disturbance）的槽位；
- 发单前查表：绝不向已知占用槽位发单；同一轮内多次发单也不许撞槽；
- 冲突失败 → 挂起重试队列，下一轮自动换相邻空槽重发（世界错误 payload 的
  官方建议就是"换到相邻空闲时段"）；同一单最多重试 2 次（防重试风暴）。
"""

from __future__ import annotations

import re

SLOT_ORDER = (2, 1, 0, 3)  # 减压事件偏好晚上，其次下午/上午，深夜兜底
SLOTS_PER_DAY = 4
MAX_RETRY_ATTEMPTS = 2     # 同一冲突单的重试次数上限
_HINT_SLOT = re.compile(r"（([^（）]*)）")


class BookingMemory:
    def __init__(self) -> None:
        self.booked: dict[str, str] = {}      # "day:slot"（绝对日）→ 事件名
        self.retry_queue: list[dict] = []     # 待重试的绝对目标 {name,location,goal,day,slot}
        self._last_calls: list[dict] = []     # 上一轮发出的 add_event_todo args（对账用）

    # ---- 占用查询 ----
    def occupied(self, day: int, slot: int) -> bool:
        return f"{day}:{slot}" in self.booked

    def hint_slots(self, schedule_hint: str, slot_names: list[str]) -> set[int]:
        """schedule_hint "名字（晚上）；…" → 今日被世界占用/应避让的槽位集合。"""
        out: set[int] = set()
        for seg in (schedule_hint or "").split("；"):
            m = _HINT_SLOT.search(seg)
            if m and m.group(1) in slot_names:
                out.add(slot_names.index(m.group(1)))
        return out

    def pick_slot(self, today: int, taken_today: set[int] | None = None,
                  prefer: tuple[int, ...] = SLOT_ORDER) -> tuple[int, int] | None:
        """第一个空闲 (绝对日, 槽位)：今天找一遍，明天再找一遍；都没有返回 None。"""
        taken_today = taken_today or set()
        for day in (today, today + 1):
            for s in prefer:
                if self.occupied(day, s):
                    continue
                if day == today and s in taken_today:
                    continue
                return day, s
        return None

    # ---- 发单登记与对账 ----
    def stage(self, args: dict, today: int, taken_today: set[int] | None = None) -> dict | None:
        """发单前登记：换算绝对日、查占用（自订 + 今日 hint 占用）；通过则返回规范 args。"""
        try:
            day = today + int(args.get("day_offset", 0))
            slot = int(args.get("slot", 2))
        except (TypeError, ValueError):
            return None
        if slot < 0 or slot > 3 or day < today or day > today + 1:
            return None
        if self.occupied(day, slot):
            return None
        if day == today and taken_today and slot in taken_today:
            return None
        self.booked[f"{day}:{slot}"] = str(args.get("name", ""))  # 乐观占位，失败时回滚
        return {"name": str(args.get("name", "")), "location": str(args.get("location", "")),
                "day_offset": day - today, "slot": slot, "goal": str(args.get("goal", ""))}

    def commit_calls(self, calls: list[dict], today: int) -> None:
        """记下本轮实际发出的 add_event_todo（绝对日+槽位），供下一轮对账。"""
        self._last_calls = []
        for c in calls:
            try:
                day = today + int(c.get("day_offset", 0))
                slot = int(c.get("slot", 2))
            except (TypeError, ValueError):
                continue
            self._last_calls.append({"name": str(c.get("name", "")),
                                     "location": str(c.get("location", "")),
                                     "goal": str(c.get("goal", "")),
                                     "attempts": int(c.get("attempts", 0) or 0),
                                     "day": day, "slot": slot})

    def reconcile(self, tool_results, today: int, taken_today: set[int] | None = None):
        """按序对账上一轮 add_event_todo 的执行结果：
        成功 → 入 succeeded（带世界返回的真实 effect 与 span，供 tracker 精确登记
        剂量）；同时把 span 覆盖的全部槽位登记为占用（世界按 span 占满，只记起点
        会让后续单反复撞同一事件——第五轮实测 17 连撞的根因）；
        失败 → 回滚乐观占位、入 failed（供 recent_arrangements 撤名）；
        冲突类失败额外挂起重试（换到下一个空闲槽，避让 hint 占用；同名已在队列
        或已达重试上限则不挂——防重试风暴）。"""
        calls = self._last_calls
        self._last_calls = []
        succeeded: list[tuple[dict, int, int, dict | None, int]] = []
        failed: list[dict] = []
        results = [r for r in tool_results if r.name == "add_event_todo"]
        for call, res in zip(calls, results):
            key = f"{call['day']}:{call['slot']}"
            if res.ok:
                ev = (res.payload or {}).get("event") or {}
                eff = ev.get("effect")
                span = max(1, int(ev.get("span_slots", 1) or 1))
                start = ev.get("start_slot")
                if isinstance(start, int):  # 绝对 t → 登记 span 覆盖的全部槽位
                    for i in range(span):
                        d, s = divmod(start + i, SLOTS_PER_DAY)
                        self.booked[f"{d}:{s}"] = call["name"]
                succeeded.append((call, call["day"], call["slot"],
                                  eff if isinstance(eff, dict) else None, span))
                continue
            failed.append(call)
            err = str((res.payload or {}).get("error", ""))
            attempts = int(call.get("attempts", 0)) + 1
            if ("冲突" in err and attempts <= MAX_RETRY_ATTEMPTS
                    and not any(r["name"] == call["name"] for r in self.retry_queue)):
                # 先选新槽（旧槽仍占着，避免选回原槽），再回滚旧占位
                nxt = self.pick_slot(today, taken_today)
                if nxt is not None:
                    self.retry_queue.append({"name": call["name"],
                                             "location": call.get("location", ""),
                                             "goal": call.get("goal", ""),
                                             "attempts": attempts,
                                             "day": nxt[0], "slot": nxt[1]})
                    self.booked[f"{nxt[0]}:{nxt[1]}"] = call["name"]
            self.booked.pop(key, None)  # 回滚乐观占位
        return succeeded, failed

    # ---- 重试队列 ----
    def pop_retries(self, today: int) -> list[dict]:
        """取出仍有效的重试单（转成相对 day_offset），过期（<今天）丢弃。"""
        out: list[dict] = []
        keep: list[dict] = []
        for item in self.retry_queue:
            offset = int(item["day"]) - today
            if offset < 0:
                continue  # 过期：目标日已过，不再补
            if offset > 1:  # 世界只接受 day_offset 0/1：留到明天再发
                keep.append(item)
                continue
            out.append({"name": item["name"], "location": item.get("location", ""),
                        "day_offset": offset, "slot": int(item["slot"]),
                        "goal": item.get("goal", ""),
                        "attempts": int(item.get("attempts", 0))})
        self.retry_queue = keep
        return out

    def prune(self, today: int) -> None:
        """丢弃昨天以前的占位（世界不会拒绝过去的槽位，留着只会误挡）。"""
        self.booked = {k: v for k, v in self.booked.items()
                       if int(k.split(":")[0]) >= today - 1}

    # ---- 续跑支持 ----
    def snapshot(self) -> dict:
        return {"booked": dict(self.booked), "retry_queue": [dict(i) for i in self.retry_queue]}

    def restore(self, state: dict) -> None:
        self.booked = {str(k): str(v) for k, v in (state.get("booked") or {}).items()}
        self.retry_queue = [dict(i) for i in (state.get("retry_queue") or [])]
        self._last_calls = []
