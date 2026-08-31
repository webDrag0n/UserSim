"""确定性状态观测器：felt 分档反查（session 首轮锚定）+ 公开动力学轮间积分。

为什么存在：benchmark 的 est_err/est_slope 度量 ‖x−x̂‖，而 v4 让 LLM 凭感觉打
数值分（实测 est_err 0.385，扣满 8 分）。用户台词由世界的 felt 翻译器条件化生
成，措辞里带着分档信息；轮与轮之间状态按公开差分方程演化。一个确定性滤波器
（措辞→档位锚定 + 动力学积分 + 自事件剂量）比 LLM 直读数值准得多，且天然单调
改善（每次 session 首轮重新锚定，误差不会随天数放大）。

信息边界：只用 HarnessObs 已有字段（user_say/history/tool_results/day/slot/
balance）。动力学常数抄自 config/system.toml [dynamics]、[state]（公开配置，
同机 CLI agent 同样可读）；felt 词典复制自 usersim/world/felt.py 的分档表——
agents 依赖规则禁止 import usersim.world（tests/test_dependency_rules.py），
故复制数据而非引用。

Caveat（docs/03 已知问题）：felt 反查利用了"用户措辞 ↔ 状态分档"的规则映射，
是 Phase 2 计划堵上的泄漏点（届时 LLM 只报定性方向）。USE_FELT_LOOKUP=False
可关掉锚定，退化为纯积分器。
"""

from __future__ import annotations

import json

# ---------------------------------------------------------------
# felt 分档反查表（数据复制自 usersim/world/felt.py，含全部同义变体；
# 另补少量常见口语变体以提高召回。中点 = 档位区间中值，>末档取 0.85/0.90）
# ---------------------------------------------------------------
USE_FELT_LOOKUP = True

# (短语列表, 档位中点)；匹配按列出的顺序取首个命中（极端档在前，信息量大）。
# 每档先列 felt.py 的全部 5 个同义变体，再列实测用户 LLM 的常见改写（门控 v3
# 回放实锤：高压期"快被压垮了/喘不上气/脑子嗡嗡响"等改写全漏，锚定失效）。
_STRESS_TIERS = [
    (["快崩溃了", "真的要炸了", "完全撑不住了", "到极限了", "整个人都快散架了",
      "快被压垮", "压垮", "喘不上气", "喘不过气", "崩溃了", "撑不住"], 0.90),
    (["压力很大", "感觉快扛不住了", "压力大得离谱", "脑子里全是事", "被事情追着跑",
      "压力大到", "脑仁", "脑子嗡嗡", "压力好大", "压力山大", "扛不住"], 0.70),
    (["压力有点大", "感觉有些紧绷", "压力上来了", "心里有点悬着", "绷着一根弦", "绷着"], 0.50),
    (["压力还好", "压力一般般", "有点压力但", "不算紧张", "还扛得住"], 0.30),
    (["没什么压力", "压力不大", "挺轻松的", "心里没什么事压着", "一身轻", "没压力"], 0.10),
]
_ENERGY_TIERS = [
    (["快没电了", "累得不行", "整个人很虚", "眼皮直打架", "动都不想动",
      "累瘫", "精疲力尽"], 0.15),
    (["有点累", "有点乏", "稍微有点疲惫", "有点提不起劲", "身子有点沉",
      "好累", "累了"], 0.40),
    (["精力还行", "精神还可以", "状态凑合", "不算累", "还有点力气"], 0.60),
    (["精力充沛", "元气满满", "精神头很足", "浑身是劲", "状态在线", "精神很好"], 0.85),
]
_SATIETY_TIERS = [
    (["饿得前胸贴后背", "肚子饿扁了", "饿得慌", "肚子咕咕叫", "饿惨了", "饿死"], 0.15),
    (["有点饿", "肚子有点空", "该吃点东西了", "嘴巴有点馋", "想吃点什么", "饿了"], 0.40),
    (["不饿", "肚子不饿", "还不觉得饿", "不馋", "暂时不想吃东西"], 0.60),
    (["吃得很饱", "吃撑了", "肚子圆滚滚", "撑得慌", "吃得心满意足", "吃得好饱", "吃饱"], 0.85),
]
_VALENCE_TIERS = [
    (["心情很差", "情绪很低落", "心里很堵", "丧到谷底", "看什么都不顺眼",
      "难受", "沮丧", "崩溃"], 0.20),
    (["有点丧", "有点郁闷", "情绪一般般", "提不起兴致", "心里灰灰的",
      "不开心", "烦闷"], 0.475),
    (["心情还行", "情绪还可以", "心态还算平和", "不好不坏", "心里挺平静",
      "还行", "还可以"], 0.625),
    (["心情不错", "心情挺好", "美滋滋", "心里亮堂", "莫名开心",
      "很开心", "高兴"], 0.85),
]

