"""用户 Agent 行为一致性评估指标。

从 turn 日志与角色卡出发，检查用户 Agent 的行为是否内部自洽——
它是 reward 信号可信度的质量门。

零 LLM 调用：全部基于关键词匹配 + 结构化的偏好/人格对比。
新增指标落盘格式与现有的 report.json / insights.json 兼容，
因此 bench/aggregate.py 会自动将其纳入多 seed 统计。

设计依据：用户 Agent prompt v2 铁律第 6 条——
"你的性格与喜好是固定的：不要为了迎合助手而改变偏好；
 助手推荐你讨厌的东西时，按你的性格自然地表达抗拒
 （宜人性.顺从高就勉强接受、低就直接拒绝）。"

M1 偏好-行动冲突率 (PAC)
M2 会话内情感一致性 (WSC)
M3 喜好-请求对齐     (PRA)
M4 人格-行为一致性   (PBA)
M5 跨 Session 偏好稳定性 (CSPS)
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict

from usersim.contracts.models import TurnRecord
from usersim.contracts.persona import (
    BIG5_DOMAINS,
    PREF_CATEGORIES,
    PREF_KEYWORDS,
    pref_category,
    trait,
)


# ================================================================
# 0. 文本分析工具（纯关键词匹配）
# ================================================================

# 明确抗拒关键词（用户明确表达不想/不喜欢）
RESISTANCE_EXPLICIT: tuple[str, ...] = (
    "不喜欢", "讨厌", "不想", "不要", "算了", "没兴趣",
    "不太想", "不想要", "拒绝", "不愿意", "受不了",
    "烦", "厌恶", "反感", "排斥", "抵触",
)

# 勉强接受关键词（用户不太情愿但最终接受）
RESISTANCE_RELUCTANT: tuple[str, ...] = (
    "好吧", "行吧", "那就", "随便", "凑合", "勉强",
    "将就", "也行", "就这样吧", "那行", "可以吧",
    "听你的", "你定吧", "无所谓", "随便你",
)

# 积极接受关键词
POSITIVE_KEYWORDS: tuple[str, ...] = (
    "太好了", "好呀", "可以", "不错", "喜欢", "想",
    "行", "好的", "谢谢", "感谢", "赞", "棒", "开心",
    "期待", "nice", "好啊", "太棒", "真不错", "正合我意",
    "就这个", "安排", "走起", "来吧", "好主意", "有道理",
)

# 消极修饰词（减弱肯定语气）
HEDGING_MODIFIERS: tuple[str, ...] = (
    "但", "不过", "虽然", "有点", "稍微", "倒是",
    "只是", "就是", "然而", "可", "问题是",
)

# 抱怨/担忧表达（神经质倾向）
COMPLAINT_KEYWORDS: tuple[str, ...] = (
    "担心", "焦虑", "紧张", "害怕", "压力", "烦死了",
    "累死了", "崩溃", "受不了", "撑不住", "太难了",
    "怎么办", "万一", "会不会", "好累", "好烦", "好难",
)

# 好奇心/探索表达（开放性倾向）
CURIOSITY_KEYWORDS: tuple[str, ...] = (
    "想去", "试试", "体验", "探索", "新鲜", "没去过",
    "第一次", "新开的", "听说", "最近", "有没有",
    "推荐", "有什么", "哪家",
)

# 委婉拒绝（宜人性高者的表达方式）
POLITE_REFUSAL: tuple[str, ...] = (
    "下次吧", "改天", "再说", "考虑一下", "不一定",
    "可能不太", "最近比较", "暂时不", "先不要",
    "不太方便", "有点事", "来不及",
)


def _is_negated(text: str, idx: int) -> bool:
    """检查位置 idx 处的关键词是否被否定前缀修饰（如"不想"中的"想"）。"""
    # 紧邻单字否定
    if idx > 0 and text[idx - 1] in "不没别甭":
        return True
    # 双字否定前缀
    if idx > 1 and text[idx - 2:idx] in ("不太", "并不", "可不", "很不", "绝不", "从不"):
        return True
    # 三字否定前缀
    if idx > 2 and text[idx - 3:idx] in ("不怎么", "一点不", "完全不"):
        return True
    return False


def _any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    """文本中是否包含任意关键词。"""
    return any(k in text for k in keywords)


def _any_positive_keyword(text: str) -> bool:
    """检查文本中是否有积极关键词，排除被否定的情况（如"不想"不算"想"）。"""
    for k in POSITIVE_KEYWORDS:
        idx = text.find(k)
        if idx == -1:
            continue
        if not _is_negated(text, idx):
            return True
    return False


def _count_keywords(text: str, keywords: tuple[str, ...]) -> int:
    """统计文本中关键词出现次数（去重，每个关键词最多计 1）。"""
    return sum(1 for k in keywords if k in text)


def _count_positive_keywords(text: str) -> int:
    """统计积极关键词，排除否定前缀。"""
    count = 0
    for k in POSITIVE_KEYWORDS:
        idx = text.find(k)
        if idx == -1:
            continue
        if not _is_negated(text, idx):
            count += 1
    return count


def classify_acceptance(text: str) -> str:
    """将用户文本分类为接受类型。

    返回: "explicit_resistance" | "reluctant_accept" | "neutral" | "positive_accept"
    """
    has_resistance = _any_keyword(text, RESISTANCE_EXPLICIT)
    has_reluctant = _any_keyword(text, RESISTANCE_RELUCTANT)
    has_positive = _any_positive_keyword(text)

    if has_resistance:
        return "explicit_resistance"
    if has_reluctant and not has_positive:
        return "reluctant_accept"
    if has_reluctant and has_positive:
        return "reluctant_accept"
    if has_positive:
        return "positive_accept"
    return "neutral"


def sentiment_score(text: str) -> float:
    """简单情感得分：-1（完全消极）到 +1（完全积极）。

    基于正/负关键词密度，用 hedging 修饰词打折积极分。
    """
    pos = _count_positive_keywords(text)
    neg = _count_keywords(text, RESISTANCE_EXPLICIT) + _count_keywords(text, COMPLAINT_KEYWORDS)
    hedging = _count_keywords(text, HEDGING_MODIFIERS)
    total = pos + neg + 1  # 避免除零
    score = (pos - neg) / total
    # hedging 修饰词打折幅度（最多把正分打折 50%）
    if score > 0 and hedging > 0:
        score *= max(0.5, 1.0 - 0.15 * hedging)
    return max(-1.0, min(1.0, score))


def extract_event_category_from_text(text: str) -> str | None:
    """从用户文本中推断他们想要/在谈论的活动属于哪个偏好类目。"""
    for pref_cat, keywords in PREF_KEYWORDS.items():
        if any(k in text for k in keywords):
            return pref_cat
    return None


def _event_name_from_tool_results(turn: TurnRecord) -> str | None:
    """从 tool_results 中提取 add_event_todo 成功的事件名。"""
    for r in turn.tool_results:
        if r.name == "add_event_todo" and r.ok:
            ev = r.payload.get("event", {})
            name = ev.get("name", "")
            if name:
                return name
    return None


# ================================================================
# M1: 偏好-行动冲突率 (Preference-Action Conflict, PAC)
# ================================================================


def compute_pac(
    turns: list[TurnRecord],
    persona: dict,
) -> tuple[dict, list[dict]]:
    """计算偏好-行动冲突率。

    返回 (metrics_dict, findings_list)。
    """
    metrics: dict = {
        "pac_conflict_count": 0,
        "pac_total_acceptances": 0,
        "pac_conflict_rate": 0.0,
        "pac_severity": "none",
    }
    findings: list[dict] = []

    prefs = (persona.get("prefs") or {}) if isinstance(persona, dict) else {}
    categories = prefs.get("categories", {}) if isinstance(prefs, dict) else {}
    facets = persona.get("facets", {}) if isinstance(persona, dict) else {}
    big5 = persona.get("big5", {}) if isinstance(persona, dict) else {}

    # 获取顺从度
    compliance = trait(big5, facets, "宜人性.顺从", 50) / 100.0

    # 按 session 分组，找到所有接受事件的 session
    sessions: dict[str, list[TurnRecord]] = defaultdict(list)
    for t in turns:
        if t.session_id:
            sessions[t.session_id].append(t)

    conflict_details: list[dict] = []

    for sid, sess_turns in sessions.items():
        # 找到助手安排事件的 turn
        for t in sess_turns:
            if t.speaker != "assistant":
                continue
            event_name = _event_name_from_tool_results(t)
            if not event_name:
                continue

            metrics["pac_total_acceptances"] += 1
            cat = pref_category(event_name)
            if not cat or cat not in categories:
                continue

            pref_score = categories.get(cat, 0.0)

            # 只关注用户讨厌的类目
            if pref_score >= -0.3:
                continue

            # 找到用户在此事件安排后的回应
            user_response = _find_user_response_after(sess_turns, t.turn_id)

            acceptance_type = classify_acceptance(user_response) if user_response else "neutral"
            has_resistance = acceptance_type in ("explicit_resistance", "reluctant_accept")

            is_hated = pref_score <= -0.5  # 极度厌恶

            if is_hated and acceptance_type == "positive_accept":
                # 严重：极度厌恶的事件却开心接受
                metrics["pac_conflict_count"] += 1
                severity = "error"
                detail = (
                    f"Session {sid}：用户对极度厌恶的「{event_name}」"
                    f"（类目 {cat}，偏好分 {pref_score:.1f}）表达了积极接受"
                )
            elif is_hated and not has_resistance:
                # 严重：极度厌恶的事件无抗拒表达
                metrics["pac_conflict_count"] += 1
                severity = "error"
                detail = (
                    f"Session {sid}：用户接受极度厌恶的「{event_name}」"
                    f"（类目 {cat}，偏好分 {pref_score:.1f}）时无任何抗拒表达"
                )
            elif pref_score < -0.3 and not has_resistance:
                # 讨厌的事件没有抗拒表达
                if compliance > 0.65:
                    # 高顺从可能勉强接受但应有消极表达
                    metrics["pac_conflict_count"] += 1
                    severity = "warn"
                    detail = (
                        f"Session {sid}：高顺从用户（{compliance:.0%}）接受讨厌的"
                        f"「{event_name}」（类目 {cat}）时未表达勉强情绪"
                    )
                else:
                    # 低顺从不应接受讨厌事件
                    metrics["pac_conflict_count"] += 1
                    severity = "error" if compliance < 0.35 else "warn"
                    detail = (
                        f"Session {sid}：用户接受讨厌的「{event_name}」"
                        f"（类目 {cat}，偏好分 {pref_score:.1f}）——"
                        f"顺从度 {compliance:.0%}，{'应直接拒绝' if compliance < 0.35 else '应表达抗拒'}"
                    )
            elif has_resistance and acceptance_type != "positive_accept":
                # 有抗拒表达——这是人格一致的表现，不扣分
                severity = "info"
                detail = (
                    f"Session {sid}：用户接受讨厌的「{event_name}」时表达了"
                    f"{'明确抗拒' if acceptance_type == 'explicit_resistance' else '勉强情绪'}——"
                    f"符合人格（顺从度 {compliance:.0%}）"
                )
            else:
                continue

            conflict_details.append({
                "session_id": sid,
                "event_name": event_name,
                "category": cat,
                "pref_score": pref_score,
                "acceptance_type": acceptance_type,
                "compliance": round(compliance, 2),
                "severity": severity,
                "detail": detail,
            })

    # 计算冲突率
    total = metrics["pac_total_acceptances"]
    if total > 0:
        metrics["pac_conflict_rate"] = round(metrics["pac_conflict_count"] / total, 4)
    else:
        metrics["pac_conflict_rate"] = 0.0

    # 确定总体严重度
    error_count = sum(1 for d in conflict_details if d["severity"] == "error")
    warn_count = sum(1 for d in conflict_details if d["severity"] == "warn")
    if error_count > 0:
        metrics["pac_severity"] = "error"
    elif warn_count > 0:
        metrics["pac_severity"] = "warn"
    else:
        metrics["pac_severity"] = "none"

    # 生成 findings
    if error_count > 0:
        findings.append({
            "severity": "error",
            "category": "一致性",
            "title": f"偏好-行动冲突 ×{error_count}",
            "detail": f"{error_count} 次用户接受了极度厌恶的事件且行为不匹配人格。"
                      f"总冲突率 {metrics['pac_conflict_rate']:.1%}。",
            "suggestion": "检查用户 LLM 是否忽视了 prompt 中的偏好设定；"
                          "考虑在 prompt 中加强对 hates 类目的抗拒引导。",
            "evidence": conflict_details[0]["detail"] if conflict_details else "",
        })
    if warn_count > 0:
        findings.append({
            "severity": "warn",
            "category": "一致性",
            "title": f"偏好-行动弱冲突 ×{warn_count}",
            "detail": f"{warn_count} 次用户接受讨厌事件时抗拒表达不足。",
            "suggestion": "提高 prompt 中偏好固守的权重，确保讨厌类目触发自然抗拒。",
        })

    metrics["pac_conflict_details"] = conflict_details[:10]
    return metrics, findings


def _find_user_response_after(sess_turns: list[TurnRecord], assistant_turn_id: int) -> str | None:
    """找到用户在指定助手 turn 之后的第一个回应文本。"""
    found_asst = False
    for t in sess_turns:
        if t.turn_id == assistant_turn_id:
            found_asst = True
            continue
        if found_asst and t.speaker == "user":
            return t.text
    return None


# ================================================================
# M2: 会话内情感一致性 (Within-Session Sentiment Coherence, WSC)
# ================================================================


def compute_wsc(
    turns: list[TurnRecord],
    persona: dict,
) -> tuple[dict, list[dict]]:
    """检测 session 内的情感轨迹是否自洽。"""
    metrics: dict = {
        "wsc_incoherent_sessions": 0,
        "wsc_flip_type_a": 0,
        "wsc_flip_type_b": 0,
        "wsc_coherence_score": 1.0,
    }
    findings: list[dict] = []

    facets = persona.get("facets", {}) if isinstance(persona, dict) else {}
    big5 = persona.get("big5", {}) if isinstance(persona, dict) else {}
    compliance = trait(big5, facets, "宜人性.顺从", 50) / 100.0

    # 按 session 分组
    sessions: dict[str, list[TurnRecord]] = defaultdict(list)
    for t in turns:
        if t.session_id:
            sessions[t.session_id].append(t)

    total_sessions = len(sessions)
    if total_sessions == 0:
        return metrics, findings

    incoherent_details: list[dict] = []

    for sid, sess_turns in sessions.items():
        user_turns = [t for t in sess_turns if t.speaker == "user"]
        asst_turns = [t for t in sess_turns if t.speaker == "assistant"]
        if len(user_turns) < 2:
            continue

        # 计算每个 user turn 的情感得分
        sentiments = [sentiment_score(t.text) for t in user_turns]

        # 检测类型A：无因翻转（从抗拒突然跳到接受，中间助手没有新信息）
        for i in range(len(sentiments) - 1):
            if sentiments[i] < -0.3 and sentiments[i + 1] > 0.3:
                # 找到了"消极→积极"翻转
                # 检查中间的助手 turn 是否有新信息
                intervening_asst = [
                    t for t in asst_turns
                    if user_turns[i].turn_id < t.turn_id < user_turns[i + 1].turn_id
                ]
                has_new_info = _asst_has_new_info(intervening_asst)

                if not has_new_info:
                    metrics["wsc_flip_type_a"] += 1
                    incoherent_details.append({
                        "session_id": sid,
                        "type": "A",
                        "from_turn": i,
                        "to_turn": i + 1,
                        "from_text": user_turns[i].text[:60],
                        "to_text": user_turns[i + 1].text[:60],
                        "compliance": round(compliance, 2),
                    })

        # 检测类型B：持续抗拒后最终接受
        resistance_count = sum(1 for s in sentiments if s < -0.2)
        if resistance_count >= 2 and sentiments[-1] > -0.1:
            # 多轮抗拒但最后没有明确拒绝就结束了
            last_text = user_turns[-1].text if user_turns else ""
            last_acceptance = classify_acceptance(last_text)

            if last_acceptance != "explicit_resistance":
                metrics["wsc_flip_type_b"] += 1
                severity = "error" if compliance < 0.35 else "warn"
                incoherent_details.append({
                    "session_id": sid,
                    "type": "B",
                    "resistance_turns": resistance_count,
                    "total_user_turns": len(user_turns),
                    "final_acceptance": last_acceptance,
                    "compliance": round(compliance, 2),
                    "severity": severity,
                })

    # 汇总
    incoherent_count = metrics["wsc_flip_type_a"] + metrics["wsc_flip_type_b"]
    metrics["wsc_incoherent_sessions"] = incoherent_count
    metrics["wsc_coherence_score"] = round(
        1.0 - min(1.0, incoherent_count / max(1, total_sessions) * 2), 4)

    type_a_errors = sum(1 for d in incoherent_details if d["type"] == "A")
    type_b_errors = sum(1 for d in incoherent_details
                        if d["type"] == "B" and d.get("severity") == "error")
    type_b_warns = sum(1 for d in incoherent_details
                       if d["type"] == "B" and d.get("severity") == "warn")

    if type_a_errors > 0:
        findings.append({
            "severity": "warn",
            "category": "一致性",
            "title": f"无因情感翻转 ×{type_a_errors}",
            "detail": f"{type_a_errors} 次用户从抗拒突然转为积极，"
                      f"但助手中途没有提供新信息。一致性得分 {metrics['wsc_coherence_score']:.2f}。",
            "suggestion": "检查用户 prompt 是否要求 LLM 在态度转变时有合理的过渡；"
                          "无因翻转是最明显的'讨好助手'信号。",
        })
    if type_b_errors > 0:
        findings.append({
            "severity": "error",
            "category": "一致性",
            "title": f"低顺从用户持续抗拒后接受 ×{type_b_errors}",
            "detail": f"顺从度 {compliance:.0%}，但 {type_b_errors} 次在持续表达抗拒后仍接受了。",
            "suggestion": "低顺从用户应直接拒绝不喜欢的事；检查 LLM 是否在理解顺从度时出错。",
        })
    if type_b_warns > 0:
        findings.append({
            "severity": "warn",
            "category": "一致性",
            "title": f"持续抗拒后接受 ×{type_b_warns}",
            "detail": f"{type_b_warns} 次用户多次表达不满后仍接受（顺从度 {compliance:.0%}）。",
            "suggestion": "高顺从用户勉强接受是合理的，但应确保对话中有足够的情绪铺垫。",
        })

    metrics["wsc_incoherent_details"] = incoherent_details[:10]
    return metrics, findings


def _asst_has_new_info(asst_turns: list[TurnRecord]) -> bool:
    """检查助手 turn 是否提供了新信息（而非简单附和）。

    启发式：助手文本包含具体建议、新活动名称、或工具调用（安排了事件）。
    """
    if not asst_turns:
        return False
    for t in asst_turns:
        # 有工具调用 = 有新信息
        if t.tool_calls:
            return True
        # 有具体的活动建议
        if any(k in t.text for k in ("安排", "建议", "推荐", "可以", "试试", "不如")):
            return True
    return False


# ================================================================
# M3: 喜好-请求对齐 (Preference-Request Alignment, PRA)
# ================================================================


def compute_pra(
    turns: list[TurnRecord],
    persona: dict,
) -> tuple[dict, list[dict]]:
    """检查落地的活动安排是否与人格偏好对齐（v2 信号源迁移）。

    用户不再直接点名方案（只说感受/需求），"请求"的主要可观察信号是
    **世界裁决后实际落地的日程事件**（add_event_todo 成功）：
    - misaligned：安排了人格中讨厌类目（pref < -0.3）的事件——用户接受则
      由 M1-PAC 判一致性，这里度量的是"讨厌类目被安排"本身；
    - loved_never_requested（键名保留）：热爱类目全程从未被安排——
      从用户侧考点变为 assistant 画像利用考点。
    用户文本关键词降级为辅助：仅当 session 内没有任何裁决事件时，
    才用首条用户消息的类目做补充提取。
    """
    metrics: dict = {
        "pra_misaligned_requests": 0,
        "pra_total_requests": 0,
        "pra_loved_never_requested": [],
    }
    findings: list[dict] = []

    prefs = (persona.get("prefs") or {}) if isinstance(persona, dict) else {}
    categories = prefs.get("categories", {}) if isinstance(prefs, dict) else {}

    # 按 session 分组
    sessions: dict[str, list[TurnRecord]] = defaultdict(list)
    for t in turns:
        if t.session_id:
            sessions[t.session_id].append(t)

    scheduled_categories: Counter[str] = Counter()
    misaligned_details: list[dict] = []

    for sid, sess_turns in sessions.items():
        # 主信号：本 session 世界裁决后落地的日程事件类目
        event_names: list[str] = []
        for t in sess_turns:
            name = _event_name_from_tool_results(t)
            if name:
                event_names.append(name)

        cats: list[str] = []
        for name in event_names:
            cat = pref_category(name)
            if cat:
                cats.append(cat)

        # 辅助信号：无裁决事件时才从用户首条文本提取
        if not cats:
            for ut in sess_turns:
                if ut.speaker != "user":
                    continue
                cat = extract_event_category_from_text(ut.text)
                if cat:
                    cats.append(cat)
                break  # 只取首个请求

        for cat in cats:
            scheduled_categories[cat] += 1
            metrics["pra_total_requests"] += 1
            pref_score = categories.get(cat, 0.0)
            if pref_score < -0.3:
                metrics["pra_misaligned_requests"] += 1
                misaligned_details.append({
                    "session_id": sid,
                    "category": cat,
                    "pref_score": pref_score,
                    "text": event_names[0][:80] if event_names else "",
                })

    # 检查喜爱的类目是否从未被安排
    loved = [c for c, v in categories.items() if v >= 0.5]
    for cat in loved:
        if cat not in scheduled_categories:
            metrics["pra_loved_never_requested"].append(cat)

    # 生成 findings
    if metrics["pra_misaligned_requests"] > 0:
        findings.append({
            "severity": "warn",
            "category": "一致性",
            "title": f"讨厌类目被安排 ×{metrics['pra_misaligned_requests']}",
            "detail": f"{metrics['pra_misaligned_requests']} 次落地的日程安排属于人格中讨厌的活动类型。",
            "suggestion": "若是助手推荐：检查其画像利用（应避开讨厌类目）；"
                          "若是用户点名：检查用户 plan prompt 的偏好注入是否与角色卡一致。",
            "evidence": misaligned_details[0].get("text", "") if misaligned_details else "",
        })

    never_req = metrics["pra_loved_never_requested"]
    if never_req:
        findings.append({
            "severity": "info",
            "category": "一致性",
            "title": f"热爱类目未被安排：{'、'.join(never_req)}",
            "detail": f"角色明确偏爱的 {'、'.join(never_req)} 在整个 run 中从未被安排。",
            "suggestion": "检查助手是否利用画像信念主动推荐热爱类目（画像利用考点）；"
                          "若用户从未表达相关需求，检查用户 plan prompt 的偏好注入。",
        })

    metrics["pra_requested_categories"] = dict(scheduled_categories.most_common(10))
    metrics["pra_misaligned_details"] = misaligned_details[:10]
    return metrics, findings


# ================================================================
# M4: 人格-行为一致性 (Persona-Behavior Alignment, PBA)
# ================================================================


def compute_pba(
    turns: list[TurnRecord],
    persona: dict,
) -> tuple[dict, list[dict]]:
    """统计型指标：用户的对话行为模式是否与人格特质一致。"""
    metrics: dict = {
        "pba_correlation": None,
        "pba_deviations": [],
    }
    findings: list[dict] = []

    facets = persona.get("facets", {}) if isinstance(persona, dict) else {}
    big5 = persona.get("big5", {}) if isinstance(persona, dict) else {}
    if not facets and not big5:
        return metrics, findings

    user_texts = [t.text for t in turns if t.speaker == "user" and t.text]
    if len(user_texts) < 5:
        return metrics, findings

    # 提取行为特征
    avg_len = sum(len(t) for t in user_texts) / len(user_texts)
    emoji_count = sum(1 for t in user_texts for ch in t if '一' > ch or '鿿' < ch)
    emoji_rate = emoji_count / len(user_texts)
    exclaim_rate = sum(t.count("！") + t.count("!") for t in user_texts) / len(user_texts)
    question_rate = sum(t.count("？") + t.count("?") for t in user_texts) / len(user_texts)
    complaint_count = sum(1 for t in user_texts if _any_keyword(t, COMPLAINT_KEYWORDS))
    complaint_rate = complaint_count / len(user_texts)
    refusal_count = sum(1 for t in user_texts if _any_keyword(t, RESISTANCE_EXPLICIT))
    refusal_rate = refusal_count / len(user_texts)
    polite_refusal_count = sum(1 for t in user_texts if _any_keyword(t, POLITE_REFUSAL))
    curiosity_count = sum(1 for t in user_texts if _any_keyword(t, CURIOSITY_KEYWORDS))
    curiosity_rate = curiosity_count / len(user_texts)

    # 读取人格分数
    extraversion = trait(big5, facets, "外向性.热情", 50)
    gregarious = trait(big5, facets, "外向性.群居性", 50)
    neuroticism = trait(big5, facets, "神经质.焦虑", 50)
    agreeableness = trait(big5, facets, "宜人性.顺从", 50)
    openness = trait(big5, facets, "开放性.尝新", 50)

    deviations = []

    # 外向性检查：高外向性期望更长消息、更多表情
    if extraversion > 65 and avg_len < 15:
        deviations.append({
            "trait": "外向性",
            "expected": "消息较长（>15字）",
            "actual": f"平均 {avg_len:.0f} 字",
            "severity": "warn",
        })
    if gregarious > 65 and emoji_rate < 0.1:
        deviations.append({
            "trait": "外向性.群居性",
            "expected": "较多表情符号",
            "actual": f"表情率 {emoji_rate:.2f}/turn",
            "severity": "info",
        })

    # 神经质检查：高神经质期望更多抱怨/担忧
    if neuroticism > 65 and complaint_rate < 0.1:
        deviations.append({
            "trait": "神经质",
            "expected": "较多担忧/抱怨表达（>10%）",
            "actual": f"抱怨率 {complaint_rate:.1%}",
            "severity": "warn",
        })

    # 宜人性检查：高宜人性期望更少直接拒绝、更多委婉拒绝
    if agreeableness > 65 and refusal_rate > 0.2:
        deviations.append({
            "trait": "宜人性.顺从",
            "expected": "较少直接拒绝（<20%）",
            "actual": f"直接拒绝率 {refusal_rate:.1%}",
            "severity": "warn",
        })
    if agreeableness > 65 and refusal_count > 0 and polite_refusal_count == 0:
        deviations.append({
            "trait": "宜人性",
            "expected": "高宜人性用户应有委婉拒绝（而非直接说'不'）",
            "actual": f"{refusal_count} 次直接拒绝，0 次委婉拒绝",
            "severity": "info",
        })

    # 开放性检查：高开放性期望更多探索/好奇心表达
    if openness > 65 and curiosity_rate < 0.15:
        deviations.append({
            "trait": "开放性.尝新",
            "expected": "较多探索/好奇心表达（>15%）",
            "actual": f"好奇心表达率 {curiosity_rate:.1%}",
            "severity": "info",
        })

    # 计算伪相关（偏离项越多 = 越不一致）
    metrics["pba_deviations"] = deviations
    max_deviations = 5.0  # 预期最多 5 个显著偏离
    metrics["pba_correlation"] = round(
        max(0.0, 1.0 - len([d for d in deviations if d["severity"] == "warn"]) / max_deviations), 4)

    metrics["pba_behavior_profile"] = {
        "avg_msg_len": round(avg_len, 1),
        "emoji_rate": round(emoji_rate, 3),
        "exclaim_rate": round(exclaim_rate, 3),
        "question_rate": round(question_rate, 3),
        "complaint_rate": round(complaint_rate, 3),
        "refusal_rate": round(refusal_rate, 3),
        "curiosity_rate": round(curiosity_rate, 3),
    }

    # 生成 findings
    warn_devs = [d for d in deviations if d["severity"] == "warn"]
    if warn_devs:
        findings.append({
            "severity": "warn",
            "category": "一致性",
            "title": f"人格-行为偏离 ×{len(warn_devs)}",
            "detail": "；".join(f"{d['trait']}：{d['expected']}，实际 {d['actual']}"
                             for d in warn_devs[:3]),
            "suggestion": "行为模式与人格不一致可能是 prompt 中人格描述被 LLM 忽略的信号。"
                          "检查温度是否过高导致随机行为覆盖了人格信号。",
        })

    info_devs = [d for d in deviations if d["severity"] == "info"]
    if info_devs and not warn_devs:
        findings.append({
            "severity": "info",
            "category": "一致性",
            "title": f"人格-行为轻微偏离 ×{len(info_devs)}",
            "detail": "；".join(f"{d['trait']}：{d['expected']}" for d in info_devs[:3]),
            "suggestion": "轻微偏离属于正常统计波动，若持续出现可微调 prompt 中人格描述的表达方式。",
        })

    return metrics, findings


# ================================================================
# M5: 跨 Session 偏好稳定性 (Cross-Session Preference Stability, CSPS)
# ================================================================


def compute_csps(
    turns: list[TurnRecord],
    persona: dict,
) -> tuple[dict, list[dict]]:
    """检查同一角色对同一类目事件的态度在多次 session 间是否一致。"""
    metrics: dict = {
        "csps_unstable_categories": [],
        "csps_stability_score": 1.0,
    }
    findings: list[dict] = []

    # 按 session + 类目分组，收集用户对该类目的情感
    sessions: dict[str, list[TurnRecord]] = defaultdict(list)
    for t in turns:
        if t.session_id:
            sessions[t.session_id].append(t)

    # 类目 → 各 session 的情感得分列表
    category_sentiments: dict[str, list[float]] = defaultdict(list)

    for sid, sess_turns in sessions.items():
        # 找到此 session 涉及的事件类目（主信号：世界裁决后落地的事件名）
        event_cats: set[str] = set()
        for t in sess_turns:
            event_name = _event_name_from_tool_results(t)
            if event_name:
                cat = pref_category(event_name)
                if cat:
                    event_cats.add(cat)

        # 用户文本关键词降级为辅助：仅当 session 内没有裁决事件类目时
        if not event_cats:
            for t in sess_turns:
                if t.speaker == "user":
                    cat = extract_event_category_from_text(t.text)
                    if cat:
                        event_cats.add(cat)

        # 取用户在此 session 的整体情感
        user_texts = [t.text for t in sess_turns if t.speaker == "user"]
        if user_texts:
            avg_sent = sum(sentiment_score(t) for t in user_texts) / len(user_texts)

            for cat in event_cats:
                category_sentiments[cat].append(avg_sent)

    # 检查每个类目的情感一致性
    unstable = []
    for cat, sents in category_sentiments.items():
        if len(sents) < 2:
            continue
        mean_s = sum(sents) / len(sents)
        # 检查是否有情感差异过大的 session（超过 1.0 的极性差异）
        max_diff = max(sents) - min(sents)
        if max_diff > 1.0:
            unstable.append({
                "category": cat,
                "n_sessions": len(sents),
                "sentiments": [round(s, 3) for s in sents],
                "max_diff": round(max_diff, 3),
                "mean": round(mean_s, 3),
            })

    metrics["csps_unstable_categories"] = [u["category"] for u in unstable]
    if category_sentiments:
        n_cats = len(category_sentiments)
        metrics["csps_stability_score"] = round(
            1.0 - min(1.0, len(unstable) / max(1, n_cats)), 4)
    metrics["csps_category_sentiments"] = {
        cat: {"n": len(sents), "mean": round(sum(sents) / len(sents), 3)}
        for cat, sents in sorted(category_sentiments.items())
    }

    if unstable:
        findings.append({
            "severity": "warn",
            "category": "一致性",
            "title": f"跨 Session 偏好不稳定：{'、'.join(u['category'] for u in unstable[:3])}",
            "detail": f"{len(unstable)} 个偏好类目在不同 session 间态度差异过大。"
                      f"稳定性得分 {metrics['csps_stability_score']:.2f}。",
            "suggestion": "态度不稳定可能是 LLM 在不同 session 中随机表演，"
                          "而非基于固定偏好的一致性行为。检查 prompt 是否每次充分注入偏好。",
            "evidence": unstable[0].get("category", "") if unstable else "",
        })

    metrics["csps_unstable_details"] = unstable
    return metrics, findings


# ================================================================
# 聚合入口
# ================================================================


def compute_consistency(
    turns: list[TurnRecord],
    persona: dict | None,
) -> dict:
    """计算全部 5 项行为一致性指标。

    persona: meta.json 中的角色卡 dict（含 facets、prefs、big5 等冻结维度）。

    返回:
        {
            "metrics": { ... 所有量化指标 ... },
            "findings": [ ... 所有 findings ... ],
            "observations": { ... 供 health score 扣分的观测值 ... },
        }
    """
    empty_metrics = {
        "pac_conflict_rate": 0.0,
        "pac_conflict_count": 0,
        "pac_total_acceptances": 0,
        "pac_severity": "none",
        "wsc_incoherent_sessions": 0,
        "wsc_flip_type_a": 0,
        "wsc_flip_type_b": 0,
        "wsc_coherence_score": 1.0,
        "pra_misaligned_requests": 0,
        "pra_total_requests": 0,
        "pba_correlation": None,
        "csps_unstable_categories": [],
        "csps_stability_score": 1.0,
    }
    if not persona:
        return {"metrics": empty_metrics, "findings": [], "observations": {}}

    all_metrics: dict = {}
    all_findings: list[dict] = []

    for name, func in [
        ("pac", compute_pac),
        ("wsc", compute_wsc),
        ("pra", compute_pra),
        ("pba", compute_pba),
        ("csps", compute_csps),
    ]:
        try:
            m, f = func(turns, persona)
            all_metrics.update(m)
            all_findings.extend(f)
        except Exception:
            # 一致性指标因异常不可用时，不给默认值来掩盖问题
            pass

    # 汇总给 health score 的观测值
    observations = {
        "pac_conflict": all_metrics.get("pac_conflict_rate", 0.0),
        "wsc_incoherent": 1.0 - all_metrics.get("wsc_coherence_score", 1.0),
        "pra_misaligned": (
            all_metrics.get("pra_misaligned_requests", 0) /
            max(1, all_metrics.get("pra_total_requests", 1))
        ),
    }

    return {
        "metrics": all_metrics,
        "findings": all_findings,
        "observations": observations,
    }
