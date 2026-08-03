"""规则回放 Agent：无 LLM 的脚本用户与脚本助手（三档品质）。

用途：世界/评估器开发、CI、以及在没有有效 API key 时端到端验证系统。
脚本助手模拟"观测器 + 控制器"：带噪声地估计 x，按增益 K 安排恢复事件；
脚本用户模拟"表达 + 求助决策"：决定何时开 session 并生成模板化对话。
"""

from __future__ import annotations

import math

import numpy as np

from usersim.contracts import StateVec
from usersim.world.dynamics import DIMS, dim_error

QUALITY_PRESETS: dict[str, dict] = {
    "good": {"K": 0.85, "sigma0": 0.030, "sigma_floor": 0.008, "decay": 0.25, "delay": 0, "recover_prob": 0.97, "margin": 0.3},
    "mid": {"K": 1.30, "sigma0": 0.070, "sigma_floor": 0.050, "decay": 0.05, "delay": 3, "recover_prob": 0.90, "margin": 1.0},
    "poor": {"K": 0.08, "sigma0": 0.150, "sigma_floor": 0.150, "decay": 0.0, "delay": 1, "recover_prob": 0.12, "margin": 1.0},
}


def _numeric_effect(eff: dict, est: StateVec) -> dict[str, float]:
    """把配表效果统一换算为数值增量：pull 类按当前估计状态折算。"""
    out: dict[str, float] = {}
    for k, v in eff.items():
        if isinstance(v, dict) and "pull" in v:
            out[k] = (float(v["pull"][0]) - getattr(est, k)) * float(v["pull"][1])
        else:
            out[k] = float(v)
    return out