# ---------------------------------------------------------------
# 动力学常数：运行期从公开配置读取——config/system.toml [dynamics]/[events]/
# [economy] 为底，config/balance/dynamics.json 覆盖（与 world.py 的 _dyn 同一
# 合并语义）；模板餐/睡眠取 meal_tiers.json/sleep_tiers.json 默认档 M1/S1。
# 同机 CLI agent 同样可读 config/（依赖规则允许 import usersim.config；
# balance JSON 是纯数据文件直接读，import usersim.world.balance 会被禁止）。
# 任何一步读取失败都整体回退到下方硬编码快照（与 v5 配置一致的拷贝）；
# 改配置后此处自动跟随，不再有 v5.5 那种硬编码旧常数脱节问题。
# ---------------------------------------------------------------
SLOTS_PER_DAY = 4


def _load_dynamics() -> dict:
    out = {
        "satiety_drain": 0.06,           # 每 slot 饱腹消耗
        "work_stress": 0.035,            # 工作日工作时段压力增速
        "work_energy_drain": 0.04,       # 工作日工作时段精力消耗
        "rest_stress_relief": 0.020,     # 休息时段压力自然回落
        "stress_reversion_rate": 0.03,   # 压力均值回归速率/slot
        "stress_reversion_target": 0.32,
        "rebound_threshold": 0.12,       # 压力低于此值 → 工作效应反弹加倍
        "rebound_mult": 2.0,
        "valence_coupling_rate": 0.25,   # valence 向 v_eq 漂移速率（变差×1.5/变好×0.7）
        "weekend_days": (5, 6),          # day % 7 落在此处为周末
        "debt_stress_per_slot": 0.02,    # 余额为负时每 slot 压力惩罚
        "meal_pull": (0.70, 0.75),       # M1 模板餐：饱腹 pull 目标/速率（slots 0-2）
        "sleep_energy_pull": (0.80, 0.70),  # S1 正常睡眠：精力 pull 目标/速率（slot 3）
        "sleep_stress": -0.05,
    }
    try:
        from usersim.config import PROJECT_ROOT, load_system_config
        cfg = load_system_config()
        dyn = dict(cfg.dynamics.to_dict())
        bal = PROJECT_ROOT / "config" / "balance"
        ov = bal / "dynamics.json"
        if ov.exists():
            dyn.update(json.loads(ov.read_text(encoding="utf-8")))
        out.update({
            "satiety_drain": float(dyn["satiety_drain_per_slot"]),
            "work_stress": float(dyn["work_stress_per_slot"]),
            "work_energy_drain": float(dyn["work_energy_drain"]),
            "rest_stress_relief": float(dyn["rest_stress_relief"]),
            "stress_reversion_rate": float(dyn.get("stress_mean_reversion",
                                                 out["stress_reversion_rate"])),
            "stress_reversion_target": float(dyn.get("stress_reversion_target",
                                                     out["stress_reversion_target"])),
            "rebound_threshold": float(dyn["rebound_threshold"]),
            "rebound_mult": float(dyn["rebound_multiplier"]),
            "valence_coupling_rate": float(dyn["valence_coupling_rate"]),
            "weekend_days": tuple(int(d) for d in cfg.events.weekend_free_days),
            "debt_stress_per_slot": float(cfg.economy.debt_stress_per_slot),
        })
        meals = json.loads((bal / "meal_tiers.json").read_text(encoding="utf-8"))
        m1 = next((m for m in meals if m.get("vid") == "M1"), None)
        if m1 is not None:
            pull = m1["effect"]["satiety"]["pull"]
            out["meal_pull"] = (float(pull[0]), float(pull[1]))
        sleeps = json.loads((bal / "sleep_tiers.json").read_text(encoding="utf-8"))
        s1 = next((s for s in sleeps if s.get("vid") == "S1"), None)
        if s1 is not None:
            pull = s1["effect"]["energy"]["pull"]
            out["sleep_energy_pull"] = (float(pull[0]), float(pull[1]))
            out["sleep_stress"] = float(s1["effect"].get("stress", out["sleep_stress"]))
    except Exception:  # noqa: BLE001 — 配置不可读时退回上方硬编码快照
        pass
    return out


