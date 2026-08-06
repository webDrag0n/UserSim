"""行为一致性评估指标的单元测试。

构造模拟 TurnRecord 数据验证全部 5 项指标的检测逻辑，
确保 0 LLM 调用、可在 CI 中运行。
"""

from __future__ import annotations

import pytest

from usersim.contracts.models import (
    PersonaBelief,
    Preferences,
    StateVec,
    ToolCall,
    ToolResult,
    TurnRecord,
)
from usersim.evaluator.consistency import (
    classify_acceptance,
    compute_consistency,
    compute_csps,
    compute_pac,
    compute_pba,
    compute_pra,
    compute_wsc,
    extract_event_category_from_text,
    sentiment_score,
)

# ---------------------------------------------------------------
# 测试用角色卡
# ---------------------------------------------------------------

LOW_COMPLIANCE_PERSONA: dict = {
    "name": "小明",
    "archetype": "程序员",
    "big5": {"开放性": 60, "尽责性": 70, "外向性": 30, "宜人性": 25, "神经质": 65},
    "facets": {
        "开放性.尝新": 55, "开放性.审美": 50,
        "尽责性.自律": 75,
        "外向性.群居性": 20, "外向性.热情": 40,
        "宜人性.顺从": 20, "宜人性.同理心": 35,  # 低顺从 = 直接拒绝
        "神经质.焦虑": 75, "神经质.脆弱": 60,
    },
    "prefs": {
        "categories": {
            "饮食": 0.6, "休息": 0.3, "户外": -0.7, "旅行": -0.3,
            "运动": -0.6, "居家": 0.4, "社交": -0.8, "文化": 0.5,
            "音乐": 0.2, "学习": 0.1, "自然": -0.4,
        },
        "loves": ["寿喜烧", "寿司"],
        "hates": ["临时加班", "应酬", "社交聚会"],
    },
}

HIGH_COMPLIANCE_PERSONA: dict = {
    "name": "小红",
    "archetype": "护士",
    "big5": {"开放性": 55, "尽责性": 60, "外向性": 70, "宜人性": 80, "神经质": 35},
    "facets": {
        "宜人性.顺从": 80,  # 高顺从 = 勉强接受
        "外向性.群居性": 75,
        "神经质.焦虑": 30,
    },
    "prefs": {
        "categories": {
            "饮食": 0.3, "休息": 0.4, "户外": -0.6, "运动": -0.5,
            "社交": 0.7, "居家": 0.2,
        },
        "loves": [],
        "hates": ["跑步"],
    },
}

# ---------------------------------------------------------------
# 测试用 TurnRecord 构建工具
# ---------------------------------------------------------------


def _make_user_turn(
    turn_id: int,
    text: str,
    session_id: str = "S001",
    t_logical: int = 0,
) -> TurnRecord:
    return TurnRecord(
        run_id="test",
        t_logical=t_logical,
        session_id=session_id,
        turn_id=turn_id,
        speaker="user",
        text=text,
        x_true=StateVec(valence=0.6, energy=0.5, satiety=0.5, stress=0.4),
    )


def _make_asst_turn_with_event(
    turn_id: int,
    text: str,
    session_id: str = "S001",
    event_name: str = "朋友小聚 · 居酒屋",
    t_logical: int = 0,
    tool_ok: bool = True,
) -> TurnRecord:
    return TurnRecord(
        run_id="test",
        t_logical=t_logical,
        session_id=session_id,
        turn_id=turn_id,
        speaker="assistant",
        text=text,
        x_true=StateVec(valence=0.6, energy=0.5, satiety=0.5, stress=0.4),
        x_hat=StateVec(valence=0.55, energy=0.55, satiety=0.5, stress=0.45),
        tool_calls=[ToolCall(name="add_event_todo", args={"name": event_name})],
        tool_results=[
            ToolResult(
                name="add_event_todo",
                ok=tool_ok,
                payload={"event": {"name": event_name, "cost": 150}},
            )
        ],
    )


def _make_asst_turn_no_action(
    turn_id: int,
    text: str,
    session_id: str = "S001",
    t_logical: int = 0,
) -> TurnRecord:
    return TurnRecord(
        run_id="test",
        t_logical=t_logical,
        session_id=session_id,
        turn_id=turn_id,
        speaker="assistant",
        text=text,
        x_true=StateVec(valence=0.6, energy=0.5, satiety=0.5, stress=0.4),
        x_hat=StateVec(valence=0.55, energy=0.55, satiety=0.5, stress=0.45),
    )


# ================================================================
# 文本分析工具测试
# ================================================================


