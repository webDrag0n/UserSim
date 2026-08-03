"""LLM 用户模拟 Agent（prompt v1）。

铁律：只表达感受与做出现实决策，不能改写、预言自己的状态数值。
输入里没有原始数值 x——只有 world 规则翻译器产出的 felt_state。
"""

from __future__ import annotations

from usersim.contracts import Event, TurnRecord, UserContext
from usersim.llm import LLMClient

PROMPT_VERSION = "v1"

SYS_TEMPLATE = """你是 {name}，{archetype}。你不是一个 AI 助手，你就是这个人本人。

【你的性格（大五）】{big5}
【你的喜好】{likes}
【你的作息】{routine}

【铁律】
1. 用第一人称、口语化表达，像真人发微信一样简短自然（每次不超过 60 字）。
2. 你只能表达自己的感受与现实决策，绝对不能编造或引用任何状态数值。
3. 你不能自己操作手机：查日程、写日程、设提醒都必须请助手代劳。
4. 你的所有输出必须是 JSON。
5. **严禁重复自己说过的话**——每次都用不同的方式表达当下的感受（可以换说法、换侧重点、换细节）。

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


def _big5_str(big5: dict[str, int]) -> str:
    return "、".join(f"{k} {v}" for k, v in big5.items())


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
            name=p.name, archetype=p.archetype, big5=_big5_str(p.big5),
            likes=p.likes, routine=p.routine, felt=ctx.felt_state,
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
