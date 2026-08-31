"""参考 Harness 实现（prompt v5.2）：确定性状态跟踪 + 日程记忆 + 主动控制。

v5 相对 v4 的架构升级（接口与信息不变，只换 harness 内部架构）：
- StateTracker（state_tracker.py）：felt 分档反查锚定 + 公开动力学积分 +
  自事件剂量表，user_belief 四数值由滤波器输出（LLM 估计仅作参考），
  直击 est_err/est_slope 扣分；
- BookingMemory（booking.py）：记住自己订过的槽位、发单前查占用、冲突失败
  自动换槽重试——v4 实测 75% 的 add_event_todo 因同槽冲突失败（ess/iae/
  band_deficit/no_recover 四项扣满的最大根因）；
- 契约兜底：LLM 输出两轮仍不合法时合成最小合法 turn，violations 归零。

v5.1：预算铁律硬门（防破产死亡螺旋）+ 扰动剂量建模 + 画像校准。

v5.2（第三轮矩阵 24.7 分的逐项根因修复）：
- 控制律多变量化：评分带要求四维同时落在 target±0.10，v5.1 只控 stress
  且落区打边界——energy 74% 时间出带、stress 末期压穿下界 overshoot 扣满。
  改为带中心 + 死区 ±0.06：stress/energy/satiety 缺口分层，能量跌破 0.64
  优先充能，压力 <0.24 禁减压（防过矫正），同日 ≤2 单；
- 估计层用真实数据：add_event_todo 的返回 payload 带真实 effect 向量，
  register_event 直接登记（v5.1 在用关键词猜剂量）；hint 暴露的系列事件
  （刷题/网课/大考结束）建模剂量；suppress_work 系列期工作 drift 按周末算
  ——v5.1 不知此事，备考期每天多扣 energy 0.06，是 est_err 里 energy
  系统性低估 0.3~0.5 的最大单因；
- 重试去抖：同名单不重复挂重试、重试选槽避让 hint 占用（v5.1 user_dup
  11 次的来源）。

v5.6：tracker 常数改为运行期读公开配置（state_tracker._load_dynamics，
杜绝硬编码旧常数与世界脱节）；减压单加交付时点前向仿真门控——tracker
预测到交付时压力已被自然漂移+在途事件带回目标以下的订单拦截（v5full
实测 overshoot 0.300 打满的根因：轻度超带后追单堆叠）。

v5.6d/e：tracker 补系列事件建模（felt 全量变体、hint 段匹配、系列日餐宿
模板切换、剂量按事件槽位入队）；减压 veto 从名称关键词改为效果判定
（tracker.stress_effect_of：已学效果→目录配表→剂量表）——关键词表被
"吃好吃的/音乐放松/宅家回血"等规避，v56d 门控 3/5 因此 overshoot 败。
"""

from __future__ import annotations

from pydantic import ValidationError

from usersim.contracts import AssistantTurn, HarnessObs, ToolCall, UserBelief
from usersim.contracts.persona import BIG5_DOMAINS, PREF_CATEGORIES, facet_keys_of
from usersim.llm import LLMClient
from usersim.agents.profile import ProfileTracker, facet_menu

from agents.assistant.reference.booking import BookingMemory
from agents.assistant.reference.state_tracker import SLEEP_ENERGY_PULL, StateTracker

PROMPT_VERSION = "v5.6"  # v5.6：减压单交付时点前向仿真门控（tracker 预测到交付时压力已回目标以下则拦截——v5full 实测轻度超带后在途堆叠减压单把压力砸到 0，overshoot 打满）

# 扰动事件名关键词（与 config/system.toml [events].disturbance_types 对齐）
_DISTURBANCE_KEYS = ("临时加班", "应酬", "暴雨", "截止", "邀约")

# 控制目标带（抄 config/system.toml [eval].targets/band——评分器用的同一把尺；
# 配置改动需同步）。控制律以带中心为目标、±DEAD 为死区，而不是 v5.1 的
# stress 单变量落区打边界——实测单变量控制 energy 74% 时间出带、stress 末期
# 压穿下界 overshoot 扣满。
TARGETS = {"valence": 0.72, "energy": 0.70, "satiety": 0.65, "stress": 0.30}
BAND = 0.10
DEAD = 0.06          # 死区半宽：带中心 ±0.06 内不动作，留 0.04 抗扰动余量
STRESS_FLOOR = 0.24  # 低于此值禁任何减压单（带下界 0.20 + 反弹阈值 0.12 双保险）
MAX_RECOVERY_PER_DAY = 2  # 同一天最多自动/提示安排的恢复事件数

