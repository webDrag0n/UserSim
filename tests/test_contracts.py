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
