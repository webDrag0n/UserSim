"""拟人化行为引擎：习惯化曲线 + 需求动力学 + 人格调节（docs/11）。

无计时器：一切由"上次执行时间差 Δt"与规则公式计算。
曲线参数默认值在此定义；balance-sheet/UserSim数值配表.xlsx 中的
「习惯化曲线 / 需求参数 / 人格调节」sheet 可覆盖（world/balance.py 加载）。
"""

from __future__ import annotations

import ast
import math
import operator
from typing import Callable

from usersim.contracts.persona import trait

# ---------------------------------------------------------------
# 0. 安全公式解析器
# ---------------------------------------------------------------

SAFE_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.USub: operator.neg,
}

SAFE_FUNCS = {
    'abs': abs,
    'min': min,
    'max': max,
    'sqrt': math.sqrt,
}


def parse_formula_multi(expr: str, var_names: tuple[str, ...] = ('x',)) -> Callable[[dict[str, float]], float] | None:
    """安全解析多变量公式字符串为可执行函数。

    支持语法: x, y, E, N, +, -, *, /, ^, **, 括号, abs/min/max/sqrt
    示例: "1 + 1.2*E" → 传入 {"E": 0.9} 返回 2.08
    """
    try:
        expr = expr.replace('²', '**2').replace('³', '**3').replace('^', '**')
        expr = expr.replace('u=', '').replace('s=', '').strip()
        import re
        expr = re.sub(r'(\d)([a-zA-Z])', r'\1*\2', expr)

        tree = ast.parse(expr, mode='eval')

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if not isinstance(node.func, ast.Name) or node.func.id not in SAFE_FUNCS:
                    return None
            elif isinstance(node, (ast.Import, ast.ImportFrom, ast.Attribute)):
                return None
            elif isinstance(node, ast.Name):
                if node.id not in var_names and node.id not in SAFE_FUNCS:
                    return None

        code = compile(tree, '<formula>', 'eval')

        def eval_func(vars: dict[str, float]) -> float:
            result = eval(code, {"__builtins__": {}}, {**vars, **SAFE_FUNCS})
            return float(result)

        return eval_func
    except Exception:
        return None


def parse_formula(expr: str, var_name: str = 'x') -> Callable[[float], float] | None:
    """安全解析单变量公式字符串为可执行函数。"""
    multi = parse_formula_multi(expr, (var_name,))
    if multi is None:
        return None
    def eval_func(x: float) -> float:
        return multi({var_name: x})
    return eval_func

# ---------------------------------------------------------------
# 1. 习惯化曲线
# ---------------------------------------------------------------

# 规范事件名 → (w_min, tau(时段), 曲线类型 exp|sqrt|s)
HABITUATION_DEFAULTS: dict[str, tuple[float, float, str]] = {
    "吃好吃的": (0.50, 12, "exp"),
    "好好休息": (0.55, 8, "exp"),
    "出门走走": (0.30, 6, "exp"),
    "短途旅行": (0.20, 60, "s"),
    "运动健身": (0.60, 8, "exp"),
    "宅家回血": (0.35, 6, "exp"),
    "文化看展": (0.15, 20, "s"),
    "咖啡小憩": (0.45, 8, "exp"),
    "音乐放松": (0.45, 10, "exp"),
    "朋友小聚": (0.40, 16, "sqrt"),
    "自然放空": (0.30, 6, "exp"),
    "自定义活动": (0.40, 8, "exp"),
}
HAB_DEFAULT = (0.40, 8, "exp")  # 未配置动作（景点/活动等）的默认


def habit_key(event_name: str) -> str:
    """事件名 → 习惯化规范键：去掉" · 地点"后缀与自定义原称。"""
    base = event_name.split("（")[0].split(" · ")[0].strip()
    return base


def hab_weight(dt: float, w_min: float, tau: float, curve: str) -> float:
    """边际效益权重：dt=上次执行距此时段数；dt=0 → w_min；dt→∞ → 1。
    所有曲线的 c(dt) 均为 1→0 衰减核：w = 1 - (1-w_min)·c。"""
    dt = max(0.0, dt)
    if tau <= 0:
        return 1.0
    if curve == "sqrt":
        c = (tau / (dt + tau)) ** 0.5  # 前快后慢恢复（社交类）
    elif curve == "s":
        c = (tau * tau) / (tau * tau + dt * dt)  # S 型（爱好：短期不错，长期更想）
    else:  # exp
        c = math.exp(-dt / tau)
    return 1.0 - (1.0 - w_min) * c


def habit_params(name: str, overrides: dict | None = None) -> tuple[float, float, str]:
    table = (overrides or {}).get("habituation", {})
    key = habit_key(name)
    if key in table:
        row = table[key]
        return float(row["w_min"]), float(row["tau"]), str(row["curve"])
    return HABITUATION_DEFAULTS.get(key, HAB_DEFAULT)


