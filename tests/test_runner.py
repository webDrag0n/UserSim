"""Runner 编排层测试（live 链路，agent 经 broker 接入，0 token）。

agent 接入解耦后，测试用 `broker.register_local` 注册第一方 demo agent 处理器
（DemoUserAgent + 假 LLM 客户端 / DemoAssistantAgent + 假 Harness）——
与 HTTP 路径同一份请求语义，验证日志落盘、契约违约计入、续跑恢复。
"""

from __future__ import annotations

import json

import pytest

from agents.user.standard.agent import DemoUserAgent
from usersim.agents.demo import DemoAssistantAgent
from usersim.config import load_system_config
from usersim.contracts import AssistantTurn, HarnessObs, UserBelief
from usersim.evaluator.metrics import load_run
from usersim.gateway import AgentBroker


class FakeUserClient:
    """假的用户 LLM：总是开 session，说两轮就收尾。"""

    def __init__(self) -> None:
        self.calls = 0
        self.speak_calls = 0  # plan/decide_open 也消耗 LLM 调用——收尾只看 speak 轮数

    def chat_json(self, messages, max_tokens=None) -> dict:
        self.calls += 1
        text = str(messages[-1].get("content", ""))
        if '"intents"' in text:
            return {"intents": [{"type": "recover", "mode": "vague", "want": "有点累，想歇会儿"}]}
        if '"open"' in text:
            return {"open": True, "reason": "想聊聊"}
        self.speak_calls += 1
        return {"say": f"我第 {self.speak_calls} 次说话，有点累", "end_session": self.speak_calls % 3 == 0}

    def set_log_dir(self, run_dir) -> None:  # 接口兼容
        pass


class RecordingHarness:
    """记录收到的 HarnessObs，用于断言 Runner 注入的内容。"""

    def __init__(self, client=None) -> None:
        self.seen: list[HarnessObs] = []

    def on_turn(self, obs: HarnessObs) -> AssistantTurn:
        self.seen.append(obs)
        return AssistantTurn(
            reply="我给你安排一下休息。",
            user_belief=UserBelief(valence=0.6, energy=0.4, satiety=0.5, stress=0.5,
                                   persona_notes=f"见过 {len(self.seen)} 轮"),
            tool_calls=[],
        )

    def snapshot(self) -> dict:
        return {"n": len(self.seen)}

    def restore(self, state: dict) -> None:
        self.restored = state


class BrokenHarness:
    """总是抛错的 Harness：验证契约违约被记录而非崩溃整个 run。"""

    def __init__(self, client=None) -> None:
        pass

    def on_turn(self, obs: HarnessObs) -> AssistantTurn:
        raise ValueError("故意的契约错误")

    def snapshot(self) -> dict:
        return {}

    def restore(self, state: dict) -> None:
        pass


@pytest.fixture
def broker():
    return AgentBroker()


def _run(tmp_path, broker, harness, days=3, run_id="t_live", **kw):
    from usersim.runner import run_live

    cfg = load_system_config()
    broker.register_local("user", DemoUserAgent(FakeUserClient()).handle)
    broker.register_local("assistant", DemoAssistantAgent(harness).handle)
    return run_live(seed=11, days=days, cfg=cfg, out_root=tmp_path,
                    run_id=run_id, broker=broker,
                    prompt_versions={"assistant": "test", "user": "test"}, **kw)


def test_live_run_writes_logs_and_meta(tmp_path, broker):
    harness = RecordingHarness()
    run_dir = _run(tmp_path, broker, harness)

    assert (run_dir / "slots.jsonl").exists()
    assert (run_dir / "meta.json").exists()
    slots, turns, meta = load_run(run_dir)
    assert len(slots) == 3 * 4  # days × slots_per_day
    assert all(s.slots_per_day == 4 for s in slots)
    # 可复现性凭证已写入
    assert meta["artifact_hashes"]["combined"]
    assert meta["prompt_versions"] == {"assistant": "test", "user": "test"}
    assert meta["harness"] == "demo:reference"  # 接入方式 + harness 名


