"""reference v5 架构件测试：状态跟踪器 / 日程记忆 / harness 集成 / nomem 消融。

全部用罐头 client 或纯函数，不调真实 LLM。
"""

from __future__ import annotations

import pytest

from agents.assistant.reference.booking import BookingMemory
from agents.assistant.reference.harness import ReferenceHarness
from agents.assistant.reference.state_tracker import StateTracker
from agents.assistant.reference_nomem import NoMemHarness
from usersim.contracts import HarnessObs, ToolResult
from usersim.contracts.persona import FACET_KEYS, PREF_CATEGORIES

SLOT_NAMES = ["上午", "下午", "晚上", "深夜"]


def _add(name="江边步道散步", slot=2):
    return {"name": name, "location": "江边", "day_offset": 0, "slot": slot, "goal": "减压"}


# ---------------------------------------------------------------
# StateTracker：felt 反查与动力学积分
# ---------------------------------------------------------------

class TestFeltLookup:
    def test_hard_anchor_resets_to_tier_midpoint(self):
        t = StateTracker()
        t.observe("今天快没电了，而且压力很大", hard=True)
        assert t.x["energy"] == pytest.approx(0.15)
        assert t.x["stress"] == pytest.approx(0.70)

    def test_synonym_variants_hit(self):
        t = StateTracker()
        t.observe("没什么压力，心情不错，吃得很饱", hard=True)
        assert t.x["stress"] == pytest.approx(0.10)
        assert t.x["valence"] == pytest.approx(0.85)
        assert t.x["satiety"] == pytest.approx(0.85)

    def test_soft_observe_blends(self):
        t = StateTracker()
        t.x["stress"] = 0.80
        t.observe("没什么压力", hard=False)
        assert t.x["stress"] == pytest.approx(0.45)  # 0.5×0.80 + 0.5×0.10

    def test_no_phrase_keeps_estimate(self):
        t = StateTracker()
        before = dict(t.x)
        t.observe("今天天气怎么样", hard=True)
        assert t.x == before

    def test_lookup_can_be_disabled(self):
        t = StateTracker(use_felt_lookup=False)
        t.observe("快崩溃了", hard=True)
        assert t.x["stress"] == pytest.approx(0.28)  # 先验不变


class TestDynamics:
    def test_workday_morning_raises_stress(self):
        t = StateTracker()
        before = t.x["stress"]
        t._settle_slot(day=1, slot=0, balance=500.0)  # 周一工作日
        assert t.x["stress"] > before

    def test_weekend_afternoon_lifts_valence(self):
        t = StateTracker()
        t.x["valence"] = 0.50
        t.x["stress"] = 0.32  # v_eq 里压力项归零，隔离自然项
        before = t.x["valence"]
        t._settle_slot(day=6, slot=1, balance=500.0)  # 周六下午 +0.03
        assert t.x["valence"] > before

    def test_rebound_doubles_work_stress(self):
        t = StateTracker()
        t.x["stress"] = 0.10  # 反弹区
        t._settle_slot(day=1, slot=0, balance=500.0)
        # 0.10 + 0.035×2 + 回归(0.32→)×0.03 ≈ 0.1745：显著高于非反弹档
        assert t.x["stress"] == pytest.approx(0.1745, abs=1e-3)

    def test_satiety_meal_pull_bounds_drift(self):
        t = StateTracker()
        t.x["satiety"] = 0.65
        t.advance_to(day=1, slot=3, balance=500.0)  # 推进一整天（含模板三餐）
        assert 0.3 < t.x["satiety"] < 0.9  # 模板餐把饱腹托住，不无限衰减

    def test_sleep_pulls_energy_up(self):
        t = StateTracker()
        t.x["energy"] = 0.30
        t._settle_slot(day=1, slot=3, balance=500.0)  # 深夜正常睡眠
        assert t.x["energy"] > 0.40

    def test_high_stress_drags_valence(self):
        t = StateTracker()
        t.x.update({"valence": 0.75, "stress": 0.90, "energy": 0.70, "satiety": 0.65})
        t._settle_slot(day=6, slot=3, balance=500.0)  # 无工作项，纯耦合
        assert t.x["valence"] < 0.75

    def test_own_event_dose_applies_on_its_slot(self):
        t = StateTracker()
        t.x["stress"] = 0.60
        t.register_event("江边步道散步", day=0, slot=2)
        # 新时点语义：advance_to(d,s) 积分到"进入 (d,s)"——slot 2 在 advance 到 slot 3 时结算
        t.advance_to(day=0, slot=3, balance=500.0)
        # 散步 stress−0.08 应明显生效（另有工作/休息自然项与回归）
        assert t.x["stress"] < 0.56
        assert t.pending == []  # 已结算

    def test_overdue_event_dose_applies_immediately(self):
        """同槽下单：结果回到 tracker 时积分已越过事件槽位，剂量立即补记而非丢失。"""
        t = StateTracker()
        t.x["stress"] = 0.60
        t.advance_to(day=0, slot=2, balance=500.0)  # 指针 = 进入 slot 2（slot 0/1 已结算）
        before = t.x["stress"]
        t.register_event("江边步道散步", day=0, slot=1)  # slot 1 已越过
        assert t.pending == []  # 不入队
        assert t.x["stress"] == pytest.approx(before - 0.08, abs=1e-6)  # 剂量立即生效

    def test_advance_backwards_is_noop(self):
        t = StateTracker()
        t.advance_to(day=2, slot=1, balance=500.0)
        x = dict(t.x)
        t.advance_to(day=1, slot=0, balance=500.0)  # 时钟回拨不倒积
        assert t.x == x and (t.day, t.slot) == (1, 0)

    def test_snapshot_restore_roundtrip(self):
        t = StateTracker()
        t.observe("压力很大", hard=True)
        t.register_event("散步", day=1, slot=2)
        t.apply_disturbances("刷题（上午）；网课（晚上）", day=1)
        t.advance_to(day=1, slot=1, balance=500.0)
        t2 = StateTracker()
        t2.restore(t.snapshot())
        assert t2.x == t.x and (t2.day, t2.slot) == (t.day, t.slot)
        assert t2.pending == t.pending


