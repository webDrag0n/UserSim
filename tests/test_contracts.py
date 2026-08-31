"""contracts 契约测试：golden JSON 往返、默认值、校验。"""

import json

import pytest
from pydantic import ValidationError

from usersim.contracts import AssistantTurn, Event, RunMeta, SlotSettlement, StateVec, TurnRecord, UserBelief

GOLDEN_TURN = {
    "run_id": "r1",
    "t_logical": 5,
    "session_id": "S0001",
    "turn_id": 3,
    "speaker": "assistant",
    "text": "已为你安排寿喜烧",
    "tool_calls": [{"name": "add_event_todo", "args": {"name": "吃好吃的"}}],
    "tool_results": [{"name": "add_event_todo", "ok": True, "payload": {}}],
    "x_true": {"valence": 0.4, "energy": 0.25, "satiety": 0.3, "stress": 0.75},
    "x_hat": {"valence": 0.42, "energy": 0.3, "satiety": 0.35, "stress": 0.7},
}


def test_statevec_bounds():
    StateVec(valence=0, energy=1, satiety=0.5, stress=0.3)
    with pytest.raises(ValidationError):
        StateVec(valence=1.5, energy=0, satiety=0, stress=0)


def test_turn_record_golden_roundtrip():
    t = TurnRecord(**GOLDEN_TURN)
    dump = t.model_dump()
    for k, v in GOLDEN_TURN.items():
        assert dump[k] == v
    # 序列化-反序列化往返一致
    assert TurnRecord(**json.loads(t.model_dump_json())) == t


def test_assistant_turn_requires_belief():
    with pytest.raises(ValidationError):
        AssistantTurn(reply="hi")  # type: ignore[call-arg]
    t = AssistantTurn(reply="hi", user_belief=UserBelief(valence=0.5, energy=0.5, satiety=0.5, stress=0.5))
    assert t.user_belief.to_statevec().stress == 0.5


def test_event_defaults_compatible():
    e = Event(id="E1", kind="recovery", name="x", start_slot=0, span_slots=1, location="家", goal="回血")
    assert e.effect == {} and e.progress == 0.0 and e.caused_by_session_id is None


def test_slot_settlement_roundtrip():
    s = SlotSettlement(t_logical=0, x_before=StateVec(valence=0.5, energy=0.5, satiety=0.5, stress=0.5),
                       x_after=StateVec(valence=0.5, energy=0.5, satiety=0.5, stress=0.5))
    assert SlotSettlement(**json.loads(s.model_dump_json())) == s


# ---------------------------------------------------------------
# Agent 接入 wire 协议（contracts.agent_api，docs/15-agent-api.md）
# ---------------------------------------------------------------


def test_agent_envelope_roundtrip():
    from usersim.contracts import AgentRequest, AgentResponse

    req = AgentRequest(request_id="abc123", run_id="r1", role="assistant",
                       type="on_turn", payload={"user_say": "好累"},
                       agent_state={"n": 2})
    assert AgentRequest(**json.loads(req.model_dump_json())) == req

    resp = AgentResponse(request_id="abc123", result={"reply": "休息"},
                         agent_state={"n": 3},
                         persona_hat={"facets": {"神经质.焦虑": 70}, "confidence": 0.4})
    rt = AgentResponse(**json.loads(resp.model_dump_json()))
    assert rt == resp
    assert rt.persona_hat is not None and rt.persona_hat.facets["神经质.焦虑"] == 70

    # 最小响应：只有 request_id（result 空 dict）
    assert AgentResponse(request_id="x").result == {}


def test_plan_slot_payload_golden():
    from usersim.contracts import Intent, PlanSlotRequest, PlanSlotResult

    req = PlanSlotRequest(
        urges={"hunger": 0.7, "social": 0.3, "stimulation": 0.5, "achievement": 0.2},
        stress=0.6, energy=0.4, slot=2, day=3, money=1240.0,
        event_library=[{"name": "寿喜烧", "cost": 200}],
        assist_prompt=None, max_intents=5,
    )
    assert PlanSlotRequest(**json.loads(req.model_dump_json())) == req

    result = PlanSlotResult(intents=[Intent(type="eat", priority=0.7, description="饿了")])
    assert result.intents[0].type == "eat"
    # 空意图合法（本 slot 不求助）
    assert PlanSlotResult().intents == []


def test_user_side_payloads_roundtrip():
    from usersim.contracts import (
        DecideOpenRequest,
        DecideOpenResult,
        Persona,
        SessionClosedNotice,
        SpeakRequest,
        StateVec,
        UserContext,
    )

    persona = Persona(name="测试", archetype="设计师", big5={}, likes="", routine="标准",
                      x0=StateVec(valence=0.5, energy=0.5, satiety=0.5, stress=0.5))
    ctx = UserContext(persona=persona, felt_state="有点累")

    d = DecideOpenRequest(context=ctx, intent={"type": "eat", "description": "饿了"})
    assert DecideOpenRequest(**json.loads(d.model_dump_json())) == d
    assert DecideOpenResult(open=True).open is True

    s = SpeakRequest(context=ctx, history=[{"speaker": "user", "text": "hi"}],
                     intent_description="饿了")
    assert SpeakRequest(**json.loads(s.model_dump_json())) == s

    n = SessionClosedNotice(session_id="S0001", intent_type="eat", turns=3, day=2)
    assert SessionClosedNotice(**json.loads(n.model_dump_json())) == n


