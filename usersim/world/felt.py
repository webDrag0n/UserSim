"""状态语义化翻译器：数值 x → 自然语言感受（felt_state）。

规则组件（分档词典 + 同义变体），是 user_agent 唯一能看到状态的方式。
O4 优化：每档同义措辞由世界噪声流选取——从规则侧消灭台词复读。
R4 扩容：每档 5 个变体（原 3 个实测仍会被用户 LLM 学成固定词表）。
"""

from __future__ import annotations

import numpy as np

from usersim.contracts import StateVec


def _tier(v: float, edges: tuple[float, ...]) -> int:
    for i, e in enumerate(edges):
        if v < e:
            return i
    return len(edges)


_STRESS = [
    ["没什么压力", "压力不大", "挺轻松的", "心里没什么事压着", "一身轻"],
    ["压力还好", "压力一般般", "有点压力但还行", "不算紧张", "还扛得住"],
    ["压力有点大", "感觉有些紧绷", "压力上来了", "心里有点悬着", "绷着一根弦"],
    ["压力很大", "感觉快扛不住了", "压力大得离谱", "脑子里全是事", "被事情追着跑"],
    ["快崩溃了", "真的要炸了", "完全撑不住了", "到极限了", "整个人都快散架了"],
]
_ENERGY = [
    ["快没电了", "累得不行", "整个人很虚", "眼皮直打架", "动都不想动"],
    ["有点累", "有点乏", "稍微有点疲惫", "有点提不起劲", "身子有点沉"],
    ["精力还行", "精神还可以", "状态凑合", "不算累", "还有点力气"],
    ["精力充沛", "元气满满", "精神头很足", "浑身是劲", "状态在线"],
]
_SATIETY = [
    ["饿得前胸贴后背", "肚子饿扁了", "饿得慌", "肚子咕咕叫", "饿惨了"],
    ["有点饿", "肚子有点空", "该吃点东西了", "嘴巴有点馋", "想吃点什么"],
    ["不饿", "肚子不饿", "还不觉得饿", "不馋", "暂时不想吃东西"],
    ["吃得很饱", "吃撑了", "肚子圆滚滚", "撑得慌", "吃得心满意足"],
]
_VALENCE = [
    ["心情很差", "情绪很低落", "心里很堵", "丧到谷底", "看什么都不顺眼"],
    ["有点丧", "有点郁闷", "情绪一般般", "提不起兴致", "心里灰灰的"],
    ["心情还行", "情绪还可以", "心态还算平和", "不好不坏", "心里挺平静"],
    ["心情不错", "心情挺好", "美滋滋", "心里亮堂", "莫名开心"],
]


def felt_state(x: StateVec, rng: np.random.Generator | None = None) -> str:
    """语义化感受摘要。rng 给定时从同义变体中采样（世界噪声流，保持确定）。"""
    def pick(options: list[str]) -> str:
        return options[int(rng.integers(len(options)))] if rng is not None else options[0]

    s = pick(_STRESS[_tier(x.stress, (0.2, 0.4, 0.6, 0.8))])
    e = pick(_ENERGY[_tier(x.energy, (0.3, 0.5, 0.7))])
    h = pick(_SATIETY[_tier(x.satiety, (0.3, 0.5, 0.7))])
    v = pick(_VALENCE[_tier(x.valence, (0.4, 0.55, 0.7))])
    return f"{v}，{e}，{h}，{s}"
