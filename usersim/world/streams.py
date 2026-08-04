"""种子流派生：一个 run.seed 派生若干独立子流。

增减一类随机性不打乱其他流（SeedSequence.spawn）。
重要：流的顺序（槽位）必须固定。新增流只能在末尾追加，
且总槽位预留 8 个，保证旧 seed 的回放轨迹不变。
"""

from __future__ import annotations

import numpy as np

# 流名称到槽位的固定映射（顺序不可改，只能末尾追加）
STREAM_SLOTS = {
    "persona":     0,
    "schedule":    1,
    "disturbance": 2,
    "noise":       3,
    "weather":     4,   # 新增：天气系统
    "planner":     5,   # 新增：用户规划器
    # 槽位 6、7 预留
}

_TOTAL_SLOTS = 8  # 预分配槽位数，不随流数量增加而改变


def make_streams(seed: int) -> dict[str, np.random.Generator]:
    ss = np.random.SeedSequence(seed)
    children = ss.spawn(_TOTAL_SLOTS)  # 始终派生固定数量，保证确定性
    return {
        name: np.random.default_rng(children[slot])
        for name, slot in STREAM_SLOTS.items()
    }
