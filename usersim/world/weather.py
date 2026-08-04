"""天气系统：马尔可夫转移 + 状态/事件效果调节。

天气状态每天转移一次，影响心情基线和户外事件效果。
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
TRANSITION_MATRIX = np.array([
    [0.60, 0.25, 0.10, 0.04, 0.01],  # 晴 → ...
    [0.30, 0.40, 0.20, 0.08, 0.02],  # 多云 → ...
    [0.15, 0.25, 0.35, 0.20, 0.05],  # 阴 → ...
    [0.10, 0.20, 0.30, 0.30, 0.10],  # 小雨 → ...
    [0.05, 0.15, 0.25, 0.35, 0.20],  # 暴雨 → ...
])

WEATHER_ORDER = [Weather.SUNNY, Weather.PARTLY_CLOUDY, Weather.CLOUDY, Weather.LIGHT_RAIN, Weather.HEAVY_RAIN]


def initial_weather(rng: np.random.Generator) -> Weather:
    """初始化天气状态（偏向晴天）"""
    weights = [0.5, 0.25, 0.15, 0.08, 0.02]
    idx = rng.choice(len(WEATHER_ORDER), p=weights)
    return WEATHER_ORDER[idx]


def transition_weather(current: Weather, rng: np.random.Generator) -> Weather:
    """根据马尔可夫转移矩阵转移天气状态"""
    current_idx = WEATHER_ORDER.index(current)
    probs = TRANSITION_MATRIX[current_idx]
    next_idx = rng.choice(len(WEATHER_ORDER), p=probs)
    return WEATHER_ORDER[next_idx]


def weather_effect_on_state(weather: Weather) -> dict[str, float]:
    """天气对状态的直接效果（每 slot 叠加）。

    效果非常微小，仅作为氛围调剂，不破坏控制论轨迹。
    """
    effects = {
        Weather.SUNNY: {"valence": 0.003},
        Weather.PARTLY_CLOUDY: {},
        Weather.CLOUDY: {},
        Weather.LIGHT_RAIN: {"valence": -0.002},
        Weather.HEAVY_RAIN: {"valence": -0.003},
    }
    return effects.get(weather, {})


def weather_event_modifier(weather: Weather, event_name: str, effect: dict) -> dict:
    """天气对事件效果的修正（户外活动受影响）"""
    # 户外活动关键词
    outdoor_keywords = ["公园", "爬山", "徒步", "骑行", "露营", "野餐", "海边", "登山", "户外", "散步", "跑步", "钓鱼"]

    is_outdoor = any(kw in event_name for kw in outdoor_keywords)

    if not is_outdoor:
        return effect

    # 根据天气调整户外事件效果
    modifiers = {
        Weather.SUNNY: 1.1,  # 晴天增强 10%
        Weather.PARTLY_CLOUDY: 1.0,  # 多云无影响
        Weather.CLOUDY: 0.9,  # 阴天打折 10%
        Weather.LIGHT_RAIN: 0.6,  # 小雨打折 40%
        Weather.HEAVY_RAIN: 0.3,  # 暴雨打折 70%
    }

    mult = modifiers.get(weather, 1.0)

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
