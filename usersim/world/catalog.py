"""数值配表（单一数据源）：基础效果 + 档位加权模型。

核心数值哲学（对标游戏配表）：
- 每个事件有 base_effect：任何档位都有的基础数值（如吃饭都能吃饱）；
- 每个档位有 weight：档位预算在各维度上的"加权分配"——
  低档餐厅虽然能吃饱但不会很开心（weight 几乎不给心情），
  高档餐厅把预算加权到心情与减压上；
- 合计效果 = base + weight，结算时按 span 摊销（pull 类除外）。
- 进餐与睡眠也是事件（日常档位进模板日程，可被助手/用户升级）；
- 收入按职业分档（PROFESSIONS）。
生成 Excel 配表：python scripts/export_balance_sheet.py
"""

from __future__ import annotations

# ---------------------------------------------------------------
# 经济参数
# ---------------------------------------------------------------

ECONOMY = {
    "initial_money": 1000,
    "work_income_per_slot": 200,   # 缺省收入（职业表未命中时兜底）
    "overtime_income": 150,
    "debt_stress_per_slot": 0.02,
    "note": "收入按职业分档（见 PROFESSIONS）；日常餐食为必需开销，睡眠不足可付费升级",
}

# ---------------------------------------------------------------
# 职业收入表：archetype → 每工作时段收入
# ---------------------------------------------------------------

PROFESSIONS: list[dict] = [
    {"archetype": "高压互联网从业者", "income_per_slot": 260, "note": "高薪高压，买得起但没时间"},
    {"archetype": "自由插画师", "income_per_slot": 130, "note": "收入不稳定，需量入为出"},
    {"archetype": "备考研究生", "income_per_slot": 80, "note": "只有兼职收入，免费恢复是主力"},
    {"archetype": "初创公司创始人", "income_per_slot": 320, "note": "收入最高，扰动也最猛"},
    {"archetype": "倒班护士", "income_per_slot": 190, "note": "收入中等，作息特殊"},
    {"archetype": "远程程序员", "income_per_slot": 230, "note": "中高收入，通勤零成本"},
]

# ---------------------------------------------------------------
# 进餐事件（日常档进模板日程；pull = 拉向准稳态，不摊销）
# ---------------------------------------------------------------

MEAL_TIERS: list[dict] = [
    {"vid": "M0", "name": "随便对付一口", "tier": "应付", "cost": 0,
     "effect": {"satiety": {"pull": [0.55, 0.60]}},
     "design_intent": "能吃饱但不开心：饱腹只拉到 0.55，毫无心情加成"},
    {"vid": "M1", "name": "日常家常", "tier": "日常", "cost": 10,
     "effect": {"satiety": {"pull": [0.70, 0.75]}, "valence": 0.01},
     "design_intent": "模板默认档：¥10 一顿，饱腹拉到 0.70"},
    {"vid": "M2", "name": "品质外卖", "tier": "品质", "cost": 25,
     "effect": {"satiety": {"pull": [0.78, 0.75]}, "valence": 0.03},
     "design_intent": "多花点钱，饱腹略高且有点开心"},
]

SLEEP_TIERS: list[dict] = [
    {"vid": "S0", "name": "熬夜后浅睡", "tier": "劣质", "cost": 0,
     "effect": {"energy": {"pull": [0.55, 0.50]}},
     "design_intent": "惩罚档：精力只能回到 0.55（扰动/报复性熬夜的结果）"},
    {"vid": "S1", "name": "正常睡眠", "tier": "日常", "cost": 0,
     "effect": {"energy": {"pull": [0.80, 0.50]}, "stress": -0.05},
     "design_intent": "模板默认档（O1：精力上限 0.80，睡眠成为真实减压槽）"},
    {"vid": "S2", "name": "高质量睡眠（助眠仪式）", "tier": "品质", "cost": 50,
     "effect": {"energy": {"pull": [0.88, 0.60]}, "stress": -0.04},
     "design_intent": "付费升级：精力上限更高、入睡更快、额外降压"},
]

# ---------------------------------------------------------------
# 恢复事件配表：base_effect + 档位 weight
# ---------------------------------------------------------------

