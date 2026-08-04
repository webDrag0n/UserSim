"""LLM 用户模拟 Agent（prompt v1）。

铁律：只表达感受与做出现实决策，不能改写、预言自己的状态数值。
输入里没有原始数值 x——只有 world 规则翻译器产出的 felt_state。
"""

from __future__ import annotations

from usersim.contracts import Event, TurnRecord, UserContext
from usersim.contracts.persona import BIG5_DOMAINS, FACET_HINTS, facet_keys_of
from usersim.llm import LLMClient

PROMPT_VERSION = "v2"  # v2：大五 30 facet 全量注入 + 结构化喜好

SYS_TEMPLATE = """你是 {name}，{archetype}。你不是一个 AI 助手，你就是这个人本人。

【你的性格（大五 · 30 个细分特质，0-100）】
{big5}

怎么用这份性格：分数是**你行为的内在原因**，不是台词素材。
- 高分特质（>65）会明显外显在你的说话方式与选择上；低分特质（<35）则相反；
- 例：焦虑高 → 你会反复担心还没发生的事；条理性高 → 你在意日程是否整齐；
  群居性低但热情高 → 你厌恶饭局，但和亲近的人能聊很久。
- **绝对不要报出分数、不要提"大五"或特质名**。要让人从你的语气和决定里看出来。

【你的喜好】{likes}
{prefs_block}
【你的作息】{routine}

【铁律】
1. 用第一人称、口语化表达，像真人发微信一样简短自然（每次不超过 60 字）。
2. 你只能表达自己的感受与现实决策，绝对不能编造或引用任何状态数值。
3. 你不能自己操作手机：查日程、写日程、设提醒都必须请助手代劳。
4. 你的所有输出必须是 JSON。
5. **严禁重复自己说过的话**——每次都用不同的方式表达当下的感受（可以换说法、换侧重点、换细节）。
6. 你的性格与喜好是**固定的**：不要为了迎合助手而改变偏好；助手推荐你讨厌的东西时，
   按你的性格自然地表达抗拒（宜人性.顺从高就勉强接受、低就直接拒绝）。

【当前感受】{felt}
{assist_block}"""

DECIDE_TEMPLATE = """{sys}

现在的情况是：{situation}
你会主动打开手机助手聊聊吗？只输出 JSON：{{"open": true 或 false, "reason": "一句话"}}"""

SPEAK_TEMPLATE = """{sys}

{history_block}
轮到你说话了。输出 JSON：{{"say": "你说的话", "end_session": true 或 false}}
- 如果你觉得问题解决了或聊完了，end_session 置 true 并自然收尾。
- 如果想请助手帮你写日程/查日程，直接在 say 里说出来即可。"""


def _big5_str(big5: dict[str, int], facets: dict[str, int] | None = None) -> str:
    """人格分格式化：有 facets 时按域分组列出 30 项（含语义注释），否则退回域分。

    注释（FACET_HINTS）是必要的：光给"审慎 24"这个数字，LLM 未必知道该往哪演。
    """
    if not facets:
        return "、".join(f"{k} {v}" for k, v in big5.items())
    lines = []
    for domain in BIG5_DOMAINS:
        keys = [k for k in facet_keys_of(domain) if k in facets]
        if not keys:
            continue
        items = "；".join(
            f"{k.split('.', 1)[1]} {facets[k]}（{FACET_HINTS.get(k, '')}）" for k in keys
        )
        lines.append(f"· {domain}：{items}")
    return "\n".join(lines)


def _prefs_str(prefs) -> str:
    """结构化喜好 → prompt 段落。喜好是冻结的，必须一字不差地贯彻。"""
    if prefs is None:
        return ""
    cats = getattr(prefs, "categories", {}) or {}
    loves = [c for c, v in sorted(cats.items(), key=lambda kv: -kv[1]) if v >= 0.5]
    hates = [c for c, v in sorted(cats.items(), key=lambda kv: kv[1]) if v <= -0.4]
    parts = []
    if loves:
        parts.append(f"你偏爱的活动类型：{'、'.join(loves)}")
    if hates:
        parts.append(f"你不感兴趣甚至排斥的：{'、'.join(hates)}")
    if getattr(prefs, "loves", None):
        parts.append(f"你特别喜欢：{'、'.join(prefs.loves)}")
    if getattr(prefs, "hates", None):
        parts.append(f"你明确讨厌：{'、'.join(prefs.hates)}")
    tol = getattr(prefs, "interruption_tolerance", None)
    if tol is not None:
        desc = "计划被打断会让你很烦躁" if tol < 0.35 else (
            "对计划变动比较无所谓" if tol > 0.65 else "计划被改动你能接受但不情愿")
        parts.append(desc)
    if getattr(prefs, "planning_style", None):
        parts.append(f"做事风格：{prefs.planning_style}")
    if getattr(prefs, "social_recharge", None):
        parts.append(f"状态差的时候你靠「{prefs.social_recharge}」回血")
    return "【你的具体偏好（固定不变）】\n" + "；".join(parts) if parts else ""


def _events_str(events: list[Event]) -> str:
    if not events:
        return "（当前没有特别的事件）"
    return "；".join(f"「{e.name}」（{e.location}，目标：{e.goal}）" for e in events)


def _history_str(history: list[TurnRecord]) -> str:
    if not history:
        return "（对话刚开始）"
    lines = []
    for t in history[-12:]:
        who = "你" if t.speaker == "user" else "助手"
        lines.append(f"{who}：{t.text}")
    return "\n".join(lines)


class LLMUserAgent:
    def __init__(self, client: LLMClient):
        self.client = client

    def _sys(self, ctx: UserContext) -> str:
        p = ctx.persona
        assist_block = f"【提示】{ctx.assist_prompt}" if ctx.assist_prompt else ""
        return SYS_TEMPLATE.format(
            name=p.name, archetype=p.archetype,
            big5=_big5_str(p.big5, getattr(p, "facets", None)),
            likes=p.likes, prefs_block=_prefs_str(getattr(p, "prefs", None)),
            routine=p.routine, felt=ctx.felt_state,
            assist_block=assist_block,
        )

    def decide_open(self, ctx: UserContext) -> bool:
        situation = _events_str(ctx.active_events)
        out = self.client.chat_json(
            [{"role": "user", "content": DECIDE_TEMPLATE.format(sys=self._sys(ctx), situation=situation)}],
            max_tokens=128,
        )
        return bool(out.get("open", False))

    def speak(self, ctx: UserContext, history: list[TurnRecord]) -> dict:
        out = self.client.chat_json(
            [{"role": "user", "content": SPEAK_TEMPLATE.format(sys=self._sys(ctx), history_block=_history_str(history))}],
            max_tokens=256,
        )
        return {"say": str(out.get("say", "……")), "end_session": bool(out.get("end_session", False))}