# ---------------------------------------------------------------
# 2. 需求动力学
# ---------------------------------------------------------------

NEED_DEFAULTS: dict[str, float] = {
    "hunger": 0.2, "social": 0.3, "stimulation": 0.5, "achievement": 0.2,
}

SOCIAL_EVENTS = ("朋友小聚", "朋友临时邀约", "商务应酬", "聚会")
STIM_EVENTS = ("文化看展", "音乐放松", "自然放空", "自定义活动", "雪山湖泊", "人文古迹", "市集商圈",
               "主题乐园", "海边发呆", "温泉疗养", "夜市小吃", "看展", "周边一日游", "短途旅行")
ACHIEVE_EVENTS = ("刷题", "网课", "工作", "大考结束")


class Needs:
    """需求层：只驱动求助倾向与效果权重，不直接写状态。"""

    def __init__(self, state: dict[str, float] | None = None):
        self.n = dict(NEED_DEFAULTS if state is None else state)
        self._urge_funcs: dict[str, Callable[[float], float]] = {}
        self._satisfy_funcs: dict[str, Callable[[float], float]] = {}

    def to_dict(self) -> dict[str, float]:
        return dict(self.n)

    def update(self, satiety: float, active_names: list[str], extraversion: int,
               exam_active: bool, deadline_disturbance: bool, slot: int = 1) -> None:
        n = self.n
        # 饥饿：直接由饱腹推导（低饱腹加速驱动）
        n["hunger"] = max(0.0, min(1.0, 1.0 - satiety))
        # 生物钟：三餐时段前后饥饿驱动力额外放大（上午末/下午/晚间入口）
        # slot 0=上午, 1=下午, 2=晚上, 3=深夜
        meal_slots = (1, 2)  # 午饭/晚饭时段，饥饿驱动更迫切
        if slot in meal_slots:
            n["hunger"] = min(1.0, n["hunger"] * 1.2)
        # 社交：每时段累积，群居性高者更快；社交事件后释放
        # 晚间社交需求稍高（下班后更想社交）
        social_rate = 0.01 * (1.6 if extraversion >= 60 else 1.0)
        if slot == 2:  # 晚上社交需求累积更快
            social_rate *= 1.3
        n["social"] = min(1.0, n["social"] + social_rate)
        if any(any(k in nm for k in SOCIAL_EVENTS) for nm in active_names):
            n["social"] = max(0.1, n["social"] - 0.5)
        # 刺激：向无聊基线回落，新异事件提升
        n["stimulation"] = max(0.0, n["stimulation"] - 0.01)
        stim_hits = sum(1 for nm in active_names if any(k in nm for k in STIM_EVENTS))
        n["stimulation"] = min(1.0, n["stimulation"] + 0.12 * stim_hits)
        # 成就：备考/截止逼近时陡增，推进时缓释
        if exam_active:
            n["achievement"] = min(1.0, n["achievement"] + 0.06)
        if deadline_disturbance:
            n["achievement"] = min(1.0, n["achievement"] + 0.2)
        if any(any(k in nm for k in ACHIEVE_EVENTS) for nm in active_names):
            n["achievement"] = max(0.1, n["achievement"] - 0.03)

    # ---- 驱动力曲线 u(x)：→ 求助倾向 ----
    def urges(self, overrides: dict | None = None) -> dict[str, float]:
        """计算各需求的驱动力。优先使用配置公式，回退到硬编码默认值。"""
        n = self.n
        needs_cfg = (overrides or {}).get("needs", {})

        result = {}

        # 需求名映射（配置文件用中文键，内部用英文键）
        need_map = {
            "hunger": "饥饿",
            "social": "社交",
            "stimulation": "刺激",
            "achievement": "成就"
        }

        for eng_key, value in n.items():
            cn_key = need_map.get(eng_key, eng_key)
            cfg = needs_cfg.get(cn_key, {})
            formula_str = cfg.get("urge_curve", "")

            # 尝试使用配置公式（按公式内容缓存，避免不同 overrides 互相污染）
            func = None
            if formula_str:
                cache_key = f"{eng_key}:{formula_str}"
                if cache_key not in self._urge_funcs:
                    self._urge_funcs[cache_key] = parse_formula(formula_str, 'x')
                func = self._urge_funcs.get(cache_key)

            if func:
                try:
                    result[eng_key] = max(0.0, min(1.0, func(value)))
                    continue
                except:
                    pass

            # 回退到硬编码默认值
            if eng_key == "hunger":
                result[eng_key] = min(1.0, (value / 0.6) ** 1.5) if value > 0 else 0.0
            elif eng_key == "social":
                result[eng_key] = value ** 2
            elif eng_key == "stimulation":
                result[eng_key] = 1.0 - (2 * value - 1) ** 2
            elif eng_key == "achievement":
                result[eng_key] = value ** 2.5
            else:
                result[eng_key] = value

        return result

    def session_urge(self, overrides: dict | None = None) -> float:
        return max(self.urges(overrides).values())

    # ---- 满足曲线 s(x)：→ 效果权重 ----
    def satisfaction(self, event_name: str, overrides: dict | None = None) -> float:
        """计算事件的满足权重。优先使用配置公式，回退到硬编码逻辑。"""
        n = self.n
        u = self.urges(overrides)
        needs_cfg = (overrides or {}).get("needs", {})

        # 识别事件类型并尝试使用配置公式
        if any(k in event_name for k in ("吃", "餐", "美食", "火锅", "寿喜烧")):
            cfg = needs_cfg.get("饥饿", {})
            formula_str = cfg.get("satisfy_curve", "")
            if formula_str:
                cache_key = f"hunger:{formula_str}"
                if cache_key not in self._satisfy_funcs:
                    self._satisfy_funcs[cache_key] = parse_formula(formula_str, 'u')
                func = self._satisfy_funcs.get(cache_key)
                if func:
                    try:
                        return max(0.0, func(u["hunger"]))
                    except:
                        pass
            # 硬编码回退
            return 1.0 + 1.5 * u["hunger"]

        if any(k in event_name for k in SOCIAL_EVENTS):
            cfg = needs_cfg.get("社交", {})
            formula_str = cfg.get("satisfy_curve", "")
            if formula_str:
                cache_key = f"social:{formula_str}"
                if cache_key not in self._satisfy_funcs:
                    self._satisfy_funcs[cache_key] = parse_formula(formula_str, 'u')
                func = self._satisfy_funcs.get(cache_key)
                if func:
                    try:
                        return max(0.0, func(u["social"]))
                    except:
                        pass
            # 硬编码回退
            return 1.0 + 0.8 * u["social"]

        if any(k in event_name for k in STIM_EVENTS):
            cfg = needs_cfg.get("刺激", {})
            formula_str = cfg.get("satisfy_curve", "")
            if formula_str:
                cache_key = f"stimulation:{formula_str}"
                if cache_key not in self._satisfy_funcs:
                    self._satisfy_funcs[cache_key] = parse_formula(formula_str, 'x')
                func = self._satisfy_funcs.get(cache_key)
                if func:
                    try:
                        return max(0.0, func(n["stimulation"]))
                    except:
                        pass
            # 硬编码回退：中等最爽，过载打折（非单调）
            return 0.6 + 0.8 * (1.0 - abs(2 * n["stimulation"] - 1))

        return 1.0


