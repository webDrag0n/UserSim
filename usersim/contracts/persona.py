"""人格与喜好的共享词表 + 画像误差度量（契约的一部分）。

放在 contracts 的理由与 metrics.py 相同：**"什么叫一个人的人格与喜好"必须三方一致**——
world 用它生成角色并调节动力学，agents 用它表演与估计，evaluator 用它算画像精度。
若各包各自定义 facet 名，估计与真值就无法逐项比对（画像精度指标失去意义）。

本模块零依赖（仅标准库），不得 import 任何业务包。
对应文档：docs/05-contracts.md 第 1 节、docs/13-persona-model.md
"""

from __future__ import annotations

# ---------------------------------------------------------------
# 1. 大五人格：5 域 × 6 细分面（NEO-PI-R 分面体系）
# ---------------------------------------------------------------

BIG5_DOMAINS: list[str] = ["开放性", "尽责性", "外向性", "宜人性", "神经质"]

# 域 → 6 个细分面（顺序固定：facet key = f"{域}.{面}"）
BIG5_FACETS: dict[str, list[str]] = {
    "开放性": ["想象力", "审美", "情感丰富", "尝新", "思辨", "价值开放"],
    "尽责性": ["胜任感", "条理性", "尽职", "成就追求", "自律", "审慎"],
    "外向性": ["热情", "群居性", "果断", "活跃", "寻求刺激", "积极情绪"],
    "宜人性": ["信任", "直率", "利他", "顺从", "谦逊", "同理心"],
    "神经质": ["焦虑", "愤怒敌意", "抑郁", "自我意识", "冲动性", "脆弱"],
}

# 全部 30 个 facet key（顺序固定：域顺序 × 面顺序）
FACET_KEYS: list[str] = [f"{d}.{f}" for d in BIG5_DOMAINS for f in BIG5_FACETS[d]]

# facet 语义注释：供用户 Agent 表演与助手估计时对齐理解（prompt 素材）
FACET_HINTS: dict[str, str] = {
    "开放性.想象力": "爱做白日梦、内心世界丰富",
    "开放性.审美": "对美、艺术、音乐敏感",
    "开放性.情感丰富": "能清晰觉察并表达自己的情绪",
    "开放性.尝新": "愿意尝试没做过的事、去没去过的地方",
    "开放性.思辨": "喜欢琢磨抽象问题、爱思考",
    "开放性.价值开放": "对不同观念与生活方式持开放态度",
    "尽责性.胜任感": "觉得自己有能力把事情办成",
    "尽责性.条理性": "东西与计划都要整整齐齐",
    "尽责性.尽职": "答应的事一定做到、守规则",
    "尽责性.成就追求": "有明确目标并为之持续努力",
    "尽责性.自律": "能顶着不情愿把事做完、不拖延",
    "尽责性.审慎": "行动前先想清楚、不冲动决策",
    "外向性.热情": "对人亲近热络、容易与人建立亲密感",
    "外向性.群居性": "喜欢人多热闹的场合",
    "外向性.果断": "敢表达主张、愿意主导",
    "外向性.活跃": "节奏快、精力外放、闲不住",
    "外向性.寻求刺激": "需要强刺激与新鲜感才觉得带劲",
    "外向性.积极情绪": "容易高兴、常有兴奋与愉悦感",
    "宜人性.信任": "倾向相信别人是善意的",
    "宜人性.直率": "坦白、不拐弯、不算计",
    "宜人性.利他": "乐于帮别人、把他人需要放前面",
    "宜人性.顺从": "冲突时倾向让步而非对抗",
    "宜人性.谦逊": "不爱标榜自己",
    "宜人性.同理心": "容易被别人的处境触动",
    "神经质.焦虑": "容易担心、紧张、想到坏结果",
    "神经质.愤怒敌意": "容易被惹恼、憋火",
    "神经质.抑郁": "容易低落、失去兴致、自责",
    "神经质.自我意识": "在意别人怎么看自己、容易尴尬",
    "神经质.冲动性": "难抵挡即时诱惑（暴食/熬夜/乱花钱）",
    "神经质.脆弱": "压力下容易慌、扛不住就崩",
}


def facet_keys_of(domain: str) -> list[str]:
    """某个域的 6 个 facet key。"""
    return [f"{domain}.{f}" for f in BIG5_FACETS.get(domain, [])]


def domain_of(facet_key: str) -> str:
    """facet key → 所属域名。"""
    return facet_key.split(".", 1)[0]


def domain_score(facets: dict[str, int], domain: str, default: int = 50) -> int:
    """域分 = 该域 6 个 facet 的均值（facets 缺失时回退 default）。"""
    vals = [facets[k] for k in facet_keys_of(domain) if k in facets]
    return int(round(sum(vals) / len(vals))) if vals else int(default)


def domains_from_facets(facets: dict[str, int], default: int = 50) -> dict[str, int]:
    """30 facet → 5 域分（供动力学与旧接口使用）。"""
    return {d: domain_score(facets, d, default) for d in BIG5_DOMAINS}


def trait(big5: dict[str, int], facets: dict[str, int] | None, key: str, default: int = 50) -> int:
    """读取一个人格分：facet key 优先，缺失时回退到所属域分，再回退 default。

    动力学里所有人格调节都走这个函数——旧存档（只有 big5、没有 facets）
    因此仍能运行，且行为与升级前一致。
    """
    if facets and key in facets:
        return int(facets[key])
    dom = domain_of(key)
    if facets:
        vals = [facets[k] for k in facet_keys_of(dom) if k in facets]
        if vals:
            return int(round(sum(vals) / len(vals)))
    return int((big5 or {}).get(dom, default))