# ---------------------------------------------------------------
# 画像增量合并（merge_persona_delta：ProfileTracker 与 Runner 退化路径共用）
# ---------------------------------------------------------------

from usersim.contracts import PersonaBelief, PersonaBeliefDelta, merge_persona_delta


def test_merge_delta_first_evidence():
    m = merge_persona_delta(PersonaBelief(), PersonaBeliefDelta(
        facets={"神经质.焦虑": 80}, categories={"饮食": 0.8},
        loves=["寿喜烧"], confidence=0.5))
    assert m.facets == {"神经质.焦虑": 80}
    assert m.categories == {"饮食": 0.8}
    assert m.loves == ["寿喜烧"] and m.confidence == 0.5


def test_merge_delta_ema_blends_existing():
    base = PersonaBelief(facets={"神经质.焦虑": 60}, categories={"社交": -0.5})
    m = merge_persona_delta(base, PersonaBeliefDelta(
        facets={"神经质.焦虑": 80}, categories={"社交": 0.1}))
    assert m.facets["神经质.焦虑"] == 72        # 60*0.4 + 80*0.6
    assert m.categories["社交"] == pytest.approx(-0.14, abs=1e-3)  # -0.5*0.4 + 0.1*0.6


def test_merge_delta_drops_unknown_keys_and_clamps():
    m = merge_persona_delta(PersonaBelief(), PersonaBeliefDelta(
        facets={"瞎编.特质": 50, "神经质.焦虑": 250},
        categories={"不存在": 1.0, "饮食": 5.0},
        interruption_tolerance=9.0))
    assert m.facets == {"神经质.焦虑": 100}
    assert m.categories == {"饮食": 1.0}
    assert m.interruption_tolerance == 1.0


def test_merge_delta_tags_dedup_new_first_truncated():
    base = PersonaBelief(loves=[f"旧{i}" for i in range(12)])
    m = merge_persona_delta(base, PersonaBeliefDelta(loves=["新宠", "旧3"]))
    assert m.loves[0] == "新宠"
    assert m.loves.count("旧3") == 1
    assert len(m.loves) == 12


def test_merge_delta_absent_fields_keep_base():
    base = PersonaBelief(planning_style="提前规划", notes="老笔记", confidence=0.3)
    m = merge_persona_delta(base, PersonaBeliefDelta(facets={"外向性.群居性": 30}))
    assert m.planning_style == "提前规划" and m.notes == "老笔记" and m.confidence == 0.3
    # base 不被原地修改
    assert base.facets == {}


# ---------------------------------------------------------------
# 阶段 1 新增字段（replaces_meal / satiation_note）：只加不删，
# 旧 JSON 无此字段可反序列化（golden 默认值）
# ---------------------------------------------------------------


def test_event_replaces_meal_default_and_legacy_json():
    e = Event(id="E1", kind="recovery", name="x", start_slot=0, span_slots=1, location="家", goal="回血")
    assert e.replaces_meal is False
    # 旧快照/旧日志（无该字段）可反序列化
    old = {"id": "E2", "kind": "template", "name": "三餐", "start_slot": 0, "span_slots": 3,
           "location": "家", "goal": "补充能量", "effect": {}, "cost": 30}
    assert Event(**old).replaces_meal is False
    e2 = Event(**{**old, "replaces_meal": True})
    assert e2.replaces_meal is True
    assert Event(**json.loads(e2.model_dump_json())) == e2


def test_context_satiation_note_defaults_and_legacy_json():
    from usersim.contracts import EventContext, Persona, UserContext

    ctx = EventContext(t_logical=0, day=0, slot=0, slot_name="上午")
    assert ctx.satiation_note is None
    # 旧 JSON（无该字段）可反序列化
    old = {"t_logical": 1, "day": 0, "slot": 1, "slot_name": "下午"}
    assert EventContext(**old).satiation_note is None

    persona = Persona(name="测试", archetype="设计师", big5={}, likes="", routine="标准",
                      x0=StateVec(valence=0.5, energy=0.5, satiety=0.5, stress=0.5))
    uctx = UserContext(persona=persona, felt_state="有点累")
    assert uctx.satiation_note is None
    uctx2 = UserContext(persona=persona, felt_state="有点累", satiation_note="最近总是火锅，感觉有点腻了")
    assert UserContext(**json.loads(uctx2.model_dump_json())) == uctx2
