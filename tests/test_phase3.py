"""阶段 3 测试：PRA 信号源迁移（裁决事件为主）、rec_rejected 推荐接受度、
reference harness 的 catalog 消费与近期安排去重。"""

from __future__ import annotations

from agents.assistant.reference.harness import ReferenceHarness
from usersim.contracts import HarnessObs, StateVec, ToolCall, ToolResult, TurnRecord
from usersim.evaluator.consistency import compute_pra
from usersim.evaluator.insights import compute_insights

PERSONA = {"prefs": {"categories": {"饮食": 0.6, "社交": -0.8, "户外": -0.7, "文化": 0.5}}}
TARGETS = {"valence": 0.72, "energy": 0.70, "satiety": 0.65, "stress": 0.30}


def _user_turn(turn_id: int, text: str, session_id: str = "S001") -> TurnRecord:
    return TurnRecord(
        run_id="test", t_logical=0, session_id=session_id, turn_id=turn_id,
        speaker="user", text=text,
        x_true=StateVec(valence=0.6, energy=0.5, satiety=0.5, stress=0.4),
    )


def _asst_event_turn(turn_id: int, event_name: str, session_id: str = "S001") -> TurnRecord:
    return TurnRecord(
        run_id="test", t_logical=0, session_id=session_id, turn_id=turn_id,
        speaker="assistant", text="给你安排好了",
        x_true=StateVec(valence=0.6, energy=0.5, satiety=0.5, stress=0.4),
        tool_calls=[ToolCall(name="add_event_todo", args={"name": event_name})],
        tool_results=[ToolResult(name="add_event_todo", ok=True,
                                 payload={"event": {"name": event_name, "cost": 100}})],
    )


# ---------------------------------------------------------------
# PRA v2：裁决事件为主信号，用户文本降级为辅助
# ---------------------------------------------------------------

class TestPRAAdjudicatedSignal:
    def test_scheduled_hated_category_is_misaligned(self):
        """用户只说感受（无类目词），但落地了讨厌类目的安排 → misaligned。"""
        turns = [
            _user_turn(1, "有点累，想放松一下"),
            _asst_event_turn(2, "朋友小聚 · 居酒屋"),  # 社交 = -0.8
        ]
        metrics, _ = compute_pra(turns, PERSONA)
        assert metrics["pra_misaligned_requests"] == 1
        assert metrics["pra_total_requests"] == 1

    def test_loved_never_scheduled(self):
        """热爱类目全程未被安排 → loved_never_requested（键名保留，语义已迁移）。"""
        turns = [
            _user_turn(1, "想见人"),
            _asst_event_turn(2, "朋友小聚 · 居酒屋"),  # 只安排了社交
        ]
        metrics, _ = compute_pra(turns, PERSONA)
        assert "饮食" in metrics["pra_loved_never_requested"]
        assert "文化" in metrics["pra_loved_never_requested"]

    def test_text_is_fallback_only(self):
        """有裁决事件的 session 不再从用户文本重复计数。"""
        turns = [
            _user_turn(1, "想吃火锅"),                      # 文本含类目词（饮食）
            _asst_event_turn(2, "朋友小聚 · 居酒屋"),        # 但落地的是社交
        ]
        metrics, _ = compute_pra(turns, PERSONA)
        # 只计裁决事件：社交 1 次（misaligned），饮食不计
        assert metrics["pra_total_requests"] == 1
        assert metrics["pra_misaligned_requests"] == 1

    def test_no_events_text_fallback(self):
        """无任何裁决事件时，用户首条文本仍是辅助信号。"""
        turns = [_user_turn(1, "想出去爬山徒步")]  # 户外 = -0.7
        metrics, _ = compute_pra(turns, PERSONA)
        assert metrics["pra_misaligned_requests"] == 1


# ---------------------------------------------------------------
# rec_rejected：推荐接受度 insight
# ---------------------------------------------------------------