class TestClassifyAcceptance:
    def test_explicit_resistance(self):
        assert classify_acceptance("我不想去，太累了") == "explicit_resistance"
        assert classify_acceptance("这个我不喜欢") == "explicit_resistance"
        assert classify_acceptance("不要不要，真的太讨厌了") == "explicit_resistance"

    def test_reluctant_accept(self):
        assert classify_acceptance("好吧那就这个吧") == "reluctant_accept"
        assert classify_acceptance("行吧，凑合吧") == "reluctant_accept"
        assert classify_acceptance("那就随便吃点") == "reluctant_accept"

    def test_positive_accept(self):
        assert classify_acceptance("太好了！就是这家") == "positive_accept"
        assert classify_acceptance("好的谢谢") == "positive_accept"
        assert classify_acceptance("不错，安排吧") == "positive_accept"

    def test_neutral(self):
        assert classify_acceptance("嗯") == "neutral"
        assert classify_acceptance("知道了") == "neutral"
        assert classify_acceptance("") == "neutral"


class TestSentimentScore:
    def test_positive(self):
        assert sentiment_score("太好了谢谢你") > 0.3
        assert sentiment_score("很开心期待") > 0.3

    def test_negative(self):
        assert sentiment_score("我不喜欢不想去") < -0.3
        assert sentiment_score("烦死了焦虑") < -0.3

    def test_hedging_modifiers(self):
        # 积极但带消极修饰 → 分打折
        base = sentiment_score("好的，可以")
        hedged = sentiment_score("好的，但有点不太想")
        assert hedged < base

    def test_neutral(self):
        score = sentiment_score("嗯知道了")
        assert -0.3 < score < 0.3


class TestExtractCategory:
    def test_dining(self):
        assert extract_event_category_from_text("想吃火锅") == "饮食"
        assert extract_event_category_from_text("去咖啡馆坐坐") == "饮食"

    def test_social(self):
        assert extract_event_category_from_text("想找人聚聚") == "社交"
        assert extract_event_category_from_text("朋友叫我去聚会") == "社交"

    def test_outdoor(self):
        assert extract_event_category_from_text("出去走走散散步") == "户外"

    def test_none(self):
        assert extract_event_category_from_text("今天天气不错") is None
        assert extract_event_category_from_text("") is None


# ================================================================
# M1: PAC (偏好-行动冲突) 测试
# ================================================================


class TestPAC:
    def test_no_conflict_when_user_hates_and_rejects(self):
        """用户在讨厌的事件安排后明确拒绝 → 无冲突。"""
        turns = [
            _make_user_turn(1, "最近压力好大"),
            _make_asst_turn_with_event(2, "要不要去社交聚会放松？", event_name="朋友小聚 · 居酒屋"),
            _make_user_turn(3, "不要，我最讨厌这种社交了", session_id="S001"),
        ]
        metrics, findings = compute_pac(turns, LOW_COMPLIANCE_PERSONA)
        assert metrics["pac_total_acceptances"] == 1
        # 明确拒绝 → 不算冲突（行为一致）
        assert metrics["pac_conflict_count"] == 0
        assert metrics["pac_conflict_rate"] == 0.0

    def test_conflict_when_user_hates_but_happily_accepts(self):
        """用户极度厌恶社交但开心接受 → 严重冲突。"""
        turns = [
            _make_user_turn(1, "最近压力好大"),
            _make_asst_turn_with_event(2, "要不要去社交聚会？", event_name="朋友小聚 · 居酒屋"),
            _make_user_turn(3, "太好了！正合我意！", session_id="S001"),
        ]
        metrics, findings = compute_pac(turns, LOW_COMPLIANCE_PERSONA)
        assert metrics["pac_total_acceptances"] == 1
        assert metrics["pac_conflict_count"] == 1
        assert metrics["pac_conflict_rate"] == 1.0
        assert metrics["pac_severity"] == "error"

    def test_high_compliance_reluctant_accept_is_consistent(self):
        """高顺从用户勉强接受讨厌事件 → 人格一致，不算冲突。"""
        turns = [
            _make_user_turn(1, "有点累"),
            _make_asst_turn_with_event(2, "出去走走？", event_name="出门走走 · 公园"),
            _make_user_turn(3, "好吧好吧那就走走吧", session_id="S001"),
        ]
        metrics, findings = compute_pac(turns, HIGH_COMPLIANCE_PERSONA)
        # 高顺从用户勉强接受了讨厌的户外活动
        # 注意：HIGH_COMPLIANCE_PERSONA 的户外是 -0.6
        assert metrics["pac_total_acceptances"] == 1
        # 勉强接受且有消极表达，应该不算严重冲突
        # 但需要检查是否被标记为 info
        if metrics["pac_conflict_count"] > 0:
            assert metrics["pac_severity"] != "error"

    def test_low_compliance_accepting_hated_thing_is_error(self):
        """低顺从用户接受极度厌恶事件且无抵触 → 应标 error。"""
        turns = [
            _make_user_turn(1, "好累"),
            _make_asst_turn_with_event(2, "去社交聚会吧？", event_name="朋友小聚 · 居酒屋"),
            _make_user_turn(3, "好的", session_id="S001"),  # 中性回应，无抗拒
        ]
        metrics, findings = compute_pac(turns, LOW_COMPLIANCE_PERSONA)
        assert metrics["pac_total_acceptances"] == 1
        assert metrics["pac_conflict_count"] == 1
        assert metrics["pac_severity"] == "error"

    def test_no_acceptances_returns_zero(self):
        """没有任何 add_event_todo → 0/0 无冲突。"""
        turns = [
            _make_user_turn(1, "你好"),
            _make_asst_turn_no_action(2, "你好啊"),
        ]
        metrics, findings = compute_pac(turns, LOW_COMPLIANCE_PERSONA)
        assert metrics["pac_total_acceptances"] == 0
        assert metrics["pac_conflict_count"] == 0
        assert metrics["pac_conflict_rate"] == 0.0