_C = _load_dynamics()
SATIETY_DRAIN: float = _C["satiety_drain"]
WORK_STRESS: float = _C["work_stress"]
WORK_ENERGY_DRAIN: float = _C["work_energy_drain"]
REST_STRESS_RELIEF: float = _C["rest_stress_relief"]
STRESS_REVERSION_RATE: float = _C["stress_reversion_rate"]
STRESS_REVERSION_TARGET: float = _C["stress_reversion_target"]
REBOUND_THRESHOLD: float = _C["rebound_threshold"]
REBOUND_MULT: float = _C["rebound_mult"]
VALENCE_COUPLING_RATE: float = _C["valence_coupling_rate"]
WEEKEND_DAYS: tuple[int, ...] = _C["weekend_days"]
DEBT_STRESS_PER_SLOT: float = _C["debt_stress_per_slot"]
MEAL_PULL: tuple[float, float] = _C["meal_pull"]
SLEEP_ENERGY_PULL: tuple[float, float] = _C["sleep_energy_pull"]
SLEEP_STRESS: float = _C["sleep_stress"]

# 自事件剂量表（经验法则：与目录价位档一致的粗估，只用于轮间积分的
# 短暂外推——下一次 session 锚定会修正误差）。按名字关键词匹配。
_DOSE_TABLE = [
    (["温泉"], {"stress": -0.20, "energy": 0.15}),
    (["按摩", "SPA", "spa"], {"stress": -0.14}),
    (["私教"], {"stress": -0.10, "energy": -0.05}),
    (["徒步", "近郊"], {"stress": -0.10, "energy": -0.05}),
    (["散步", "公园", "江边", "放空", "走走"], {"stress": -0.08, "valence": 0.04}),
    (["电影", "游戏", "宅家", "回血"], {"stress": -0.06, "valence": 0.06}),
    (["火锅", "大餐", "寿喜烧", "寿司", "烤", "吃"], {"satiety": 0.25, "valence": 0.05}),
    (["补觉", "睡眠", "好好休息", "懒觉"], {"energy": 0.20, "stress": -0.05}),
    (["健身", "跑步", "运动"], {"stress": -0.06, "energy": -0.06, "valence": 0.04}),
]

# 扰动剂量表（数值抄自 config/balance/disturbances.json，公开配表）：
# schedule_hint 会暴露今日扰动名——不建模它们是估计误差的最大来源（压力尖峰）
_DISTURBANCE_EFFECTS = [
    (["临时加班"], {"valence": -0.08, "energy": -0.16, "stress": 0.20}),
    (["应酬"], {"energy": -0.12, "satiety": 0.15, "stress": 0.10}),
    (["暴雨"], {"valence": -0.12, "stress": 0.09}),
    (["截止"], {"valence": -0.06, "energy": -0.10, "stress": 0.24}),
    (["邀约"], {"valence": 0.10, "energy": -0.08, "satiety": 0.10}),
]

