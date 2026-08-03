"""拟人化行为引擎：习惯化曲线 + 需求动力学 + 人格调节（docs/11）。

无计时器：一切由"上次执行时间差 Δt"与规则公式计算。
曲线参数默认值在此定义；balance-sheet/UserSim数值配表.xlsx 中的
「习惯化曲线 / 需求参数 / 人格调节」sheet 可覆盖（world/balance.py 加载）。
"""

from __future__ import annotations

import math

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

    def to_dict(self) -> dict[str, float]:
        return dict(self.n)

    def update(self, satiety: float, active_names: list[str], extraversion: int,
               exam_active: bool, deadline_disturbance: bool) -> None:
        n = self.n
        # 饥饿：直接由饱腹推导（低饱腹加速驱动）
        n["hunger"] = max(0.0, min(1.0, 1.0 - satiety))
        # 社交：每时段累积，外向者更快；社交事件后释放
        n["social"] = min(1.0, n["social"] + 0.01 * (1.6 if extraversion >= 60 else 1.0))
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
    def urges(self) -> dict[str, float]:
        n = self.n
        return {
            "hunger": min(1.0, (n["hunger"] / 0.6) ** 1.5) if n["hunger"] > 0 else 0.0,
            "social": n["social"] ** 2,
            "stimulation": 1.0 - (2 * n["stimulation"] - 1) ** 2,  # 倒 U：太少无聊/太多过载
            "achievement": n["achievement"] ** 2.5,
        }

    def session_urge(self) -> float:
        return max(self.urges().values())

    # ---- 满足曲线 s(x)：→ 效果权重 ----
    def satisfaction(self, event_name: str) -> float:
        n = self.n
        u = self.urges()
        if any(k in event_name for k in ("吃", "餐", "美食", "火锅", "寿喜烧")):
            return 1.0 + 1.5 * u["hunger"]
        if any(k in event_name for k in SOCIAL_EVENTS):
            return 1.0 + 0.8 * u["social"]
        if any(k in event_name for k in STIM_EVENTS):
            # 刺激满足：中等最爽，过载打折（非单调）
            return 0.6 + 0.8 * (1.0 - abs(2 * n["stimulation"] - 1))
        return 1.0


# ---------------------------------------------------------------
# 3. 人格调节（大五生效）
# ---------------------------------------------------------------

def persona_modifiers(big5: dict[str, int], event_name: str, effect: dict) -> dict:
    """按人格修正事件效果：内向社交耗电、神经质增压、开放性爱新异。"""
    out = dict(effect)
    extra = big5.get("外向性", 50) / 100
    neuro = big5.get("神经质", 50) / 100
    openn = big5.get("开放性", 50) / 100

    def num(k: str) -> bool:
        return isinstance(out.get(k), (int, float))

    if any(k in event_name for k in SOCIAL_EVENTS):
        if num("energy"):
            out["energy"] *= (1.0 + 1.2 * extra) if out["energy"] > 0 else (1.6 - 1.2 * extra)
        else:
            out["energy"] = 0.04 * extra - 0.05 * (1 - extra)
        if extra > 0.7 and num("valence"):
            out["valence"] = out.get("valence", 0.0) + 0.03
    if num("stress") and out["stress"] > 0:
        out["stress"] *= (1.0 + (neuro - 0.5))
    if any(k in event_name for k in STIM_EVENTS):
        if num("valence") and out["valence"] > 0:
            out["valence"] *= (0.7 + 0.6 * openn)
        if num("stress") and out["stress"] < 0:
            out["stress"] *= (0.7 + 0.6 * openn)
    return out


def reversion_rate_mult(big5: dict[str, int]) -> float:
    """神经质越高，压力均值回归越慢。"""
    return 1.0 - 0.4 * (big5.get("神经质", 50) / 100)