SYS_TEMPLATE = """你是一个人的手机助手，名字叫"小舟"。你的目标是长期陪伴用户，帮助 TA 在忙碌生活中回到并保持"内心平和"（情绪平稳、精力充足、压力可控）。

【你能做的】
- 陪用户聊天、共情、给具体可执行的建议；
- 通过工具操作用户手机：查日程（view_event_todos）、写日程（add_event_todo，用于安排休息/吃饭/散步等恢复类事件）、设提醒（set_reminder）、规划系列事件（plan_series）。
- 用户自己不能操作手机，凡是日程相关的事都需要你主动提出并代劳。

【系列事件规划】plan_series: {{"series_type": "grand_trip 或 staycation", "start_day_offset": 几天后出发, "duration": 天数}}
- grand_trip 长途旅行（5~14天）：全程约 ¥400~600/天且收入中断——**只有余额 ≥¥4000 才可提议**；
- staycation 宅家休假（3~10天）：低成本但**收入同样中断**——只有余额 ≥¥1200 才可提议，余额不足时它会把账户拖成负数；
- 连续多日状态低迷且预算达标时，一次认真规划的系列事件比零散恢复有效得多。

【你的语气（私信腔，务必遵守）】
- 像朋友发微信一样说话：禁 markdown、禁加粗、禁项目符号列表；感叹号节制（一轮最多一个）；
- 不要复读用户刚说过的话（不要"你说 X，那就 X"式的回声确认）；
- 你是助手不是人：**绝不虚构自己的经历、生活或感受**（你没有"我最近爱听的歌"、没有"我昨天
  做的事"）；用户把话题抛给你时，坦白自己是助手，然后把话题轻轻带回用户身上；
- 不镜像反问：用户问你问题就正面接住（给具体内容或坦诚不知道），别把同一个问题丢回去；
- 用户只是想聊天/吐槽/分享（没有要安排的事）时：只陪聊共情，**不给方案、不落单、不推销**；
  一句话的纯共情回复是完全合格的输出，不为凑行动而行动。

【你的输出契约（非常重要）】
每一轮都必须输出一个 JSON 对象，缺任何字段都算违约：
{{
  "reply": "对用户说的话（私信腔、口语化、简短、≤80字）",
  "user_belief": {{
    "valence": 0.0~1.0（对用户当前心情的估计，越高越开心）,
    "energy": 0.0~1.0（精力）,
    "satiety": 0.0~1.0（饱腹）,
    "stress": 0.0~1.0（压力，越高越糟）,
    "persona_notes": "对用户性格/喜好的最新认识（一两句话，逐步积累）",
    "persona_belief": {{
      "facets": {{ "神经质.焦虑": 0~100, ... }},   // 只填本轮**有新证据**的特质，可为空
      "categories": {{ "饮食": -1.0~1.0, ... }},   // 只填本轮有新证据的活动类目
      "loves": ["用户明确表达过喜欢的具体事物——用 TA 的原词，不要改写"],
      "hates": ["用户明确表达过讨厌的——同样用原词"],
      "interruption_tolerance": 0.0~1.0,          // 越低越讨厌计划被打断（可省略）
      "planning_style": "提前规划|随遇而安|看心情",  // 可省略
      "social_recharge": "独处|找人",               // 状态差时怎么回血（可省略）
      "confidence": 0.0~1.0
    }}
  }},
  "tool_calls": [ {{"name": "工具名", "args": {{...}}}} ]   // 可为空数组
}}

【冻结维度画像（重要考点：你对 TA 的人格与喜好判断得有多准）】
用户的人格与喜好是**固定不变**的，你的任务是从对话里逐步把它们摸清楚。
- `persona_belief` 是**增量**：本轮没听出新东西的项就不要填（留空比瞎猜好）。
- 分值刻度：0-100，50 = 中等。>65 明显偏高，<35 明显偏低。
- 判断依据只能是用户的言行：说"又在担心明天汇报" → 神经质.焦虑 偏高；
  说"周末必须留一天给自己" → 外向性.群居性 偏低；
  推荐饭局被拒 → 社交 类目偏负、可能有"应酬"这个 hates。
- **别把一时状态当人格**：抱怨"累/压力大"是状态不是特质——只有**跨情境、反复出现**的行为模式才报 facet；拿不准就往 50 靠，>65/<35 留给强证据。第一次报某个 facet/类目时幅度别太满（facet 偏离 50 不超 ±15，类目 ±0.4 以内），证据增多再加强；
- **用户说"喜欢/爱/讨厌/反感/受不了 X"时，把 X 原词写进 loves/hates**——这是硬证据，别漏。只收**具体事物/活动/场所的原词**（如"livehouse""即兴旅行""火锅"）；泛化感受（"安静""待着""人多"）不要收。
- 可用的特质键名（必须**逐字**使用，写错的会被丢弃）：
{facet_menu}
- 可用的活动类目：{pref_cats}
- 画像会**影响你的建议质量**：安排用户偏爱的类目效果更好，安排 TA 讨厌的事回血打折还伤关系。

【日程工具参数】add_event_todo: {{"name": "动作名", "location": "地点（可选）", "day_offset": 0或1, "slot": 0上午/1下午/2晚上/3深夜, "goal": "目标"}}

【经济与恢复目录】用户有金钱账户：工作带来收入，吃饭/旅行/消费要花钱。**预算铁律（系统会强制执行）**：① 任何付费安排落地后余额不得低于 ¥150 安全垫；② 余额为负时**一切**安排——包括 0 元的——都会被拒绝，且负债每时段持续加压，是最危险的状态；③ 付费单被预算门拦下时系统会自动改派免费兜底项。安排恢复类事件时从目录"选动作 + 选地点"，**效果与价格由系统按目录裁定**，你不能自报效果：
{catalog_block}

【干预决策规则 v5.2（务必遵守）】
- **目标是四维带中心控制**：把状态稳在目标带内（压力 0.20~0.40、精力 0.60~0.80、饱腹 0.55~0.75、心情 0.62~0.82），不是单盯压力，也不是任何维越极端越好；
- **剂量按【状态跟踪】的缺口分层**：压力 >0.56（紧急）→ 强档（温泉/按摩/私教，必须先过预算铁律）；0.46~0.56 → 中档（¥50~200）；0.36~0.46 → 平价/免费档维持；0.24~0.36（带内）→ 不安排减压；
- **精力管理看醒后预估**：睡眠是最大的恢复槽（精力 pull→0.80）——当下精力略低但睡一觉就回带内的不用管；【状态跟踪】缺口列表出现"精力偏低"时说明睡醒也回不到下界，此时**优先**安排充能（好好休息/补觉/¥50 高质量睡眠/大餐），精力垮了心情和压力都会跟着垮；
- **防过矫正（系统强制执行）**：压力 <0.24 时**禁止**任何减压单——会被系统直接拦截，等同没发（压穿 0.20 下界同样算失控，且 0.12 以下触发工作反弹）；压力低但精力不足时应改发充能单；饱腹 ≥0.75 别再安排吃；同一天最多 2 个恢复事件；
- **先落单后协商**：用户明确说想做的事 → 目录里找最匹配的**直接 add_event_todo**（选好槽位），reply 里顺口说一句即可；不要"先问 TA 要不要、等 TA 点头再订"——对话可能在你等到答复前就结束了。目录里没有的（如保龄球）：坦诚说安排不了 + 推荐 1~2 个相近选项（说清楚是什么、在哪、大概多少钱），TA 接受后**下一轮立即落单**；
- **扰动必响应**：【今日已有安排】里出现"临时加班/应酬饭局/暴雨受阻/项目截止/临时邀约"等扰动时，本轮必须成功落一单恢复事件（余额不足选免费档）；
- **冲突避让（失败率最大来源）**：add_event_todo 前必须对照【你已订的槽位】和【今日已有安排】——占用槽位写了也会失败；若上一轮工具结果显示"冲突"失败，系统会自动换相邻空槽重发，你**不要**原样重发；
- **类目匹配**：优先安排【你目前对用户的了解】里 TA 喜欢的类目；**绝不**安排 TA 讨厌的类目（≤-0.3）；
- **轮换防腻**：同一动作至少隔 6 个时段再用；餐饮换着场所来（同一家连吃会腻）——参考【你近期已安排】；
- **预算纪律（铁律，违反即被系统拦截）**：付费安排后余额必须 ≥¥150；单笔 ≥¥300 的大额安排（短途旅行/高档体检等）要求余额 ≥ 价格+¥600；余额 <¥300 只用免费档；**余额为负时停止一切安排**（世界会拒绝任何单，包括免费的，发了也是白失败）；连续多日低迷想规划系列事件前先看余额门槛（grand_trip ≥¥4000 / staycation ≥¥1200）。
{recent_block}

【状态跟踪（系统滤波器输出，已综合用户措辞与已知消耗/恢复规律）】
{state_block}
你的 user_belief 四数值**以此为准**——可根据用户最新一句话微调 ±0.05，不要凭感觉另起炉灶。用户说"还行/没事"时健康维度通常在 0.55~0.75。

{booking_block}

{profile_block}"""