# 系列事件剂量表（hint 同样暴露系列事件名；数值抄自 usersim/world/series.py
# SERIES_TYPES，agents 依赖规则禁止 import，故复制）。非 pull 效果世界按 span
# 摊销，故表值=当日合计剂量，每日结算一次。"大考结束"是系列收尾的一次性巨量
# 释放——不建模它，压力估计在释放日会跟丢 0.3+。
# 注意：合并匹配表 = 系列表 + 扰动表，按特异性排序取首个命中——"商务应酬"
# 必须排在扰动"应酬"前面，否则出差的商务应酬会被两张表各算一次。
_SERIES_EFFECTS = [
    (["刷题"], {"stress": 0.06, "energy": -0.08, "valence": -0.02}),
    (["网课"], {"stress": 0.02, "energy": -0.02}),
    (["大考结束"], {"stress": -0.35, "valence": 0.20}),
    (["考前焦虑"], {"stress": 0.03}),
    (["释放后空虚"], {"valence": -0.02}),
    (["异地工作"], {"stress": 0.04, "energy": -0.04}),
    (["客户会议"], {"stress": 0.08, "energy": -0.04}),
    (["商务应酬"], {"stress": 0.10, "satiety": 0.15, "energy": -0.06}),
    (["深夜赶材料"], {"energy": -0.08, "stress": 0.06}),
    (["长途交通"], {"energy": -0.10, "stress": 0.04}),
    (["差旅交通"], {"energy": -0.08, "stress": 0.03}),
    (["雪山湖泊"], {"valence": 0.20, "stress": -0.15, "energy": -0.08}),
    (["人文古迹"], {"valence": 0.14, "stress": -0.10, "energy": -0.06}),
    (["市集商圈"], {"valence": 0.12, "satiety": 0.10, "energy": -0.05}),
    (["主题乐园"], {"valence": 0.25, "stress": -0.12, "energy": -0.12}),
    (["海边发呆"], {"valence": 0.10, "stress": -0.18, "energy": 0.03}),
    (["温泉疗养"], {"stress": -0.20, "energy": 0.08, "valence": 0.06}),
    (["夜市小吃"], {"valence": 0.08, "satiety": 0.15}),
    (["酒店休息"], {"energy": 0.08, "stress": -0.05}),
    (["周边一日游"], {"valence": 0.15, "stress": -0.12, "energy": -0.06}),
    (["看展"], {"valence": 0.10, "stress": -0.06}),
    (["朋友聚会"], {"valence": 0.12, "satiety": 0.10}),
    (["纯宅"], {"valence": 0.04, "stress": -0.06}),
    (["旅行回味"], {"valence": 0.04}),
    (["差旅疲惫与回家踏实"], {"energy": -0.06, "valence": 0.05}),
]
_EVENT_EFFECTS = _SERIES_EFFECTS + _DISTURBANCE_EFFECTS

# 系列日类型登记键（按段首命中）：世界在系列期移除模板餐宿并换系列模板
# （world.py add_series 删除区间内 template 事件），且 suppress_work 系列把
# 工作 drift 按周末结算（effective_workday；v5.1 不知此事，备考期每天多扣
# energy 0.06+ 多加 stress 0.08，是 energy 系统性低估 0.3~0.5 的最大单因）。
# 后效事件（释放后空虚/旅行回味/差旅疲惫）不算系列日——系列已结束，工作恢复。
# 出差不 suppress_work（series.py:42 实锤，收入与工作 drift 照发）。
_SERIES_DAY_TYPES = [
    ("crunch", ("刷题", "网课", "备考", "大考", "考前焦虑")),
    ("business", ("酒店餐", "客户会议", "商务应酬", "深夜赶材料", "差旅交通", "异地工作")),
    ("trip", ("旅行餐食", "雪山湖泊", "人文古迹", "市集商圈", "主题乐园",
              "海边发呆", "温泉疗养", "夜市小吃", "酒店休息", "长途交通")),
    ("staycation", ("家常三餐", "懒觉自然醒", "周边一日游", "看展", "朋友聚会", "纯宅")),
]
_SUPPRESS_WORK_TYPES = {"crunch", "trip", "staycation"}


