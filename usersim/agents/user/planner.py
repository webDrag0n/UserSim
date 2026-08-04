"""用户主动规划器：根据需求状态和生物钟，从事件库中选择本 slot 的意图事件。

规则版规划器：确定性、可测试、0 LLM。
不依赖 world 包（agents 依赖规则：只能 import contracts / llm）。
"""
from __future__ import annotations
from dataclasses import dataclass

# 内联常量（避免 agents 依赖 world 模块）
_SOCIAL_KEYWORDS = ("朋友小聚", "朋友临时邀约", "商务应酬", "聚会", "朋友", "同学")
_STIM_KEYWORDS = ("文化看展", "音乐放松", "自然放空", "自定义活动", "旅行", "电影", "游戏", "展览", "爬山", "徒步")

# 意图类型
INTENT_EAT = "eat"           # 进餐
INTENT_SOCIAL = "social"     # 社交
INTENT_STIMULATE = "stimulate"  # 寻求刺激/娱乐
INTENT_RECOVER = "recover"   # 休息恢复
INTENT_SLEEP = "sleep"       # 睡眠
INTENT_ACHIEVE = "achieve"   # 成就/学习

@dataclass
class Intent:
    type: str
    priority: float = 0.0
    event_name: str = ""      # 匹配到的事件名（可空）
    location: str = ""
    description: str = ""

class UserPlanner:
    """用户侧意图规划器（规则版）：多目标优化选择本 slot 的意图事件。"""

    def plan_slot(self, urges: dict, stress: float, energy: float,
                  slot: int, money: float, event_library: list[dict]) -> list[Intent]:
        """
        根据需求驱动力和生物钟，选出本 slot 的意图事件列表（0~3 个）。

        参数：
          urges: 需求驱动力字典 {hunger, social, stimulation, achievement}（来自 Needs.urges()）
          stress: 当前压力 (0-1)
          energy: 当前精力 (0-1)
          slot: 当前时段 (0=上午, 1=下午, 2=晚上, 3=深夜)
          money: 当前余额
          event_library: 用户个性化事件库
        """
        if slot == 3:
            return [Intent(type=INTENT_SLEEP, priority=1.0, description="该睡觉了")]

        intents = []

        # 1. 饥饿驱动（午饭时段 slot==1 或晚饭 slot==2 时额外加强）
        hunger_urge = urges["hunger"]
        if slot in (1, 2):
            hunger_urge = min(1.0, hunger_urge * 1.3)
        if hunger_urge > 0.4:
            candidates = [e for e in event_library
                         if any(k in e.get("name","") for k in ("吃","餐","食","火锅","寿喜烧","小店","外卖"))
                         and e.get("cost", 0) <= money]
            best = self._best_by_effect(candidates, "satiety", money)
            intents.append(Intent(
                type=INTENT_EAT, priority=hunger_urge,
                event_name=best.get("name","") if best else "",
                location=best.get("location","") if best else "",
                description="肚子有点饿了",
            ))

        # 2. 恢复驱动（压力高或精力低时）
        recover_urge = max(stress - 0.4, 0) + max(0.3 - energy, 0)
        if recover_urge > 0.2:
            candidates = [e for e in event_library
                         if any(k in e.get("name","") for k in ("休息","睡","按摩","温泉","散步","公园","放松","回血"))
                         and e.get("cost", 0) <= money]
            best = self._best_by_effect(candidates, "stress", money, minimize=True)
            intents.append(Intent(
                type=INTENT_RECOVER, priority=min(1.0, recover_urge),
                event_name=best.get("name","") if best else "",
                location=best.get("location","") if best else "",
                description="需要放松一下",
            ))

        # 3. 社交驱动（晚间更强）
        social_urge = urges["social"]
        if slot == 2:
            social_urge = min(1.0, social_urge * 1.2)
        if social_urge > 0.4:
            candidates = [e for e in event_library
                         if any(k in e.get("name","") for k in _SOCIAL_KEYWORDS)
                         and e.get("cost", 0) <= money]
            best = self._best_by_effect(candidates, "valence", money)
            intents.append(Intent(
                type=INTENT_SOCIAL, priority=social_urge,
                event_name=best.get("name","") if best else "",
                location=best.get("location","") if best else "",
                description="想出去见见人",
            ))

        # 4. 刺激/娱乐驱动（倒 U：无聊时或日程单调时）
        stim_urge = urges["stimulation"]
        if stim_urge > 0.4 and slot != 0:
            candidates = [e for e in event_library
                         if any(k in e.get("name","") for k in _STIM_KEYWORDS)
                         and e.get("cost", 0) <= money]
            best = self._best_by_effect(candidates, "valence", money)
            intents.append(Intent(
                type=INTENT_STIMULATE, priority=stim_urge,
                event_name=best.get("name","") if best else "",
                location=best.get("location","") if best else "",
                description="想找点乐子",
            ))

        # 5. 成就驱动（上午/下午更适合，晚间不规划）
        achieve_urge = urges["achievement"]
        if achieve_urge > 0.5 and slot in (0, 1):
            intents.append(Intent(
                type=INTENT_ACHIEVE, priority=achieve_urge,
                description="感觉应该做点正事",
            ))

        # 去重 + 按优先级排序，最多取 3 个
        seen = set()
        unique = []
        for intent in sorted(intents, key=lambda i: i.priority, reverse=True):
            if intent.type not in seen:
                seen.add(intent.type)
                unique.append(intent)
        return unique[:3]

    def _best_by_effect(self, candidates: list[dict], dim: str, money: float,
                        minimize: bool = False) -> dict | None:
        """从候选事件中选出对指定维度效果最好的（买得起）。"""
        affordable = [e for e in candidates if e.get("cost", 0) <= money]
        if not affordable:
            affordable = [e for e in candidates if e.get("cost", 0) == 0] or candidates[:1]
        if not affordable:
            return None

        def effect_val(e: dict) -> float:
            eff = e.get("effect", {})
            v = float(eff.get(dim, 0))
            if isinstance(eff.get(dim), dict):
                v = float(eff[dim].get("pull", [0, 0])[1])
            return v

        if minimize:
            return min(affordable, key=effect_val, default=None)
        return max(affordable, key=effect_val, default=None)