class TestV52Tracker:
    def test_register_event_prefers_payload_effect(self):
        t = StateTracker()
        t.x.update({"energy": 0.40, "stress": 0.50})
        # payload 真实 effect 优先于关键词剂量表（"好好休息"猜表是 +0.20/−0.05）
        t.register_event("好好休息 · 某民宿", day=0, slot=3,
                         effect={"energy": 0.23, "stress": -0.01})
        # 新时点语义：slot 3 在 advance 到次日 slot 0 时才结算
        t.advance_to(day=1, slot=0, balance=500.0)
        # 睡眠 pull 也会生效，但 stress 应 ≈ 0.50−0.01−0.05(睡)+漂移+回归，而非 −0.05 猜表
        assert t.pending == []  # 已结算
        t2 = StateTracker()
        t2.x["stress"] = 0.50
        t2.register_event("好好休息", day=0, slot=3)  # 无 payload → 猜表 −0.05
        t2.advance_to(day=1, slot=0, balance=500.0)
        assert t.x["stress"] > t2.x["stress"]  # 真实剂量(−0.01) < 猜表剂量(−0.05)

    def test_series_hint_modelled_once_per_day(self):
        t = StateTracker()
        t.x["stress"] = 0.50
        t.apply_disturbances("刷题（上午）；网课（晚上）", day=1)
        assert t.x["stress"] == pytest.approx(0.50 + 0.06 + 0.02, abs=1e-6)
        t.apply_disturbances("刷题（上午）；网课（晚上）", day=1)  # hint 全天可见
        assert t.x["stress"] == pytest.approx(0.58, abs=1e-6)  # 不重复结算

    def test_series_hint_suppresses_work_drift(self):
        t = StateTracker()
        t.apply_disturbances("刷题（上午）", day=1)  # day1 = 周二工作日
        e0 = t.x["energy"]
        t._settle_slot(day=1, slot=0, balance=500.0)
        assert t.x["energy"] == pytest.approx(e0 - 0.03, abs=1e-6)  # 按周末 −0.03
        # 而非工作日 −0.04 且不加工作压力

    def test_normal_workday_drift_unchanged(self):
        t = StateTracker()
        e0 = t.x["energy"]
        t._settle_slot(day=1, slot=0, balance=500.0)
        assert t.x["energy"] == pytest.approx(e0 - 0.04, abs=1e-6)  # 无 hint 仍工作日

    def test_final_exam_release_modelled(self):
        t = StateTracker()
        t.x["stress"] = 0.60
        t.apply_disturbances("大考结束（晚上）", day=10)
        assert t.x["stress"] == pytest.approx(0.25, abs=1e-6)  # −0.35 巨量释放


