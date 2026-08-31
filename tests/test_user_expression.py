"""阶段 2：用户 Agent 纯 LLM 化测试。

- expression.explicitness_tier：人格 facet → 表达直白度档位（纯函数）；
- LLMUserAgent.plan：罐装/异常 LLM 输出 → intents 解析（含 mode 与数值解耦断言）；
- DemoUserAgent：plan → Intent 映射（event_name 不再填充）、emergency 注入保持、
  speak 的 mode 指导前缀、ctx 缓存供 plan 使用、sys prompt 注入 satiation/表达习惯。
"""

from __future__ import annotations

import pytest

from agents.user.standard.agent import DemoUserAgent
from agents.user.standard.expression import explicitness_score, explicitness_tier
from agents.user.standard.llm_user import LLMUserAgent
from usersim.contracts import Persona, StateVec, UserContext
from usersim.contracts.agent_api import AgentRequest, PlanSlotRequest


# ---------------------------------------------------------------
# 测试替身
# ---------------------------------------------------------------

class CannedClient:
    """罐装 chat_json：按 prompt 内容分派；记录全部 prompt 供断言。"""

    def __init__(self, plan_out=None, broken: bool = False) -> None:
        self.plan_out = plan_out if plan_out is not None else {
            "intents": [{"type": "eat", "mode": "explicit", "want": "想吃顿好的"}]}
        self.broken = broken
        self.prompts: list[str] = []

    def chat_json(self, messages, max_tokens=None) -> dict:
        text = str(messages[-1].get("content", ""))
        self.prompts.append(text)
        if self.broken:
            raise RuntimeError("LLM 挂了")
        if '"intents"' in text:
            return self.plan_out
        if '"open"' in text:
            return {"open": True, "reason": "想聊聊"}
        return {"say": "我想吃顿好的", "end_session": True}

    def set_log_dir(self, run_dir) -> None:  # 接口兼容
        pass


def _ctx(satiation: str | None = None, facets: dict | None = None) -> UserContext:
    persona = Persona(
        name="测试", archetype="设计师",
        big5={"开放性": 60}, facets=facets or {},
        likes="火锅、爵士乐", routine="朝九晚六",
        x0=StateVec(valence=0.5, energy=0.5, satiety=0.5, stress=0.5),
    )
    return UserContext(persona=persona, felt_state="有点累", satiation_note=satiation)


def _plan_req(**kw) -> PlanSlotRequest:
    base = dict(urges={"hunger": 0.7, "social": 0.3, "stimulation": 0.5, "achievement": 0.2},
                stress=0.6, energy=0.4, slot=2, day=0, money=500.0,
                event_library=[{"name": "寿喜烧", "cost": 200}],
                assist_prompt=None, max_intents=5)
    base.update(kw)
    return PlanSlotRequest(**base)


def _handle(agent: DemoUserAgent, req_type: str, payload: dict) -> dict:
    req = AgentRequest(request_id="r1", run_id="run1", role="user",
                       type=req_type, payload=payload)
    return agent.handle(req).result


# ---------------------------------------------------------------
# explicitness_tier
# ---------------------------------------------------------------

class TestExplicitnessTier:
    def test_neutral_default_is_mid(self):
        tier, guidance = explicitness_tier(None)
        assert tier == 1
        assert explicitness_tier({})[0] == 1

    def test_reserved_is_tier0(self):
        facets = {"外向性.果断": 20, "宜人性.直率": 20,
                  "开放性.情感丰富": 30, "神经质.自我意识": 90}
        tier, guidance = explicitness_tier(facets)
        assert tier == 0
        assert "猜" in guidance

    def test_expressive_is_tier2(self):
        facets = {"外向性.果断": 90, "宜人性.直率": 85,
                  "开放性.情感丰富": 90, "神经质.自我意识": 20}
        tier, guidance = explicitness_tier(facets)
        assert tier == 2
        assert "直接说出来" in guidance

    @pytest.mark.parametrize("facets,score,expected", [
        ({"外向性.果断": 49}, 99, 0),                                  # 其余中性 → 49+50+50-50
        ({"外向性.果断": 50}, 100, 1),
        ({"外向性.果断": 80, "宜人性.直率": 70, "开放性.情感丰富": 79}, 179, 1),
        ({"外向性.果断": 80, "宜人性.直率": 70, "开放性.情感丰富": 80}, 180, 2),
    ])
    def test_boundaries(self, facets, score, expected):
        assert explicitness_score(facets) == score
        assert explicitness_tier(facets)[0] == expected


