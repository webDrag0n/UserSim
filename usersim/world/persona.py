"""角色卡生成器：seed → 大五 / 喜好 / 作息 / x0。

人格与喜好为冻结维度：不参与动力学，参与画像精度评估。
"""

from __future__ import annotations

import numpy as np

from usersim.contracts import Persona, StateVec
from usersim.world.catalog import income_for_archetype

NAMES = ["林小满", "陈屿", "苏黎", "何所思", "周野", "方糖", "沈一舟", "姜莱"]
ARCHETYPES = ["高压互联网从业者", "自由插画师", "备考研究生", "初创公司创始人", "倒班护士", "远程程序员"]
LIKE_POOL = [
    "喜欢深夜独处、爵士乐和寿喜烧；讨厌被临时邀约打断计划",
    "热衷徒步和咖啡店探店；喜欢提前一天规划，讨厌不确定性",
    "喜欢打游戏、吃辣；社交会快速耗电，需要独处回血",
    "喜欢早起跑步、清单化管理一切；讨厌拖延和油腻食物",
    "喜欢 livehouse 和即兴旅行；计划赶不上变化也无所谓",
    "喜欢做饭、看纪录片；对睡眠质量极度敏感",
    "喜欢逛美术馆、收集黑胶；周末必须有一天完全属于自己",
    "喜欢篮球和烧烤；心情差的时候需要朋友陪",
]
BIG5_LABELS = ["开放性", "尽责性", "外向性", "宜人性", "神经质"]
ROUTINES = ["规律作息型（23:00 睡 / 7:00 起）", "夜猫子型（1:00 睡 / 8:30 起）"]


def generate_persona(gen: np.random.Generator, initial: dict[str, float]) -> Persona:
    archetype = ARCHETYPES[int(gen.integers(len(ARCHETYPES)))]
    x0 = StateVec(
        valence=float(np.clip(initial["valence"] + gen.normal(0, 0.05), 0, 1)),
        energy=float(np.clip(initial["energy"] + gen.normal(0, 0.05), 0, 1)),
        satiety=float(np.clip(initial["satiety"] + gen.normal(0, 0.05), 0, 1)),
        stress=float(np.clip(initial["stress"] + gen.normal(0, 0.05), 0, 1)),
    )
    return Persona(
        name=NAMES[int(gen.integers(len(NAMES)))],
        archetype=archetype,
        big5={label: int(gen.integers(15, 95)) for label in BIG5_LABELS},
        likes=LIKE_POOL[int(gen.integers(len(LIKE_POOL)))],
        routine=ROUTINES[int(gen.integers(len(ROUTINES)))],
        x0=x0,
        income_per_slot=income_for_archetype(archetype),
    )