class TestV56dTracker:
    """v5.6d：felt 全量同步、hint 段匹配、系列日模板切换。"""

    def test_felt_paraphrase_extreme_stress(self):
        t = StateTracker()
        t.observe("快被压垮了，感觉喘不上气", hard=True)
        assert t.x["stress"] == 0.90  # 用户 LLM 改写也能锚定极端档

    def test_felt_youdianyali_is_tier030(self):
        t = StateTracker()
        t.observe("有点压力但还行", hard=True)
        assert t.x["stress"] == 0.30  # felt.py tier1 [0.2,0.4)，不是 0.50 档

    def test_composite_recovery_event_not_double_counted(self):
        t = StateTracker()
        v0 = t.x["valence"]
        t.apply_disturbances("文化看展 · 市美术馆（下午）", day=1)
        assert t.x["valence"] == v0  # 复合名跳过，剂量归 register_event
        assert 1 not in t._series_days

    def test_business_entertainment_single_count(self):
        t = StateTracker()
        s0 = t.x["stress"]
        t.apply_disturbances("商务应酬（晚上）", day=1)
        # 系列版 +0.10；不得再叠扰动"应酬"的 +0.10
        assert t.x["stress"] == pytest.approx(s0 + 0.10, abs=1e-6)

    def test_business_trip_does_not_suppress_work(self):
        t = StateTracker()
        t.apply_disturbances("酒店餐（早上）；异地工作（上午）；客户会议（下午）", day=1)
        assert t._series_days[1] == "business"
        assert 1 not in t._suppress_work_days  # 出差收入与工作 drift 照发
        e0 = t.x["energy"]
        t._settle_slot(day=1, slot=0, balance=500.0)
        assert t.x["energy"] == pytest.approx(e0 - 0.04, abs=1e-6)

    def test_crunch_sleep_template_switches(self):
        t = StateTracker()
        t.apply_disturbances("备考三餐（早上）；刷题（上午）", day=1)
        assert t._series_days[1] == "crunch"
        t.x["energy"] = 0.50
        t.x["stress"] = 0.50
        t._settle_slot(day=1, slot=3, balance=500.0)
        assert t.x["energy"] == pytest.approx(0.50 + (0.78 - 0.50) * 0.50, abs=1e-6)
        # stress：回归 0.50+(0.32−0.50)*0.03=0.4946，系列睡眠 −0.01（而非 S1 −0.05）
        assert t.x["stress"] == pytest.approx(0.4946 - 0.01, abs=1e-4)

    def test_snapshot_carries_series_days(self):
        t = StateTracker()
        t.apply_disturbances("刷题（上午）", day=3)
        t2 = StateTracker()
        t2.restore(t.snapshot())
        assert t2._series_days == {3: "crunch"}
        assert 3 in t2._suppress_work_days


# ---------------------------------------------------------------
# BookingMemory：占用、冲突重试、对账
# ---------------------------------------------------------------