# ---------------------------------------------------------------
# LLMUserAgent.plan 解析与失败路径
# ---------------------------------------------------------------

class TestPlanParsing:
    def test_maps_intents_and_drops_invalid_type(self):
        client = CannedClient({"intents": [
            {"type": "eat", "mode": "explicit", "want": "想吃顿好的"},
            {"type": "fly", "mode": "vague", "want": "想上天"},      # 非法 type → 丢弃
            {"type": "recover", "mode": "weird", "want": "想歇会儿"},  # 非法 mode → vague
            {"type": "social", "mode": "vague", "want": " "},          # 空 want → 丢弃
        ]})
        out = LLMUserAgent(client).plan(_plan_req(), ctx=_ctx())
        assert [i["type"] for i in out] == ["eat", "recover"]
        assert out[0] == {"type": "eat", "mode": "explicit", "want": "想吃顿好的"}
        assert out[1]["mode"] == "vague"

    def test_emergency_not_allowed_from_llm(self):
        client = CannedClient({"intents": [{"type": "emergency", "mode": "vague", "want": "救命"}]})
        assert LLMUserAgent(client).plan(_plan_req(), ctx=_ctx()) == []

    def test_llm_exception_returns_empty(self):
        assert LLMUserAgent(CannedClient(broken=True)).plan(_plan_req(), ctx=_ctx()) == []

    @pytest.mark.parametrize("bad", [{}, {"intents": "想吃"}, {"intents": [42]}, []])
    def test_garbage_payload_returns_empty(self, bad):
        assert LLMUserAgent(CannedClient(bad)).plan(_plan_req(), ctx=_ctx()) == []

    def test_state_numbers_never_reach_prompt(self):
        """状态-表达解耦：urges/stress/money 等数值不得出现在 plan prompt 里。"""
        client = CannedClient()
        LLMUserAgent(client).plan(_plan_req(), ctx=_ctx())
        prompt = client.prompts[-1]
        for leaked in ("0.7", "0.6", "0.4", "500"):
            assert leaked not in prompt
        assert "有点累" in prompt  # felt_state 进 prompt

    def test_no_ctx_falls_back_to_generic(self):
        """run 首个 slot 无缓存 ctx：退化为无人格通用规划，仍能产出。"""
        client = CannedClient()
        out = LLMUserAgent(client).plan(_plan_req(), ctx=None)
        assert out[0]["want"] == "想吃顿好的"
        assert "你是一个普通人" in client.prompts[-1]


# ---------------------------------------------------------------
# DemoUserAgent：映射 / emergency / mode 前缀 / ctx 缓存
# ---------------------------------------------------------------

class TestDemoAgentPlanSlot:
    def test_intents_mapped_without_event_name(self):
        client = CannedClient({"intents": [
            {"type": "eat", "mode": "explicit", "want": "想吃顿好的"},
            {"type": "recover", "mode": "vague", "want": "有点累"},
            {"type": "social", "mode": "vague", "want": "想找人聊聊"},
        ]})
        result = _handle(DemoUserAgent(client), "plan_slot", _plan_req().model_dump(mode="json"))
        intents = result["intents"]
        assert [i["type"] for i in intents] == ["eat", "recover", "social"]
        assert [i["priority"] for i in intents] == [1.0, 0.8, 0.6]
        assert intents[0]["description"] == "想吃顿好的"
        assert all(i["event_name"] == "" and i["location"] == "" for i in intents)

    def test_emergency_injection_kept(self):
        client = CannedClient()  # 罐装 eat 意图（无 recover/emergency）
        result = _handle(DemoUserAgent(client), "plan_slot",
                         _plan_req(assist_prompt="压力大得快崩了").model_dump(mode="json"))
        intents = result["intents"]
        assert intents[0]["type"] == "emergency"
        assert intents[0]["description"] == "压力大得快崩了"
        assert intents[1]["type"] == "eat"

    def test_no_emergency_when_recover_planned(self):
        client = CannedClient({"intents": [{"type": "recover", "mode": "vague", "want": "想躺平"}]})
        result = _handle(DemoUserAgent(client), "plan_slot",
                         _plan_req(assist_prompt="压力大得快崩了").model_dump(mode="json"))
        assert [i["type"] for i in result["intents"]] == ["recover"]

    def test_llm_failure_returns_empty_list(self):
        result = _handle(DemoUserAgent(CannedClient(broken=True)), "plan_slot",
                         _plan_req().model_dump(mode="json"))
        assert result["intents"] == []