RECOVERY_ACTIONS: list[dict] = [
    {
        "id": "A1", "action": "吃好吃的", "category": "饮食",
        "base_effect": {"satiety": 0.25},
        "design_intent": "都能吃饱；档位差异主要体现在心情与减压——低档吃饱不开心",
        "variants": [
            {"vid": "A1-1", "location": "楼下快餐", "tier": "平价", "cost": 30, "span": 1,
             "weight": {"valence": 0.02, "stress": -0.02}},
            {"vid": "A1-2", "location": "商场餐厅", "tier": "中档", "cost": 120, "span": 1,
             "weight": {"valence": 0.10, "stress": -0.06}},
            {"vid": "A1-3", "location": "收藏多年的小店", "tier": "高档", "cost": 200, "span": 1,
             "weight": {"valence": 0.20, "stress": -0.10}},
        ],
    },
    {
        "id": "A2", "action": "好好休息", "category": "休息",
        "base_effect": {"energy": 0.15},
        "design_intent": "躺着总能歇点；付费档位把预算大幅加权到减压",
        "variants": [
            {"vid": "A2-1", "location": "家里补觉", "tier": "平价", "cost": 0, "span": 1,
             "weight": {"energy": 0.05, "stress": -0.05}},
            {"vid": "A2-2", "location": "按摩 SPA", "tier": "中档", "cost": 150, "span": 1,
             "weight": {"stress": -0.14, "valence": 0.06}},
            {"vid": "A2-3", "location": "周边温泉酒店", "tier": "高档", "cost": 400, "span": 2,
             "weight": {"energy": 0.10, "stress": -0.20, "valence": 0.10}},
        ],
    },
    {
        "id": "A3", "action": "出门走走", "category": "户外",
        "base_effect": {"stress": -0.08},
        "design_intent": "出门就解压（基础档免费兜底）；档位加权到心情",
        "variants": [
            {"vid": "A3-1", "location": "楼下公园", "tier": "平价", "cost": 0, "span": 1,
             "weight": {"valence": 0.03}},
            {"vid": "A3-2", "location": "江边步道", "tier": "平价", "cost": 0, "span": 1,
             "weight": {"valence": 0.06, "energy": 0.02}},
            {"vid": "A3-3", "location": "近郊徒步", "tier": "中档", "cost": 80, "span": 2,
             "weight": {"valence": 0.10, "stress": -0.08, "energy": -0.06}},
        ],
    },
    {
        "id": "A4", "action": "短途旅行", "category": "旅行",
        "base_effect": {"valence": 0.12, "stress": -0.10},
        "design_intent": "旅行都有基础回血；时长与地点共同决定加权幅度，价格陡增",
        "variants": [
            {"vid": "A4-1", "location": "邻市一日", "tier": "平价", "cost": 300, "span": 2,
             "weight": {}},
            {"vid": "A4-2", "location": "海边小镇", "tier": "中档", "cost": 600, "span": 3,
             "weight": {"valence": 0.08, "stress": -0.08, "energy": 0.05}},
            {"vid": "A4-3", "location": "远方城市", "tier": "高档", "cost": 1200, "span": 4,
             "weight": {"valence": 0.15, "stress": -0.12, "energy": 0.08}},
        ],
    },
    {
        "id": "A5", "action": "运动健身", "category": "运动",
        "base_effect": {"stress": -0.08, "energy": -0.03},
        "design_intent": "运动都累但都降压（以精力换降压）；档位提升降压效率",
        "variants": [
            {"vid": "A5-1", "location": "小区跑步", "tier": "平价", "cost": 0, "span": 1,
             "weight": {"valence": 0.03}},
            {"vid": "A5-2", "location": "健身房", "tier": "中档", "cost": 50, "span": 1,
             "weight": {"stress": -0.05, "valence": 0.05}},
            {"vid": "A5-3", "location": "私教课", "tier": "高档", "cost": 200, "span": 1,
             "weight": {"stress": -0.08, "valence": 0.08, "energy": -0.02}},
        ],
    },
    {
        "id": "A6", "action": "宅家回血", "category": "居家",
        "base_effect": {"valence": 0.06},
        "design_intent": "宅都有点小开心；做顿好的把加权分到饱腹",
        "variants": [
            {"vid": "A6-1", "location": "看电影打游戏", "tier": "平价", "cost": 0, "span": 1,
             "weight": {"stress": -0.06, "satiety": -0.05}},
            {"vid": "A6-2", "location": "做顿好的", "tier": "平价", "cost": 40, "span": 1,
             "weight": {"satiety": 0.25, "stress": -0.05}},
        ],
    },
]

# ---------------------------------------------------------------
# 扰动事件配表
# ---------------------------------------------------------------

