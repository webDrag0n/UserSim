"""角色卡生成器：seed → 大五 30 facet / 结构化喜好 / 作息 / x0。

人格与喜好为**冻结维度**：生成后不可改写（Persona 的 frozen 字段强制），
不参与状态写入，但参与动力学调节（world/anthro.py）与画像精度评估。

生成模型（两层）：
1. 域基线：每个域先抽一个基线分（人的五个大方向）；
2. facet 抖动：同域内 6 个 facet 在基线附近抖动 ±18——真人不会"尽责性全项 70"，
   而是"条理性很高但自律一般"。这个域内落差正是助手需要多轮对话才能摸清的东西。
"""

from __future__ import annotations

import numpy as np

from usersim.contracts import Persona, Preferences, StateVec
from usersim.contracts.persona import (
    BIG5_DOMAINS,
    FACET_KEYS,
    PLANNING_STYLES,
    PREF_CATEGORIES,
    domains_from_facets,
    facet_keys_of,
)
from usersim.world.catalog import income_for_archetype

NAMES = ["林小满", "陈屿", "苏黎", "何所思", "周野", "方糖", "沈一舟", "姜莱"]
ARCHETYPES = ["高压互联网从业者", "自由插画师", "备考研究生", "初创公司创始人", "倒班护士", "远程程序员"]
BIG5_LABELS = BIG5_DOMAINS  # 兼容旧引用
ROUTINES = ["规律作息型（23:00 睡 / 7:00 起）", "夜猫子型（1:00 睡 / 8:30 起）"]

# 喜好画像池：自陈述文本 + 与之一致的结构化标签。
# 两者必须自洽——文本是用户 Agent 的表演素材，结构化标签是评估助手估计的真值；
# 若二者矛盾，助手无论怎么听都会被判错。
LIKE_PROFILES: list[dict] = [
    {
        "likes": "喜欢深夜独处、爵士乐和寿喜烧；讨厌被临时邀约打断计划",
        "categories": {"音乐": 0.9, "饮食": 0.8, "居家": 0.7, "休息": 0.6,
                       "社交": -0.6, "运动": -0.3, "文化": 0.4},
        "loves": ["深夜独处", "爵士乐", "寿喜烧"],
        "hates": ["临时邀约", "计划被打断"],
        "interruption_tolerance": 0.15,
        "planning_style": "提前规划",
        "social_recharge": "独处",
    },
    {
        "likes": "热衷徒步和咖啡店探店；喜欢提前一天规划，讨厌不确定性",
        "categories": {"户外": 0.9, "自然": 0.8, "饮食": 0.6, "旅行": 0.5,
                       "运动": 0.4, "居家": -0.3, "社交": 0.1},
        "loves": ["徒步", "咖啡店探店"],
        "hates": ["不确定性", "临时变更"],
        "interruption_tolerance": 0.2,
        "planning_style": "提前规划",
        "social_recharge": "独处",
    },
    {
        "likes": "喜欢打游戏、吃辣；社交会快速耗电，需要独处回血",
        "categories": {"居家": 0.9, "饮食": 0.8, "休息": 0.5,
                       "社交": -0.7, "户外": -0.2, "运动": -0.4, "文化": 0.2},
        "loves": ["打游戏", "吃辣"],
        "hates": ["人多的场合", "长时间社交"],
        "interruption_tolerance": 0.3,
        "planning_style": "看心情",
        "social_recharge": "独处",
    },
    {
        "likes": "喜欢早起跑步、清单化管理一切；讨厌拖延和油腻食物",
        "categories": {"运动": 0.9, "户外": 0.7, "学习": 0.6, "自然": 0.4,
                       "饮食": 0.1, "居家": -0.4, "社交": 0.0},
        "loves": ["早起跑步", "清单管理"],
        "hates": ["拖延", "油腻食物"],
        "interruption_tolerance": 0.25,
        "planning_style": "提前规划",
        "social_recharge": "独处",
    },
    {
        "likes": "喜欢 livehouse 和即兴旅行；计划赶不上变化也无所谓",
        "categories": {"音乐": 0.9, "旅行": 0.9, "社交": 0.6, "文化": 0.6,
                       "户外": 0.4, "居家": -0.4, "学习": -0.2},
        "loves": ["livehouse", "即兴旅行"],
        "hates": ["一成不变", "过度计划"],
        "interruption_tolerance": 0.85,
        "planning_style": "随遇而安",
        "social_recharge": "找人",
    },
    {
        "likes": "喜欢做饭、看纪录片；对睡眠质量极度敏感",
        "categories": {"居家": 0.9, "饮食": 0.8, "休息": 0.9, "文化": 0.5,
                       "社交": -0.3, "旅行": -0.2, "运动": 0.1},
        "loves": ["做饭", "看纪录片", "好好睡一觉"],
        "hates": ["熬夜", "被吵醒"],
        "interruption_tolerance": 0.25,
        "planning_style": "提前规划",
        "social_recharge": "独处",
    },
    {
        "likes": "喜欢逛美术馆、收集黑胶；周末必须有一天完全属于自己",
        "categories": {"文化": 0.9, "音乐": 0.8, "居家": 0.5, "休息": 0.6,
                       "社交": -0.4, "运动": -0.2, "旅行": 0.3},
        "loves": ["美术馆", "黑胶", "独处的一天"],
        "hates": ["周末被占满", "应酬"],
        "interruption_tolerance": 0.2,
        "planning_style": "提前规划",
        "social_recharge": "独处",
    },
    {
        "likes": "喜欢篮球和烧烤；心情差的时候需要朋友陪",
        "categories": {"运动": 0.9, "饮食": 0.8, "社交": 0.9, "户外": 0.6,
                       "居家": -0.2, "文化": 0.0, "学习": -0.3},
        "loves": ["篮球", "烧烤", "和朋友吹牛"],
        "hates": ["一个人闷着", "冷场"],
        "interruption_tolerance": 0.7,
        "planning_style": "随遇而安",
        "social_recharge": "找人",
    },
]
LIKE_POOL = [p["likes"] for p in LIKE_PROFILES]  # 兼容旧引用