class TestRecRejected:
    def _turns(self):
        turns = []
        for i, (sid, reply) in enumerate([
            ("S001", "不要，我最讨厌这个了"),   # 明确抗拒
            ("S002", "算了，别安排了"),          # 明确抗拒
            ("S003", "好呀，正合我意"),          # 接受
        ]):
            turns.append(_user_turn(1, "有点累", session_id=sid))
            turns.append(_asst_event_turn(2, "朋友小聚 · 居酒屋", session_id=sid))
            turns.append(_user_turn(3, reply, session_id=sid))
        return turns

    def test_ratio_and_finding(self):
        out = compute_insights([], self._turns(), {"persona": PERSONA}, TARGETS, 0.1)
        rec = out["stats"]["rec_rejected"]
        assert rec == {"scheduled": 3, "rejected": 2, "ratio": round(2 / 3, 3)}
        assert any("推荐被明确拒绝" in f["title"] for f in out["findings"])

    def test_no_warning_when_few_rejections(self):
        turns = [
            _user_turn(1, "有点累"),
            _asst_event_turn(2, "朋友小聚 · 居酒屋"),
            _user_turn(3, "好呀"),
        ]
        out = compute_insights([], turns, {"persona": PERSONA}, TARGETS, 0.1)
        assert out["stats"]["rec_rejected"]["ratio"] == 0.0
        assert not any("推荐被明确拒绝" in f["title"] for f in out["findings"])


# ---------------------------------------------------------------
# reference harness：catalog 渲染与近期安排去重
# ---------------------------------------------------------------

class _CannedClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def chat_json(self, messages, max_tokens=None) -> dict:
        self.prompts.append("".join(m.get("content", "") for m in messages))
        return {
            "reply": "给你安排了巷子里那家火锅。",
            "user_belief": {"valence": 0.6, "energy": 0.5, "satiety": 0.4,
                            "stress": 0.5, "persona_notes": "可能喜欢火锅"},
            "tool_calls": [{"name": "add_event_todo",
                            "args": {"name": "川渝老火锅（巷子里店）", "slot": 2}}],
        }

    def set_log_dir(self, run_dir) -> None:
        pass


def _obs(catalog=None) -> HarnessObs:
    return HarnessObs(
        user_say="想吃火锅", history=[], tool_results=[], balance=500.0,
        schedule_hint="", recovery_catalog=catalog if catalog is not None else [
            {"action": "川渝老火锅（巷子里店）", "vid": "V001", "location": "巷子里的火锅店",
             "cost": 120, "span": 1, "category": "饮食", "cuisine": "火锅"},
        ],
        slot_names=["上午", "下午", "晚上", "深夜"], day=0, slot=2,
    )


class TestReferenceHarnessCatalog:
    def test_catalog_rendered_with_category(self):
        client = _CannedClient()
        ReferenceHarness(client).on_turn(_obs())
        assert "[饮食/火锅] 川渝老火锅（巷子里店）" in client.prompts[-1]
        assert "¥120" in client.prompts[-1]

    def test_recent_arrangements_tracked_and_rendered(self):
        client = _CannedClient()
        h = ReferenceHarness(client)
        h.on_turn(_obs())
        assert h.recent_arrangements == ["川渝老火锅（巷子里店）"]
        h.on_turn(_obs())
        assert "【你近期已安排】\n川渝老火锅（巷子里店）" in client.prompts[-1]

    def test_snapshot_restore_roundtrip(self):
        client = _CannedClient()
        h = ReferenceHarness(client)
        h.on_turn(_obs())
        h2 = ReferenceHarness(client)
        h2.restore(h.snapshot())
        assert h2.recent_arrangements == h.recent_arrangements

    def test_empty_catalog_fallback_text(self):
        client = _CannedClient()
        ReferenceHarness(client).on_turn(_obs(catalog=[]))
        assert "目录暂不可用" in client.prompts[-1]
