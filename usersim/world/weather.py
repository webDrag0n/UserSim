"""天气系统：马尔可夫转移 + 状态/事件效果调节。

天气状态每天转移一次，影响心情基线和户外事件效果。
参数默认值在此定义；config/balance/weather.json 可覆盖。
"""

from __future__ import annotations

from enum import Enum

import numpy as np


class Weather(str, Enum):
    """天气状态枚举"""
    SUNNY = "晴"
    PARTLY_CLOUDY = "多云"
    CLOUDY = "阴"
    LIGHT_RAIN = "小雨"
    HEAVY_RAIN = "暴雨"


# 天气转移概率矩阵（行：当前，列：下一天）
# 顺序：晴 多云 阴 小雨 暴雨
DEFAULT_TRANSITION_MATRIX = np.array([
    [0.60, 0.25, 0.10, 0.04, 0.01],  # 晴 → ...
    [0.30, 0.40, 0.20, 0.08, 0.02],  # 多云 → ...
    [0.15, 0.25, 0.35, 0.20, 0.05],  # 阴 → ...
    [0.10, 0.20, 0.30, 0.30, 0.10],  # 小雨 → ...
    [0.05, 0.15, 0.25, 0.35, 0.20],  # 暴雨 → ...
])

DEFAULT_INITIAL_WEIGHTS = [0.5, 0.25, 0.15, 0.08, 0.02]

WEATHER_ORDER: list[Weather] = [Weather.SUNNY, Weather.PARTLY_CLOUDY, Weather.CLOUDY, Weather.LIGHT_RAIN, Weather.HEAVY_RAIN]

DEFAULT_STATE_EFFECTS: dict[str, dict[str, float]] = {
    "晴": {"valence": 0.003},
    "多云": {},
    "阴": {},
    "小雨": {"valence": -0.002},
    "暴雨": {"valence": -0.003},
}

DEFAULT_OUTDOOR_MODIFIERS: dict[str, float] = {
    "晴": 1.1,
    "多云": 1.0,
    "阴": 0.9,
    "小雨": 0.6,
    "暴雨": 0.3,
}

OUTDOOR_KEYWORDS = ["公园", "爬山", "徒步", "骑行", "露营", "野餐", "海边", "登山", "户外", "散步", "跑步", "钓鱼"]


def _get_weather_config():
    """读取天气配置覆盖（来自 balance.py 缓存）。"""
    from usersim.world.balance import load_overrides
    return (load_overrides() or {}).get("weather", {})


def get_transition_matrix() -> np.ndarray:
    cfg = _get_weather_config()
    raw = cfg.get("transition_matrix")
    if raw and len(raw) == len(WEATHER_ORDER):
        return np.array(raw, dtype=float)
    return DEFAULT_TRANSITION_MATRIX


def get_initial_weights() -> list[float]:
    cfg = _get_weather_config()
    raw = cfg.get("initial_weights")
    if raw and len(raw) == len(WEATHER_ORDER):
        return [float(w) for w in raw]
    return list(DEFAULT_INITIAL_WEIGHTS)


def get_state_effects() -> dict[str, dict[str, float]]:
    cfg = _get_weather_config()
    raw = cfg.get("state_effects", {})
    if raw:
        return {k: dict(v) for k, v in raw.items()}
    return DEFAULT_STATE_EFFECTS


def get_outdoor_modifiers() -> dict[str, float]:
    cfg = _get_weather_config()
    raw = cfg.get("outdoor_modifiers", {})
    if raw:
        return {k: float(v) for k, v in raw.items()}
    return dict(DEFAULT_OUTDOOR_MODIFIERS)


def initial_weather(rng: np.random.Generator) -> Weather:
    """初始化天气状态（偏向晴天）"""
    weights = get_initial_weights()
    idx = rng.choice(len(WEATHER_ORDER), p=weights)
    return WEATHER_ORDER[idx]


def transition_weather(current: Weather, rng: np.random.Generator) -> Weather:
    """根据马尔可夫转移矩阵转移天气状态"""
    current_idx = WEATHER_ORDER.index(current)
    probs = get_transition_matrix()[current_idx]
    next_idx = rng.choice(len(WEATHER_ORDER), p=probs)
    return WEATHER_ORDER[next_idx]


def weather_effect_on_state(weather: Weather) -> dict[str, float]:
    """天气对状态的直接效果（每 slot 叠加）。

    效果非常微小，仅作为氛围调剂，不破坏控制论轨迹。
    """
    effects = get_state_effects()
    return effects.get(weather.value, {})


def weather_event_modifier(weather: Weather, event_name: str, effect: dict) -> dict:
    """天气对事件效果的修正（户外活动受影响）"""
    is_outdoor = any(kw in event_name for kw in OUTDOOR_KEYWORDS)

    if not is_outdoor:
        return effect

    modifiers = get_outdoor_modifiers()
    mult = modifiers.get(weather.value, 1.0)

    # 应用修正到所有效果值
    modified = {}
    for k, v in effect.items():
        if isinstance(v, dict) and "pull" in v:
            # pull 效果：只修正速率
            modified[k] = {"pull": [v["pull"][0], v["pull"][1] * mult]}
        else:
            # 数值效果：直接乘以系数
            modified[k] = v * mult

    return modified