# ---------------------------------------------------------------
# 2. 喜好：类目词表（与 world/catalog 的 category 及归一化类目对齐）
# ---------------------------------------------------------------

# 偏好分 ∈ [-1, 1]：+1 极爱、0 中立、-1 讨厌
PREF_CATEGORIES: list[str] = [
    "饮食", "休息", "户外", "旅行", "运动", "居家",
    "社交", "文化", "音乐", "学习", "自然",
]

# 事件名/类目关键词 → 偏好类目（world 结算与 evaluator 归因共用）
PREF_KEYWORDS: dict[str, tuple[str, ...]] = {
    "饮食": ("吃", "餐", "美食", "火锅", "寿喜烧", "夜市", "小吃", "咖啡", "升级一餐"),
    "休息": ("休息", "补觉", "睡", "按摩", "SPA", "温泉", "懒觉", "休整"),
    "户外": ("出门走走", "散步", "步道", "徒步", "遛弯", "公园"),
    "旅行": ("旅行", "旅游", "一日", "海边", "小镇", "远方", "景点", "古迹", "乐园", "商圈"),
    "运动": ("运动", "健身", "跑步", "私教", "球"),
    "居家": ("宅家", "宅", "看电影", "打游戏", "做顿好的", "居家"),
    "社交": ("朋友小聚", "聚会", "应酬", "邀约", "聚"),
    "文化": ("看展", "美术馆", "博物馆", "文化", "话剧", "电影院"),
    "音乐": ("音乐", "livehouse", "黑胶", "爵士", "演出", "唱"),
    "学习": ("学习", "充电", "刷题", "网课", "备考", "看书"),
    "自然": ("自然放空", "雪山", "湖泊", "山", "海边发呆", "露营"),
}

# catalog 的 category 字段 → 偏好类目（精确映射优先于关键词）
CATEGORY_TO_PREF: dict[str, str] = {
    "饮食": "饮食", "休息": "休息", "户外": "户外",
    "旅行": "旅行", "运动": "运动", "居家": "居家",
}

# 计划风格枚举（冻结特质：影响用户对"临时安排"的接受度）
PLANNING_STYLES: list[str] = ["提前规划", "随遇而安", "看心情"]


def pref_category(event_name: str, category: str | None = None) -> str | None:
    """事件名（+可选 catalog category）→ 偏好类目；无法归类时 None。"""
    if category and category in CATEGORY_TO_PREF:
        return CATEGORY_TO_PREF[category]
    name = event_name or ""
    for pref, keys in PREF_KEYWORDS.items():
        if any(k in name for k in keys):
            return pref
    return None


# ---------------------------------------------------------------
# 3. 画像误差度量（evaluator 与前端共用的定义）
# ---------------------------------------------------------------


def facet_error(true_facets: dict[str, int], hat_facets: dict[str, int]) -> float | None:
    """人格估计误差：逐 facet 平均绝对误差，归一到 [0,1]（分值域 0-100）。

    只对助手**给出了估计**的 facet 计误差；一个都没给则返回 None（记为"未估计"，
    由上层单独统计覆盖率，不能当成 0 误差——否则不作为的助手看起来最准）。
    """
    pairs = [(true_facets[k], hat_facets[k]) for k in FACET_KEYS
             if k in true_facets and k in hat_facets]
    if not pairs:
        return None
    return sum(abs(a - b) for a, b in pairs) / len(pairs) / 100.0


def facet_coverage(hat_facets: dict[str, int]) -> float:
    """估计覆盖率：助手给出了 30 个 facet 中的几成。"""
    return sum(1 for k in FACET_KEYS if k in hat_facets) / len(FACET_KEYS)


def prefs_error(true_cats: dict[str, float], hat_cats: dict[str, float]) -> float | None:
    """类目偏好估计误差：逐类目 MAE 归一到 [0,1]（分值域 [-1,1]，故除以 2）。"""
    pairs = [(float(true_cats[k]), float(hat_cats[k])) for k in PREF_CATEGORIES
             if k in true_cats and k in hat_cats]
    if not pairs:
        return None
    return sum(abs(a - b) for a, b in pairs) / len(pairs) / 2.0


def _norm_tokens(items: list[str]) -> set[str]:
    return {str(s).strip() for s in items if str(s).strip()}


def tag_hit_rate(true_tags: list[str], hat_tags: list[str]) -> float | None:
    """loves/hates 命中率：F1（既惩罚漏报也惩罚瞎猜）。

    命中判定为**双向包含**——真值"寿喜烧"与估计"喜欢吃寿喜烧"算命中，
    因为助手是从自然对话里学到的，不该要求它复现角色卡的原文措辞。
    """
    truth, hat = _norm_tokens(true_tags), _norm_tokens(hat_tags)
    if not truth and not hat:
        return None
    matched_hat = {h for h in hat if any(h in t or t in h for t in truth)}
    matched_truth = {t for t in truth if any(h in t or t in h for h in hat)}
    if not hat or not truth:
        return 0.0
    precision = len(matched_hat) / len(hat)
    recall = len(matched_truth) / len(truth)
    if precision + recall <= 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)