# ---------------------------------------------------------------
# 3. 人格调节（大五生效）
# ---------------------------------------------------------------

def persona_modifiers(big5: dict[str, int], event_name: str, effect: dict,
                      facets: dict[str, int] | None = None,
                      overrides: dict | None = None) -> dict:
    """按人格修正事件效果（facet 粒度）。覆盖大五人格全部五个维度。

    facets 给定时按细分面调节，缺失时自动回退到域分——旧存档因此行为不变：

    - **社交电池（外向性）**：群居性 决定社交耗电/回血，热情 决定心情加成；
    - **压力放大（神经质）**：焦虑 + 脆弱 的均值决定压力事件被放大多少；
    - **新异刺激（开放性）**：尝新 + 审美 决定新异/文化类事件的收益；
    - **任务承压（尽责性）**：自律 决定工作/成就类事件的负面压力被缓冲多少；
    - **人际融洽（宜人性）**：同理心 决定社交事件正面心情的额外加成。

    配置中 `persona_mod` 的公式可覆盖默认系数；公式非法或缺失时回退硬编码。
    """
    out = dict(effect)
    gregarious = trait(big5, facets, "外向性.群居性") / 100
    warmth = trait(big5, facets, "外向性.热情") / 100
    anxiety = trait(big5, facets, "神经质.焦虑") / 100
    vulnerability = trait(big5, facets, "神经质.脆弱") / 100
    neuro = (anxiety + vulnerability) / 2
    novelty = trait(big5, facets, "开放性.尝新") / 100
    aesthetic = trait(big5, facets, "开放性.审美") / 100
    conscientious = trait(big5, facets, "尽责性.自律") / 100
    empathy = trait(big5, facets, "宜人性.同理心") / 100

    persona_cfg = (overrides or {}).get("persona_mod", {})

    def _mult(key: str, default_expr: str, vars: dict[str, float]) -> float:
        """从配置公式计算倍率，失败则使用默认表达式。"""
        cfg = persona_cfg.get(key, {})
        formula = cfg.get("formula") or cfg.get("rule", "")
        if formula:
            func = parse_formula_multi(formula, tuple(vars.keys()))
            if func is not None:
                try:
                    return func(vars)
                except Exception:
                    pass
        # 默认表达式也走安全解析，避免手写系数与公式不同步
        func = parse_formula_multi(default_expr, tuple(vars.keys()))
        if func is not None:
            return func(vars)
        return 1.0

    def num(k: str) -> bool:
        return isinstance(out.get(k), (int, float))

    is_social = any(k in event_name for k in SOCIAL_EVENTS)
    is_work_achieve = any(k in event_name for k in ("工作", "刷题", "网课", "大考", "项目", "截止"))
    is_stim = any(k in event_name for k in STIM_EVENTS)

    if is_social:
        if num("energy"):
            pos_mult = _mult("外向性", "1 + 1.2*E", {"E": gregarious})
            out["energy"] *= pos_mult if out["energy"] > 0 else (1.6 - 1.2 * gregarious)
        else:
            out["energy"] = 0.04 * gregarious - 0.05 * (1 - gregarious)
        # 宜人性：社交正面心情加成
        if num("valence") and out["valence"] > 0:
            agree_mult = _mult("宜人性", "1 + 0.3*A", {"A": empathy})
            out["valence"] *= agree_mult
        # 外向性热情：高热情额外加心情小冲量
        if warmth > 0.7 and num("valence"):
            out["valence"] = out.get("valence", 0.0) + 0.03
    if num("stress") and out["stress"] > 0:
        stress_mult = _mult("神经质", "1 + (N - 0.5)", {"N": neuro})
        out["stress"] *= stress_mult
    if is_stim:
        openness = (novelty + aesthetic) / 2
        stim_mult = _mult("开放性", "0.7 + 0.6*O", {"O": openness})
        if num("valence") and out["valence"] > 0:
            out["valence"] *= stim_mult
        if num("stress") and out["stress"] < 0:
            out["stress"] *= stim_mult
    # 尽责性：工作/成就类负面压力缓冲
    if is_work_achieve and num("stress") and out["stress"] < 0:
        cons_mult = _mult("尽责性", "1 - 0.3*C", {"C": conscientious})
        out["stress"] *= cons_mult
    return out


