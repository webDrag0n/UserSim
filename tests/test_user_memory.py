"""R6 用户记忆去重：session_closed 携带具体活动名 → 记忆注入 prompt（0 token）。

根因：记忆只记意图标签（"找乐子"），LLM 不知道自己刚去过 livehouse → 重复提同一安排。
修复：runner 收集本 session 成功落单的事件名，经 SessionClosedNotice.activities 传给用户记忆。
"""

from __future__ import annotations

from agents.user.standard.agent import DemoUserAgent
from usersim.agents.demo import DemoAssistantAgent
from usersim.config import load_system_config
from usersim.contracts import AssistantTurn, HarnessObs, ToolCall, UserBelief
from usersim.contracts.agent_api import AgentRequest
from usersim.gateway import AgentBroker


class _FakeClient:
    def chat_json(self, messages, max_tokens=None) -> dict:
        return {"open": False, "reason": "x"}

    def set_log_dir(self, run_dir) -> None:
        pass


def test_session_closed_records_activities_in_memory():
    agent = DemoUserAgent(_FakeClient())
    req = AgentRequest(request_id="r1", run_id="run1", role="user", type="session_closed",
                       payload={"session_id": "S1", "intent_type": "stimulate",
                                "turns": 2, "day": 3,
                                "activities": ["livehouse · 地下现场"]},
                       agent_state={})
    resp = agent.handle(req)
    assert resp.result["ack"] is True
    block = agent.memory.prompt_block()
    assert "livehouse · 地下现场" in block, "记忆应显示具体活动名而非只有意图标签"
    assert "找乐子" in block
    # agent_state 存档可回灌
    saved = resp.agent_state["memory"]["sessions"][0]
    assert saved["activities"] == ["livehouse · 地下现场"]


class _TwoTurnUserClient:
    """说两轮就收尾的用户（给助手留出落单回合）。"""

    def __init__(self) -> None:
        self.n = 0

    def chat_json(self, messages, max_tokens=None) -> dict:
        text = str(messages[-1].get("content", ""))
        if '"intents"' in text:
            return {"intents": [{"type": "recover", "mode": "explicit", "want": "想去散步"}]}
        if '"open"' in text:
            return {"open": True, "reason": "想动动"}
        self.n += 1
        return {"say": f"第 {self.n} 轮说话，想去散步", "end_session": self.n >= 2}

    def set_log_dir(self, run_dir) -> None:
        pass


class _BookingHarness:
    """首轮就落单"散步"的助手。"""

    def __init__(self, client=None) -> None:
        self.n = 0

    def on_turn(self, obs: HarnessObs) -> AssistantTurn:
        self.n += 1
        calls = [ToolCall(name="add_event_todo",
                          args={"name": "散步", "day_offset": 0, "slot": 2})] if self.n == 1 else []
        return AssistantTurn(
            reply=f"好，第 {self.n} 次回应",
            user_belief=UserBelief(valence=0.5, energy=0.5, satiety=0.5, stress=0.5),
            tool_calls=calls)

    def snapshot(self) -> dict:
        return {}

    def restore(self, state: dict) -> None:
        pass


def test_booked_activity_reaches_user_memory(tmp_path):
    from usersim.runner import run_live

    broker = AgentBroker()
    user_agent = DemoUserAgent(_TwoTurnUserClient())
    broker.register_local("user", user_agent.handle)
    broker.register_local("assistant", DemoAssistantAgent(_BookingHarness()).handle)
    run_live(seed=11, days=1, cfg=load_system_config(), out_root=tmp_path, run_id="t_mem",
             broker=broker, prompt_versions={"assistant": "t", "user": "t"})

    block = user_agent.memory.prompt_block()
    assert "散步" in block, f"落单的活动应进入用户记忆，实际记忆：{block!r}"