# 职业 → 域基线偏移：职业不改人格本质，但人群分布确有差异（更真实的角色池）
ARCHETYPE_BIAS: dict[str, dict[str, int]] = {
    "高压互联网从业者": {"尽责性": 8, "神经质": 6},
    "自由插画师": {"开放性": 12, "尽责性": -6},
    "备考研究生": {"尽责性": 6, "神经质": 8, "外向性": -6},
    "初创公司创始人": {"外向性": 10, "尽责性": 8, "神经质": 4},
    "倒班护士": {"宜人性": 10, "神经质": 4},
    "远程程序员": {"外向性": -8, "开放性": 4},
}


def _generate_facets(gen: np.random.Generator, archetype: str) -> dict[str, int]:
    """两层生成：域基线 + 域内 facet 抖动（造出域内落差）。"""
    bias = ARCHETYPE_BIAS.get(archetype, {})
    facets: dict[str, int] = {}
    for domain in BIG5_DOMAINS:
        base = float(gen.integers(20, 85)) + bias.get(domain, 0)
        for key in facet_keys_of(domain):
            v = base + gen.normal(0, 12)
            facets[key] = int(np.clip(round(v), 5, 95))
    return facets


def _generate_prefs(gen: np.random.Generator, profile: dict) -> Preferences:
    """喜好 = 画像模板 + 未指定类目的轻度随机（保持模板自洽，补全全类目）。"""
    cats: dict[str, float] = {}
    for c in PREF_CATEGORIES:
        if c in profile["categories"]:
            base = float(profile["categories"][c])
            cats[c] = float(np.clip(base + gen.normal(0, 0.06), -1.0, 1.0))
        else:
            cats[c] = float(np.clip(gen.normal(0, 0.28), -1.0, 1.0))
    style = profile.get("planning_style") or PLANNING_STYLES[int(gen.integers(len(PLANNING_STYLES)))]
    return Preferences(
        categories={k: round(v, 2) for k, v in cats.items()},
        loves=list(profile["loves"]),
        hates=list(profile["hates"]),
        interruption_tolerance=float(np.clip(
            profile["interruption_tolerance"] + gen.normal(0, 0.05), 0.0, 1.0)),
        planning_style=style,
        social_recharge=profile.get("social_recharge", "独处"),
    )


def _build_event_library(prefs, facets: dict, archetype: str) -> list[dict]:
    """按人格偏好构建个性化事件库（从地点支持表 flatten 筛选 + 自定义）。"""
    from usersim.world.catalog import all_variants  # 延迟 import
    library = []

    for action, variant in all_variants():
        if action.get("id") in ("MEAL", "SLEEP"):
            continue  # 日常升级档不进用户事件库（与旧版一致）
        action_name = action["action"]
        # 社交内向者降低社交类事件权重（不是完全排除）
        gregarious = facets.get("外向性.群居性", 50)
        if any(k in action_name for k in ("朋友小聚", "应酬", "聚会")) and gregarious < 35:
            continue  # 内向者的主动事件库里没有饭局

        library.append({
            "name": action_name,
            "location": variant.get("location", ""),
            "cost": float(variant.get("cost", 0)),
            "effect": variant.get("effect", {}),
            "span": int(variant.get("span", 1)),
            "vid": variant.get("vid", ""),
            "tags": [action_name],
        })

    return library


def generate_persona(gen: np.random.Generator, initial: dict[str, float],
                     archetype: str | None = None) -> Persona:
    """seed 流 → 完整角色卡。

    archetype 给定时用它（前端可指定职业），否则从池中抽——职业会轻微偏移
    人格域基线，因此必须在抽 facet 之前确定。
    """
    arch = archetype or ARCHETYPES[int(gen.integers(len(ARCHETYPES)))]
    x0 = StateVec(
        valence=float(np.clip(initial["valence"] + gen.normal(0, 0.05), 0, 1)),
        energy=float(np.clip(initial["energy"] + gen.normal(0, 0.05), 0, 1)),
        satiety=float(np.clip(initial["satiety"] + gen.normal(0, 0.05), 0, 1)),
        stress=float(np.clip(initial["stress"] + gen.normal(0, 0.05), 0, 1)),
    )
    facets = _generate_facets(gen, arch)
    profile = LIKE_PROFILES[int(gen.integers(len(LIKE_PROFILES)))]
    prefs = _generate_prefs(gen, profile)
    event_library = _build_event_library(prefs, facets, arch)
    return Persona(
        name=NAMES[int(gen.integers(len(NAMES)))],
        archetype=arch,
        big5=domains_from_facets(facets),
        facets=facets,
        likes=profile["likes"],
        prefs=prefs,
        routine=ROUTINES[int(gen.integers(len(ROUTINES)))],
        x0=x0,
        income_per_slot=income_for_archetype(arch),
        event_library=event_library,
    )