class TestBookingMemory:
    _add = staticmethod(_add)

    def test_stage_blocks_double_booking(self):
        b = BookingMemory()
        assert b.stage(self._add(), today=0) is not None
        assert b.stage(self._add("另一个", slot=2), today=0) is None  # 同槽被占

    def test_pick_slot_skips_occupied_and_hint(self):
        b = BookingMemory()
        b.stage(self._add(slot=2), today=0)
        assert b.pick_slot(0, taken_today={1}) == (0, 0)  # 顺序 2→1→0→3，2 占 1 被 hint 占
        assert b.pick_slot(0, taken_today={0, 1, 3}) == (1, 2)  # 今天全满 → 明天晚上

    def test_hint_slots_parsing(self):
        b = BookingMemory()
        assert b.hint_slots("临时加班（上午）；散步（晚上）", SLOT_NAMES) == {0, 2}

    def test_conflict_failure_enqueues_retry_elsewhere(self):
        b = BookingMemory()
        staged = b.stage(self._add(slot=2), today=0)
        b.commit_calls([staged], today=0)
        ok, failed = b.reconcile(
            [ToolResult(name="add_event_todo", ok=False,
                        payload={"error": "与已有恢复事件 R0003 冲突"})], today=0)
        assert ok == [] and len(failed) == 1
        assert len(b.retry_queue) == 1
        retry = b.retry_queue[0]
        assert (retry["day"], retry["slot"]) != (0, 2)  # 换了槽位
        # 弹出为相对 day_offset，且槽位已被预留
        calls = b.pop_retries(today=0)
        assert calls and calls[0]["day_offset"] == retry["day"] - 0

    def test_failed_booking_rolls_back_occupation(self):
        b = BookingMemory()
        staged = b.stage(self._add(slot=1), today=0)
        b.commit_calls([staged], today=0)
        b.reconcile([ToolResult(name="add_event_todo", ok=False,
                                payload={"error": "余额不足"})], today=0)
        assert not b.occupied(0, 1)  # 非冲突失败也回滚占位
        assert b.retry_queue == []   # 但只有冲突才重试

    def test_success_keeps_occupation(self):
        b = BookingMemory()
        staged = b.stage(self._add(slot=2), today=0)
        b.commit_calls([staged], today=0)
        ok, failed = b.reconcile(
            [ToolResult(name="add_event_todo", ok=True, payload={})], today=0)
        assert len(ok) == 1 and b.occupied(0, 2)

    def test_prune_drops_past_days(self):
        b = BookingMemory()
        b.booked["0:2"] = "旧安排"
        b.prune(today=2)
        assert "0:2" not in b.booked


class TestV52Booking:
    _add = staticmethod(_add)

    def test_success_returns_payload_effect(self):
        b = BookingMemory()
        staged = b.stage({"name": "好好休息", "location": "", "day_offset": 0,
                          "slot": 3, "goal": "充能"}, today=0)
        b.commit_calls([staged], today=0)
        ok, _ = b.reconcile([ToolResult(
            name="add_event_todo", ok=True,
            payload={"event": {"effect": {"energy": 0.23, "stress": -0.01}}})], today=0)
        assert ok[0][3] == {"energy": 0.23, "stress": -0.01}  # 真实 effect 透出

    def test_retry_skips_hint_occupied_slots(self):
        b = BookingMemory()
        staged = b.stage(self._add(slot=2), today=0)
        b.commit_calls([staged], today=0)
        b.reconcile([ToolResult(name="add_event_todo", ok=False,
                                payload={"error": "与已有恢复事件冲突"})],
                    today=0, taken_today={0, 1, 3})  # hint 占满其余槽
        assert (b.retry_queue[0]["day"], b.retry_queue[0]["slot"]) == (1, 2)
        # 今天全被占 → 换到明天晚上，而不是撞 hint 占用槽

    def test_retry_dedup_same_name(self):
        b = BookingMemory()
        for i in range(2):  # 同一单两轮各冲突失败一次
            staged = b.stage(self._add(slot=2), today=i)
            if staged is None:  # 第二轮原槽可能仍被预留占用，换个入口
                staged = {"name": "江边步道散步", "location": "江边",
                          "day_offset": 0, "slot": 2, "goal": "减压"}
            b.commit_calls([staged], today=i)
            b.reconcile([ToolResult(name="add_event_todo", ok=False,
                                    payload={"error": "冲突"})], today=i)
        assert len(b.retry_queue) == 1  # 同名不重复挂起

    def test_span_event_occupies_all_covered_slots(self):
        b = BookingMemory()
        staged = b.stage({"name": "短途旅行 · 海边小镇", "location": "海边小镇",
                          "day_offset": 1, "slot": 0, "goal": "回血"}, today=9)
        b.commit_calls([staged], today=9)
        ok, _ = b.reconcile([ToolResult(name="add_event_todo", ok=True, payload={
            "event": {"start_slot": 40, "span_slots": 3,  # day10 slot0 起占 3 槽
                      "effect": {"valence": 0.2, "stress": -0.18}}})], today=9)
        assert ok[0][4] == 3  # span 透出给 tracker 摊销
        for s in (0, 1, 2):
            assert b.occupied(10, s), f"span 覆盖槽 10:{s} 未登记"
        assert not b.occupied(10, 3)

    def test_retry_attempts_capped(self):
        b = BookingMemory()
        for i in range(4):  # 反复冲突失败：第 3 次起不再挂起
            staged = b.stage(self._add(name=f"动作{i}", slot=2), today=i) \
                or {"name": f"动作{i}", "location": "", "day_offset": 0, "slot": 2,
                    "goal": "", "attempts": i}
            b.commit_calls([staged], today=i)
            b.reconcile([ToolResult(name="add_event_todo", ok=False,
                                    payload={"error": "与已有恢复事件冲突"})], today=i)
        attempts = [r["attempts"] for r in b.retry_queue]
        assert all(a <= 2 for a in attempts)  # 重试上限 2


