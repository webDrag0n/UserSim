"""R4 对话质量优化的回归测试（0 token）。

覆盖：
- runner 复读熔断（用户侧 / 助手侧强制收尾，落盘 system 记录含"复读熔断"标记）
- felt_state 同义变体池（每档 5 变体、同 seed 确定性）
- chat 非事务意图被 plan 解析接受
- evaluator.dialogue 形态指标纯函数
"""

from __future__ import annotations

import numpy as np
import pytest

from agents.user.standard.agent import DemoUserAgent
from agents.user.standard.llm_user import _parse_plan
from usersim.agents.demo import DemoAssistantAgent
from usersim.config import load_system_config
from usersim.contracts import AssistantTurn, HarnessObs, StateVec, TurnRecord, UserBelief
from usersim.evaluator.dialogue import compute_dialogue_stats
from usersim.evaluator.metrics import load_run
from usersim.gateway import AgentBroker
from usersim.world.felt import _ENERGY, _SATIETY, _STRESS, _VALENCE, felt_state


class RepeatUserClient:
    """永远说同一句话、永不主动收尾的用户——触发用户侧复读熔断。"""

    def chat_json(self, messages, max_tokens=None) -> dict:
        text = str(messages[-1].get("content", ""))
        if '"intents"' in text:
            return {"intents": [{"type": "recover", "mode": "vague", "want": "有点累"}]}
        if '"open"' in text:
            return {"open": True, "reason": "想聊聊"}
        return {"say": "我还是觉得好累啊，真的不想动", "end_session": False}

    def set_log_dir(self, run_dir) -> None:
        pass


class ChattyUserClient:
    """每轮说不同的话——让用户侧熔断不触发，专测助手侧熔断。"""

    def __init__(self) -> None:
        self.n = 0

    def chat_json(self, messages, max_tokens=None) -> dict:
        text = str(messages[-1].get("content", ""))
        if '"intents"' in text:
            return {"intents": [{"type": "recover", "mode": "vague", "want": "有点累"}]}
        if '"open"' in text:
            return {"open": True, "reason": "想聊聊"}
        self.n += 1
        return {"say": f"这是我第 {self.n} 件完全不同的事", "end_session": False}

    def set_log_dir(self, run_dir) -> None:
        pass


class VaryingHarness:
    """每轮回复真正不同的助手（配合复读用户）：轮换语义完全不同的句子。"""

    _REPLIES = ["要不要先躺十分钟", "冰箱里有剩饭可以热", "周末想去哪走走吗",
                "水喝得够不够", "先把灯关了吧", "晚点再决定也行"]

    def __init__(self, client=None) -> None:
        self.n = 0

    def on_turn(self, obs: HarnessObs) -> AssistantTurn:
        reply = self._REPLIES[self.n % len(self._REPLIES)]
        self.n += 1
        return AssistantTurn(
            reply=reply,
            user_belief=UserBelief(valence=0.5, energy=0.5, satiety=0.5, stress=0.5),
            tool_calls=[])

    def snapshot(self) -> dict:
        return {}

    def restore(self, state: dict) -> None:
        pass


class ParrotHarness:
    """永远同一句话的助手（配合话痨用户）。"""

    def __init__(self, client=None) -> None:
        pass

    def on_turn(self, obs: HarnessObs) -> AssistantTurn:
        return AssistantTurn(
            reply="好嘞，我帮你安排！",
            user_belief=UserBelief(valence=0.5, energy=0.5, satiety=0.5, stress=0.5),
            tool_calls=[])

    def snapshot(self) -> dict:
        return {}

    def restore(self, state: dict) -> None:
        pass


def _run(tmp_path, broker, client, harness, days=1):
    from usersim.runner import run_live

    cfg = load_system_config()
    broker.register_local("user", DemoUserAgent(client).handle)
    broker.register_local("assistant", DemoAssistantAgent(harness).handle)
    return run_live(seed=11, days=days, cfg=cfg, out_root=tmp_path, run_id="t_fuse",
                    broker=broker, prompt_versions={"assistant": "t", "user": "t"})


def test_user_repeat_fuse_breaks_session(tmp_path):
    run_dir = _run(tmp_path, AgentBroker(), RepeatUserClient(), VaryingHarness())
    _, turns, _ = load_run(run_dir)
    fuses = [t for t in turns if t.speaker == "system" and "复读熔断" in t.text]
    assert fuses, "复读用户应触发熔断"
    assert any("用户连续复述" in t.text for t in fuses)


def test_assistant_repeat_fuse_breaks_session(tmp_path):
    run_dir = _run(tmp_path, AgentBroker(), ChattyUserClient(), ParrotHarness())
    _, turns, _ = load_run(run_dir)
    fuses = [t for t in turns if t.speaker == "system" and "复读熔断" in t.text]
    assert fuses, "复读助手应触发熔断"
    assert any("助手连续复述" in t.text for t in fuses)


def test_felt_pool_has_5_variants_and_is_deterministic():
    for pool in (_STRESS, _ENERGY, _SATIETY, _VALENCE):
        assert all(len(tier) >= 5 for tier in pool), "每档应至少 5 个同义变体"
    x = StateVec(valence=0.2, energy=0.2, satiety=0.8, stress=0.9)
    a = felt_state(x, np.random.default_rng(42))
    b = felt_state(x, np.random.default_rng(42))
    assert a == b, "同 seed 措辞必须确定"
    # 无 rng 时取每档第一个变体（兼容旧调用）
    assert felt_state(x) == felt_state(x)


def test_chat_intent_accepted_by_parse_plan():
    out = {"intents": [
        {"type": "chat", "mode": "vague", "want": "就是想找人说说话"},
        {"type": "bogus", "mode": "vague", "want": "非法类型应丢弃"},
    ]}
    intents = _parse_plan(out)
    assert [i["type"] for i in intents] == ["chat"]


def _t(sid: str, turn_id: int, speaker: str, text: str) -> TurnRecord:
    return TurnRecord(run_id="r", t_logical=turn_id, session_id=sid, turn_id=turn_id,
                      speaker=speaker, text=text,
                      x_true=StateVec(valence=0.5, energy=0.5, satiety=0.5, stress=0.5))


def test_dialogue_stats_counts_repeats_fillers_and_fuses():
    turns = [
        _t("s1", 0, "user", "今天好累"),
        _t("s1", 1, "assistant", "好嘞，帮你安排一下！"),
        _t("s1", 2, "user", "今天好累"),          # 用户复读 ×1
        _t("s1", 3, "assistant", "好嘞，帮你安排一下！"),  # 助手复读 ×1、口癖 ×2
        _t("s1", 4, "system", "复读熔断：助手连续复述同一内容，session 由 runner 强制收尾"),
        _t("s2", 0, "user", "吃了吗"),
        _t("s2", 1, "assistant", "还没呢，你呢"),   # 无口癖
        _t("s2", 2, "user", "我随便问问"),          # 不复读
        _t("s2", 3, "assistant", "那晚上吃点好的"),  # 不复读、无口癖
    ]
    d = compute_dialogue_stats(turns)
    assert d["user_repeat_rate"] == pytest.approx(0.5)   # 2 对相邻，1 次复读
    assert d["assistant_repeat_rate"] == pytest.approx(0.5)
    assert d["assistant_filler_rate"] == pytest.approx(0.5)
    assert d["fused_sessions"] == 1
    assert d["sessions"] == 2


def test_dialogue_stats_empty():
    d = compute_dialogue_stats([])
    assert d["sessions"] == 0
    assert d["user_repeat_rate"] is None
    assert d["fused_sessions"] == 0
