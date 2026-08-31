"""LLM 用户模拟 Agent（prompt v3）。

铁律：只表达感受与做出现实决策，不能改写、预言自己的状态数值。
输入里没有原始数值 x——只有 world 规则翻译器产出的 felt_state。

v3：意图规划纯 LLM 化（废除规则版规划器）——plan() 让人格与当前感受直接
产出"想要什么"（want），并新增表达直白度调制（expression.explicitness_tier）：
"点名想做的事"（explicit）与"只说感受"（vague）两种模式随人格 facet 分档。
"""

from __future__ import annotations

from agents.user.standard.expression import explicitness_tier
from usersim.contracts import DialogueTurn, Event, UserContext
from usersim.contracts.agent_api import (
    INTENT_ACHIEVE,
    INTENT_CHAT,
    INTENT_EAT,
    INTENT_RECOVER,
    INTENT_SLEEP,
    INTENT_SOCIAL,
    INTENT_STIMULATE,
    PlanSlotRequest,
)
from usersim.contracts.persona import BIG5_DOMAINS, FACET_HINTS, facet_keys_of
from usersim.llm import LLMClient

PROMPT_VERSION = "v6.1"  # v6.1：utility_menu 带变体名（"最近做过"），修复变体失忆；v6：边际效用感知

SYS_TEMPLATE = """你是 {name}，{archetype}。

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
{expression_block}

【铁律】
1. 用第一人称。你在对**手机助手**说话，不是和朋友微信闲聊：有事说事、简短直接
   （每次不超过 50 字），少用语气词、网络梗和表情符号，不客套、不绕弯子。
2. 你只能表达自己的感受与现实决策，绝对不能编造或引用任何状态数值。
3. 你不能自己操作手机：查日程、写日程、设提醒都必须请助手代劳。
4. 你的所有输出必须是 JSON。
5. **严禁重复自己说过的话**——每次都用不同的方式表达当下的感受（可以换说法、换侧重点、换细节）。
   而且不要逐字复述【当前感受】的措辞——用具体生活细节表现它
   （例：不说"有点累"，说"眼皮打架""咖啡续到第三杯"；不说"压力大"，说"脑子被事情塞满了"）。
6. 你的性格与喜好是**固定的**：不要为了迎合助手而改变偏好；对助手的安排给出真实反馈——
   喜欢就开心接受，讨厌或腻了就按你的性格自然地抗拒（顺从高就勉强接受、低就直接拒绝）。
7. 你不是规划器：你只说想要的和感受到的。**具体去哪儿、怎么实现、花多少钱，都交给助手想办法**，
   你按自己的喜好接受或拒绝。
8. 表达模式按【你的表达习惯】：点名想做的事时不要说实现细节（不说地点、价位）；
   只说感受时不要自己给方案。
9. 参考【各活动现在对你的吸引力】做选择与反馈：
   - 括号里"最近做过"的具体花样你**记得自己做过**——助手再推荐它们时别说"没试过"；
   - "腻了/基本没什么用"的事别再提，也别接受——助手若又安排这类事，明确说
     "这个对我已经没什么用了"，拒绝并要求换一个；
   - "做太多次/效果明显打折"的事可以勉强接受，但要让助手听出来你觉得一般；
   - 做完一件事若感觉没什么效果，如实说"好像没什么用"，不捧场。

【当前感受】{felt}
{satiation_block}
{utility_block}
{weather_block}
{memory_block}
{assist_block}"""

DECIDE_TEMPLATE = """{sys}

现在的情况是：{situation}
你会主动打开手机助手聊聊吗？只输出 JSON：{{"open": true 或 false, "reason": "一句话"}}"""