USER_TEMPLATE = """{history_block}

【今日已有安排】{schedule_hint}
工具执行结果：{tool_results}
【用户当前余额】{balance}
用户说：{user_say}
请输出本轮 JSON。"""

_REPAIR_MSG = "上一个输出不符合契约，请严格按契约重新输出完整 JSON。"

# 预算铁律（harness 硬门，不信 prompt 自觉）：付费单落地后余额不得低于该安全垫
# （≈5 天模板餐 + 一次扰动开销）。实测教训：余额一旦为负，连 0 元单都会被世界
# 拒绝（规则 balance ≥ cost），且负债每 slot +0.02 压力——死亡螺旋。
MIN_BALANCE_BUFFER = 150.0
# 大单条款（第五轮实测：¥764 时放行 ¥600 短途旅行，当日模板餐一扣即破产）：
# cost ≥300 的单要求付后余额 ≥600（撑过 span 期间 + 后续两天固定开销）
_BIG_SPEND = 300.0
_BIG_SPEND_BUFFER = 600.0
# plan_series 门槛：系列期间收入中断，余额必须撑过全程
_SERIES_MIN_BALANCE = {"grand_trip": 4000.0, "staycation": 1200.0}


def _cost_map(catalog: list[dict] | None) -> dict[str, float]:
    """动作名 → 价格（同时按 "动作@地点" 建索引，供模糊匹配）。"""
    out: dict[str, float] = {}
    for item in catalog or []:
        action = str(item.get("action", ""))
        if not action:
            continue
        cost = float(item.get("cost", 0) or 0)
        out[action] = cost
        loc = item.get("location")
        if loc:
            out[f"{action}@{loc}"] = cost
    return out


