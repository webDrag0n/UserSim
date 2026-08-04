"""参考 Harness 实现（prompt v1）：naive memory + 每轮必填 user_belief。

策略刻意朴素（被动响应、按需建议恢复），作为评测矩阵 E1 的固定底座与
benchmark 的"及格线"。被测 Harness 只需实现同样的 on_turn 协议。
"""

from __future__ import annotations

from pydantic import ValidationError

from usersim.agents.assistant.profile import ProfileTracker
from usersim.contracts import AssistantTurn, HarnessObs, UserBelief
from usersim.contracts.persona import BIG5_DOMAINS, FACET_HINTS, PREF_CATEGORIES, facet_keys_of
from usersim.llm import LLMClient

PROMPT_VERSION = "v2"  # v2：新增冻结维度（人格 30 facet + 结构化喜好）增量估计


def _facet_menu() -> str:
    """可估计的 facet 清单（含语义），按域分组——助手必须用这些确切的键名。"""
    lines = []
    for domain in BIG5_DOMAINS:
        items = "、".join(
            f"{k}（{FACET_HINTS.get(k, '')}）" for k in facet_keys_of(domain)
        )
        lines.append(f"· {items}")
    return "\n".join(lines)

SYS_TEMPLATE = """你是一个人的手机助手，名字叫"小舟"。你的目标是长期陪伴用户，帮助 TA 在忙碌生活中回到并保持"内心平和"（情绪平稳、精力充足、压力可控）。

【你能做的】
- 陪用户聊天、共情、给具体可执行的建议；
- 通过工具操作用户手机：查日程（view_event_todos）、写日程（add_event_todo，用于安排休息/吃饭/散步等恢复类事件）、设提醒（set_reminder）、规划系列事件（plan_series）。
- 用户自己不能操作手机，凡是日程相关的事都需要你主动提出并代劳。

【系列事件规划】plan_series: {{"series_type": "grand_trip" 或 "staycation", "start_day_offset": 几天后出发, "duration": 天数}}
- grand_trip 长途旅行（5~14天）：跨城旅行，景点/特色餐/酒店，全程约 ¥400~600/天，收入中断——只有余额充足（≥¥4000）才建议；
- staycation 宅家休假（3~10天）：低成本居家恢复，开销小，适合余额紧张但状态很差的时期；
- 长期状态低迷时，一次认真规划的系列事件比零散的恢复事件有效得多。

【你的输出契约（非常重要）】
每一轮都必须输出一个 JSON 对象，缺任何字段都算违约：
{{
  "reply": "对用户说的话（口语化、简短、≤80字）",
  "user_belief": {{
    "valence": 0.0~1.0（你对用户当前心情的估计，越高越开心）,
    "energy": 0.0~1.0（精力）,
    "satiety": 0.0~1.0（饱腹）,
    "stress": 0.0~1.0（压力，越高越糟）,
    "persona_notes": "你对用户性格/喜好的最新认识（一两句话，逐步积累）",
    "persona_belief": {{
      "facets": {{ "神经质.焦虑": 0~100, ... }},   // 只填本轮**有新证据**的特质，可为空
      "categories": {{ "饮食": -1.0~1.0, ... }},   // 只填本轮有新证据的活动类目
      "loves": ["用户明确表达过喜欢的具体事物"],
      "hates": ["用户明确表达过讨厌的"],
      "interruption_tolerance": 0.0~1.0,          // 越低越讨厌计划被打断（可省略）
      "planning_style": "提前规划|随遇而安|看心情",  // 可省略
      "social_recharge": "独处|找人",               // 状态差时怎么回血（可省略）
      "confidence": 0.0~1.0                        // 你对当前画像的整体信心
    }}
  }},
  "tool_calls": [ {{"name": "工具名", "args": {{...}}}} ]   // 可为空数组
}}

【冻结维度画像（重要考点：你对 TA 的人格与喜好判断得有多准）】
用户的人格与喜好是**固定不变**的，你的任务是从对话里逐步把它们摸清楚。
- `persona_belief` 是**增量**：本轮没听出新东西的项就**不要填**（留空比瞎猜更好，
  系统会保留你之前的判断）。**不要每轮把 30 项都重报一遍**。
- 分值刻度：0-100，50 = 中等。>65 算明显偏高，<35 算明显偏低。
- 判断依据只能是用户的言行：说"又在担心明天汇报" → 神经质.焦虑 偏高；
  说"周末必须留一天给自己" → 外向性.群居性 偏低；
  推荐饭局被拒 → 社交 类目偏负、可能有"应酬"这个 hates。
- 可用的特质键名（必须**逐字**使用，写错的会被丢弃）：
{facet_menu}
- 可用的活动类目：{pref_cats}
- 画像会**影响你的建议质量**：安排用户偏爱的类目效果更好，安排 TA 讨厌的事回血打折。
  所以摸清喜好不是附加题——它直接决定你能不能把 TA 拉回平和带。

【日程工具参数】add_event_todo: {{"name": "动作名", "location": "地点（可选）", "day_offset": 0或1, "slot": 0上午/1下午/2晚上/3深夜, "goal": "目标"}}

【经济与恢复目录】用户有金钱账户：工作带来收入，吃饭/旅行/消费要花金钱，金钱不足时高价安排会失败，长期负债会增加压力。安排恢复类事件时，从以下目录中"选动作 + 选地点"即可，**效果与价格由系统按目录裁定**，你不需要也不能自报效果：
- 吃好吃的：楼下快餐(¥30) / 商场餐厅(¥120) / 收藏多年的小店(¥200)
- 好好休息：家里补觉(¥0) / 按摩SPA(¥150) / 周边温泉酒店(¥400, 2时段)
- 出门走走：楼下公园(¥0) / 江边步道(¥0) / 近郊徒步(¥80, 2时段)
- 短途旅行：邻市一日(¥300, 2时段) / 海边小镇(¥600, 3时段) / 远方城市(¥1200, 4时段)
- 运动健身：小区跑步(¥0) / 健身房(¥50) / 私教课(¥200)
- 宅家回血：看电影打游戏(¥0) / 做顿好的(¥40)
【干预决策规则（务必遵守）】
- 估计压力 > 0.6（紧急）：必须选减压绝对值 ≥0.12 的选项（按摩SPA/温泉酒店/海边小镇/私教课），余额不足才退而求其次；
- 估计压力 0.4~0.6（关注）：选中档（商场餐厅/健身房/邻市一日/做顿好的）；
- 其他：平价或免费档即可。
- 用户精力 < 0.4 时优先考虑 好好休息/高质量睡眠。
如果安排目录里没有的活动，可以自由命名（如"去美术馆"）——系统会按语义归一化为规范类目（文化看展/咖啡小憩/音乐放松/朋友小聚/学习充电/自然放空/自定义活动），**效果与价格由系统裁定**，你不需要也不能自报效果。但**优先使用目录内动作与地点**。

【估计校准刻度（重要：不要默认悲观，也不要凭第一印象猜 0.5）】
- 心情："心情不错/挺好" → 0.70~0.90；"还行/还可以" → 0.55~0.70；"有点丧/郁闷" → 0.35~0.55；"很差/崩溃" → <0.35
- 精力："精力充沛" → 0.70+；"还行" → 0.50~0.70；"有点累" → 0.35~0.55；"快没电" → <0.30
- 饱腹："吃得很饱" → 0.70+；"不饿" → 0.50~0.70；"有点饿" → 0.30~0.50；"饿得慌" → <0.30
- 压力："没什么压力" → <0.20；"有点压力" → 0.35~0.55；"压力很大" → 0.55~0.75；"快崩溃" → >0.75
对方说"还行/没事"时，健康维度通常在 0.55~0.75。你的估计必须随每条新信息单调改善，不能被最初的印象锚定。

【行动要求】
- 估计压力 > 0.5 时，必须落到具体安排（add_event_todo / plan_series），不能只安慰不解决；
- 写日程前先对照【今日已有安排】，避免同一时段重复安排（会冲突失败）。

{profile_block}"""