SPEAK_TEMPLATE = """{sys}

{history_block}
轮到你说话了。输出 JSON：{{"say": "你说的话", "end_session": true 或 false}}
- 如果你觉得问题解决了或聊完了，end_session 置 true 并自然收尾——
  真人对助手说完事就结束，不会聊个没完。
- 如果想请助手帮你写日程/查日程，直接在 say 里说出来即可。
- 如果本次意图是明确想做的事：可以直接说想做什么，但具体地点、价位让助手想办法；
  如果只是模糊的感受：只描述你的感受和需求，让助手给方案。"""

PLAN_TEMPLATE = """{sys}

现在是【{slot_name}】。{situation}
想想你现在想要什么、感觉到什么。输出 JSON：
{{"intents": [{{"type": "eat|social|stimulate|recover|sleep|achieve|chat", "mode": "explicit|vague", "want": "一句口语化的需求或感受"}}]}}
- 0 到 3 条，按想要的强烈程度排序；真的没什么想要就输出 {{"intents": []}}。
- want 是一句口语化的需求或感受（如"想吃点好的犒劳自己"、"好累，什么都不想干"、"想吐槽下今天的事"）。
- type 含义：eat 想吃东西 / social 想见人说说话 / stimulate 想找点乐子 /
  recover 想休息放松 / sleep 想睡觉 / achieve 想做点正事 /
  chat 无目的的闲聊、分享或吐槽（不想要什么安排，就是想找人说说话）——
  没什么具体需求但想说话时用它，不要硬凹出一个需求。
- mode：explicit = 你明确想做某件事（说想做的事，但不说地点、价位等实现细节）；
  vague = 只是一种模糊的需要（只说感受，不自己给方案）。按【你的表达习惯】选择。
- 看看【你最近和助手聊过的事】：刚做过的活动别再提，真人会腻，想玩就换个新的。
- 参考【各活动现在对你的吸引力】：从"还很新鲜/没试过"的里面选想做的；
  全都腻了就说感受（vague），让助手帮你想新花样。"""

# plan_slot 契约只带 slot 序号（不含时刻表配置）——demo 侧内联时段名（与系统默认 4 时段一致）
_SLOT_NAMES = ("上午", "下午", "晚上", "深夜")

# LLM 可产出的意图类型（emergency 只能由世界注入，不允许 LLM 自编）
_PLAN_TYPES = {
    INTENT_EAT, INTENT_SOCIAL, INTENT_STIMULATE,
    INTENT_RECOVER, INTENT_SLEEP, INTENT_ACHIEVE, INTENT_CHAT,
}


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


def _history_str(history: list[DialogueTurn]) -> str:
    if not history:
        return "（对话刚开始）"
    lines = []
    for t in history[-12:]:
        who = "你" if t.speaker == "user" else "助手"
        lines.append(f"{who}：{t.text}")
    return "\n".join(lines)


def _parse_plan(out) -> list[dict]:
    """plan 输出解析：只保留合法 type 且 want 非空的条目；mode 非法时按 vague 处理。"""
    raw = out.get("intents", []) if isinstance(out, dict) else []
    if not isinstance(raw, list):
        return []
    intents = []
    for item in raw[:3]:
        if not isinstance(item, dict):
            continue
        itype = str(item.get("type", ""))
        want = str(item.get("want", "")).strip()
        if itype not in _PLAN_TYPES or not want:
            continue  # 未知 type / 空 want 直接丢弃
        mode = "explicit" if item.get("mode") == "explicit" else "vague"
        intents.append({"type": itype, "mode": mode, "want": want})
    return intents