DISTURBANCES: list[dict] = [
    {"id": "D1", "name": "临时加班", "location": "公司", "cost": 0, "income": 150,
     "effect": {"energy": -0.16, "stress": 0.20, "valence": -0.08},
     "design_intent": "最常见强扰动：钱换命（有收入但状态大损）"},
    {"id": "D2", "name": "应酬饭局", "location": "餐厅", "cost": 100, "income": 0,
     "effect": {"energy": -0.12, "stress": 0.10, "satiety": 0.15},
     "design_intent": "花钱还受累的中等扰动（但确实吃饱了）"},
    {"id": "D3", "name": "暴雨行程受阻", "location": "路上", "cost": 0, "income": 0,
     "effect": {"valence": -0.12, "stress": 0.09},
     "design_intent": "轻扰动，主要打乱心情"},
    {"id": "D4", "name": "项目截止压缩", "location": "公司", "cost": 0, "income": 0,
     "effect": {"stress": 0.24, "energy": -0.10, "valence": -0.06},
     "design_intent": "最强压力扰动"},
    {"id": "D5", "name": "朋友临时邀约", "location": "外面", "cost": 80, "income": 0,
     "effect": {"valence": 0.10, "energy": -0.08, "satiety": 0.10},
     "design_intent": "难得的正面扰动，但有金钱与精力代价"},
]

# ---------------------------------------------------------------
# 模板事件（工作/休整：作用融入自然动力学；进餐与睡眠已移入事件配表）
# ---------------------------------------------------------------

TEMPLATE_EVENTS: list[dict] = [
    {"id": "T1", "name": "上午工作", "slot": "上午", "location": "公司",
     "implicit_effect": "精力 -0.06 · 压力 +0.048 · 收入按职业（由动力学+经济结算）"},
    {"id": "T2", "name": "下午工作", "slot": "下午", "location": "公司",
     "implicit_effect": "精力 -0.06 · 压力 +0.048 · 收入按职业"},
    {"id": "T3", "name": "晚间休整", "slot": "晚上", "location": "家",
     "implicit_effect": "压力 -0.01 · 精力 -0.04（工作日）"},
    {"id": "T4", "name": "周末休闲", "slot": "下午", "location": "外面",
     "implicit_effect": "心情 +0.03 · 压力 -0.01 · 精力 -0.03"},
]

# ---------------------------------------------------------------
# 合计效果计算与查找辅助
# ---------------------------------------------------------------


def variant_total_effect(action: dict, variant: dict) -> dict:
    """合计效果 = base + weight。"""
    total = dict(action["base_effect"])
    for k, v in variant["weight"].items():
        total[k] = total.get(k, 0) + v
    return total


# 预计算：variant["effect"] = 合计效果（供选择策略与结算直接使用）
for _a in RECOVERY_ACTIONS:
    for _v in _a["variants"]:
        _v["effect"] = variant_total_effect(_a, _v)


def all_variants() -> list[tuple[dict, dict]]:
    """[(action, variant), ...]：恢复动作 + 进餐/睡眠升级档（伪动作）。"""
    out = [(a, v) for a in get_recovery_actions() for v in a["variants"]]
    out.append(({"id": "MEAL", "action": "升级一餐", "category": "日常", "design_intent": ""},
                MEAL_TIERS[2]))
    out.append(({"id": "SLEEP", "action": "高质量睡眠", "category": "日常", "design_intent": ""},
                SLEEP_TIERS[2]))
    return out


def _ov() -> dict:
    from usersim.world.balance import load_overrides
    return load_overrides()


def get_recovery_actions() -> list[dict]:
    acts = _ov().get("recovery_actions") or RECOVERY_ACTIONS
    # 确保每个 variant 有合计 effect（JSON 行可能只有 base/weight）
    for a in acts:
        for v in a["variants"]:
            if "effect" not in v or not v["effect"]:
                v["effect"] = variant_total_effect(a, v)
    return acts


def get_disturbances() -> list[dict]:
    return _ov().get("disturbances") or DISTURBANCES


def get_economy() -> dict:
    return {**ECONOMY, **_ov().get("economy_params", {})}


def get_meal_tiers() -> list[dict]:
    return _ov().get("meal_tiers") or MEAL_TIERS


def get_sleep_tiers() -> list[dict]:
    return _ov().get("sleep_tiers") or SLEEP_TIERS


def get_custom_activities() -> list[dict]:
    return _ov().get("custom_activities") or CUSTOM_ACTIVITIES


def get_professions() -> list[dict]:
    return _ov().get("professions") or PROFESSIONS


# 常见口语别名 → 变体 ID（LLM 自由措辞也能命中配表）
VARIANT_ALIASES: dict[str, str] = {
    "早睡": "A2-1", "补觉": "A2-1", "睡觉": "A2-1", "休息": "A2-1",
    "散步": "A3-1", "遛弯": "A3-1", "走走": "A3-1", "公园": "A3-1",
    "跑步": "A5-1", "运动": "A5-1", "健身": "A5-2",
    "大餐": "A1-2", "美食": "A1-2", "火锅": "A1-2", "寿喜烧": "A1-3",
    "旅行": "A4-2", "旅游": "A4-2", "海边": "A4-2",
    "看电影": "A6-1", "打游戏": "A6-1", "宅": "A6-1",
    "按摩": "A2-2", "温泉": "A2-3",
    "助眠": "S2", "高质量睡眠": "S2",
    "加餐": "M2", "外卖": "M2",
}

