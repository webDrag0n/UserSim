"""表达直白度调制：由人格 facet 确定性推导用户"点名想做的事 vs 只说感受"的表达档位。

纯函数、0 LLM、可单测。只依赖 contracts 词表（agents 依赖规则：只能 import contracts / llm）。
"""

from __future__ import annotations

# 档位文案：注入 sys prompt 的【你的表达习惯】，指导 LLM 选择 explicit / vague 表达模式
TIER_GUIDANCE: dict[int, str] = {
    0: "你习惯只说自己的感受，想要什么让别人猜——就算心里有具体想做的事，也只会绕着说感受。",
    1: "你有时直接说想做什么，有时只描述感受，看事情也看心情。",
    2: "你想做什么通常会直接说出来，不喜欢拐弯抹角。",
}

# 参与计算的 facet（缺失时按中性 50 计）
_FACETS_POS = ("外向性.果断", "宜人性.直率", "开放性.情感丰富")
_FACET_NEG = "神经质.自我意识"

# 分档阈值（score = 果断 + 直率 + 情感丰富 - 自我意识，理论区间 [-100, 300]，全中性 = 100）
_TIER_MID = 100    # < 100 → 含蓄
_TIER_HIGH = 180   # >= 180 → 直白；[100, 180) → 中等


def explicitness_score(facets: dict[str, int] | None) -> int:
    """表达直白度原始分：果断 + 直率 + 情感丰富 - 自我意识（各项 0-100，缺失按 50）。"""
    facets = facets or {}
    pos = sum(int(facets.get(k, 50)) for k in _FACETS_POS)
    return pos - int(facets.get(_FACET_NEG, 50))


def explicitness_tier(facets: dict[str, int] | None) -> tuple[int, str]:
    """由 facets 计算表达直白度档位（0=含蓄 / 1=中等 / 2=直白）及对应的自然语言指导文案。"""
    score = explicitness_score(facets)
    if score < _TIER_MID:
        tier = 0
    elif score < _TIER_HIGH:
        tier = 1
    else:
        tier = 2
    return tier, TIER_GUIDANCE[tier]