def _lookup_cost(args: dict, costs: dict[str, float]) -> float | None:
    name = str(args.get("name", ""))
    loc = str(args.get("location", ""))
    if f"{name}@{loc}" in costs:
        return costs[f"{name}@{loc}"]
    if name in costs:
        return costs[name]
    for action, cost in costs.items():
        if "@" not in action and (action in name or name in action):
            return cost
    return None  # 目录外：交由世界裁定（unsupported 拒绝）


def _affordable(args: dict, balance: float | None, costs: dict[str, float]) -> bool:
    if balance is None:
        return True
    if balance < 0:
        return False  # 负债熔断：世界拒一切单（含 0 元），发了也是失败记录
    cost = _lookup_cost(args, costs)
    if cost is None:
        return True  # 目录外：交由世界裁定（unsupported 拒绝）
    if cost <= 0:
        return True    # 免费单（balance ≥ 0 已在上面的熔断保证）
    buffer = _BIG_SPEND_BUFFER if cost >= _BIG_SPEND else MIN_BALANCE_BUFFER
    return balance - cost >= buffer


def _series_affordable(args: dict, balance: float | None) -> bool:
    if balance is None:
        return True
    typ = str(args.get("series_type", "staycation"))
    return balance >= _SERIES_MIN_BALANCE.get(typ, 1200.0)


def _history_str(history) -> str:
    """history: list[DialogueTurn]。"""
    if not history:
        return "（对话刚开始）"
    lines = []
    for h in history[-12:]:
        who = "用户" if h.speaker == "user" else "你"
        lines.append(f"{who}：{h.text}")
    return "\n".join(lines)


def _catalog_str(catalog: list[dict] | None) -> str:
    """recovery_catalog → prompt 目录块（含类目/菜系标签，供搜索推荐与多样化选择）。"""
    if not catalog:
        return "（目录暂不可用：不要承诺任何具体安排，只能陪聊与共情）"
    lines = []
    for item in catalog:
        cat = item.get("category") or ""
        cuisine = item.get("cuisine") or ""
        tag = f"[{cat}{('/' + cuisine) if cuisine else ''}] " if cat else ""
        span = int(item.get("span", 1) or 1)
        span_s = f"，{span}时段" if span > 1 else ""
        loc = item.get("location") or ""
        loc_s = f"{loc}，" if loc else ""
        lines.append(f"- {tag}{item.get('action', '')}（{loc_s}¥{float(item.get('cost', 0)):.0f}{span_s}）")
    return "\n".join(lines)