# ---------------------------------------------------------------
# 目录效果表（config/balance/venues.json + custom_activities.json，公开配表，
# 运行期读取、改配置自动跟随）：恢复事件的剂量精确回退与减压 veto 的判定依据。
# v5.6d 门控实锤：名称关键词 veto 被"吃好吃的/音乐放松/宅家回血"等规避——这些
# 单都带 stress −0.04~−0.10 的效果，压力地板下照样下单，把压力压到 0.04。
# 45 个场所里仅"家"有多 support 且 stress 差异 0.01，按首 support 取值足够。
# ---------------------------------------------------------------
def _load_catalog_effects() -> list[tuple[tuple[str, ...], dict]]:
    """(匹配键组, 效果向量) 列表，按键长降序（特异性优先）。读取失败返回空表。"""
    entries: list[tuple[tuple[str, ...], dict]] = []
    try:
        from usersim.config import PROJECT_ROOT
        bal = PROJECT_ROOT / "config" / "balance"
        for v in json.loads((bal / "venues.json").read_text(encoding="utf-8")):
            supports = [s for s in v.get("supports", []) if s.get("effect")]
            if not supports:
                continue
            eff = {k: float(x) for k, x in supports[0]["effect"].items()
                   if isinstance(x, (int, float))}
            keys = tuple(n for n in [v.get("name", ""), *v.get("aliases", [])] if n)
            if keys and eff:
                entries.append((keys, eff))
        for a in json.loads((bal / "custom_activities.json").read_text(encoding="utf-8")):
            eff = {k: float(x) for k, x in (a.get("effect") or {}).items()
                   if isinstance(x, (int, float))}
            keys = tuple(n for n in [a.get("name", ""), *a.get("keywords", [])] if n)
            if keys and eff:
                entries.append((keys, eff))
    except Exception:  # noqa: BLE001 — 配表不可读时退化为关键词剂量表
        return []
    entries.sort(key=lambda kv: max(len(k) for k in kv[0]), reverse=True)
    return entries


_CATALOG_EFFECTS = _load_catalog_effects()


def catalog_effect_of(text: str) -> dict | None:
    """文本（事件名/场所/组合）→ 目录效果向量；无命中返回 None。"""
    for keys, eff in _CATALOG_EFFECTS:
        if any(k in text for k in keys):
            return eff
    return None


def _clip01(v: float) -> float:
    return min(1.0, max(0.0, v))


def _lookup(text: str, tiers: list[tuple[list[str], float]]) -> float | None:
    """措辞 → 档位中点；无命中返回 None（该维本轮无观测）。"""
    for phrases, mid in tiers:
        if any(p in text for p in phrases):
            return mid
    return None


