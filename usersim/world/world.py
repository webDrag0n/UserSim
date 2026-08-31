"""World 门面：对外只暴露上下文查询、工具执行与 slot 推进。

约束：本包 0 次 LLM 调用；同一 seed 的规则回放必须产出完全相同的轨迹。
"""

from __future__ import annotations

from usersim.contracts import Event, EventContext, Persona, Series, SlotSettlement, StateVec, ToolResult
from usersim.world import dynamics, events as ev
from usersim.world.anthro import (
    HABITUATION_DEFAULTS,
    Needs,
    hab_weight,
    habit_params,
    habit_resolve,
    persona_modifiers,
    preference_modifiers,
    reversion_rate_mult,
)
from usersim.world.balance import load_overrides
from usersim.world.catalog import find_variant, get_economy
from usersim.world.felt import felt_state
from usersim.world.persona import generate_persona
from usersim.world.series import SERIES_TYPES, generate_itinerary
from usersim.world.streams import make_streams
from usersim.world.weather import Weather, initial_weather, transition_weather, weather_effect_on_state, weather_event_modifier


class World:
    # 不构成"游玩/办事"需求的系列内容关键词（餐宿/工作/学习/交通/后效）
    _SERIES_PASSIVE_KEYWORDS = ("餐", "睡", "懒觉", "工作", "刷题", "网课", "交通", "休整", "回味", "疲惫", "空虚", "焦虑", "结束")

    def __init__(self, seed: int, days: int, cfg, archetype: str | None = None):  # cfg: system.toml Namespace
        self.seed = seed
        self.days = days
        self.cfg = cfg
        self.slots_per_day: int = cfg.clock.slots_per_day
        self.total_slots = days * self.slots_per_day
        self.weekend_days: list[int] = list(cfg.events.weekend_free_days)

        self.streams = make_streams(seed)
        # archetype 传入生成器而非事后改写：职业会偏移人格域基线，且 Persona 的
        # 人格/喜好字段是 frozen 的（冻结维度不可运行期改写）。
        self.persona: Persona = generate_persona(
            self.streams["persona"], cfg.state.initial.to_dict(), archetype=archetype
        )
        self.x: StateVec = self.persona.x0.model_copy(deep=True)
        self.t = 0

        eco_cfg = cfg.get("economy")
        if eco_cfg is None:
            self._eco = get_economy()
        else:
            self._eco = {**get_economy(), **(eco_cfg.to_dict() if hasattr(eco_cfg, "to_dict") else dict(eco_cfg))}
        self.money: float = float(self._eco.get("initial_money", 1000))

        self.events: list[Event] = ev.build_template_schedule(days, self.slots_per_day, self.weekend_days)
        self.events += ev.sample_disturbances(
            self.streams["disturbance"], days, self.slots_per_day, cfg.events.disturbance_prob_per_day
        )
        self._user_event_count = 0
        self._reminders: list[dict] = []
        self.series: list[Series] = []
        self._last_done: dict[str, int] = {}  # 习惯化：规范事件名 → 上次执行 t
        self._last_variants: dict[str, list[str]] = {}  # 规范名 → 最近做过的具体变体（最多 3 个）
        self.needs = Needs()  # 需求层（饥饿/社交/刺激/成就）
        self._series_track: dict[str, dict] = {}  # 峰终定律跟踪
        self._balance = load_overrides()  # Excel 数值覆盖（习惯化/需求/人格/动力学）
        self.overrides = self._balance  # 让 Needs.urges/satisfaction 读取覆盖
        # 动力学参数：system.toml [dynamics] 为底，config/balance/dynamics.json 覆盖
        # （Balance 编辑器改动力学生效；此前 dynamics.json 加载后无人消费 = 死配置）
        from usersim.config import Namespace as _NS
        self._dyn = _NS({**cfg.dynamics.to_dict(), **(self._balance.get("dynamics_params") or {})})

        # 天气系统
        self.weather: Weather = initial_weather(self.streams["weather"])

        self._inject_forced_series()

    # ---------------- 系列事件 ----------------
    def _inject_forced_series(self) -> None:
        """强制系列：备考冲刺（限备考型角色）、出差（扰动流）。"""
        gen = self.streams["disturbance"]
        if self.persona.archetype == "备考研究生" and self.days >= 21:
            self.add_series("exam_crunch", 14, 10, rng=gen)
        if self.days >= 10:
            for wk in range(1, self.days // 7):
                if gen.random() < 0.14:
                    dur = int(gen.integers(2, 6))
                    start = wk * 7 + int(gen.integers(0, 3))
                    self.add_series("business_trip", start, dur, rng=gen)
                    break

    def active_series(self, day: int | None = None) -> Series | None:
        d = self.day if day is None else day
        for s in self.series:
            if s.start_day <= d < s.end_day:
                return s
        return None

    def add_series(self, series_type: str, start_day: int, duration: int,
                   rng=None, planned_by: str | None = None) -> ToolResult:
        """创建系列：校验 → 物化行程单 → 覆盖区间内模板日程。"""
        import numpy as np

        if series_type not in SERIES_TYPES:
            return ToolResult(name="plan_series", ok=False, payload={"error": f"未知系列类型 {series_type}"})
        sdef = SERIES_TYPES[series_type]
        lo, hi = sdef["duration_range"]
        duration = max(lo, min(hi, duration))
        if start_day < self.day:
            return ToolResult(name="plan_series", ok=False, payload={"error": "开始日期不能早于今天"})
        if start_day + duration > self.days:
            duration = self.days - start_day
            if duration < lo:
                return ToolResult(name="plan_series", ok=False, payload={"error": "剩余天数不足"})
        for s in self.series:
            if not (start_day + duration <= s.start_day or s.end_day <= start_day):
                return ToolResult(name="plan_series", ok=False, payload={"error": f"与已有系列「{s.name}」时间冲突"})

        rng = rng or np.random.default_rng(int(self.streams["schedule"].integers(1 << 30)))
        ticket_budget = max(0.0, self.money * 0.4) if planned_by else 300.0
        sid = f"SER{len(self.series):02d}"
        new_events = generate_itinerary(sid, series_type, start_day, duration,
                                        self.slots_per_day, rng, ticket_budget)
        # 覆盖：移除区间内模板事件（工作/家常餐/家睡眠/休整），扰动保留
        s0, s1 = start_day * self.slots_per_day, (start_day + duration) * self.slots_per_day
        self.events = [e for e in self.events
                       if not (e.kind == "template" and s0 <= e.start_slot < s1)]
        self.events.extend(new_events)
        series = Series(id=sid, type=series_type, name=sdef["name"], icon=sdef["icon"],
                        start_day=start_day, end_day=start_day + duration)
        self.series.append(series)
        return ToolResult(name="plan_series", ok=True,
                          payload={"series": series.model_dump(), "n_events": len(new_events)})

    def plan_series(self, series_type: str, start_day_offset: int, duration: int) -> ToolResult:
        """助手侧工具：规划长途旅行/宅家休假（花用户的钱，需预算校验）。"""
        sdef = SERIES_TYPES.get(series_type)
        if sdef is None or sdef["source"] != "planned":
            return ToolResult(name="plan_series", ok=False, payload={"error": "该系列不可主动规划"})
        start_day = self.day + max(0, start_day_offset)
        # 粗估全程花费（餐宿 + 门票预算），不足则拒绝
        est_cost = duration * 300
        if est_cost > self.money:
            return ToolResult(name="plan_series", ok=False,
                              payload={"error": f"预算不足：预计需要 ¥{est_cost}，当前 ¥{self.money:.0f}"})
        return self.add_series(series_type, start_day, duration, planned_by="assistant")

    # ---------------- 时钟 ----------------
    @property
    def day(self) -> int:
        return self.t // self.slots_per_day

    @property
    def slot(self) -> int:
        return self.t % self.slots_per_day

    @property
    def done(self) -> bool:
        return self.t >= self.total_slots

    def is_workday(self, day: int | None = None) -> bool:
        d = self.day if day is None else day
        return d % 7 not in self.weekend_days

    # ---------------- 上下文 ----------------
    def active_events(self, t: int | None = None) -> list[Event]:
        tt = self.t if t is None else t
        return [e for e in self.events if e.start_slot <= tt < e.start_slot + e.span_slots]

    def current_context(self) -> EventContext:
        active = self.active_events()
        upcoming = sorted(
            [e for e in self.events if e.start_slot > self.t],
            key=lambda e: e.start_slot,
        )[:8]
        assist_prompt = None

        # ---- 助手介入点（事件驱动需求）----
        # 触发优先级：扰动 > 高压 > 系列游玩 > 饭点 > 空闲闲聊
        # 后三者为概率触发（世界噪声流，保持确定性）
        gen = self.streams["noise"]
        probs_cfg = self.cfg.user_agent.get("scene_probs")
        probs = probs_cfg if isinstance(probs_cfg, dict) else {}

        dist = [e for e in active if e.kind == "disturbance"]
        series_acts = [
            e for e in active
            if e.kind == "series" and not any(k in e.name for k in self._SERIES_PASSIVE_KEYWORDS)
        ]
        if dist:
            assist_prompt = "刚发生了扰动事件，用户状态可能受损，可能需要安排恢复"
        elif self.x.stress > self.cfg.user_agent.help_seek_stress_threshold:
            assist_prompt = "用户压力持续偏高，可能需要帮助"
        elif series_acts and gen.random() < probs.get("series_activity", 0.6):
            e = series_acts[0]
            if "会议" in e.name or "应酬" in e.name:
                assist_prompt = f"用户即将/正在参加「{e.name}」，可能需要准备材料、提醒或安排车辆"
            else:
                assist_prompt = f"用户即将/正在游玩「{e.name}」，可能需要攻略、导航、订票或附近美食推荐"
        elif self.slot == 1 and gen.random() < probs.get("meal", 0.12) * (0.5 + self.needs.urges(self.overrides)["hunger"]):
            assist_prompt = "饭点到了，用户可能想要美食推荐或订餐协助"
        elif gen.random() < probs.get("idle", 0.08) * (0.3 + 0.7 * self.needs.session_urge(self.overrides)):
            assist_prompt = "用户似乎有点空闲，可能想随便聊聊或办点杂事"

        # ---- 餍足提示：最近一次执行的恢复动作习惯化权重仍过低 → "腻了" ----
        satiation_note = None
        if self._last_done:
            last_name, last_t = max(self._last_done.items(), key=lambda kv: kv[1])
            w_sat = hab_weight(self.t - last_t, *habit_params(last_name, self._balance))
            if w_sat < 0.6:
                satiation_note = f"最近总是{last_name}，感觉有点腻了"

        ctx = EventContext(
            t_logical=self.t,
            day=self.day,
            slot=self.slot,
            slot_name=self.cfg.clock.slot_names[self.slot],
            active_events=active,
            assist_prompt=assist_prompt,
            schedule_view=upcoming,
            weather=self.weather.value,  # 新增：当前天气
            satiation_note=satiation_note,
            utility_menu=self.utility_menu(),  # R7：各活动边际效用档位（用户感知通道）
        )
        return ctx

    def felt_state(self) -> str:
        return felt_state(self.x, self.streams["noise"])

    # 边际效用语义档位（hab_weight → 用户可读标签），阈值即感受分档
    _UTILITY_TIERS = (
        (0.85, "还很新鲜"),
        (0.60, "效果还在，但吸引力降了"),
        (0.35, "做太多次，效果明显打折"),
        (0.00, "已经腻了，基本没什么用"),
    )
    # "没试过"清单的候选来源：规范动作键（排除场所键与豁免类目/兜底）
    _UTILITY_FRESH_EXCLUDE = ("自定义活动",)

    def utility_menu(self) -> list[str]:
        """各恢复活动当前对用户的吸引力（习惯化权重的语义档位，0-LLM 翻译）。

        与效果裁决同一数据源（_last_done × habituation 配表、同一 hab_weight 公式）——
        用户感知到的边际效用必须与世界实际施加的衰减一致（R7：重复安排应被嫌弃）。
        """
        done = []
        for name, last_t in self._last_done.items():
            w = hab_weight(self.t - last_t, *habit_params(name, self._balance))
            tier = next(label for edge, label in self._UTILITY_TIERS if w >= edge)
            variants = self._last_variants.get(name)
            shown = f"{name}（最近做过：{'、'.join(variants)}）" if variants else name
            done.append((w, shown, tier))
        # 权重升序：最腻的在前，最需要拒绝的最显眼
        lines = [f"{name}——{tier}" for _, name, tier in sorted(done)]
        fresh = sorted(k for k in HABITUATION_DEFAULTS
                       if k not in self._last_done and k not in self._UTILITY_FRESH_EXCLUDE)[:8]
        if fresh:
            lines.append("还没试过的：" + "、".join(fresh))
        return lines

    # ---------------- 工具执行（助手侧工具的世界端实现） ----------------
    def view_event_todos(self) -> ToolResult:
        upcoming = [e.model_dump() for e in sorted(self.events, key=lambda e: e.start_slot) if e.start_slot >= self.t][:12]
        return ToolResult(name="view_event_todos", ok=True, payload={"events": upcoming})

    def add_event_todo(
        self,
        name: str,
        day_offset: int,
        slot: int,
        goal: str,
        effect: dict[str, float],
        span_slots: int = 1,
        caused_by_session_id: str | None = None,
        variant_id: str | None = None,
        location: str | None = None,
    ) -> ToolResult:
        """新增日程事件。数值裁决规则：配表命中 → 效果/价格/时长以配表为准；
        未命中 → 按关键词归一化到规范类目（C1~C6，世界裁定数值，自报效果无效）；
        仍不命中 → 系统不支持该活动，拒绝安排（助手应坦诚告知并推荐目录内替代）。
        金钱不足同样拒绝。"""
        found = None
        if variant_id:
            found = find_variant(variant_id)
        if found is None:
            found = find_variant(name, location)
        replaces_meal = False
        if found is not None:
            action, variant = found
            variant_loc = variant.get("location") or variant.get("name", "")
            name = f"{action['action']} · {variant_loc}"
            effect = dict(variant["effect"])
            cost = float(variant["cost"])
            span_slots = int(variant.get("span", 1))
            goal = goal or f"{action['action']}（{variant_loc}）"
            location = location or variant_loc
            # 餐饮场所（venue 带 replaces_meal 标记）替代当日模板餐
            replaces_meal = bool(variant.get("replaces_meal"))
        else:
            # 目录外自由命名：按关键词归一化到规范类目（C1~C6）；
            # 关键词也不命中 = 系统不支持的活动（如"打保龄球"）→ 拒绝，
            # 不给兜底效果——世界只安排配表覆盖的事，用户可能想要不存在的东西
            from usersim.world.catalog import match_custom_activity
            original = name
            cat = match_custom_activity(original)
            if cat is None:
                return ToolResult(name="add_event_todo", ok=False, payload={
                    "error": f"附近没有提供「{original}」的场所，暂时无法安排这项活动",
                    "unsupported": True})
            name = cat["name"]
            effect = dict(cat["effect"])
            cost = float(cat["cost"])
            location = location or cat["name"]
            if original != name:
                goal = f"{name}（原称：{original}）"
            else:
                goal = goal or name

        if cost > self.money:
            return ToolResult(name="add_event_todo", ok=False,
                              payload={"error": f"金钱不足：需要 {cost}，当前 {self.money:.0f}"})

        start = (self.day + day_offset) * self.slots_per_day + slot
        event = Event(
            id=f"R{self._user_event_count:04d}",
            kind="recovery",
            name=name,
            start_slot=start,
            span_slots=span_slots,
            location=location or "待定",
            goal=goal or name,
            effect=effect,
            cost=cost,
            caused_by_session_id=caused_by_session_id,
            replaces_meal=replaces_meal,
        )
        result = ev.validate_new_event(event, self.events, self.total_slots)
        if result.ok:
            self._user_event_count += 1
            self.events.append(event)
            result.payload["event"] = event.model_dump()
        return result

    def set_reminder(self, message: str = "", time_str: str = "") -> ToolResult:
        """设提醒（日程元数据，无状态效果）。"""
        self._reminders.append({"t_set": self.t, "message": message, "time": time_str})
        return ToolResult(name="set_reminder", ok=True, payload={"message": message, "time": time_str})

    # ---------------- 快照（续跑/回放支持） ----------------
    def to_snapshot(self) -> dict:
        return {
            "seed": self.seed,
            "days": self.days,
            "t": self.t,
            "money": self.money,
            "x": self.x.model_dump(),
            "persona": self.persona.model_dump(),
            "events": [e.model_dump() for e in self.events],
            "streams": {k: g.bit_generator.state for k, g in self.streams.items()},
            "user_event_count": self._user_event_count,
            "reminders": self._reminders,
            "series": [s.model_dump() for s in self.series],
            "last_done": self._last_done,
            "last_variants": self._last_variants,
            "needs": self.needs.to_dict(),
            "series_track": self._series_track,
            "weather": self.weather.value,  # 新增：天气状态
        }

    @classmethod
    def from_snapshot(cls, snap: dict, cfg, extra_days: int = 0) -> "World":
        import numpy as np

        w = cls.__new__(cls)
        w.cfg = cfg
        w.seed = snap["seed"]
        w.days = snap["days"] + extra_days
        w.slots_per_day = cfg.clock.slots_per_day
        w.total_slots = w.days * w.slots_per_day
        w.weekend_days = list(cfg.events.weekend_free_days)
        w.persona = Persona(**snap["persona"])
        w.x = StateVec(**snap["x"])
        w.t = snap["t"]
        eco_cfg = cfg.get("economy")
        w._eco = get_economy() if eco_cfg is None else {**get_economy(), **(eco_cfg.to_dict() if hasattr(eco_cfg, "to_dict") else dict(eco_cfg))}
        w.money = snap["money"]
        w.events = [Event(**e) for e in snap["events"]]
        streams = {}
        for k, s in snap["streams"].items():
            g = np.random.Generator(np.random.PCG64())
            g.bit_generator.state = s
            streams[k] = g
        w.streams = streams
        w._user_event_count = snap.get("user_event_count", 0)
        w._reminders = snap.get("reminders", [])
        w.series = [Series(**s) for s in snap.get("series", [])]
        w._last_done = dict(snap.get("last_done", {}))
        w._last_variants = {k: list(v) for k, v in snap.get("last_variants", {}).items()}
        from usersim.world.anthro import Needs as _Needs
        w.needs = _Needs(snap.get("needs"))
        w._series_track = dict(snap.get("series_track", {}))
        w._balance = load_overrides()
        w.overrides = w._balance
        from usersim.config import Namespace as _NS
        w._dyn = _NS({**cfg.dynamics.to_dict(), **(w._balance.get("dynamics_params") or {})})
        # 恢复天气状态（旧快照兼容：默认晴天）
        weather_str = snap.get("weather", "晴")
        w.weather = Weather(weather_str)
        return w

    # ---------------- 拟人化：有效事件计算 ----------------
    _HAB_EXEMPT = ("餐", "睡眠", "懒觉", "工作", "刷题", "网课", "交通", "回味", "疲惫", "空虚", "焦虑", "结束")

    def _effective_events(self, active: list[Event]) -> list[Event]:
        """按习惯化 × 需求满足曲线 × 人格调节变换活跃事件的效果。"""
        out: list[Event] = []
        for e in active:
            if not e.effect or e.kind == "template":
                out.append(e)
                continue
            # 习惯化：恢复/系列中的活动类（餐宿/工作/学习不腻）；
            # "餐"只豁免系列餐食——恢复事件里的餐饮场所（venue 餐厅）重复吃会腻，照常习惯化
            w = 1.0
            if e.kind in ("recovery", "series") and not any(
                k in e.name for k in self._HAB_EXEMPT if k != "餐" or e.kind == "series"
            ):
                key = habit_resolve(e.name, self._balance)
                last = self._last_done.get(key)
                dt = (self.t - last) if last is not None else 999
                w = hab_weight(dt, *habit_params(key, self._balance))
                if e.start_slot == self.t:  # 长事件只在开始时记录执行
                    self._last_done[key] = self.t
                    # 记录具体变体名（"好好休息 · 按摩 SPA" → "按摩 SPA"），
                    # 供 utility_menu 展示——否则用户会把做过的变体当新花样
                    variant_label = e.name.split(" · ", 1)[1].strip() if " · " in e.name else None
                    if variant_label:
                        seen = [v for v in self._last_variants.get(key, []) if v != variant_label]
                        seen.append(variant_label)
                        self._last_variants[key] = seen[-3:]
            sat = self.needs.satisfaction(e.name, self.overrides) if e.kind in ("recovery", "series") else 1.0
            eff: dict = {}
            for k, v in e.effect.items():
                if isinstance(v, dict) and "pull" in v:
                    eff[k] = {"pull": [v["pull"][0], v["pull"][1] * w]}
                else:
                    eff[k] = v * w * sat
            eff = persona_modifiers(self.persona.big5, e.name, eff, facets=self.persona.facets, overrides=self._balance)
            # 喜好调节：爱做的事回血更多、讨厌的事效果打折（只作用于恢复/系列活动，
            # 工作与模板事件不受喜好影响——不喜欢也得上班）
            if e.kind in ("recovery", "series"):
                eff = preference_modifiers(self.persona.prefs, e.name, eff)
            # 天气调节：户外事件受天气影响（暴雨打折）
            eff = weather_event_modifier(self.weather, e.name, eff)
            out.append(e.model_copy(update={"effect": eff}))
        return out

    # ---------------- 推进 ----------------
    def step_slot(self) -> SlotSettlement:
        # 天气转移（每个 slot 开头）
        if self.slot == 0:  # 每天开始时转移天气
            self.weather = transition_weather(self.weather, self.streams["weather"])

        x_before = self.x.model_copy(deep=True)
        money_before = self.money
        active = self.active_events()
        series = self.active_series()
        sdef = SERIES_TYPES[series.type] if series else None
        suppress_income = bool(sdef and sdef["suppress_income"])
        effective_workday = self.is_workday() and not (sdef and sdef["suppress_work"])

        # 经济结算：工作收入（按职业，系列抑制时停发）+ 事件首个活跃时段的收支
        if effective_workday and self.slot in (0, 1) and not suppress_income:
            self.money += float(self.persona.income_per_slot)
        for e in active:
            if e.start_slot == self.t:
                self.money += e.income - e.cost

        # 餐饮场所替代模板餐：slot 1/2 有 replaces_meal 事件活跃时，当日"三餐"
        # （跨 3 时段的单事件）在该 slot 的效果不生效——按 slot 粒度抑制，不删事件
        effective = self._effective_events(active)
        if self.slot in (1, 2) and any(e.replaces_meal for e in effective):
            effective = [
                e.model_copy(update={"effect": {}})
                if e.kind == "template" and e.name == "三餐" else e
                for e in effective
            ]

        x_after, natural, event_fx, control_fx = dynamics.settle_slot(
            self.x, self.day, self.slot, effective_workday, effective, self._dyn,
            reversion_mult=reversion_rate_mult(self.persona.big5, self.persona.facets),
        )

        # ---- 天气效果叠加（心情微调）----
        weather_eff = weather_effect_on_state(self.weather)
        for k, v in weather_eff.items():
            if k == "valence":
                x_after.valence = min(1.0, max(0.0, x_after.valence + v))
                natural[k] += v
            elif k == "stress":
                x_after.stress = min(1.0, max(0.0, x_after.stress + v))
                natural[k] += v

        # ---- 需求层更新（不直接写状态，只驱动求助与效果权重）----
        active_names = [e.name for e in active]
        self.needs.update(
            satiety=x_after.satiety,
            active_names=active_names,
            extraversion=self.persona.facet("外向性.群居性"),
            exam_active=bool(series and series.type == "exam_crunch"),
            deadline_disturbance=any("截止" in n for n in active_names),
            slot=self.slot,  # 新增：生物钟调制
        )
        # 刺激过载：连续高刺激日程也会烦躁（倒 U 的另一侧）
        if self.needs.n["stimulation"] > 0.8:
            x_after.valence = max(0.0, x_after.valence - 0.02)
            natural["valence"] -= 0.02

        # ---- 峰终定律：系列结束时按 峰值×0.5 + 末值×0.5 结算回味 ----
        if series:
            tr = self._series_track.setdefault(series.id, {"peak": 0.0, "last": 0.7, "type": series.type})
            tr["peak"] = max(tr["peak"], x_after.valence)
            tr["last"] = x_after.valence
        elif self._series_track:
            for _, tr in self._series_track.items():
                impulse = max(-0.15, min(0.15, 0.5 * tr["peak"] + 0.5 * tr["last"] - 0.65))
                x_after.valence = min(1.0, max(0.0, x_after.valence + impulse))
                natural["valence"] += impulse
            self._series_track.clear()

        # 负债压力：金钱为负产生持续压力（限幅后重新收敛）
        if self.money < 0:
            debt = float(self._eco.get("debt_stress_per_slot", 0.03))
            x_after.stress = min(1.0, x_after.stress + debt)
            natural["stress"] += debt

        settlement = SlotSettlement(
            t_logical=self.t,
            x_before=x_before,
            x_after=x_after,
            natural_drift=natural,
            event_effects=event_fx,
            control_effects=control_fx,
            active_event_ids=[e.id for e in active],
            money_before=money_before,
            money_after=self.money,
            active_series=f"{series.icon} {series.name}" if series else None,
            slots_per_day=self.slots_per_day,
            weather=self.weather.value,  # 新增：当前天气
        )
        self.x = x_after
        self.t += 1
        return settlement