def test_harness_receives_injected_context(tmp_path, broker):
    """Runner 必须注入余额/日程/恢复目录——被测件不得自己去碰 world。"""
    harness = RecordingHarness()
    _run(tmp_path, broker, harness)

    assert harness.seen, "Harness 从未被调用（介入点或用户决策链路断了）"
    obs = harness.seen[0]
    assert obs.balance is not None
    assert obs.slot_names and len(obs.slot_names) == 4
    assert isinstance(obs.recovery_catalog, list)
    assert obs.user_say


def test_x_hat_is_recorded_from_harness(tmp_path, broker):
    harness = RecordingHarness()
    run_dir = _run(tmp_path, broker, harness)
    _, turns, _ = load_run(run_dir)
    asst = [t for t in turns if t.speaker == "assistant"]
    assert asst, "没有助手 turn"
    assert all(t.x_hat is not None for t in asst)
    assert all(t.x_true is not None for t in asst)


def test_contract_violation_is_logged_not_fatal(tmp_path, broker):
    run_dir = _run(tmp_path, broker, BrokenHarness(), run_id="t_broken")
    slots, turns, _ = load_run(run_dir)
    assert len(slots) == 3 * 4, "违约不应中断世界推进"
    assert any(t.contract_violation for t in turns), "违约未被记录"


def test_resume_restores_agent_state(tmp_path, broker):
    harness = RecordingHarness()
    run_dir = _run(tmp_path, broker, harness, days=2, run_id="t_resume")
    state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
    assert state["agent_state"]["assistant"] == {"n": len(harness.seen)}
    assert "memory" in state["agent_state"]["user"]

    fresh = RecordingHarness()
    broker.register_local("assistant", DemoAssistantAgent(fresh).handle)
    from usersim.runner import run_live
    cfg = load_system_config()
    run_live(seed=11, days=2, cfg=cfg, out_root=tmp_path, run_id="t_resume",
             broker=broker, resume_dir=run_dir, extra_days=1)
    assert getattr(fresh, "restored", None) is not None, "续跑未从 agent_state 恢复 harness 记忆"
    assert fresh.restored == {"n": len(harness.seen)}

    slots, _, _ = load_run(run_dir)
    assert len(slots) == 3 * 4, "续跑应追加到 3 天"


# ---------------------------------------------------------------
# 外部 agent 画像退化路径（persona_hat 缺失时 Runner 侧 EMA 累积，docs/15 第 3 节）
# ---------------------------------------------------------------

def _external_delta_handler(calls: list[int]):
    """模拟外部 HTTP agent：只回 result（含 persona_belief 增量），从不回 persona_hat。"""
    from usersim.contracts.agent_api import AgentResponse

    def handle(req):
        calls.append(1)
        turn = AssistantTurn(
            reply="我在听。",
            user_belief=UserBelief(
                valence=0.6, energy=0.5, satiety=0.5, stress=0.4,
                persona_notes=f"第 {len(calls)} 轮笔记",
                persona_belief={"facets": {"神经质.焦虑": 80}, "loves": ["爵士乐"]},
            ),
            tool_calls=[],
        )
        return AgentResponse(request_id=req.request_id, result=turn.model_dump())

    return handle