# ================================================================
# M2: WSC (会话内情感一致性) 测试
# ================================================================


class TestWSC:
    def test_coherent_session_no_flip(self):
        """正常一致的 session → 无翻转。"""
        turns = [
            _make_user_turn(1, "最近好累啊，想放松一下", session_id="S001"),
            _make_asst_turn_no_action(2, "听起来你需要休息"),
            _make_user_turn(3, "是啊，有没有什么推荐的", session_id="S001"),
            _make_asst_turn_no_action(4, "可以去温泉放松"),
            _make_user_turn(5, "好呀，那安排吧", session_id="S001"),
        ]
        metrics, findings = compute_wsc(turns, LOW_COMPLIANCE_PERSONA)
        assert metrics["wsc_flip_type_a"] == 0
        assert metrics["wsc_coherence_score"] >= 0.9

    def test_unexplained_flip_type_a(self):
        """无因翻转：从抗拒突然跳转到积极，助手没有新信息。"""
        turns = [
            _make_user_turn(1, "我不喜欢出门，太麻烦了", session_id="S001"),
            _make_asst_turn_no_action(2, "嗯嗯"),  # 助手没有提供新信息
            _make_user_turn(3, "太好了！那就出去吧！", session_id="S001"),  # 突然积极
        ]
        metrics, findings = compute_wsc(turns, LOW_COMPLIANCE_PERSONA)
        assert metrics["wsc_flip_type_a"] > 0

    def test_flip_with_assistant_info_is_not_flagged(self):
        """助手提供了新信息后的态度转变 → 不应标记。"""
        turns = [
            _make_user_turn(1, "我不想出门", session_id="S001"),
            _make_asst_turn_with_event(2, "我建议你去这家新开的店试试，有优惠", event_name="吃好吃的 · 新餐厅"),
            _make_user_turn(3, "那试试吧", session_id="S001"),
        ]
        metrics, findings = compute_wsc(turns, LOW_COMPLIANCE_PERSONA)
        # 助手有工具调用 = 有实质性建议 → 不应标记为无因翻转
        assert metrics["wsc_flip_type_a"] == 0

    def test_type_b_continued_resistance_then_accept(self):
        """持续多轮抗拒后最终接受 → type B。"""
        turns = [
            _make_user_turn(1, "最近好累", session_id="S001"),
            _make_asst_turn_no_action(2, "怎么了"),
            _make_user_turn(3, "不想动，什么都不想做", session_id="S001"),
            _make_asst_turn_no_action(4, "出去走走会好点"),
            _make_user_turn(5, "好吧那就走走", session_id="S001"),
        ]
        metrics, findings = compute_wsc(turns, LOW_COMPLIANCE_PERSONA)
        # 多次消极 → 最后接受
        assert metrics["wsc_flip_type_b"] > 0

    def test_empty_session(self):
        """没有 session 的 turns → 全部默认值。"""
        turns: list[TurnRecord] = []
        metrics, findings = compute_wsc(turns, LOW_COMPLIANCE_PERSONA)
        assert metrics["wsc_incoherent_sessions"] == 0
        assert metrics["wsc_coherence_score"] == 1.0


# ================================================================
# M3: PRA (喜好-请求对齐) 测试
# ================================================================