class TestBudgetGate:
    def test_big_spend_needs_bigger_buffer(self):
        from agents.assistant.reference.harness import _affordable
        args = {"name": "短途旅行", "location": "海边小镇"}
        costs = {"短途旅行@海边小镇": 600.0}
        assert not _affordable(args, 1000.0, costs)   # 1000−600=400 < 600 拦下
        assert _affordable(args, 1300.0, costs)       # 1300−600=700 ≥ 600 放行
        small = {"name": "按摩", "location": "楼下"}
        costs2 = {"按摩@楼下": 120.0}
        assert _affordable(small, 300.0, costs2)      # 小单仍按 150 垫
        assert not _affordable(small, 200.0, costs2)

    def test_negative_balance_blocks_everything(self):
        from agents.assistant.reference.harness import _affordable
        assert not _affordable({"name": "散步"}, -50.0, {})          # 目录外也拦
        assert not _affordable({"name": "散步"}, -50.0, {"散步": 0.0})  # 免费也拦


# ---------------------------------------------------------------
# ReferenceHarness v5 集成（罐头 client）
# ---------------------------------------------------------------

class _CannedClient:
    def __init__(self, payload: dict | None = None) -> None:
        self.prompts: list[str] = []
        self.payload = payload or {
            "reply": "给你安排了散步。",
            "user_belief": {"valence": 0.6, "energy": 0.5, "satiety": 0.4,
                            "stress": 0.5, "persona_notes": ""},
            "tool_calls": [],
        }

    def chat_json(self, messages, max_tokens=None) -> dict:
        self.prompts.append("".join(m.get("content", "") for m in messages))
        return self.payload

    def set_log_dir(self, run_dir) -> None:
        pass


class _BrokenClient:
    def chat_json(self, messages, max_tokens=None) -> dict:
        return {"完全": "不合法"}

    def set_log_dir(self, run_dir) -> None:
        pass


def _obs(text="有点累", day=0, slot=2, hint="", history=None, results=None,
         catalog=None, balance=500.0) -> HarnessObs:
    return HarnessObs(
        user_say=text,
        history=history if history is not None else [],
        tool_results=results or [],
        balance=balance,
        schedule_hint=hint,
        recovery_catalog=catalog if catalog is not None else [
            {"action": "江边步道散步", "vid": "V002", "location": "江边",
             "cost": 0, "span": 1, "category": "户外", "cuisine": ""},
            {"action": "川渝老火锅", "vid": "V001", "location": "巷子里",
             "cost": 120, "span": 1, "category": "饮食", "cuisine": "火锅"},
        ],
        slot_names=SLOT_NAMES, day=day, slot=slot,
    )