def test_external_agent_delta_accumulated_by_runner(tmp_path, broker):
    from usersim.contracts.agent_api import AgentResponse  # noqa: F401
    from usersim.runner import run_live

    cfg = load_system_config()
    broker.register_local("user", DemoUserAgent(FakeUserClient()).handle)
    broker.register_local("assistant", _external_delta_handler([]))
    run_dir = run_live(seed=11, days=2, cfg=cfg, out_root=tmp_path, run_id="t_ext",
                       broker=broker)

    _, turns, _ = load_run(run_dir)
    asst = [t for t in turns if t.speaker == "assistant"]
    assert asst, "没有助手 turn"
    assert all(t.persona_hat is not None for t in asst), "退化路径未落盘 persona_hat"
    # EMA 累积：同一 facet 反复给 80，估计从 80 起仍保持 80；loves 保留；notes 逐轮更新
    assert asst[0].persona_hat.facets["神经质.焦虑"] == 80
    assert asst[-1].persona_hat.loves == ["爵士乐"]
    assert asst[-1].persona_hat.notes.endswith("轮笔记")

    # 续跑：Runner 侧累积器从日志重建，新增量在旧基线上继续 EMA（不被清空）
    broker.register_local("assistant", _external_delta_handler([]))
    run_live(seed=11, days=2, cfg=cfg, out_root=tmp_path, run_id="t_ext",
             broker=broker, resume_dir=run_dir, extra_days=1)
    _, turns2, _ = load_run(run_dir)
    asst2 = [t for t in turns2 if t.speaker == "assistant"]
    assert len(asst2) > len(asst)
    assert asst2[-1].persona_hat.facets["神经质.焦虑"] == 80
    assert asst2[-1].persona_hat.loves == ["爵士乐"]


def test_tool_results_survive_session_boundary(tmp_path, broker):
    """session 末轮 assistant 的工具执行结果，必须在下一 session 首轮的
    HarnessObs.tool_results 里呈现——否则 harness 的对账（成功剂量登记/失败
    换槽重试）永远缺最后一单。"""
    from usersim.contracts import ToolCall

    class BookingHarness(RecordingHarness):
        def on_turn(self, obs: HarnessObs) -> AssistantTurn:
            self.seen.append(obs)
            return AssistantTurn(
                reply="给你安排了散步。",
                user_belief=UserBelief(valence=0.6, energy=0.4, satiety=0.5,
                                       stress=0.5, persona_notes=""),
                tool_calls=[ToolCall(name="add_event_todo",
                                     args={"name": "散步", "slot": 2, "day_offset": 0})])

    h = BookingHarness()
    _run(tmp_path, broker, h, days=2, run_id="t_carry")
    firsts = [o for o in h.seen if len(o.history) <= 1]  # 各 session 首轮
    assert len(firsts) > 1, "需要多个 session 才能验证跨边界传递"
    carried = [o for o in firsts[1:] if o.tool_results]
    assert carried, "上一 session 末轮的工具结果未带入下一 session 首轮"
    assert carried[0].tool_results[0].name == "add_event_todo"


def test_agent_snapshot_replaces_runner_baseline(tmp_path, broker):
    """agent 回 persona_hat 快照时直接落盘，并成为后续增量的新基线。"""
    from usersim.contracts.agent_api import AgentResponse
    from usersim.runner import run_live

    cfg = load_system_config()
    broker.register_local("user", DemoUserAgent(FakeUserClient()).handle)
    calls: list[int] = []

    def handle(req):
        calls.append(1)
        turn = AssistantTurn(
            reply="嗯。",
            user_belief=UserBelief(
                valence=0.6, energy=0.5, satiety=0.5, stress=0.4,
                persona_belief={"facets": {"神经质.焦虑": 80}},
            ),
        )
        resp = AgentResponse(request_id=req.request_id, result=turn.model_dump())
        if len(calls) > 1:  # 第二轮起回快照：焦虑只有 20，取代之前累积的 80
            resp.persona_hat = PersonaBelief(facets={"神经质.焦虑": 20})
        return resp

    from usersim.contracts import PersonaBelief
    broker.register_local("assistant", handle)
    run_dir = run_live(seed=11, days=2, cfg=cfg, out_root=tmp_path, run_id="t_snap",
                       broker=broker)
    _, turns, _ = load_run(run_dir)
    asst = [t for t in turns if t.speaker == "assistant"]
    assert asst[0].persona_hat.facets["神经质.焦虑"] == 80
    assert asst[1].persona_hat.facets["神经质.焦虑"] == 20  # 快照取代累积值