class StateTracker:
    """跨 turn 的状态滤波器：session 首轮 felt 锚定，轮间公开动力学积分。"""

    def __init__(self, use_felt_lookup: bool = True) -> None:
        self.use_felt_lookup = use_felt_lookup
        # 先验取 config [state].initial（公开配置）：与角色卡 x0 大致同档
        self.x = {"valence": 0.70, "energy": 0.75, "satiety": 0.60, "stress": 0.28}
        self.day = 0
        self.slot = 0
        self.pending: list[dict] = []  # 自己安排的、尚未生效的事件 {"day","slot","span","effect"}
        self._dist_seen: set[str] = set()  # 已结算的扰动 "day:事件名"（hint 全天可见，防重复）
        self._suppress_work_days: set[int] = set()  # suppress_work 系列期（工作 drift 按周末算）
        self._series_days: dict[int, str] = {}  # day → 系列类型（crunch/trip/staycation/business）
        self._learned_effects: dict[str, dict] = {}  # 事件名 → 工具回执里的真实效果向量

    # ---- 效果解析：减压 veto 与剂量回退共用的判定 ----
    def stress_effect_of(self, name: str, location: str = "", goal: str = "") -> float:
        """估计一个待下单事件对压力的效果（<0 即减压单）。
        链式解析：已学到的真实效果（工具回执）→ 目录配表（场所/别名/动作/关键词）
        → 关键词剂量表 → 默认 −0.06（未知动作按最轻恢复档——对地板 veto 是保守向）。"""
        eff = self._resolve_effect(name, location, goal)
        v = eff.get("stress", 0.0)
        if isinstance(v, dict):  # pull 类：拉向目标值，按目标-0.30 的符号估
            return float(v["pull"][0]) - 0.30
        return float(v)

    def _resolve_effect(self, name: str, location: str = "", goal: str = "") -> dict:
        for text in (name, f"{name} · {location}" if location else ""):
            if text and text in self._learned_effects:
                return self._learned_effects[text]
        for text in (f"{name} · {location}" if location else "", name, goal):
            if not text:
                continue
            eff = catalog_effect_of(text)
            if eff:
                return eff
        for keys, eff in _DOSE_TABLE:
            if any(k in name or k in location or k in goal for k in keys):
                return dict(eff)
        return {"stress": -0.06}  # 未知动作按最轻恢复档估

    # ---- 观测：用户措辞 → 状态锚定/修正 ----
    def observe(self, user_say: str, *, hard: bool) -> None:
        """hard=True（session 首轮）：命中维度直接重置为中点；
        其余轮：命中维度向中点收一半（措辞可能是旧信息，留一半给积分值）。"""
        if not self.use_felt_lookup:
            return
        for key, tiers in (("stress", _STRESS_TIERS), ("energy", _ENERGY_TIERS),
                           ("satiety", _SATIETY_TIERS), ("valence", _VALENCE_TIERS)):
            hit = _lookup(user_say, tiers)
            if hit is None:
                continue
            self.x[key] = hit if hard else _clip01(0.5 * self.x[key] + 0.5 * hit)

    # ---- 扰动/系列事件建模：schedule_hint 暴露的今日事件，每 (天, 事件) 结算一次 ----
    def apply_disturbances(self, schedule_hint: str, day: int,
                           slot_names: list[str] | None = None) -> None:
        """hint 全天可见，每 (天, 事件) 只结算一次；措辞锚定在其后执行可覆盖之。
        按段匹配（"；分隔、（时段）"后缀）：助手自订恢复事件是"动作 · 场所"复合名，
        剂量走 register_event——段内含 " · " 直接跳过，防止与系列关键词双计
        （v5.6c 实锤："文化看展 · 市美术馆"曾误中系列"看展"）。每段取合并表首个
        命中（表按特异性排序，"商务应酬"先于扰动"应酬"）。
        剂量按事件实际槽位入队结算（世界在该槽位结束才生效，turns 的 x_true 是
        进入槽位的状态——首次见到就立即加曾把当日上午的加班压力提前半天计入，
        d27 实锤 +0.20 提前量）；槽位不可解析或已越过时退化为立即结算。
        同时登记系列日类型：suppress_work 系列（备考/旅行/宅家）把工作 drift 按
        周末算，出差不 suppress；系列餐宿模板在 _settle_slot 按类型切换。"""
        hint = schedule_hint or ""
        for seg in hint.split("；"):
            if " · " in seg:
                continue
            name, _, tail = seg.partition("（")
            name = name.strip()
            if not name:
                continue
            slot_idx = None
            if slot_names and tail:
                sname = tail.split("（")[0].rstrip("）").strip()
                if sname in slot_names:
                    slot_idx = slot_names.index(sname)
            for keys, eff in _EVENT_EFFECTS:
                if not any(k in name for k in keys):
                    continue
                tag = f"{day}:{name}"
                if tag not in self._dist_seen:
                    self._dist_seen.add(tag)
                    if slot_idx is None or (day, slot_idx) < (self.day, self.slot):
                        for k, v in eff.items():  # 已越过/不可解析：立即补记
                            self.x[k] = _clip01(self.x[k] + v)
                    else:  # 入队，随该槽位结算（对齐世界时点）
                        self.pending.append({"day": day, "slot": slot_idx, "span": 1,
                                             "span_total": 1, "effect": dict(eff)})
                break  # 每段只取首个命中
            if day not in self._series_days:
                for stype, keys in _SERIES_DAY_TYPES:
                    if any(k in name for k in keys):
                        self._series_days[day] = stype
                        if stype in _SUPPRESS_WORK_TYPES:
                            self._suppress_work_days.add(day)
                        break
        # 21 天滚动清理（系列最长 14 天，窗口足够覆盖）
        self._series_days = {d: t for d, t in self._series_days.items() if d >= day - 21}
        self._suppress_work_days = {d for d in self._suppress_work_days if d >= day - 21}

    # ---- 自事件登记（add_event_todo 成功后由 harness 调用）----
    def register_event(self, name: str, day: int, slot: int, span: int = 1,
                       effect: dict | None = None) -> None:
        """effect 优先用 add_event_todo 返回 payload 里的真实效果向量（世界直接
        告知，v5.1 实测回复 payload 带 effect 字段；pull 类按世界语义保留——
        拉向准稳态、不摊销）；拿不到才回退关键词剂量表。
        已过时段的剂量立即补记：工具结果回到 tracker 时积分常已越过事件槽位，
        入队永远等不到触发（v5.6 实测这是 stress 估计系统性偏高 +0.1~0.2 的
        最大单因——同槽下单的减压剂量整剂丢失）。
        payload 真实效果同时写入学习表，供 veto/后续同名单复用。"""
        clean: dict[str, float | dict] = {}
        if effect:
            for k, v in effect.items():
                if k not in self.x:
                    continue
                if isinstance(v, (int, float)):
                    clean[k] = float(v)
                elif isinstance(v, dict) and "pull" in v:
                    clean[k] = {"pull": [float(v["pull"][0]), float(v["pull"][1])]}
        if clean:
            self._learned_effects[name] = {k: (dict(v) if isinstance(v, dict) else v)
                                           for k, v in clean.items()}
        else:
            clean = dict(self._resolve_effect(name))
        ev = {"day": day, "slot": slot, "span": max(1, int(span)),
              "span_total": max(1, int(span)), "effect": clean}
        # 积分指针已过（结果晚到）的时段：立即补记，不入队
        while ev["span"] > 0 and (ev["day"], ev["slot"]) < (self.day, self.slot):
            self._apply_event_dose(ev)
            ev["span"] -= 1
            ev["slot"] += 1
        if ev["span"] > 0:
            self.pending.append(ev)

    def _apply_event_dose(self, ev: dict) -> None:
        """单时段剂量：数值效果按原始 span 摊销；pull 类拉向准稳态不摊销。"""
        for k, v in ev["effect"].items():
            if isinstance(v, dict):
                target, rate = float(v["pull"][0]), float(v["pull"][1])
                self.x[k] = _clip01(self.x[k] + (target - self.x[k]) * rate)
            else:
                self.x[k] = _clip01(self.x[k] + v / ev["span_total"])

    # ---- 积分：推进到"进入 (day, slot)"的状态（即该时段结算之前）----
    def advance_to(self, day: int, slot: int, balance: float | None) -> None:
        """对齐世界时点：slot 的结算发生在时段结束、session 进行时观察到的
        是进入该时段的状态（turns 里 x_true == 上一 slot 的 x_after），
        故积分到 (day, slot) 的前一个 slot 为止。"""
        steps = (day - self.day) * SLOTS_PER_DAY + (slot - self.slot)
        if steps < 0:  # 续跑/时钟回拨：不倒积，只同步指针
            self.day, self.slot = day, slot
            return
        for _ in range(steps):
            self._settle_slot(self.day, self.slot, balance)
            self.slot += 1
            if self.slot >= SLOTS_PER_DAY:
                self.slot = 0
                self.day += 1

    def _settle_slot(self, day: int, slot: int, balance: float | None) -> None:
        """对齐 dynamics.py 的结算顺序：漂移 → 反弹 → 事件 → 耦合 → 限幅。"""
        x = self.x
        series = self._series_days.get(day)
        workday = (day % 7) not in WEEKEND_DAYS and day not in self._suppress_work_days
        x["satiety"] -= SATIETY_DRAIN
        rebound = x["stress"] < REBOUND_THRESHOLD
        mult = REBOUND_MULT if rebound else 1.0
        if slot == 0:
            if workday:
                x["energy"] -= WORK_ENERGY_DRAIN * (1.5 if rebound else 1.0)
                x["stress"] += WORK_STRESS * mult
            else:
                x["energy"] -= 0.03
        elif slot == 1:
            if workday:
                x["energy"] -= WORK_ENERGY_DRAIN * (1.5 if rebound else 1.0)
                x["stress"] += WORK_STRESS * mult
            else:
                x["energy"] -= 0.03
                x["valence"] += 0.03
                x["stress"] -= REST_STRESS_RELIEF
        elif slot == 2:
            x["stress"] -= REST_STRESS_RELIEF
            x["energy"] -= 0.04 if workday else 0.03
        # 压力均值回归（人格调节系数对被测件不可见，按 1.0 估）
        x["stress"] += (STRESS_REVERSION_TARGET - x["stress"]) * STRESS_REVERSION_RATE
        # 负债压力
        if balance is not None and balance < 0:
            x["stress"] += DEBT_STRESS_PER_SLOT
        # 模板餐（slots 0-2）与睡眠（slot 3）：世界在系列期移除模板事件并换系列
        # 模板（world.py add_series），此处按系列日类型同步切换（v5.6c 实锤：crunch
        # 期睡眠是 [0.78,0.50] stress−0.01，tracker 用 S1 每天多压 stress 0.04）。
        if slot <= 2:
            target, rate = MEAL_PULL
            if series == "trip":
                target, rate = 0.80, 0.75
                x["valence"] += 0.04  # 旅行餐食 valence+0.12 按 span 3 摊销
            elif series == "staycation":
                target, rate = 0.73, 0.75
            elif series == "business":
                target, rate = 0.76, 0.75
                x["stress"] += 0.01  # 酒店餐 stress+0.03 按 span 3 摊销
            x["satiety"] += (target - x["satiety"]) * rate
        if slot == 3:
            target, rate = SLEEP_ENERGY_PULL
            s_eff = SLEEP_STRESS
            if series == "crunch":
                target, rate, s_eff = 0.78, 0.50, -0.01
            elif series == "trip":
                target, rate, s_eff = 0.72, 0.50, 0.0
            elif series == "staycation":
                target, rate, s_eff = 0.85, 0.55, 0.0
                x["valence"] += 0.03  # 懒觉自然醒附带心情加成
            elif series == "business":
                target, rate, s_eff = 0.70, 0.50, 0.0
            x["energy"] += (target - x["energy"]) * rate
            x["stress"] += s_eff
        # 自己安排的事件生效（数值按原始 span 摊销；pull 类不摊销）
        for ev in list(self.pending):
            if (ev["day"], ev["slot"]) == (day, slot):
                self._apply_event_dose(ev)
                ev["span"] -= 1
                ev["slot"] += 1
                if ev["span"] <= 0:
                    self.pending.remove(ev)
        # 心情耦合（消极偏向）
        v_eq = (0.75 + 0.35 * (x["energy"] - 0.68)
                - 0.55 * (x["stress"] - 0.30) + 0.10 * (x["satiety"] - 0.60))
        delta = v_eq - x["valence"]
        x["valence"] += VALENCE_COUPLING_RATE * (1.5 if delta < 0 else 0.7) * delta
        for k in x:
            x[k] = _clip01(x[k])

    # ---- 输出 ----
    def estimate(self) -> dict[str, float]:
        return {k: round(_clip01(v), 3) for k, v in self.x.items()}

    # ---- 前向仿真：预测 (day, slot) 的状态（含在途事件与自然漂移，不改自身）----
    def predict_at(self, day: int, slot: int, balance: float | None) -> dict[str, float]:
        """下单前评估交付时点：轻度超带若靠休息/睡眠自然回落即可自愈，
        追单只会把状态压穿下界（v5full 实测 overshoot 0.300 打满的来源）。"""
        sim = StateTracker(use_felt_lookup=False)
        sim.restore(self.snapshot())
        sim.advance_to(day, slot, balance)
        return sim.x

    # ---- 续跑支持 ----
    def snapshot(self) -> dict:
        return {"x": dict(self.x), "day": self.day, "slot": self.slot,
                "pending": [dict(ev) for ev in self.pending],
                "dist_seen": sorted(self._dist_seen),
                "suppress_work_days": sorted(self._suppress_work_days),
                "series_days": {str(d): t for d, t in self._series_days.items()},
                "learned_effects": {k: dict(v) for k, v in self._learned_effects.items()}}

    def restore(self, state: dict) -> None:
        if not state:
            return
        x = state.get("x")
        if isinstance(x, dict):
            for k in self.x:
                if k in x:
                    self.x[k] = _clip01(float(x[k]))
        self.day = int(state.get("day", 0))
        self.slot = int(state.get("slot", 0))
        self.pending = [dict(ev) for ev in (state.get("pending") or [])]
        for ev in self.pending:  # 旧快照无 span_total：按当前 span 兜底
            ev.setdefault("span_total", ev.get("span", 1))
        self._dist_seen = {str(t) for t in (state.get("dist_seen") or [])}
        self._suppress_work_days = {int(d) for d in (state.get("suppress_work_days") or [])}
        self._series_days = {int(d): str(t)
                             for d, t in (state.get("series_days") or {}).items()}
        self._learned_effects = {str(k): dict(v) for k, v in
                                 (state.get("learned_effects") or {}).items()
                                 if isinstance(v, dict)}