class TestModeAndCtxFlow:
    def test_speak_gets_mode_prefix(self):
        """plan 暂存 {want: mode}；speak 按 mode 拼入表达指导前缀。"""
        client = CannedClient()  # explicit 想吃顿好的
        agent = DemoUserAgent(client)
        _handle(agent, "plan_slot", _plan_req().model_dump(mode="json"))
        _handle(agent, "speak", {"context": _ctx().model_dump(mode="json"),
                                 "history": [], "intent_description": "想吃顿好的"})
        speak_prompt = client.prompts[-1]
        assert "可以直接说想做什么" in speak_prompt

    def test_speak_vague_prefix_and_runner_hint_kept(self):
        client = CannedClient({"intents": [{"type": "recover", "mode": "vague", "want": "有点累"}]})
        agent = DemoUserAgent(client)
        _handle(agent, "plan_slot", _plan_req().model_dump(mode="json"))
        _handle(agent, "speak", {"context": _ctx().model_dump(mode="json"), "history": [],
                                 "intent_description": "有点累\n（你们聊了挺久了，如果事情办好了可以结束对话了）"})
        speak_prompt = client.prompts[-1]
        assert "只说感受和需求" in speak_prompt
        assert "如果事情办好了可以结束对话了" in speak_prompt  # runner 收尾 hint 不丢

    def test_unknown_want_no_prefix(self):
        """emergency 意图的 description 不在 {want: mode} 映射里 → 不加前缀。"""
        client = CannedClient()
        agent = DemoUserAgent(client)
        _handle(agent, "speak", {"context": _ctx().model_dump(mode="json"),
                                 "history": [], "intent_description": "压力大得快崩了"})
        assert "你想做的事：" not in client.prompts[-1]  # explicit 指导前缀未拼入（模板通用指导不算）

    def test_decide_open_carries_want_and_ctx_cached(self):
        """decide_open 把 intent.description 补进 situation；其 ctx 供后续 plan 使用。"""
        client = CannedClient()
        agent = DemoUserAgent(client)
        # 首个 plan：无缓存 ctx → 通用规划
        _handle(agent, "plan_slot", _plan_req().model_dump(mode="json"))
        assert "你是一个普通人" in client.prompts[-1]
        # decide_open 携带 ctx + intent
        _handle(agent, "decide_open", {
            "context": _ctx().model_dump(mode="json"),
            "intent": {"type": "eat", "priority": 1.0, "description": "想吃顿好的"},
        })
        assert "你心里正想着：想吃顿好的" in client.prompts[-1]
        # 之后的 plan：用上缓存 ctx（persona 进 prompt）
        _handle(agent, "plan_slot", _plan_req().model_dump(mode="json"))
        assert "你是 测试，设计师。" in client.prompts[-1]


class TestSysPromptBlocks:
    def test_satiation_note_in_speak_prompt(self):
        client = CannedClient()
        agent = DemoUserAgent(client)
        _handle(agent, "speak", {
            "context": _ctx(satiation="最近总是火锅，感觉有点腻了").model_dump(mode="json"),
            "history": [], "intent_description": "",
        })
        assert "【最近的感觉】最近总是火锅，感觉有点腻了" in client.prompts[-1]

    def test_no_satiation_no_block(self):
        client = CannedClient()
        agent = DemoUserAgent(client)
        _handle(agent, "speak", {"context": _ctx().model_dump(mode="json"),
                                 "history": [], "intent_description": ""})
        assert "【最近的感觉】" not in client.prompts[-1]

    def test_expression_guidance_in_prompt(self):
        facets = {"外向性.果断": 90, "宜人性.直率": 85,
                  "开放性.情感丰富": 90, "神经质.自我意识": 20}
        client = CannedClient()
        agent = DemoUserAgent(client)
        _handle(agent, "speak", {"context": _ctx(facets=facets).model_dump(mode="json"),
                                 "history": [], "intent_description": ""})
        assert "【你的表达习惯】你想做什么通常会直接说出来" in client.prompts[-1]