class TestHarnessV5:
    def test_belief_numbers_come_from_tracker_not_llm(self):
        h = ReferenceHarness(_CannedClient())
        turn = h.on_turn(_obs("压力很大，快没电了"))
        # 罐头 LLM 报 0.6/0.5/0.4/0.5；tracker 锚定后应显著不同
        assert turn.user_belief.stress != 0.5
        assert turn.user_belief.stress >= 0.60  # "压力很大" → 0.70 锚定（积分后仍高）
        assert turn.user_belief.energy <= 0.30  # "快没电了" → 0.15 锚定

    def test_state_block_in_prompt(self):
        client = _CannedClient()
        ReferenceHarness(client).on_turn(_obs("压力很大"))
        assert "状态跟踪" in client.prompts[-1]
        assert "压力" in client.prompts[-1]

    def test_broken_llm_still_returns_valid_turn(self):
        h = ReferenceHarness(_BrokenClient())
        turn = h.on_turn(_obs())  # 两轮都坏 → 兜底合成，不抛出
        assert turn.reply and 0 <= turn.user_belief.stress <= 1

    def test_disturbance_triggers_auto_relief_booking(self):
        h = ReferenceHarness(_CannedClient())  # 罐头不安排任何工具
        turn = h.on_turn(_obs("压力很大", hint="临时加班（上午）"))
        adds = [tc for tc in turn.tool_calls if tc.name == "add_event_todo"]
        assert adds, "扰动当轮必须保底落一单"
        assert adds[0].args["name"] == "江边步道散步"  # 免费减压优先

    def test_no_auto_booking_when_calm(self):
        h = ReferenceHarness(_CannedClient())
        turn = h.on_turn(_obs("没什么压力，心情不错", hint="临时加班（上午）"))
        assert not [tc for tc in turn.tool_calls if tc.name == "add_event_todo"]

    def test_double_booking_filtered(self):
        payload = {
            "reply": "好", "user_belief": {"valence": 0.6, "energy": 0.5,
                                          "satiety": 0.4, "stress": 0.5},
            "tool_calls": [
                {"name": "add_event_todo", "args": {"name": "散步", "slot": 2}},
                {"name": "add_event_todo", "args": {"name": "按摩", "slot": 2}},
            ],
        }
        h = ReferenceHarness(_CannedClient(payload))
        # 高压场景（"压力很大" 锚定 0.70）：减压单过前向仿真门控，同槽第二单被拦
        turn = h.on_turn(_obs("压力很大"))
        adds = [tc for tc in turn.tool_calls if tc.name == "add_event_todo"]
        assert len(adds) == 1  # 同槽第二单被拦

    def test_conflict_retry_next_turn(self):
        payload = {
            "reply": "好", "user_belief": {"valence": 0.6, "energy": 0.5,
                                          "satiety": 0.4, "stress": 0.5},
            "tool_calls": [{"name": "add_event_todo", "args": {"name": "散步", "slot": 2}}],
        }
        h = ReferenceHarness(_CannedClient(payload))
        from usersim.contracts import DialogueTurn
        # 高压场景（锚定 0.70）：减压单过前向仿真门控，冲突失败后下轮换槽重发
        h.on_turn(_obs("压力很大", history=[DialogueTurn(speaker="user", text="压力很大")]))
        turn = h.on_turn(_obs(
            history=[DialogueTurn(speaker="user", text="累"),
                     DialogueTurn(speaker="assistant", text="好"),
                     DialogueTurn(speaker="user", text="嗯")],
            results=[ToolResult(name="add_event_todo", ok=False,
                                payload={"error": "与已有恢复事件 R0001（散步）冲突"})],
        ))
        adds = [tc for tc in turn.tool_calls if tc.name == "add_event_todo"]
        assert adds and adds[0].args["slot"] != 2  # 自动换槽重发


