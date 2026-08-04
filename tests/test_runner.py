"""Runner 编排层测试（此前编排与 live 路径零回归保护）。

用 stub LLM 客户端替代真实调用：验证 Harness 可插拔、契约违约计入、
日志落盘、续跑恢复——全部不花 token。
"""

from __future__ import annotations

import json

import pytest

from usersim.config import load_system_config
from usersim.contracts import AssistantTurn, HarnessObs, UserBelief
from usersim.evaluator.metrics import load_run


class FakeUserClient:
    """假的用户 LLM：总是开 session，说两轮就收尾。"""

    def __init__(self) -> None:
        self.calls = 0

    def chat_json(self, messages, max_tokens=None) -> dict:
        self.calls += 1
        text = str(messages[-1].get("content", ""))
        if '"open"' in text:
            return {"open": True, "reason": "想聊聊"}
        return {"say": f"我第 {self.calls} 次说话，有点累", "end_session": self.calls % 3 == 0}

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
def patched_live(monkeypatch):
    """把 run_live 里的用户 LLM 换成假客户端（助手侧走 harness_factory）。"""
    import usersim.runner as runner_mod
    from usersim.agents.user import LLMUserAgent

    monkeypatch.setattr(runner_mod, "llm_roles_summary", lambda: {}, raising=False)

    def _fake_user_agent(client):
        return LLMUserAgent(FakeUserClient())

    import usersim.agents.user as user_pkg
    monkeypatch.setattr(user_pkg, "LLMUserAgent", _fake_user_agent)
    return monkeypatch


def _run(tmp_path, harness_factory, days=3, run_id="t_live", **kw):
    from usersim.runner import run_live

    cfg = load_system_config()
    return run_live(seed=11, days=days, cfg=cfg, out_root=tmp_path,
                    run_id=run_id, harness_factory=harness_factory, **kw)


def test_live_run_writes_logs_and_meta(tmp_path, patched_live):
    harness = RecordingHarness()
    run_dir = _run(tmp_path, lambda c: harness)

    assert (run_dir / "slots.jsonl").exists()
    assert (run_dir / "meta.json").exists()
    slots, turns, meta = load_run(run_dir)
    assert len(slots) == 3 * 4  # days × slots_per_day
    assert all(s.slots_per_day == 4 for s in slots)
    # 可复现性凭证已写入
    assert meta["artifact_hashes"]["combined"]
    assert meta["prompt_versions"]["assistant"]
    assert meta["harness"] == "reference"  # harness_factory 不改名，默认名仍记录


def test_harness_receives_injected_context(tmp_path, patched_live):
    """Runner 必须注入余额/日程/恢复目录——被测件不得自己去碰 world。"""
    harness = RecordingHarness()
    _run(tmp_path, lambda c: harness)

    assert harness.seen, "Harness 从未被调用（介入点或用户决策链路断了）"
    obs = harness.seen[0]
    assert obs.balance is not None
    assert obs.slot_names and len(obs.slot_names) == 4
    assert isinstance(obs.recovery_catalog, list)
    assert obs.user_say


def test_x_hat_is_recorded_from_harness(tmp_path, patched_live):
    harness = RecordingHarness()
    run_dir = _run(tmp_path, lambda c: harness)
    _, turns, _ = load_run(run_dir)
    asst = [t for t in turns if t.speaker == "assistant"]
    assert asst, "没有助手 turn"
    assert all(t.x_hat is not None for t in asst)
    assert all(t.x_true is not None for t in asst)


def test_contract_violation_is_logged_not_fatal(tmp_path, patched_live):
    run_dir = _run(tmp_path, lambda c: BrokenHarness(), run_id="t_broken")
    slots, turns, _ = load_run(run_dir)
    assert len(slots) == 3 * 4, "违约不应中断世界推进"
    assert any(t.contract_violation for t in turns), "违约未被记录"


def test_resume_restores_harness_memory(tmp_path, patched_live):
    harness = RecordingHarness()
    run_dir = _run(tmp_path, lambda c: harness, days=2, run_id="t_resume")
    state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
    assert state["harness_state"] == {"n": len(harness.seen)}

    fresh = RecordingHarness()
    from usersim.runner import run_live
    cfg = load_system_config()
    run_live(seed=11, days=2, cfg=cfg, out_root=tmp_path, run_id="t_resume",
             harness_factory=lambda c: fresh, resume_dir=run_dir, extra_days=1)
    assert getattr(fresh, "restored", None) is not None, "续跑未调用 Harness.restore"

    slots, _, _ = load_run(run_dir)
    assert len(slots) == 3 * 4, "续跑应追加到 3 天"
