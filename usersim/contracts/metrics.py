"""共享误差度量：world / evaluator / agents 三方共用的纯函数。

放在 contracts 是因为它是**契约的一部分**——"什么叫偏离内心平和"这个定义
必须三方一致，否则世界的动力学目标、助手的控制目标、评估器的打分标准会漂移。

本模块零依赖（仅 contracts.models），不得 import 任何业务包。
对应文档：docs/00-architecture.md 依赖表、docs/04-evaluator.md 第 2 节
"""

from __future__ import annotations

from usersim.contracts.models import StateVec

# 维度顺序固定（与 config/system.toml [state].dims 一致）
DIMS: list[str] = ["valence", "energy", "satiety", "stress"]

# 越低越好的维度（其余维度越高越好）
LOWER_IS_BETTER: frozenset[str] = frozenset({"stress"})


def dim_error(x: StateVec, dim: str, targets: dict[str, float]) -> float:
    """单侧偏差：健康维低于目标才算误差，压力高于目标才算误差。

    "过度开心"不算失控——这是本系统的价值判断，不是数学上的对称距离。
    """
    v = getattr(x, dim)
    t = targets[dim]
    return max(0.0, v - t) if dim in LOWER_IS_BETTER else max(0.0, t - v)


def total_error(x: StateVec, targets: dict[str, float]) -> float:
    """综合误差 e(t)：各维单侧偏差的均值。"""
    return sum(dim_error(x, k, targets) for k in DIMS) / len(DIMS)


def belief_error(x_true: StateVec, x_hat: StateVec) -> float:
    """估计误差 ‖x−x̂‖₂（观测器考点）。"""
    return sum((getattr(x_true, d) - getattr(x_hat, d)) ** 2 for d in DIMS) ** 0.5
