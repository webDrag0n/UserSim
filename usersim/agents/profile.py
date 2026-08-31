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

from usersim.contracts import (
    PersonaBelief,
    PersonaBeliefDelta,
    merge_persona_delta,
)
from usersim.contracts.models import PERSONA_BLEND_NEW, PERSONA_MAX_TAGS
from usersim.contracts.persona import (
    BIG5_DOMAINS,
    FACET_HINTS,
    facet_keys_of,
)

# 合并语义的唯一来源是 contracts.merge_persona_delta（Runner 退化路径共用）；
# 两个常量为兼容旧引用而保留别名（docs/13 引用 BLEND_NEW）。
BLEND_NEW = PERSONA_BLEND_NEW
MAX_TAGS = PERSONA_MAX_TAGS


def facet_menu() -> str:
    """可估计的 facet 清单（含语义），按域分组——助手必须用这些确切的键名。"""
    lines = []
    for domain in BIG5_DOMAINS:
        items = "、".join(
            f"{k}（{FACET_HINTS.get(k, '')}）" for k in facet_keys_of(domain)
        )
        lines.append(f"· {items}")
    return "\n".join(lines)


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
        merged = merge_persona_delta(self.to_belief(), delta)
        self.facets = dict(merged.facets)
        self.categories = dict(merged.categories)
        self.loves = list(merged.loves)
        self.hates = list(merged.hates)
        self.interruption_tolerance = merged.interruption_tolerance
        self.planning_style = merged.planning_style
        self.social_recharge = merged.social_recharge
        self.confidence = merged.confidence
        self.notes = merged.notes

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