# ---------------------------------------------------------------
# 自定义活动规范类目：LLM 发明的目录外活动按关键词归一化。
# 归一化后：名称/效果/价格统一（世界裁定，不信自报），
# 同类活动在日程图/日志中合并为一行。
# ---------------------------------------------------------------

CUSTOM_ACTIVITIES: list[dict] = [
    {"id": "C1", "name": "文化看展", "cost": 80,
     "keywords": ["美术馆", "展览", "看展", "博物馆", "艺术展", "画展", "逛馆"],
     "effect": {"valence": 0.10, "stress": -0.06},
     "design_intent": "精神滋养类：温和开心、小幅降压"},
    {"id": "C2", "name": "咖啡小憩", "cost": 35,
     "keywords": ["咖啡", "下午茶", "点心", "奶茶", "甜品"],
     "effect": {"valence": 0.06, "stress": -0.04, "energy": 0.03, "satiety": 0.05},
     "design_intent": "小额高频的即时慰藉"},
    {"id": "C3", "name": "音乐放松", "cost": 50,
     "keywords": ["黑胶", "音乐", "听歌", "livehouse", "唱片", "演唱会"],
     "effect": {"valence": 0.08, "stress": -0.07},
     "design_intent": "情绪价值类"},
    {"id": "C4", "name": "朋友小聚", "cost": 100,
     "keywords": ["朋友", "聚会", "聚餐", "见面", "约饭"],
     "effect": {"valence": 0.10, "satiety": 0.08, "energy": -0.03},
     "design_intent": "社交回血但耗电"},
    {"id": "C5", "name": "学习充电", "cost": 0,
     "keywords": ["学习", "看书", "读书", "课程", "复习", "刷数学", "开题", "论文"],
     "effect": {"stress": 0.02, "valence": 0.02, "energy": -0.02},
     "design_intent": "有意义但有消耗，不算恢复"},
    {"id": "C6", "name": "自然放空", "cost": 0,
     "keywords": ["放空", "发呆", "吹风", "看海", "爬山"],
     "effect": {"valence": 0.07, "stress": -0.08},
     "design_intent": "免费强降压"},
    {"id": "C0", "name": "自定义活动", "cost": 0, "keywords": [],
     "effect": {"valence": 0.06, "stress": -0.05},
     "design_intent": "兜底：做喜欢的事总是有点用（规则默认值）"},
]


def match_custom_activity(name: str) -> dict | None:
    """自由文本 → 规范类目；未命中返回兜底 C0。"""
    for cat in CUSTOM_ACTIVITIES:
        if any(k in name for k in cat["keywords"]):
            return cat
    return CUSTOM_ACTIVITIES[-1]


def find_variant(name_or_id: str, location: str | None = None) -> tuple[dict, dict] | None:
    """按动作名/变体ID/地点名/别名（+可选地点关键词）查变体。"""
    key = name_or_id.strip()
    # 0) 别名命中（包含匹配）
    for alias, vid in VARIANT_ALIASES.items():
        if alias in key:
            found = find_variant(vid)
            if found:
                return found
    # 1) 变体 ID 精确匹配
    for action, variant in all_variants():
        if key == variant["vid"]:
            return action, variant
    # 2) 动作名匹配 + 地点关键词
    if location:
        for action, variant in all_variants():
            vloc = variant.get("location", variant.get("name", ""))
            if key in action["action"] and (location in vloc or vloc in location):
                return action, variant
    # 3) 动作名/类别匹配
    for action, variant in all_variants():
        if key in (action["id"], action["action"]):
            return action, variant
    # 4) 模糊匹配：动作名包含 / 地点名包含（如 "家里补觉"→好好休息, "江边步道散步"→出门走走）
    for action, variant in all_variants():
        vloc = variant.get("location", variant.get("name", ""))
        if key and (key in action["action"] or (vloc and (key in vloc or vloc in key))):
            return action, variant
    return None


def affordable_variants(money: float) -> list[tuple[dict, dict]]:
    return [(a, v) for a, v in all_variants() if v["cost"] <= money]


def income_for_archetype(archetype: str) -> int:
    for p in PROFESSIONS:
        if p["archetype"] == archetype:
            return int(p["income_per_slot"])
    return int(ECONOMY["work_income_per_slot"])