class LLMUserAgent:
    def __init__(self, client: LLMClient):
        self.client = client

    def _sys(self, ctx: UserContext, memory_block: str = "", intent_description: str = "") -> str:
        p = ctx.persona
        assist_raw = ctx.assist_prompt or ""
        if intent_description:
            assist_raw = f"（你这次找助手是为了：{intent_description}）" + (f"\n{assist_raw}" if assist_raw else "")
        assist_block = f"【提示】{assist_raw}" if assist_raw else ""
        weather_block = f"【今日天气】{ctx.weather}" if ctx.weather else ""
        _, guidance = explicitness_tier(getattr(p, "facets", None))
        expression_block = f"【你的表达习惯】{guidance}"
        satiation_block = f"【最近的感觉】{ctx.satiation_note}" if ctx.satiation_note else ""
        utility_block = ("【各活动现在对你的吸引力】\n" + "\n".join(ctx.utility_menu)
                         ) if ctx.utility_menu else ""
        return SYS_TEMPLATE.format(
            name=p.name, archetype=p.archetype,
            big5=_big5_str(p.big5, getattr(p, "facets", None)),
            likes=p.likes, prefs_block=_prefs_str(getattr(p, "prefs", None)),
            routine=p.routine, expression_block=expression_block,
            felt=ctx.felt_state,
            satiation_block=satiation_block,
            utility_block=utility_block,
            weather_block=weather_block,
            memory_block=memory_block,
            assist_block=assist_block,
        )

    def plan(self, p: PlanSlotRequest, ctx: UserContext | None = None,
             memory_block: str = "") -> list[dict]:
        """纯 LLM 意图规划：返回 0~3 条 {"type", "mode", "want"}（按强烈程度排序）。

        状态-表达解耦：契约里的 urges/stress/energy/money 数值**不进 prompt**，
        LLM 只看到 persona、felt、时段、事件、天气、记忆与 assist_prompt。
        LLM 失败 / 解析失败 → 空列表（本 slot 无 session，由 runner 记 degraded）。
        """
        slot_name = _SLOT_NAMES[p.slot] if 0 <= p.slot < len(_SLOT_NAMES) else f"时段{p.slot}"
        if ctx is not None:
            # 用请求里新鲜的 assist_prompt 覆盖缓存 ctx 的过期值（其余字段至多才一个 slot 旧）
            ctx = ctx.model_copy(update={"assist_prompt": p.assist_prompt})
            sys = self._sys(ctx, memory_block=memory_block)
            situation = _events_str(ctx.active_events)
        else:
            # run 首个 slot 尚无缓存的 UserContext（契约不含 persona/felt）：
            # 退化为无人格的通用规划，表达习惯按中档默认
            _, guidance = explicitness_tier(None)
            sys = (f"你是一个普通人，正在考虑要不要找手机助手聊聊。\n"
                   f"【你的表达习惯】{guidance}\n"
                   f"{memory_block}".rstrip())
            situation = "（当前没有特别的事件）"
        try:
            out = self.client.chat_json(
                [{"role": "user", "content": PLAN_TEMPLATE.format(
                    sys=sys, slot_name=slot_name, situation=situation)}],
                max_tokens=2048,  # 推理模型地板：思考链会吃掉小预算导致空响应
            )
        except Exception:
            return []
        return _parse_plan(out)

    def decide_open(self, ctx: UserContext, memory_block: str = "", want: str = "") -> bool:
        situation = _events_str(ctx.active_events)
        if want:
            situation += f"\n（你心里正想着：{want}）"
        out = self.client.chat_json(
            [{"role": "user", "content": DECIDE_TEMPLATE.format(
                sys=self._sys(ctx, memory_block=memory_block), situation=situation)}],
            max_tokens=1024,  # 推理模型地板：思考链会吃掉小预算导致空响应
        )
        return bool(out.get("open", False))

    def speak(self, ctx: UserContext, history: list[DialogueTurn],
              memory_block: str = "", intent_description: str = "") -> dict:
        out = self.client.chat_json(
            [{"role": "user", "content": SPEAK_TEMPLATE.format(
                sys=self._sys(ctx, memory_block=memory_block, intent_description=intent_description),
                history_block=_history_str(history))}],
            max_tokens=2048,  # 推理模型地板：思考链会吃掉小预算导致空响应
        )
        return {"say": str(out.get("say", "……")), "end_session": bool(out.get("end_session", False))}