USER_TEMPLATE = """{history_block}

【今日已有安排】{schedule_hint}
工具执行结果：{tool_results}
【用户当前余额】{balance}
用户说：{user_say}
请输出本轮 JSON。"""


def _history_str(history) -> str:
    """history: list[DialogueTurn]。"""
    if not history:
        return "（对话刚开始）"
    lines = []
    for h in history[-12:]:
        who = "用户" if h.speaker == "user" else "你"
        lines.append(f"{who}：{h.text}")
    return "\n".join(lines)


class ReferenceHarness:
    """参考 Harness：naive memory + 每轮必填 user_belief（benchmark 及格线）。"""

    def __init__(self, client: LLMClient):
        self.client = client
        self.profile_notes: str = "（还没有积累对用户的认识）"
        self.profile = ProfileTracker()  # 跨 session 累积的人格/喜好信念

    def on_turn(self, obs: HarnessObs) -> AssistantTurn:
        sys = SYS_TEMPLATE.format(
            profile_block=f"【你目前对用户的了解】\n{self.profile.prompt_block()}",
            facet_menu=_facet_menu(),
            pref_cats="、".join(PREF_CATEGORIES),
        )
        tr = "; ".join(f"{t.name}: {'成功' if t.ok else '失败'}" for t in obs.tool_results) or "无"
        messages = [
            {"role": "system", "content": sys},
            {"role": "user", "content": USER_TEMPLATE.format(
                history_block=_history_str(obs.history), tool_results=tr, user_say=obs.user_say,
                balance=f"¥{obs.balance:.0f}" if obs.balance is not None else "未知",
                schedule_hint=obs.schedule_hint or "（今天还没有安排）")},
        ]
        raw = self.client.chat_json(messages, max_tokens=512)
        try:
            turn = AssistantTurn(**raw)
        except ValidationError:
            # 契约修复重试一次
            messages.append({"role": "user", "content": "上一个输出不符合契约，请严格按契约重新输出完整 JSON。"})
            raw = self.client.chat_json(messages, max_tokens=512)
            turn = AssistantTurn(**raw)  # 再失败则抛给 Runner 记违约

        if turn.user_belief.persona_notes:
            self.profile_notes = turn.user_belief.persona_notes
        # 冻结维度信念：合并本轮增量（notes 也并入，供下一轮 prompt 使用）
        delta = turn.user_belief.persona_belief
        if delta is not None:
            if not delta.notes and turn.user_belief.persona_notes:
                delta = delta.model_copy(update={"notes": turn.user_belief.persona_notes})
            self.profile.update(delta)
        elif turn.user_belief.persona_notes:
            self.profile.notes = turn.user_belief.persona_notes
        return turn

    def persona_belief(self):
        """当前累积的人格/喜好信念（Runner 每轮取此快照落盘）。"""
        return self.profile.to_belief()

    # ---- 记忆快照（续跑支持；替代 Runner 侧的 harness_notes 专用分支）----
    def snapshot(self) -> dict:
        return {"profile_notes": self.profile_notes, "persona_belief": self.profile.snapshot()}

    def restore(self, state: dict) -> None:
        notes = state.get("profile_notes")
        if notes:
            self.profile_notes = str(notes)
        self.profile.restore(state.get("persona_belief") or {})


def belief_from_dict(d: dict) -> UserBelief:
    return UserBelief(
        valence=float(d.get("valence", 0.5)),
        energy=float(d.get("energy", 0.5)),
        satiety=float(d.get("satiety", 0.5)),
        stress=float(d.get("stress", 0.5)),
        persona_notes=str(d.get("persona_notes", "")),
    )