class ScriptedAssistant:
    """三档脚本助手：估计噪声、滞后与增益决定了回路表现（收敛/振荡/发散）。"""

    def __init__(self, quality: str, gen: np.random.Generator, targets: dict[str, float], band: float):
        self.q = QUALITY_PRESETS[quality]
        self.quality = quality
        self.gen = gen
        self.targets = targets
        self.band = band
        self.hist: list[StateVec] = []

    def observe(self, x_true: StateVec, day: int) -> StateVec:
        sigma = self.q["sigma_floor"] + (self.q["sigma0"] - self.q["sigma_floor"]) * math.exp(-self.q["decay"] * day)
        est = StateVec(
            valence=float(np.clip(x_true.valence + self.gen.normal(0, sigma), 0, 1)),
            energy=float(np.clip(x_true.energy + self.gen.normal(0, sigma), 0, 1)),
            satiety=float(np.clip(x_true.satiety + self.gen.normal(0, sigma), 0, 1)),
            stress=float(np.clip(x_true.stress + self.gen.normal(0, sigma), 0, 1)),
        )
        self.hist.append(est)
        return est

    def delayed_estimate(self) -> StateVec | None:
        if not self.hist:
            return None
        idx = max(0, len(self.hist) - 1 - self.q["delay"])
        return self.hist[idx]

    def violates(self, est: StateVec) -> bool:
        # margin < 1 表示"预判型"助手：贴近带边就开始温和干预
        return any(dim_error(est, d, self.targets) > self.band * self.q["margin"] for d in DIMS)

    def should_intervene(self) -> bool:
        est = self.delayed_estimate()
        return est is not None and self.violates(est) and self.gen.random() < self.q["recover_prob"]

    def choose_recovery(self, money: float, spent_today: float = 0.0, daily_income: float = 200.0) -> tuple[str, str] | None:
        """按估计误差从配表选择恢复变体，返回 (动作名, 变体ID)。

        三档策略：
        - good：在买得起的变体中选"效果最接近 u=K·ê"的（精准控制）
        - mid：买效果总量最大的（增益过猛 → 超调）
        - poor：只选最便宜的（控制不足）
        """
        from usersim.world.catalog import affordable_variants

        est = self.delayed_estimate()
        if est is None:
            return None
        K = self.q["K"]
        t = self.targets
        need = {
            "stress": K * max(0.0, est.stress - t["stress"]),
            "energy": K * max(0.0, t["energy"] - est.energy),
            "valence": 0.9 * K * max(0.0, t["valence"] - est.valence),
            "satiety": K * max(0.0, t["satiety"] - est.satiety),
        }
        if not any(v > 0 for v in need.values()):
            return None

        candidates = affordable_variants(max(0.0, money))
        if not candidates:
            return None

        if self.quality == "mid":
            # 增益过猛：选"比需求大一号"的变体（过量 30%）；
            # 日预算护栏：当日恢复开销 ≤ 日收入×60% + 存款×5%——超调但不破产
            need_total = sum(need.values())
            daily_budget = daily_income * 0.6 + max(0.0, money) * 0.05
            allowed = min(400.0, max(0.0, daily_budget - spent_today))
            sane = [av for av in candidates if av[1]["cost"] <= allowed]
            if not sane:
                sane = [av for av in candidates if av[1]["cost"] == 0] or candidates
            ascending = sorted(sane, key=lambda av: sum(abs(v) for v in _numeric_effect(av[1]["effect"], est).values()))
            best = next(
                (av for av in ascending if sum(abs(v) for v in _numeric_effect(av[1]["effect"], est).values()) >= 1.3 * need_total),
                ascending[-1],
            )
        elif self.quality == "poor":
            best = min(candidates, key=lambda av: av[1]["cost"])
        else:  # good：最小化"执行后的预测总误差"（量化动作下的最优一拍控制）
            # 节俭规则：余额紧张时只用免费档（优秀控制器懂得量入为出）
            if money < 300:
                free = [av for av in candidates if av[1]["cost"] == 0]
                if free:
                    candidates = free

            def score(av) -> float:
                x = est.model_dump()
                for k, v in _numeric_effect(av[1]["effect"], est).items():
                    x[k] = min(1.0, max(0.0, x[k] + v))
                pred = StateVec(**x)
                err = sum(dim_error(pred, d, t) for d in DIMS) / len(DIMS)
                # 反弹区惩罚：压力被压进 <0.15 会触发积压反弹，优秀控制器必须避开
                rebound_penalty = max(0.0, 0.15 - x["stress"]) * 3.0
                return err + rebound_penalty + av[1]["cost"] * 1e-4
            best = min(candidates, key=score)
        action, variant = best
        return action["action"], variant["vid"]


class ScriptedUser:
    """模板化表达的用户：根据 felt_state 与活跃事件生成对话。"""

    OPENERS = [
        "唉，{felt}……",
        "跟你说个事，我现在{felt}。",
        "今天真是不行，{felt}。",
    ]
    EVENT_LINES = [
        "刚经历了「{event}」，{felt}。",
        "「{event}」搞得我{felt}。",
    ]
    ACK = ["好，听你的。", "行，就这么办。", "嗯嗯，有盼头了。", "谢啦，那我先去了。"]

    def __init__(self, gen: np.random.Generator):
        self.gen = gen

    def opener(self, felt: str, active_event_names: list[str]) -> str:
        if active_event_names and self.gen.random() < 0.6:
            tpl = self.EVENT_LINES[int(self.gen.integers(len(self.EVENT_LINES)))]
            return tpl.format(event=active_event_names[0], felt=felt)
        tpl = self.OPENERS[int(self.gen.integers(len(self.OPENERS)))]
        return tpl.format(felt=felt)

    def ack(self) -> str:
        return self.ACK[int(self.gen.integers(len(self.ACK)))]


ASSISTANT_REPLIES = [
    "辛苦啦！我看了下你的日程，先帮你把恢复安排上：{plan}，你觉得行吗？",
    "听起来消耗很大。我建议{plan}，已经写进日程了，今晚先好好休息。",
    "懂了。我给你安排了{plan}，另外今晚尽量早点睡，明早我叫你。",
]