class TestPRA:
    def test_user_requests_hated_category(self):
        """用户主动请求讨厌类目活动 → misaligned。"""
        turns = [
            _make_user_turn(1, "想出去爬山徒步", session_id="S001"),  # 户外 = -0.7
            _make_asst_turn_no_action(2, "好的"),
        ]
        metrics, findings = compute_pra(turns, LOW_COMPLIANCE_PERSONA)
        assert metrics["pra_misaligned_requests"] >= 1

    def test_user_requests_loved_category_is_ok(self):
        """用户请求喜爱的类目 → 对齐，不算 misaligned。"""
        turns = [
            _make_user_turn(1, "想吃火锅", session_id="S001"),  # 饮食 = 0.6
            _make_asst_turn_no_action(2, "好的"),
        ]
        metrics, findings = compute_pra(turns, LOW_COMPLIANCE_PERSONA)
        assert metrics["pra_misaligned_requests"] == 0

    def test_loved_never_requested(self):
        """喜爱的类目从未被主动请求 → 报告中列出。"""
        turns = [
            _make_user_turn(1, "想去社交聚会", session_id="S001"),  # 社交 = -0.8
            _make_asst_turn_no_action(2, "好的"),
        ]
        metrics, findings = compute_pra(turns, LOW_COMPLIANCE_PERSONA)
        # 饮食(0.6)、居家(0.4)、文化(0.5) 从未被请求
        loved = metrics.get("pra_loved_never_requested", [])
        assert "饮食" in loved or len(loved) > 0


# ================================================================
# M4: PBA (人格-行为一致性) 测试
# ================================================================


class TestPBA:
    def test_enough_turns_to_compute(self):
        """5+ user turns → 可以计算行为画像。"""
        turns = [
            _make_user_turn(i, f"这是第{i}条消息", session_id=f"S{i//3:03d}")
            for i in range(10)
        ]
        metrics, findings = compute_pba(turns, LOW_COMPLIANCE_PERSONA)
        assert metrics["pba_correlation"] is not None
        assert "avg_msg_len" in metrics.get("pba_behavior_profile", {})

    def test_few_turns_skips(self):
        """少于 5 条 user turns → 不计算。"""
        turns = [
            _make_user_turn(1, "hi", session_id="S001"),
            _make_user_turn(2, "bye", session_id="S001"),
        ]
        metrics, findings = compute_pba(turns, LOW_COMPLIANCE_PERSONA)
        assert metrics["pba_correlation"] is None

    def test_high_neurotic_without_complaints(self):
        """高神经质但从不抱怨 → 行为与人格偏离。"""
        # 高神经质（75）应该多抱怨，但我们构造不抱怨的对话
        turns = [
            _make_user_turn(i, "今天天气真好心情不错", session_id=f"S{i//3:03d}")
            for i in range(8)
        ]
        metrics, findings = compute_pba(turns, LOW_COMPLIANCE_PERSONA)
        deviations = metrics.get("pba_deviations", [])
        # 神经质高但抱怨少 → 应该有偏离
        neuro_dev = [d for d in deviations if "神经质" in d.get("trait", "")]
        assert len(neuro_dev) > 0


# ================================================================
# M5: CSPS (跨 Session 偏好稳定性) 测试
# ================================================================


class TestCSPS:
    def test_stable_preferences(self):
        """同一类目在不同 session 情感一致 → 高稳定性。"""
        turns = [
            _make_user_turn(1, "想吃火锅", session_id="S001", t_logical=0),
            _make_asst_turn_with_event(2, "安排火锅", event_name="吃好吃的 · 火锅店", session_id="S001", t_logical=0),
            _make_user_turn(3, "太好了谢谢", session_id="S001", t_logical=0),
            # 另一个 session，同样喜欢饮食
            _make_user_turn(10, "又想吃日料了", session_id="S002", t_logical=10),
            _make_asst_turn_with_event(11, "安排日料", event_name="吃好吃的 · 日料店", session_id="S002", t_logical=10),
            _make_user_turn(12, "不错可以", session_id="S002", t_logical=10),
        ]
        metrics, findings = compute_csps(turns, LOW_COMPLIANCE_PERSONA)
        assert metrics["csps_stability_score"] >= 0.8

    def test_unstable_preferences(self):
        """同一类目一次积极一次消极 → 态度不稳定。"""
        turns = [
            _make_user_turn(1, "想吃火锅", session_id="S001", t_logical=0),
            _make_asst_turn_with_event(2, "安排火锅", event_name="吃好吃的 · 火锅店", session_id="S001", t_logical=0),
            _make_user_turn(3, "太好了！正想吃这个", session_id="S001", t_logical=0),
            # 另一个 session，同类目但消极
            _make_user_turn(10, "不想吃任何东西", session_id="S002", t_logical=10),
            _make_asst_turn_with_event(11, "安排晚餐", event_name="吃好吃的 · 中餐馆", session_id="S002", t_logical=10),
            _make_user_turn(12, "讨厌死了不想吃", session_id="S002", t_logical=10),
        ]
        metrics, findings = compute_csps(turns, LOW_COMPLIANCE_PERSONA)
        # 饮食类目一次积极一次消极 → 应该有不稳定标记
        assert metrics["csps_stability_score"] < 1.0

    def test_empty_turns(self):
        """空 turns → 默认值。"""
        metrics, findings = compute_csps([], LOW_COMPLIANCE_PERSONA)
        assert metrics["csps_stability_score"] == 1.0
        assert len(metrics["csps_unstable_categories"]) == 0