def reversion_rate_mult(big5: dict[str, int], facets: dict[str, int] | None = None) -> float:
    """神经质（焦虑 + 脆弱）越高，压力均值回归越慢。"""
    anxiety = trait(big5, facets, "神经质.焦虑") / 100
    vulnerability = trait(big5, facets, "神经质.脆弱") / 100
    return 1.0 - 0.4 * ((anxiety + vulnerability) / 2)


# ---------------------------------------------------------------
# 4. 喜好调节（结构化偏好生效）
# ---------------------------------------------------------------

# 喜好对效果的最大调幅：±40%。上限刻意保守——喜好要能被观测到（否则助手无从学起，
# 画像精度也就无从谈起），但不能大到让"猜中喜好"压倒控制策略本身。
PREF_GAIN = 0.4


def preference_multiplier(pref_score: float) -> float:
    """类目偏好分 [-1,1] → 效果倍率。爱做的事回血更多，讨厌的事事倍功半。"""
    return 1.0 + PREF_GAIN * max(-1.0, min(1.0, float(pref_score)))


def preference_modifiers(prefs, event_name: str, effect: dict,
                         category: str | None = None) -> dict:
    """按结构化喜好修正事件的**正向**效果。

    只放大/缩小对用户有益的分量（valence 正、stress 负）——讨厌的活动不会因为
    "讨厌"就变得更伤身，它只是**没那么回血**。此外命中 loves/hates 关键词时
    额外给心情一个小冲量：这是助手"真的懂我"最直接的可观测信号。
    """
    if prefs is None or not effect:
        return effect
    from usersim.contracts.persona import pref_category

    cat = category or pref_category(event_name)
    out = dict(effect)
    mult = preference_multiplier(prefs.pref_of(cat)) if cat else 1.0

    if mult != 1.0:
        for k, v in list(out.items()):
            if isinstance(v, dict) and "pull" in v:
                continue  # pull 类是"拉向准稳态"，喜好不改变目标值
            if k == "stress" and v < 0:
                out[k] = v * mult
            elif k in ("valence", "energy") and v > 0:
                out[k] = v * mult

    name = event_name or ""
    hit_love = any(tag and tag in name for tag in getattr(prefs, "loves", []))
    hit_hate = any(tag and tag in name for tag in getattr(prefs, "hates", []))
    if hit_love or hit_hate:
        bonus = (0.04 if hit_love else 0.0) - (0.04 if hit_hate else 0.0)
        base = out.get("valence")
        if isinstance(base, (int, float)):
            out["valence"] = base + bonus
        elif base is None:
            out["valence"] = bonus
    return out