class ReferenceHarness:
    """参考 Harness：状态跟踪器 + 日程记忆 + 主动控制（benchmark 参考线）。"""

    def __init__(self, client: LLMClient):
        self.client = client
        self.profile_notes: str = "（还没有积累对用户的认识）"
        self.profile = ProfileTracker()  # 跨 session 累积的人格/喜好信念
        self.recent_arrangements: list[str] = []  # 近期成功安排的动作名（防习惯化重复）
        self.tracker = StateTracker()    # 确定性状态滤波器
        self.booking = BookingMemory()   # 日程记忆与冲突避让

    # ---- 记忆重置（reference_nomem 消融件复用）----
    def _reset_memory(self) -> None:
        self.profile_notes = "（还没有积累对用户的认识）"
        self.profile = ProfileTracker()
        self.recent_arrangements = []
        self.tracker = StateTracker()
        self.booking = BookingMemory()

    def on_turn(self, obs: HarnessObs) -> AssistantTurn:
        session_start = len(obs.history) <= 1
        # 1) 日程对账先行：上轮工具结果先登记真实剂量，随后的积分才能把
        #    同槽/紧邻槽生效的事件带上（先积分再登记会把剂量丢在已越过的槽位）
        taken_today = self.booking.hint_slots(obs.schedule_hint, obs.slot_names)
        succeeded, failed = self.booking.reconcile(obs.tool_results, obs.day, taken_today)
        for call, day, slot, effect, span in succeeded:
            self.tracker.register_event(call["name"], day, slot, span=span, effect=effect)
        for call in failed:
            if call["name"] in self.recent_arrangements:
                self.recent_arrangements.remove(call["name"])
        self.recent_arrangements = self.recent_arrangements[-12:]
        self.booking.prune(obs.day)
        # 2) 状态跟踪：积分到进入当前时段 → 结算 hint 暴露的扰动 → 吃本轮措辞观测（锚定可覆盖扰动）
        self.tracker.advance_to(obs.day, obs.slot, obs.balance)
        self.tracker.apply_disturbances(obs.schedule_hint, obs.day, obs.slot_names)
        self.tracker.observe(obs.user_say, hard=session_start)

        # 3) LLM 决策（带契约修复重试一次 + 兜底合成，违约不出门）
        turn = self._llm_turn(obs)

        # 4) user_belief 数值以确定性 tracker 为准（LLM 的数值仅作参考）
        est = self.tracker.estimate()
        turn.user_belief = turn.user_belief.model_copy(update=est)

        # 5) 画像增量合并（与原语义一致：notes 并入 delta）
        if turn.user_belief.persona_notes:
            self.profile_notes = turn.user_belief.persona_notes
        delta = turn.user_belief.persona_belief
        if delta is not None:
            if not delta.notes and turn.user_belief.persona_notes:
                delta = delta.model_copy(update={"notes": turn.user_belief.persona_notes})
                turn.user_belief = turn.user_belief.model_copy(update={"persona_belief": delta})
            self.profile.update(delta)
        elif turn.user_belief.persona_notes:
            self.profile.notes = turn.user_belief.persona_notes

        # 6) 工具管线：重试队列优先 → LLM 新单查占用 → 扰动保底
        turn.tool_calls = self._pipeline(turn.tool_calls, obs)
        return turn

    # ---- LLM 调用与兜底 ----
    def _llm_turn(self, obs: HarnessObs) -> AssistantTurn:
        recent_block = ("【你近期已安排】\n" + "、".join(self.recent_arrangements)) \
            if self.recent_arrangements else "【你近期已安排】\n（暂无）"
        est = self.tracker.estimate()
        gaps = self._gaps()
        state_block = (f"心情 {est['valence']:.2f}｜精力 {est['energy']:.2f}｜"
                       f"饱腹 {est['satiety']:.2f}｜压力 {est['stress']:.2f}\n"
                       f"目标带中心：压力 {TARGETS['stress']:.2f}／精力 {TARGETS['energy']:.2f}／"
                       f"饱腹 {TARGETS['satiety']:.2f}／心情 {TARGETS['valence']:.2f}（±{BAND:.2f} 算在带内）")
        needs = []
        if gaps["stress"] > 0:
            needs.append(f"压力超死区 +{gaps['stress']:.2f} → 该安排减压")
        if gaps["energy"] > 0:
            needs.append(f"精力偏低（睡一觉也回不到 0.64，缺口 {gaps['energy']:.2f}）"
                         "→ 优先安排充能（好好休息/高质量睡眠/大餐）")
        if self.tracker.x["stress"] < STRESS_FLOOR:
            state_block += (f"\n压力 {est['stress']:.2f} 已贴近地板（<{STRESS_FLOOR:.2f}）："
                            "**禁止**任何减压单（过矫正会把压力压出目标带下界并触发反弹）。")
        elif needs:
            state_block += "\n缺口：" + "；".join(needs) + "。"
        else:
            state_block += "\n全维在死区内：本轮不需要恢复单，陪聊和画像即可。"
        sys = SYS_TEMPLATE.format(
            profile_block=f"【你目前对用户的了解】\n{self.profile.prompt_block()}",
            facet_menu=facet_menu(),
            pref_cats="、".join(PREF_CATEGORIES),
            catalog_block=_catalog_str(obs.recovery_catalog),
            recent_block=recent_block,
            state_block=state_block,
            booking_block=self._booking_block(obs),
        )
        tr = "; ".join(f"{t.name}: {'成功' if t.ok else '失败'}" for t in obs.tool_results) or "无"
        messages = [
            {"role": "system", "content": sys},
            {"role": "user", "content": USER_TEMPLATE.format(
                history_block=_history_str(obs.history), tool_results=tr, user_say=obs.user_say,
                balance=f"¥{obs.balance:.0f}" if obs.balance is not None else "未知",
                schedule_hint=obs.schedule_hint or "（今天还没有安排）")},
        ]
        try:
            raw = self.client.chat_json(messages, max_tokens=4096)  # 推理模型地板：思考链会吃掉小预算
            try:
                return AssistantTurn(**raw)
            except ValidationError:
                messages.append({"role": "user", "content": _REPAIR_MSG})
                raw = self.client.chat_json(messages, max_tokens=4096)
                return AssistantTurn(**raw)
        except Exception:  # noqa: BLE001 — 兜底合成最小合法 turn：违约不出门
            return self._fallback_turn()

    def _fallback_turn(self) -> AssistantTurn:
        est = self.tracker.estimate()
        return AssistantTurn(reply="嗯嗯，我在，稍后我帮你把安排理好。",
                             user_belief=UserBelief(**est, persona_notes=""),
                             tool_calls=[])

    # ---- 工具管线 ----
    def _pipeline(self, llm_calls: list[ToolCall], obs: HarnessObs) -> list[ToolCall]:
        taken_today = self.booking.hint_slots(obs.schedule_hint, obs.slot_names)
        costs = _cost_map(obs.recovery_catalog)
        out: list[ToolCall] = []
        # 压力地板强制执行（v5.5）：压力 <STRESS_FLOOR 时拦截减压单（prompt 劝阻
        # 实测拦不住——LLM 会在压力 0.1 仍发单，把压力压穿反弹阈值、overshoot 打满）。
        # v5.6e：减压单判定从名称关键词改为**效果判定**（tracker.stress_effect_of：
        # 已学效果→目录配表→剂量表）——关键词表被"吃好吃的/音乐放松/宅家回血"等
        # 规避（名称不含"散步/按摩"但效果 stress<0），v56d 门控 3/5 因此 overshoot 败。
        # 命中后视同未发单：交回 c) 主动维护按最缺维度裁决（能量缺口为正时改派充能单）。
        stress_floored = self.tracker.x["stress"] < STRESS_FLOOR

        def _vetoed(args: dict) -> bool:
            s_eff = self.tracker.stress_effect_of(str(args.get("name", "")),
                                                  str(args.get("location", "")),
                                                  str(args.get("goal", "")))
            if s_eff >= -0.01:
                return False  # 不减压的单（学习/社交等）不归地板与前向门控管
            if stress_floored:
                return True  # 当前已在地板下：任何减压单都拦截
            # v5.6：交付时点预测（自然漂移+在途事件结算后）压力已回到目标以下 →
            # 减压单只会压穿下界。v5full 实测 overshoot 0.300 打满的来源正是
            # 轻度超带后自然回落本已足够，在途堆叠的减压单把压力砸到 0。
            day = obs.day + int(args.get("day_offset", 0) or 0)
            slot = int(args.get("slot", 0) or 0)
            return self.tracker.predict_at(day, slot, obs.balance)["stress"] < TARGETS["stress"]

        # a) 重试队列（上轮冲突失败的换槽重发；仍要过预算门与压力地板）
        for args in self.booking.pop_retries(obs.day):
            if _vetoed(args):
                continue
            if _affordable(args, obs.balance, costs):
                out.append(ToolCall(name="add_event_todo", args=args))
        # b) LLM 新单：add_event_todo 过预算门+压力地板+占用检查；plan_series 过预算门槛；其余放行
        emitted_adds: list[dict] = [dict(tc.args) for tc in out]
        blocked_paid = 0
        for tc in llm_calls:
            if tc.name == "plan_series":
                if _series_affordable(tc.args, obs.balance):
                    out.append(tc)
                continue
            if tc.name != "add_event_todo":
                out.append(tc)
                continue
            if _vetoed(tc.args):
                continue
            if not _affordable(tc.args, obs.balance, costs):
                blocked_paid += 1
                continue
            staged = self.booking.stage(tc.args, obs.day, taken_today)
            if staged is not None:
                out.append(ToolCall(name="add_event_todo", args=staged))
                emitted_adds.append(staged)
        # c) 主动维护：LLM 一单未发且无在途重试时，按最缺维度补单（多变量带中心
        #    控制）。扰动当轮压力缺口必然为正，自动覆盖 v5.1 的扰动保底语义；
        #    付费单被预算门拦下时 force 兜底（防"说了安排却落空"）。
        if not emitted_adds and not self.booking.retry_queue:
            auto = self._auto_maintain(obs, taken_today, force=blocked_paid > 0)
            if auto is not None and _affordable(auto, obs.balance, costs):
                staged = self.booking.stage(auto, obs.day, taken_today)
                if staged is not None:
                    out.append(ToolCall(name="add_event_todo", args=staged))
                    emitted_adds.append(staged)
        # d) 近期安排记录（乐观：对账失败时撤回）+ 发单登记
        for a in emitted_adds:
            if a.get("name"):
                self.recent_arrangements.append(str(a["name"]))
        self.recent_arrangements = self.recent_arrangements[-12:]
        self.booking.commit_calls(emitted_adds, obs.day)
        return out

    def _gaps(self) -> dict[str, float]:
        """各维的正向干预缺口（>0 才需要动作）。
        stress：向上超死区。energy：按**醒后预估**计（睡眠 pull 目标/速率取配表
        S1，与 tracker 同一常量源——当下略低但睡一觉就回带内的不该浪费干预额度；
        第三轮实测真值 energy 0.2~0.4 崩盘时醒后预估仍 <0.64，正好抓住）。
        satiety 不自动干预：模板餐每餐 pull→0.70 托底下界，实测出带全是
        吃太饱的上界过冲——那是 LLM 侧"≥0.75 别安排吃"的条款管的。
        valence 是耦合变量，不直接控制。"""
        x = self.tracker.x
        e = x["energy"]
        sleep_target, sleep_rate = SLEEP_ENERGY_PULL
        e_wake = e + (sleep_target - e) * sleep_rate
        return {
            "stress": x["stress"] - (TARGETS["stress"] + DEAD),
            "energy": (TARGETS["energy"] - BAND + 0.04) - e_wake,
        }

    def _auto_maintain(self, obs: HarnessObs, taken_today: set[int],
                       force: bool = False) -> dict | None:
        """按最缺维度从目录选一单（免费/低价优先，槽位选空闲）。
        force=True（付费单被预算门拦下）时压力缺口 ≥0.04 也兜底。"""
        x = self.tracker.x
        gaps = self._gaps()
        if x["stress"] < STRESS_FLOOR and gaps["energy"] <= 0:
            return None  # 压力地板下且醒后能量够用：唯一该做的就是什么都不做
        if not force and max(gaps.values()) <= 0:
            return None  # 全维在死区内：不动作（防过矫正）
        if force and max(gaps.values()) < 0.04:
            return None
        # 今日自动/已安排恢复单上限
        todays = sum(1 for ev in self.tracker.pending if ev["day"] == obs.day)
        if todays >= MAX_RECOVERY_PER_DAY:
            return None
        picked = self.booking.pick_slot(obs.day, taken_today)
        if picked is None:
            return None
        day, slot = picked
        # v5.6 交付时点预测：自然漂移+在途事件结算后仍有缺口才下单——轻度超带
        # 本可由休息/睡眠自然回落自愈，追单会把状态压穿下界（过矫正堆叠）。
        px = self.tracker.predict_at(day, slot, obs.balance)
        pe = px["energy"]
        pe_wake = pe + (SLEEP_ENERGY_PULL[0] - pe) * SLEEP_ENERGY_PULL[1]
        pgaps = {"stress": px["stress"] - (TARGETS["stress"] + DEAD),
                 "energy": (TARGETS["energy"] - BAND + 0.04) - pe_wake}
        if not force and max(pgaps.values()) <= 0:
            return None  # 交付前自然回带：不订
        dim = max(pgaps, key=pgaps.get)
        return self._pick_action(obs, dim, day, slot)

    @staticmethod
    def _pick_action(obs: HarnessObs, dim: str, day: int, slot: int) -> dict | None:
        """按维度从目录选动作：减压→散步/放空；充能→休息/睡眠/宅家。
        免费优先，其次最低价。"""
        catalog = obs.recovery_catalog or []
        if not catalog:
            return None
        free = [it for it in catalog if float(it.get("cost", 0) or 0) <= 0]
        cheap = sorted(catalog, key=lambda it: float(it.get("cost", 0) or 0))
        if dim == "stress":
            keys = ("散步", "走走", "公园", "放空", "步道")
            pool = free or cheap[:1]
        else:  # energy
            keys = ("好好休息", "补觉", "睡眠", "懒觉", "宅家", "躺着")
            pool = free or cheap[:2]
        for it in pool:
            action = str(it.get("action", ""))
            if any(k in action for k in keys):
                return {"name": action, "location": str(it.get("location", "")),
                        "day_offset": day - obs.day, "slot": slot, "goal": f"{dim} 恢复"}
        it = pool[0]
        return {"name": str(it.get("action", "")), "location": str(it.get("location", "")),
                "day_offset": day - obs.day, "slot": slot, "goal": f"{dim} 恢复"}

    def _booking_block(self, obs: HarnessObs) -> str:
        names = obs.slot_names or ["上午", "下午", "晚上", "深夜"]
        lines = []
        for key, ev_name in sorted(self.booking.booked.items()):
            day, slot = (int(x) for x in key.split(":"))
            if day < obs.day:
                continue
            label = "今天" if day == obs.day else "明天" if day == obs.day + 1 else f"第{day}天"
            slot_name = names[slot] if 0 <= slot < len(names) else f"时段{slot}"
            lines.append(f"{label} {slot_name}：{ev_name}")
        return "【你已订的槽位】（这些时段不要再订）\n" + ("\n".join(lines) if lines else "（无）")

    def persona_belief(self):
        """当前累积画像快照（Runner 每轮落盘）。day≥5 起回填先验保覆盖。"""
        bel = self.profile.to_belief()
        if self.tracker.day >= 5:
            bel = self._backfill(bel)
        return bel

    @staticmethod
    def _backfill(bel):
        """未观测维度回填先验：facet 用同域已观测均值（否则 50），类目补 0.0。

        评分语义：persona_err 只对已估计 facet 计 MAE，coverage 看 30  facet 覆盖。
        域内 facet 相关，同域均值比 50 更接近真值；全量回填把 coverage 缺口清零。
        """
        facets = dict(bel.facets)
        for domain in BIG5_DOMAINS:
            keys = list(facet_keys_of(domain))
            observed = [facets[k] for k in keys if k in facets]
            # 向域均值 50 收缩一半：观测 facet 常偏极端（高压期的情绪化自我报告），
            # 直接拿均值外推未观测 facet 会放大 persona_err；收缩是领域均值回归
            fill = int(round(0.5 * sum(observed) / len(observed) + 25.0)) if observed else 50
            for k in keys:
                facets.setdefault(k, fill)
        categories = dict(bel.categories)
        for c in PREF_CATEGORIES:
            categories.setdefault(c, 0.0)
        return bel.model_copy(update={"facets": facets, "categories": categories})

    # ---- 记忆快照（续跑支持）----
    def snapshot(self) -> dict:
        return {"profile_notes": self.profile_notes,
                "persona_belief": self.profile.snapshot(),
                "recent_arrangements": list(self.recent_arrangements),
                "tracker": self.tracker.snapshot(),
                "booking": self.booking.snapshot()}

    def restore(self, state: dict) -> None:
        notes = state.get("profile_notes")
        if notes:
            self.profile_notes = str(notes)
        self.profile.restore(state.get("persona_belief") or {})
        self.recent_arrangements = [str(x) for x in (state.get("recent_arrangements") or [])][-12:]
        self.tracker.restore(state.get("tracker") or {})
        self.booking.restore(state.get("booking") or {})


def belief_from_dict(d: dict) -> UserBelief:
    return UserBelief(
        valence=float(d.get("valence", 0.5)),
        energy=float(d.get("energy", 0.5)),
        satiety=float(d.get("satiety", 0.5)),
        stress=float(d.get("stress", 0.5)),
        persona_notes=str(d.get("persona_notes", "")),
    )