class TestV52ControlLaw:
    """多变量带中心控制律：能量崩盘出充能单、压力地板下禁减压。"""

    _CATALOG = [
        {"action": "江边步道散步", "vid": "V002", "location": "江边",
         "cost": 0, "span": 1, "category": "户外", "cuisine": ""},
        {"action": "好好休息", "vid": "V010", "location": "家",
         "cost": 0, "span": 1, "category": "休息", "cuisine": ""},
    ]

    def _two_turns(self, h, energy, stress):
        from usersim.contracts import DialogueTurn
        h.on_turn(_obs("还行", day=0, slot=0, catalog=self._CATALOG))
        h.tracker.x.update({"energy": energy, "stress": stress})
        return h.on_turn(_obs("还行", day=0, slot=1, catalog=self._CATALOG,
                              history=[DialogueTurn(speaker="user", text="还行"),
                                       DialogueTurn(speaker="assistant", text="好"),
                                       DialogueTurn(speaker="user", text="嗯")]))

    def test_energy_crash_triggers_charge_booking(self):
        h = ReferenceHarness(_CannedClient())
        turn = self._two_turns(h, energy=0.20, stress=0.30)
        # energy 0.20 → 醒后预估 0.62 < 0.64 → 充能单（非减压单）
        adds = [tc for tc in turn.tool_calls if tc.name == "add_event_todo"]
        assert adds and adds[0].args["name"] == "好好休息"

    def test_energy_mild_dip_no_booking(self):
        h = ReferenceHarness(_CannedClient())
        # energy 0.63 → 醒后 ≈0.75 回带内：睡眠是自然恢复槽，不浪费干预
        turn = self._two_turns(h, energy=0.63, stress=0.28)
        assert not [tc for tc in turn.tool_calls if tc.name == "add_event_todo"]

    def test_stress_floor_blocks_relief_but_not_charge(self):
        h = ReferenceHarness(_CannedClient())
        # 压力 0.18 地板下 + 能量崩盘（0.20 → 醒后 0.62 < 0.64）：应出充能单而绝非减压单
        turn = self._two_turns(h, energy=0.20, stress=0.18)
        adds = [tc for tc in turn.tool_calls if tc.name == "add_event_todo"]
        assert adds and adds[0].args["name"] == "好好休息"

    def test_llm_stress_order_vetoed_below_floor(self):
        """v5.5：压力地板对 LLM 新单强制 veto（prompt 劝阻拦不住，管线强制执行）。"""
        payload = {
            "reply": "好", "user_belief": {"valence": 0.6, "energy": 0.5,
                                          "satiety": 0.4, "stress": 0.5},
            "tool_calls": [{"name": "add_event_todo",
                            "args": {"name": "江边步道散步", "location": "江边",
                                     "slot": 2, "goal": "减压"}}],
        }
        h = ReferenceHarness(_CannedClient(payload))
        turn1 = h.on_turn(_obs("压力很大", day=0, slot=0, catalog=self._CATALOG))  # 锚定 0.70 高压
        assert [tc for tc in turn1.tool_calls if tc.name == "add_event_todo"]  # 高压时放行
        # 压力压到地板下 + 能量充足：同一张减压单必须被拦截，且不应改派任何单
        h.tracker.x.update({"stress": 0.18, "energy": 0.70})
        turn2 = h.on_turn(_obs("嗯", day=0, slot=1, catalog=self._CATALOG))
        assert not [tc for tc in turn2.tool_calls if tc.name == "add_event_todo"]

    def test_llm_stress_order_vetoed_falls_back_to_charge(self):
        """减压单被 veto 后，能量缺口为正时主动维护改派充能单（而不是不出单）。"""
        payload = {
            "reply": "好", "user_belief": {"valence": 0.6, "energy": 0.5,
                                          "satiety": 0.4, "stress": 0.5},
            "tool_calls": [{"name": "add_event_todo",
                            "args": {"name": "江边步道散步", "location": "江边",
                                     "slot": 2, "goal": "减压"}}],
        }
        h = ReferenceHarness(_CannedClient(payload))
        h.on_turn(_obs("压力大", day=0, slot=0, catalog=self._CATALOG))
        h.tracker.x.update({"stress": 0.18, "energy": 0.20})  # 醒后 0.62 < 0.64
        turn = h.on_turn(_obs("嗯", day=0, slot=1, catalog=self._CATALOG))
        adds = [tc for tc in turn.tool_calls if tc.name == "add_event_todo"]
        assert adds and adds[0].args["name"] == "好好休息"

    def test_llm_food_order_vetoed_below_floor(self):
        """v5.6e：减压 veto 改效果判定——"吃好吃的"名称不含减压关键词但目录效果
        stress<0，地板下必须拦截（v56d 门控 3/5 overshoot 败的根因）。"""
        payload = {
            "reply": "好", "user_belief": {"valence": 0.6, "energy": 0.5,
                                          "satiety": 0.4, "stress": 0.5},
            "tool_calls": [{"name": "add_event_todo",
                            "args": {"name": "吃好吃的", "location": "咖啡甜品店（街角落地窗）",
                                     "slot": 2, "goal": "犒劳自己"}}],
        }
        h = ReferenceHarness(_CannedClient(payload))
        h.tracker.x.update({"stress": 0.18, "energy": 0.70})  # 地板下、能量充足
        turn = h.on_turn(_obs("嗯", day=0, slot=1, catalog=self._CATALOG))
        # 槽位空闲，唯一拦截理由只能是 veto
        assert not [tc for tc in turn.tool_calls if tc.name == "add_event_todo"]

    def test_llm_study_order_not_vetoed_below_floor(self):
        """学习充电（规范类目 C5 效果 stress+0.02，非减压单）在压力地板下不拦截。
        （注意：带场所的"学习充电 · 独立书店"按场所变体 stress−0.04 算减压单——
        与世界的数值裁决一致，此处测的是无场所命中规范类目的路径。）"""
        payload = {
            "reply": "好", "user_belief": {"valence": 0.6, "energy": 0.5,
                                          "satiety": 0.4, "stress": 0.5},
            "tool_calls": [{"name": "add_event_todo",
                            "args": {"name": "学习充电", "slot": 2, "goal": "充电"}}],
        }
        h = ReferenceHarness(_CannedClient(payload))
        h.tracker.x.update({"stress": 0.18, "energy": 0.70})
        turn = h.on_turn(_obs("嗯", day=0, slot=1, catalog=self._CATALOG))
        assert [tc for tc in turn.tool_calls if tc.name == "add_event_todo"]

    def test_prompt_states_band_center(self):
        client = _CannedClient()
        ReferenceHarness(client).on_turn(_obs("压力很大", catalog=self._CATALOG))
        assert "目标带中心" in client.prompts[-1]

    def test_backfill_after_day5(self):
        h = ReferenceHarness(_CannedClient())
        h.on_turn(_obs(day=0))
        early = h.persona_belief()
        assert len(early.facets) < 30  # 前期不回填
        h.on_turn(_obs(day=6))
        late = h.persona_belief()
        assert set(late.facets) == set(FACET_KEYS)
        assert set(late.categories) == set(PREF_CATEGORIES)

    def test_snapshot_restore_roundtrip(self):
        h = ReferenceHarness(_CannedClient())
        h.on_turn(_obs("压力很大", hint="临时加班（上午）"))
        h2 = ReferenceHarness(_CannedClient())
        h2.restore(h.snapshot())
        assert h2.recent_arrangements == h.recent_arrangements
        assert h2.tracker.x == h.tracker.x
        assert h2.booking.booked == h.booking.booked


