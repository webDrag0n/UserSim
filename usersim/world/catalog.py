"""数值配表（单一数据源）：事件表 + 统一地点表（supports）模型。

核心数值哲学（对标游戏配表）：
- 事件（RECOVERY_ACTIONS：A1-A6）只携带元信息（类目/设计意图/默认时长），
  不携带地点与效果；
- 一次"在某地点做某事件"的价格与效果由地点表（VENUES）该条支持记录自带：
  venue.supports[] = {event, cost, span, effect}，结算时按 span 摊销（pull 类除外）；
- 同一地点可支持多事件多条目（如"家"：补觉/看电影/做顿好的），
  vid = f"{事件id}@{地点id}"，同事件多条目按序加 "#n"；
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
     "effect": {"energy": {"pull": [0.80, 0.70]}, "stress": -0.05},
     "design_intent": "模板默认档（O1：精力上限 0.80；v5 入睡速率 0.5→0.70，模板工作日精力周期收敛到 0.63-0.75 全在带内）"},
    {"vid": "S2", "name": "高质量睡眠（助眠仪式）", "tier": "品质", "cost": 50,
     "effect": {"energy": {"pull": [0.85, 0.80]}, "stress": -0.04},
     "design_intent": "付费升级：精力上限更高、入睡更快、额外降压（v5 上限 0.88→0.85 避免顶带沿饱和）"},
]

# ---------------------------------------------------------------
# 恢复事件配表：base_effect + 档位 weight
# ---------------------------------------------------------------

RECOVERY_ACTIONS: list[dict] = [
    {
        "id": "A1",
        "action": "吃好吃的",
        "category": "饮食",
        "design_intent": "都能吃饱；档位差异主要体现在心情与减压——低档吃饱不开心",
        "default_span": 1
    },
    {
        "id": "A2",
        "action": "好好休息",
        "category": "休息",
        "design_intent": "躺着总能歇点；付费档位把预算大幅加权到减压",
        "default_span": 1
    },
    {
        "id": "A3",
        "action": "出门走走",
        "category": "户外",
        "design_intent": "出门就解压（基础档免费兜底）；档位加权到心情",
        "default_span": 1
    },
    {
        "id": "A4",
        "action": "短途旅行",
        "category": "旅行",
        "design_intent": "旅行都有基础回血；时长与地点共同决定加权幅度，价格陡增",
        "default_span": 2
    },
    {
        "id": "A5",
        "action": "运动健身",
        "category": "运动",
        "design_intent": "运动都累但都降压（以精力换降压）；档位提升降压效率",
        "default_span": 1
    },
    {
        "id": "A6",
        "action": "宅家回血",
        "category": "居家",
        "design_intent": "宅都有点小开心；做顿好的把加权分到饱腹",
        "default_span": 1
    }
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
     "implicit_effect": "精力 -0.04 · 压力 +0.035 · 收入按职业（由动力学+经济结算）"},
    {"id": "T2", "name": "下午工作", "slot": "下午", "location": "公司",
     "implicit_effect": "精力 -0.04 · 压力 +0.035 · 收入按职业"},
    {"id": "T3", "name": "晚间休整", "slot": "晚上", "location": "家",
     "implicit_effect": "压力 -0.02 · 精力 -0.04（工作日）"},
    {"id": "T4", "name": "周末休闲", "slot": "下午", "location": "外面",
     "implicit_effect": "心情 +0.03 · 压力 -0.02 · 精力 -0.03"},
]

# ---------------------------------------------------------------
# 地点支持表 flatten 与查找辅助
# ---------------------------------------------------------------


def _event_index() -> dict[str, dict]:
    """事件 id → 事件元信息（A1-A6 恢复事件 + C1-C6 自定义活动，供 supports 引用）。"""
    idx = {a["id"]: a for a in get_recovery_actions()}
    for c in get_custom_activities():
        idx.setdefault(c["id"], {"id": c["id"], "action": c["name"], "category": "",
                                 "design_intent": c.get("design_intent", "")})
    return idx


def _flatten_venues() -> list[tuple[dict, dict]]:
    """venues × supports → [(event_meta, variant_like)]，与旧恢复变体同构。

    variant_like = {vid, id=场所id, name=事件action名, location=场所名（或 support 标签）,
                    cost, span, effect, category, cuisine, replaces_meal?}；
    vid = f"{事件id}@{场所id}"；同一 venue 同一事件多条目按序加 "#n"（如家 A6@V034#1/#2）。
    """
    events = _event_index()
    out: list[tuple[dict, dict]] = []
    for vn in get_venues():
        supports = vn.get("supports") or []
        counts: dict[str, int] = {}
        for s in supports:
            counts[s["event"]] = counts.get(s["event"], 0) + 1
        seen: dict[str, int] = {}
        for s in supports:
            meta = events.get(s["event"])
            if meta is None:
                continue  # 引用未知事件：跳过（配置错误不应炸掉整个目录）
            seen[s["event"]] = seen.get(s["event"], 0) + 1
            vid = f"{s['event']}@{vn['id']}"
            if counts[s["event"]] > 1:
                vid = f"{vid}#{seen[s['event']]}"
            event_meta = {"id": meta["id"], "action": meta["action"],
                          "category": meta.get("category") or vn.get("category", ""),
                          "design_intent": meta.get("design_intent", "")}
            variant = {
                "vid": vid,
                "id": vn["id"],
                "name": meta["action"],
                "location": s.get("label") or vn.get("name", ""),
                "cost": s.get("cost", 0),
                "span": s.get("span", 1),
                "effect": s.get("effect", {}),
                "category": event_meta["category"],
                "cuisine": vn.get("cuisine", ""),
            }
            if vn.get("replaces_meal"):
                variant["replaces_meal"] = True
            out.append((event_meta, variant))
    return out


def all_variants() -> list[tuple[dict, dict]]:
    """[(event_meta, variant_like)]：地点支持表 flatten + 进餐/睡眠升级档（伪动作）。"""
    out = _flatten_venues()
    out.append(({"id": "MEAL", "action": "升级一餐", "category": "日常", "design_intent": ""},
                get_meal_tiers()[2]))
    out.append(({"id": "SLEEP", "action": "高质量睡眠", "category": "日常", "design_intent": ""},
                get_sleep_tiers()[2]))
    return out


def _ov() -> dict:
    from usersim.world.balance import load_overrides
    return load_overrides()


def get_recovery_actions() -> list[dict]:
    return _ov().get("recovery_actions") or RECOVERY_ACTIONS


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


def get_venues() -> list[dict]:
    return _ov().get("venues") or VENUES


# 常见口语别名 → 变体 ID（f"{事件id}@{场所id}"）/ 场所 ID（LLM 自由措辞也能命中配表）
VARIANT_ALIASES: dict[str, str] = {
    "早睡": "A2@V034", "补觉": "A2@V034", "睡觉": "A2@V034", "休息": "A2@V034",
    "散步": "A3@V037", "遛弯": "A3@V037", "走走": "A3@V037", "公园": "A3@V037",
    "跑步": "A5@V043", "运动": "A5@V043", "健身": "A5@V044",
    "大餐": "A1@V032", "美食": "A1@V032",
    # 高频品类 → 具体场所（场所 id 命中时取其首个支持条目）
    "火锅": "V001", "寿喜烧": "V003",
    "日料": "V005", "寿司": "V004", "烧烤": "V006", "海鲜": "V013",
    "咖啡": "V014", "甜品": "V014", "素食": "V012", "牛排": "V009",
    "居酒屋": "V015", "大排档": "V016",
    "旅行": "A4@V041", "旅游": "A4@V041", "海边": "A4@V041",
    "看电影": "A6@V034#1", "打游戏": "A6@V034#1", "宅": "A6@V034#1",
    "按摩": "A2@V035", "温泉": "A2@V036",
    "助眠": "S2", "高质量睡眠": "S2",
    "加餐": "M2", "外卖": "M2",
}

# ---------------------------------------------------------------
# 自定义活动规范类目：LLM 发明的目录外活动按关键词归一化。
# 归一化后：名称/效果/价格统一（世界裁定，不信自报），
# 同类活动在日程图/日志中合并为一行。
# **没有 C0 兜底**：关键词全部未命中 = 系统不支持的活动，
# add_event_todo 直接拒绝——助手应坦诚告知用户"找不到这样的地方"，
# 并推断真实需求、推荐目录内相近选项（见 docs/03）。
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
]


def match_custom_activity(name: str) -> dict | None:
    """自由文本 → 规范类目；未命中返回 None（系统不支持，由 add_event_todo 拒绝）。"""
    for cat in CUSTOM_ACTIVITIES:
        if any(k in name for k in cat["keywords"]):
            return cat
    return None


# ---------------------------------------------------------------
# 统一地点表（config/balance/venues.json 的代码回退副本，两者须保持一致）：
# 一次"在某地点做某事件"的价格/时长/效果由 supports 条目自带；
# 用户只表达模糊需求（"想吃日料"），世界按地点裁决名称/效果/价格/时长。
# flatten（venues × supports）是恢复目录的唯一数据源（见 _flatten_venues）。
# ---------------------------------------------------------------

VENUES: list[dict] = [
    {
        "id": "V001",
        "name": "川渝老火锅（巷子里店）",
        "category": "饮食",
        "cuisine": "火锅",
        "aliases": [
            "火锅",
            "川渝火锅",
            "老火锅"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 120,
                "span": 1,
                "effect": {
                    "valence": 0.1,
                    "satiety": 0.18,
                    "stress": -0.05
                }
            }
        ],
        "design_intent": "平价火锅主力：辣锅解馋饱腹强，重口略有刺激",
        "replaces_meal": True
    },
    {
        "id": "V002",
        "name": "精品鲜货火锅（商场旗舰店）",
        "category": "饮食",
        "cuisine": "火锅",
        "aliases": [
            "精品火锅",
            "鲜货火锅"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 220,
                "span": 1,
                "effect": {
                    "valence": 0.16,
                    "satiety": 0.16,
                    "stress": -0.08
                }
            }
        ],
        "design_intent": "高档火锅：环境与服务把预算加权到心情与减压，饱腹反而略低",
        "replaces_meal": True
    },
    {
        "id": "V003",
        "name": "寿喜烧专门店（和牛放题）",
        "category": "饮食",
        "cuisine": "寿喜烧",
        "aliases": [
            "寿喜烧",
            "和牛寿喜烧"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 180,
                "span": 1,
                "effect": {
                    "valence": 0.14,
                    "satiety": 0.16,
                    "stress": -0.06
                }
            }
        ],
        "design_intent": "甜口和牛：温和开心，价位中高的小确幸餐",
        "replaces_meal": True
    },
    {
        "id": "V004",
        "name": "回转寿司（商场店）",
        "category": "饮食",
        "cuisine": "寿司",
        "aliases": [
            "寿司",
            "回转寿司"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 80,
                "span": 1,
                "effect": {
                    "valence": 0.08,
                    "satiety": 0.14,
                    "stress": -0.03
                }
            }
        ],
        "design_intent": "平价日料：快捷饱腹，心情小加成",
        "replaces_meal": True
    },
    {
        "id": "V005",
        "name": "鮨·omakase（主厨发办）",
        "category": "饮食",
        "cuisine": "日料",
        "aliases": [
            "日料",
            "omakase",
            "主厨发办"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 450,
                "span": 1,
                "effect": {
                    "valence": 0.22,
                    "satiety": 0.12,
                    "stress": -0.1
                }
            }
        ],
        "design_intent": "顶级日料：分量少但仪式感拉满，预算几乎全加权到心情",
        "replaces_meal": True
    },
    {
        "id": "V006",
        "name": "深夜烧烤摊（街角炭火）",
        "category": "饮食",
        "cuisine": "烧烤",
        "aliases": [
            "烧烤",
            "烤串",
            "撸串"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 60,
                "span": 1,
                "effect": {
                    "valence": 0.08,
                    "satiety": 0.16,
                    "stress": -0.02,
                    "energy": -0.03
                }
            }
        ],
        "design_intent": "深夜烤串：解馋但熬夜伤身，精力小扣",
        "replaces_meal": True
    },
    {
        "id": "V007",
        "name": "川香小馆（水煮鱼招牌）",
        "category": "饮食",
        "cuisine": "川菜",
        "aliases": [
            "川菜",
            "水煮鱼",
            "麻辣香锅"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 90,
                "span": 1,
                "effect": {
                    "valence": 0.09,
                    "satiety": 0.18,
                    "stress": 0.02
                }
            }
        ],
        "design_intent": "重口川菜：麻辣过瘾但刺激肠胃，压力微升",
        "replaces_meal": True
    },
    {
        "id": "V008",
        "name": "粤式茶餐厅（虾饺必点）",
        "category": "饮食",
        "cuisine": "粤菜",
        "aliases": [
            "茶餐厅",
            "粤菜",
            "虾饺"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 55,
                "span": 1,
                "effect": {
                    "valence": 0.06,
                    "satiety": 0.15,
                    "stress": -0.03
                }
            }
        ],
        "design_intent": "街坊茶餐厅：便宜快捷的日常外食",
        "replaces_meal": True
    },
    {
        "id": "V009",
        "name": "牛排馆（纪念日之选）",
        "category": "饮食",
        "cuisine": "西餐",
        "aliases": [
            "牛排",
            "西餐"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 260,
                "span": 1,
                "effect": {
                    "valence": 0.17,
                    "satiety": 0.15,
                    "stress": -0.07
                }
            }
        ],
        "design_intent": "纪念日西餐：仪式感换心情，饱腹一般",
        "replaces_meal": True
    },
    {
        "id": "V010",
        "name": "兰州牛肉面馆（街角老店）",
        "category": "饮食",
        "cuisine": "面馆",
        "aliases": [
            "面馆",
            "牛肉面",
            "拉面"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 18,
                "span": 1,
                "effect": {
                    "valence": 0.02,
                    "satiety": 0.14
                }
            }
        ],
        "design_intent": "最便宜的一餐：能吃饱，毫无仪式感",
        "replaces_meal": True
    },
    {
        "id": "V011",
        "name": "东北饺子馆（手工现包）",
        "category": "饮食",
        "cuisine": "饺子",
        "aliases": [
            "饺子",
            "饺子馆",
            "水饺"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 28,
                "span": 1,
                "effect": {
                    "valence": 0.03,
                    "satiety": 0.16
                }
            }
        ],
        "design_intent": "家常水饺：便宜管饱，略有余温",
        "replaces_meal": True
    },
    {
        "id": "V012",
        "name": "素食斋（清淡养身）",
        "category": "饮食",
        "cuisine": "素食",
        "aliases": [
            "素食",
            "斋菜"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 70,
                "span": 1,
                "effect": {
                    "valence": 0.06,
                    "satiety": 0.12,
                    "stress": -0.05
                }
            }
        ],
        "design_intent": "清淡素食：饱腹一般但肠胃无负担，小幅降压",
        "replaces_meal": True
    },
    {
        "id": "V013",
        "name": "海鲜大酒楼（宴请规格）",
        "category": "饮食",
        "cuisine": "海鲜",
        "aliases": [
            "海鲜",
            "大酒楼"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 500,
                "span": 1,
                "effect": {
                    "valence": 0.2,
                    "satiety": 0.2,
                    "stress": -0.09
                }
            }
        ],
        "design_intent": "宴请天花板：海鲜管够，心情与排场拉满",
        "replaces_meal": True
    },
    {
        "id": "V014",
        "name": "咖啡甜品店（街角落地窗）",
        "category": "饮食",
        "cuisine": "咖啡甜品",
        "aliases": [
            "咖啡",
            "甜品",
            "下午茶"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 40,
                "span": 1,
                "effect": {
                    "valence": 0.07,
                    "satiety": 0.06,
                    "stress": -0.04,
                    "energy": 0.02
                }
            }
        ],
        "design_intent": "下午茶：不顶饱，主要买心情与片刻安静",
        "replaces_meal": True
    },
    {
        "id": "V015",
        "name": "深夜居酒屋（巷子深处）",
        "category": "饮食",
        "cuisine": "居酒屋",
        "aliases": [
            "居酒屋",
            "深夜食堂"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 130,
                "span": 1,
                "effect": {
                    "valence": 0.12,
                    "satiety": 0.14,
                    "stress": -0.08,
                    "energy": -0.03
                }
            }
        ],
        "design_intent": "深夜小酌：解压强但耗精力，第二天略累",
        "replaces_meal": True
    },
    {
        "id": "V016",
        "name": "路边大排档（夏夜小龙虾）",
        "category": "饮食",
        "cuisine": "大排档",
        "aliases": [
            "大排档",
            "小龙虾",
            "路边摊"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 50,
                "span": 1,
                "effect": {
                    "valence": 0.07,
                    "satiety": 0.17,
                    "stress": -0.02
                }
            }
        ],
        "design_intent": "夏夜排挡：烟火气解馋，环境嘈杂减压有限",
        "replaces_meal": True
    },
    {
        "id": "V017",
        "name": "私房菜馆（预约制）",
        "category": "饮食",
        "cuisine": "私房菜",
        "aliases": [
            "私房菜"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 350,
                "span": 1,
                "effect": {
                    "valence": 0.19,
                    "satiety": 0.16,
                    "stress": -0.08
                }
            }
        ],
        "design_intent": "预约制私房菜：口味与私密感都好，贵",
        "replaces_meal": True
    },
    {
        "id": "V018",
        "name": "自助餐厅（烤肉火锅双拼）",
        "category": "饮食",
        "cuisine": "自助餐",
        "aliases": [
            "自助",
            "自助餐"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 150,
                "span": 1,
                "effect": {
                    "valence": 0.1,
                    "satiety": 0.24,
                    "stress": -0.04,
                    "energy": -0.02
                }
            }
        ],
        "design_intent": "自助餐：饱腹天花板，吃撑了略犯困",
        "replaces_meal": True
    },
    {
        "id": "V019",
        "name": "泰餐厅（冬阴功招牌）",
        "category": "饮食",
        "cuisine": "泰餐",
        "aliases": [
            "泰餐",
            "冬阴功"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 110,
                "span": 1,
                "effect": {
                    "valence": 0.11,
                    "satiety": 0.15,
                    "stress": -0.05
                }
            }
        ],
        "design_intent": "酸辣泰餐：开胃提神，异域感加心情",
        "replaces_meal": True
    },
    {
        "id": "V020",
        "name": "韩式烤肉（五花肉必点）",
        "category": "饮食",
        "cuisine": "韩料",
        "aliases": [
            "韩料",
            "韩式烤肉",
            "烤肉"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 100,
                "span": 1,
                "effect": {
                    "valence": 0.1,
                    "satiety": 0.17,
                    "stress": -0.04
                }
            }
        ],
        "design_intent": "韩式烤肉：自己动手氛围好，饱腹强",
        "replaces_meal": True
    },
    {
        "id": "V021",
        "name": "麻辣烫小店（夜宵据点）",
        "category": "饮食",
        "cuisine": "麻辣烫",
        "aliases": [
            "麻辣烫"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 25,
                "span": 1,
                "effect": {
                    "valence": 0.04,
                    "satiety": 0.15,
                    "stress": 0.01
                }
            }
        ],
        "design_intent": "夜宵麻辣烫：便宜解馋，重口略刺激",
        "replaces_meal": True
    },
    {
        "id": "V022",
        "name": "轻食沙拉（健身搭子）",
        "category": "饮食",
        "cuisine": "轻食",
        "aliases": [
            "轻食",
            "沙拉"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 35,
                "span": 1,
                "effect": {
                    "valence": 0.03,
                    "satiety": 0.1,
                    "stress": -0.02
                }
            }
        ],
        "design_intent": "轻食沙拉：吃得干净，饱腹与满足感都一般",
        "replaces_meal": True
    },
    {
        "id": "V023",
        "name": "日式拉面馆（一人食吧台）",
        "category": "饮食",
        "cuisine": "日式拉面",
        "aliases": [
            "日式拉面",
            "豚骨拉面"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 45,
                "span": 1,
                "effect": {
                    "valence": 0.05,
                    "satiety": 0.15
                }
            }
        ],
        "design_intent": "一人食拉面：快捷治愈，深夜食堂平替",
        "replaces_meal": True
    },
    {
        "id": "V024",
        "name": "汉堡快餐（出餐飞快）",
        "category": "饮食",
        "cuisine": "快餐",
        "aliases": [
            "汉堡",
            "快餐"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 30,
                "span": 1,
                "effect": {
                    "valence": 0.03,
                    "satiety": 0.14,
                    "stress": -0.01
                }
            }
        ],
        "design_intent": "汉堡快餐：出餐快能吃饱，开心有限",
        "replaces_meal": True
    },
    {
        "id": "V025",
        "name": "地下 livehouse（周末场）",
        "category": "音乐",
        "cuisine": "",
        "aliases": [
            "livehouse",
            "演出",
            "现场音乐"
        ],
        "supports": [
            {
                "event": "C3",
                "cost": 120,
                "span": 1,
                "effect": {
                    "valence": 0.12,
                    "stress": -0.1,
                    "energy": -0.04
                }
            }
        ],
        "design_intent": "现场音乐：情绪释放强，散场略累"
    },
    {
        "id": "V026",
        "name": "市美术馆（常设展）",
        "category": "文化",
        "cuisine": "",
        "aliases": [
            "看展",
            "展览"
        ],
        "supports": [
            {
                "event": "C1",
                "cost": 60,
                "span": 1,
                "effect": {
                    "valence": 0.1,
                    "stress": -0.06
                }
            }
        ],
        "design_intent": "看展：精神滋养，温和开心小幅降压"
    },
    {
        "id": "V027",
        "name": "羽毛球馆（晚场两小时）",
        "category": "运动",
        "cuisine": "",
        "aliases": [
            "羽毛球",
            "球馆",
            "打球"
        ],
        "supports": [
            {
                "event": "A5",
                "cost": 40,
                "span": 1,
                "effect": {
                    "valence": 0.06,
                    "stress": -0.1,
                    "energy": -0.06
                }
            }
        ],
        "design_intent": "打球：以精力换减压，出身汗很爽"
    },
    {
        "id": "V028",
        "name": "桌游店（拼桌友好）",
        "category": "社交",
        "cuisine": "",
        "aliases": [
            "桌游",
            "剧本杀"
        ],
        "supports": [
            {
                "event": "C4",
                "cost": 60,
                "span": 1,
                "effect": {
                    "valence": 0.1,
                    "satiety": 0.04,
                    "energy": -0.03
                }
            }
        ],
        "design_intent": "桌游社交：拼桌也能玩，开心但耗电"
    },
    {
        "id": "V029",
        "name": "滨江步道（落日机位）",
        "category": "户外",
        "cuisine": "",
        "aliases": [
            "江边步道",
            "滨江",
            "步道"
        ],
        "supports": [
            {
                "event": "A3",
                "cost": 0,
                "span": 1,
                "effect": {
                    "valence": 0.06,
                    "stress": -0.08,
                    "energy": 0.02
                }
            }
        ],
        "design_intent": "免费滨江散步：吹风看落日，稳定小回血"
    },
    {
        "id": "V030",
        "name": "独立书店（咖啡角）",
        "category": "学习",
        "cuisine": "",
        "aliases": [
            "书店",
            "看书"
        ],
        "supports": [
            {
                "event": "C5",
                "cost": 30,
                "span": 1,
                "effect": {
                    "valence": 0.05,
                    "stress": -0.04,
                    "energy": -0.02
                }
            }
        ],
        "design_intent": "书店自习：安静输入，小幅回血但耗神"
    },
    {
        "id": "V031",
        "name": "楼下快餐",
        "category": "饮食",
        "cuisine": "",
        "aliases": [
            "楼下快餐",
            "快餐店"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 30,
                "span": 1,
                "effect": {
                    "valence": {
                        "pull": [
                            0.5,
                            0.1
                        ]
                    },
                    "satiety": 0.25,
                    "stress": -0.02
                }
            }
        ],
        "design_intent": "平价兜底：能吃饱但不太开心（原 A1 平价档）"
    },
    {
        "id": "V032",
        "name": "商场餐厅",
        "category": "饮食",
        "cuisine": "",
        "aliases": [
            "商场餐厅",
            "商场"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 120,
                "span": 1,
                "effect": {
                    "valence": 0.1,
                    "satiety": 0.25,
                    "stress": -0.06
                }
            }
        ],
        "design_intent": "中档外食：心情与减压都加权一些（原 A1 中档）"
    },
    {
        "id": "V033",
        "name": "收藏多年的小店",
        "category": "饮食",
        "cuisine": "",
        "aliases": [
            "收藏多年的小店",
            "小店",
            "珍藏小店"
        ],
        "supports": [
            {
                "event": "A1",
                "cost": 200,
                "span": 1,
                "effect": {
                    "valence": 0.2,
                    "satiety": 0.25,
                    "stress": -0.1
                }
            }
        ],
        "design_intent": "高档小馆：预算大幅加权到心情与减压（原 A1 高档）"
    },
    {
        "id": "V034",
        "name": "家",
        "category": "居家",
        "cuisine": "",
        "aliases": [
            "家里",
            "在家"
        ],
        "supports": [
            {
                "event": "A2",
                "label": "家里补觉",
                "cost": 0,
                "span": 1,
                "effect": {
                    "energy": 0.2,
                    "stress": -0.05
                }
            },
            {
                "event": "A6",
                "label": "看电影打游戏",
                "cost": 0,
                "span": 1,
                "effect": {
                    "valence": 0.06,
                    "satiety": -0.05,
                    "stress": -0.06
                }
            },
            {
                "event": "A6",
                "label": "做顿好的",
                "cost": 40,
                "span": 1,
                "effect": {
                    "valence": 0.06,
                    "satiety": 0.25,
                    "stress": -0.05
                }
            }
        ],
        "design_intent": "零成本基地：补觉/看片/下厨，三种宅法"
    },
    {
        "id": "V035",
        "name": "按摩 SPA",
        "category": "休息",
        "cuisine": "",
        "aliases": [
            "按摩",
            "SPA",
            "spa",
            "马杀鸡"
        ],
        "supports": [
            {
                "event": "A2",
                "cost": 150,
                "span": 1,
                "effect": {
                    "valence": 0.06,
                    "energy": 0.15,
                    "stress": -0.14
                }
            }
        ],
        "design_intent": "付费休息中档：预算大幅加权到减压（原 A2 中档）"
    },
    {
        "id": "V036",
        "name": "周边温泉酒店",
        "category": "休息",
        "cuisine": "",
        "aliases": [
            "温泉",
            "温泉酒店",
            "周边温泉"
        ],
        "supports": [
            {
                "event": "A2",
                "cost": 400,
                "span": 2,
                "effect": {
                    "valence": 0.1,
                    "energy": 0.25,
                    "stress": -0.2
                }
            }
        ],
        "design_intent": "高档休整：两时段，回血与减压都强（原 A2 高档）"
    },
    {
        "id": "V037",
        "name": "楼下公园",
        "category": "户外",
        "cuisine": "",
        "aliases": [
            "楼下公园",
            "小区公园"
        ],
        "supports": [
            {
                "event": "A3",
                "cost": 0,
                "span": 1,
                "effect": {
                    "valence": 0.03,
                    "stress": -0.08
                }
            }
        ],
        "design_intent": "免费兜底散步点（原 A3 平价档）"
    },
    {
        "id": "V038",
        "name": "江边步道",
        "category": "户外",
        "cuisine": "",
        "aliases": [
            "江边",
            "江边步道"
        ],
        "supports": [
            {
                "event": "A3",
                "cost": 0,
                "span": 1,
                "effect": {
                    "valence": 0.06,
                    "energy": 0.02,
                    "stress": -0.08
                }
            }
        ],
        "design_intent": "免费散步加强版：心情更好还回点精力（原 A3 平价档）"
    },
    {
        "id": "V039",
        "name": "近郊徒步",
        "category": "户外",
        "cuisine": "",
        "aliases": [
            "徒步",
            "近郊徒步"
        ],
        "supports": [
            {
                "event": "A3",
                "cost": 80,
                "span": 2,
                "effect": {
                    "valence": 0.1,
                    "energy": -0.06,
                    "stress": -0.16
                }
            }
        ],
        "design_intent": "两时段徒步：心情强但耗精力（原 A3 中档）"
    },
    {
        "id": "V040",
        "name": "邻市一日",
        "category": "旅行",
        "cuisine": "",
        "aliases": [
            "邻市",
            "一日游",
            "邻市一日"
        ],
        "supports": [
            {
                "event": "A4",
                "cost": 300,
                "span": 2,
                "effect": {
                    "valence": 0.12,
                    "stress": -0.1
                }
            }
        ],
        "design_intent": "平价短途：基础回血（原 A4 平价档）"
    },
    {
        "id": "V041",
        "name": "海边小镇",
        "category": "旅行",
        "cuisine": "",
        "aliases": [
            "海边",
            "海边小镇",
            "小镇"
        ],
        "supports": [
            {
                "event": "A4",
                "cost": 600,
                "span": 3,
                "effect": {
                    "valence": 0.2,
                    "energy": 0.05,
                    "stress": -0.18
                }
            }
        ],
        "design_intent": "中档旅行：三天，加权心情与减压（原 A4 中档）"
    },
    {
        "id": "V042",
        "name": "远方城市",
        "category": "旅行",
        "cuisine": "",
        "aliases": [
            "远方",
            "远方城市",
            "远游"
        ],
        "supports": [
            {
                "event": "A4",
                "cost": 1200,
                "span": 4,
                "effect": {
                    "valence": 0.27,
                    "energy": 0.08,
                    "stress": -0.22
                }
            }
        ],
        "design_intent": "高档旅行：四天，全面加权（原 A4 高档）"
    },
    {
        "id": "V043",
        "name": "小区跑步",
        "category": "运动",
        "cuisine": "",
        "aliases": [
            "跑步",
            "小区跑步",
            "夜跑"
        ],
        "supports": [
            {
                "event": "A5",
                "cost": 0,
                "span": 1,
                "effect": {
                    "valence": {
                        "pull": [
                            0.5,
                            0.1
                        ]
                    },
                    "energy": {
                        "pull": [
                            0.5,
                            0.1
                        ]
                    },
                    "stress": -0.08
                }
            }
        ],
        "design_intent": "免费运动：以精力换降压（原 A5 平价档）"
    },
    {
        "id": "V044",
        "name": "健身房",
        "category": "运动",
        "cuisine": "",
        "aliases": [
            "健身房",
            "健身",
            "撸铁"
        ],
        "supports": [
            {
                "event": "A5",
                "cost": 50,
                "span": 1,
                "effect": {
                    "valence": 0.05,
                    "energy": -0.03,
                    "stress": -0.13
                }
            }
        ],
        "design_intent": "中档运动：降压效率更高（原 A5 中档）"
    },
    {
        "id": "V045",
        "name": "私教课",
        "category": "运动",
        "cuisine": "",
        "aliases": [
            "私教",
            "私教课",
            "教练"
        ],
        "supports": [
            {
                "event": "A5",
                "cost": 200,
                "span": 1,
                "effect": {
                    "valence": 0.08,
                    "energy": -0.05,
                    "stress": -0.16
                }
            }
        ],
        "design_intent": "高档运动：最强降压，略耗精力（原 A5 高档）"
    }
]


def _resolve_ref(ref: str, flat: list[tuple[dict, dict]]) -> tuple[dict, dict] | None:
    """vid（"A1@V001"/"A6@V034#1"/"M2"）或场所 id（"V001"）精确解析；
    场所 id 命中时取其首个支持条目。"""
    for meta, variant in flat:
        if ref == variant["vid"]:
            return meta, variant
    for vn in get_venues():
        if ref == vn.get("id"):
            for meta, variant in flat:
                if variant.get("id") == vn["id"]:
                    return meta, variant
    return None


def _venue_match_texts(venue: dict) -> list[str]:
    return [venue.get("name", ""), venue.get("cuisine", ""),
            *[s.get("label", "") for s in venue.get("supports", [])],
            *venue.get("aliases", [])]


def _pick_support(venue: dict, flat: list[tuple[dict, dict]],
                  location: str | None = None, key: str = "") -> tuple[dict, dict] | None:
    """venue 的 flatten 条目里挑一条：location/查询词命中 support 标签者优先，否则首条。"""
    entries = [(m, v) for m, v in flat if v.get("id") == venue["id"]]
    if not entries:
        return None
    for kw in (location, key):
        if kw:
            for m, v in entries:
                if kw in v["location"] or v["location"] in kw:
                    return m, v
    return entries[0]


def find_variant(name_or_id: str, location: str | None = None) -> tuple[dict, dict] | None:
    """按事件名/vid/场所名/别名（+可选地点关键词）查地点支持条目。"""
    key = name_or_id.strip()
    flat = all_variants()
    # 1) 别名表命中（包含匹配）：值 = vid 或场所 id
    for alias, target in VARIANT_ALIASES.items():
        if alias in key:
            found = _resolve_ref(target, flat)
            if found:
                return found
    # 2) vid / 场所 id 精确匹配
    found = _resolve_ref(key, flat)
    if found:
        return found
    # 3) 场所名/菜系/别名/support 标签：精确场所名优先，其次双向包含（location 可再过滤到具体条目）
    venues = get_venues()
    for vn in venues:
        if key and key == vn.get("name"):
            picked = _pick_support(vn, flat, location, key)
            if picked:
                return picked
    for vn in venues:
        names = _venue_match_texts(vn)
        if key and any(n and (key in n or n in key) for n in names):
            picked = _pick_support(vn, flat, location, key)
            if picked:
                return picked
    # 4) 事件 action 名/id 匹配：有 location 选该地点条目，否则选最便宜的支持场所
    events = _event_index()
    for eid, meta in events.items():
        if not (key == eid or key in meta["action"] or meta["action"] in key):
            continue
        entries = [(m, v) for m, v in flat if m["id"] == eid]
        if not entries:
            continue
        if location:
            # 场所本名（去括号修饰）/support 标签优先，菜系兜底；别名不参与
            # （"快餐"这类泛词会把"楼下快餐"错误引到汉堡店）
            for want_cuisine in (False, True):
                for m, v in entries:
                    vn = next((x for x in venues if x["id"] == v.get("id")), {})
                    texts = [v["location"].split("（")[0], vn.get("name", "").split("（")[0]]
                    if want_cuisine:
                        texts = [vn.get("cuisine", "")]
                    if any(t and (location in t or t in location) for t in texts):
                        return m, v
        return min(entries, key=lambda mv: float(mv[1]["cost"]))
    # 5) 模糊匹配：事件名包含 / 地点名包含（如 "家里补觉"→好好休息）
    for meta, variant in flat:
        vloc = variant.get("location", variant.get("name", ""))
        if key and (key in meta["action"] or (vloc and (key in vloc or vloc in key))):
            return meta, variant
    return None


def affordable_variants(money: float) -> list[tuple[dict, dict]]:
    """买得起的地点支持条目（与 all_variants 同源过滤）。"""
    return [(a, v) for a, v in all_variants() if v["cost"] <= money]


def income_for_archetype(archetype: str) -> int:
    for p in PROFESSIONS:
        if p["archetype"] == archetype:
            return int(p["income_per_slot"])
    return int(ECONOMY["work_income_per_slot"])
