"""助手侧画像累积器：把每轮的估计增量合并成完整的人格/喜好信念。

为什么是增量合并而不是每轮全量重写：
- 30 个 facet 每轮全量输出既费 token，又会让弱模型随机抖动（今天焦虑 70、明天 40，
  不是学到了东西而是噪声）；
- 真实的"认识一个人"是单调积累的：本轮听出对方讨厌应酬，就只更新那一项；
- 累积器用**指数滑动平均**吸收新证据，因此估计既能被新信息推动，又不会被单句话带跑。
  这直接决定了 `persona_err_slope_per_day` 是否为负（是否越聊越懂用户）。

本模块只依赖 contracts（agents 包的依赖规则见 docs/00 依赖表）。
"""

from __future__ import annotations

from usersim.contracts import PersonaBelief, PersonaBeliefDelta
from usersim.contracts.persona import FACET_KEYS, PREF_CATEGORIES

# 新证据权重：0.6 表示"以新观察为主，但保留 40% 已有认识"。
# 偏高是有意的——助手应该敢于修正错误的第一印象（docs/03 的锚定问题）。
BLEND_NEW = 0.6
MAX_TAGS = 12  # loves/hates 各自的上限（防止 Harness 无节制堆词刷命中率）


def _blend(old: float, new: float, w: float = BLEND_NEW) -> float:
    return old * (1.0 - w) + new * w


def _merge_tags(existing: list[str], incoming: list[str]) -> list[str]:
    """标签合并：去重、保序、截断。新标签靠前（近期证据更相关）。"""
    out: list[str] = []
    for tag in list(incoming) + list(existing):
        t = str(tag).strip()
        if t and t not in out:
            out.append(t)
    return out[:MAX_TAGS]


class ProfileTracker:
    """跨 session 累积的人格/喜好信念。Harness 持有一个实例。"""

    def __init__(self) -> None:
        self.facets: dict[str, int] = {}
        self.categories: dict[str, float] = {}
        self.loves: list[str] = []
        self.hates: list[str] = []
        self.interruption_tolerance: float | None = None
        self.planning_style: str | None = None
        self.social_recharge: str | None = None
        self.confidence: float = 0.0
        self.notes: str = ""

    # ---- 合并一轮增量 ----
    def update(self, delta: PersonaBeliefDelta | None) -> None:
        if delta is None:
            return
        for key, val in (delta.facets or {}).items():
            if key not in FACET_KEYS:
                continue  # 未知 facet 名静默丢弃（被测件可能瞎编，不能污染信念）
            try:
                v = float(val)
            except (TypeError, ValueError):
                continue
            v = max(0.0, min(100.0, v))
            self.facets[key] = int(round(_blend(self.facets[key], v) if key in self.facets else v))

        for cat, val in (delta.categories or {}).items():
            if cat not in PREF_CATEGORIES:
                continue
            try:
                v = float(val)
            except (TypeError, ValueError):
                continue
            v = max(-1.0, min(1.0, v))
            self.categories[cat] = round(
                _blend(self.categories[cat], v) if cat in self.categories else v, 3)

        if delta.loves:
            self.loves = _merge_tags(self.loves, delta.loves)
        if delta.hates:
            self.hates = _merge_tags(self.hates, delta.hates)
        if delta.interruption_tolerance is not None:
            v = max(0.0, min(1.0, float(delta.interruption_tolerance)))
            self.interruption_tolerance = round(
                _blend(self.interruption_tolerance, v) if self.interruption_tolerance is not None else v, 3)
        if delta.planning_style:
            self.planning_style = str(delta.planning_style)
        if delta.social_recharge:
            self.social_recharge = str(delta.social_recharge)
        if delta.confidence is not None:
            self.confidence = max(0.0, min(1.0, float(delta.confidence)))
        if delta.notes:
            self.notes = str(delta.notes)

    # ---- 导出 ----
    def to_belief(self) -> PersonaBelief:
        """当前完整信念快照（Runner 每轮落盘这个对象）。"""
        return PersonaBelief(
            facets=dict(self.facets),
            categories=dict(self.categories),
            loves=list(self.loves),
            hates=list(self.hates),
            interruption_tolerance=self.interruption_tolerance,
            planning_style=self.planning_style,
            social_recharge=self.social_recharge,
            confidence=self.confidence,
            notes=self.notes,
        )

    def prompt_block(self) -> str:
        """注入系统提示的"我目前对用户的了解"（只列已形成判断的项）。"""
        if not any((self.facets, self.categories, self.loves, self.hates, self.notes)):
            return "（还没有积累对用户的认识——本轮开始观察）"
        lines: list[str] = []
        if self.notes:
            lines.append(f"画像笔记：{self.notes}")
        if self.facets:
            strong = sorted(self.facets.items(), key=lambda kv: -kv[1])[:6]
            weak = sorted(self.facets.items(), key=lambda kv: kv[1])[:4]
            lines.append("已判断偏高的特质：" + "、".join(f"{k} {v}" for k, v in strong if v >= 55))
            lines.append("已判断偏低的特质：" + "、".join(f"{k} {v}" for k, v in weak if v <= 45))
        if self.categories:
            liked = [c for c, v in sorted(self.categories.items(), key=lambda kv: -kv[1]) if v >= 0.4]
            disliked = [c for c, v in sorted(self.categories.items(), key=lambda kv: kv[1]) if v <= -0.3]
            if liked:
                lines.append(f"看起来喜欢：{'、'.join(liked)}")
            if disliked:
                lines.append(f"看起来不喜欢：{'、'.join(disliked)}")
        if self.loves:
            lines.append(f"明确偏爱：{'、'.join(self.loves)}")
        if self.hates:
            lines.append(f"明确反感：{'、'.join(self.hates)}")
        if self.planning_style:
            lines.append(f"做事风格：{self.planning_style}")
        if self.social_recharge:
            lines.append(f"回血方式：{self.social_recharge}")
        if self.interruption_tolerance is not None:
            lines.append(f"打扰容忍度：{self.interruption_tolerance:.2f}")
        lines.append(f"（已覆盖 {len(self.facets)}/30 个人格特质，置信度 {self.confidence:.2f}）")
        return "\n".join(x for x in lines if x and not x.endswith("："))

    # ---- 续跑支持 ----
    def snapshot(self) -> dict:
        return self.to_belief().model_dump()

    def restore(self, state: dict) -> None:
        if not state:
            return
        bel = PersonaBelief(**state)
        self.facets = dict(bel.facets)
        self.categories = dict(bel.categories)
        self.loves = list(bel.loves)
        self.hates = list(bel.hates)
        self.interruption_tolerance = bel.interruption_tolerance
        self.planning_style = bel.planning_style
        self.social_recharge = bel.social_recharge
        self.confidence = bel.confidence
        self.notes = bel.notes