# ================================================================
# 聚合入口测试
# ================================================================


class TestComputeConsistency:
    def test_null_persona_returns_defaults(self):
        """没有 persona → 返回空指标无报错。"""
        result = compute_consistency([], None)
        assert result["findings"] == []
        assert result["metrics"]["pac_conflict_rate"] == 0.0

    def test_full_pipeline(self):
        """完整的 5 项指标流水线不报错。"""
        turns = [
            _make_user_turn(1, "想吃火锅", session_id="S001"),
            _make_asst_turn_with_event(2, "安排聚餐", event_name="朋友小聚 · 居酒屋", session_id="S001"),
            _make_user_turn(3, "太好了正合我意", session_id="S001"),  # 低顺从 + 讨厌社交但开心接受
            _make_user_turn(4, "好累想休息", session_id="S002"),
            _make_asst_turn_no_action(5, "辛苦了"),
            _make_user_turn(6, "好的谢谢", session_id="S002"),
            _make_user_turn(7, "今天天气不错", session_id="S003"),
            _make_user_turn(8, "我想出门散步", session_id="S003"),  # 户外=-0.7，讨厌但主动请求
        ]
        result = compute_consistency(turns, LOW_COMPLIANCE_PERSONA)
        assert "metrics" in result
        assert "findings" in result
        assert "observations" in result
        # 应该检测到冲突（低顺从 + 接受讨厌社交 + 开心回应）
        assert result["observations"]["pac_conflict"] > 0
        assert len(result["findings"]) > 0


# ================================================================
# 边界测试
# ================================================================


class TestEdgeCases:
    def test_empty_turns_all_metrics(self):
        """空 turns 列表 → 所有指标返回安全默认值。"""
        result = compute_consistency([], LOW_COMPLIANCE_PERSONA)
        m = result["metrics"]
        assert m["pac_conflict_rate"] == 0.0
        assert m["pac_conflict_count"] == 0
        assert m["wsc_coherence_score"] == 1.0
        assert m["csps_stability_score"] == 1.0

    def test_single_session(self):
        """单个 session → 跨 session 指标无数据但不出错。"""
        turns = [
            _make_user_turn(1, "hi", session_id="S001"),
            _make_asst_turn_no_action(2, "hi"),
            _make_user_turn(3, "bye", session_id="S001"),
        ]
        result = compute_consistency(turns, LOW_COMPLIANCE_PERSONA)
        assert result["observations"]["wsc_incoherent"] >= 0.0

    def test_missing_prefs_in_persona(self):
        """persona 中没有 prefs → 不报错，返回默认值。"""
        persona_no_prefs = {"name": "测试", "big5": {}, "facets": {}}
        result = compute_consistency(
            [_make_user_turn(1, "hi", session_id="S001")],
            persona_no_prefs,
        )
        assert result["metrics"]["pac_conflict_rate"] == 0.0

    def test_tool_result_not_add_event(self):
        """忽略非 add_event_todo 的工具调用。"""
        turns = [
            _make_user_turn(1, "看看日程"),
            TurnRecord(
                run_id="test",
                t_logical=0,
                session_id="S001",
                turn_id=2,
                speaker="assistant",
                text="好的",
                x_true=StateVec(valence=0.6, energy=0.5, satiety=0.5, stress=0.4),
                x_hat=StateVec(valence=0.55, energy=0.55, satiety=0.5, stress=0.45),
                tool_calls=[ToolCall(name="view_event_todos", args={})],
                tool_results=[ToolResult(name="view_event_todos", ok=True, payload={"events": []})],
            ),
        ]
        metrics, _ = compute_pac(turns, LOW_COMPLIANCE_PERSONA)
        assert metrics["pac_total_acceptances"] == 0