# ---------------------------------------------------------------
# reference_nomem 消融件
# ---------------------------------------------------------------

class TestNoMem:
    def test_registry_dispatch(self):
        from usersim.agents.registry import create, available
        h = create("reference_nomem", None)
        assert isinstance(h, NoMemHarness)
        assert "reference_nomem" in {i["name"] for i in available()}

    def test_memory_wiped_at_session_boundary(self):
        class _SeqClient:
            def __init__(self):
                self.payloads = [
                    {"reply": "好",
                     "user_belief": {"valence": 0.6, "energy": 0.5, "satiety": 0.4,
                                     "stress": 0.5, "persona_notes": "喜欢爵士乐",
                                     "persona_belief": {"loves": ["爵士乐"],
                                                        "facets": {"神经质.焦虑": 70}}},
                     "tool_calls": [{"name": "add_event_todo", "args": {"name": "散步", "slot": 2}}]},
                    {"reply": "嗯",
                     "user_belief": {"valence": 0.5, "energy": 0.5, "satiety": 0.5,
                                     "stress": 0.5, "persona_notes": ""},
                     "tool_calls": []},
                ]

            def chat_json(self, messages, max_tokens=None):
                return self.payloads.pop(0) if self.payloads else self.payloads

            def set_log_dir(self, run_dir):
                pass

        from usersim.contracts import DialogueTurn
        h = NoMemHarness(_SeqClient())
        # 高压开场（锚定 0.70）让罐头减压单过前向仿真门控，session 内正常落单
        h.on_turn(_obs("压力很大，我很喜欢爵士乐"))  # session 1 首轮
        assert h.recent_arrangements  # session 内正常工作
        assert h.profile.facets       # session 内画像增量已合并
        assert h.persona_belief() is None  # 消融：从不形成跨 session 画像
        # session 2 首轮（history 只剩新的一句）→ 记忆应被清空
        h.on_turn(_obs("压力大", history=[DialogueTurn(speaker="user", text="压力大")]))
        assert h.recent_arrangements == []  # 本轮无新单 → 旧记录确已清空
        assert h.profile.facets == {}
        assert h.booking.booked == {}

    def test_persona_delta_stripped_from_turn(self):
        client = _CannedClient({
            "reply": "好",
            "user_belief": {"valence": 0.6, "energy": 0.5, "satiety": 0.4, "stress": 0.5,
                            "persona_belief": {"loves": ["爵士乐"]}},
            "tool_calls": [],
        })
        turn = NoMemHarness(client).on_turn(_obs())
        assert turn.user_belief.persona_belief is None  # 阻断 Runner 侧 EMA 兜底
