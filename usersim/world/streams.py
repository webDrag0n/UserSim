"""种子流派生：一个 run.seed 派生若干独立子流。

增减一类随机性不打乱其他流（SeedSequence.spawn）。
"""

from __future__ import annotations

import numpy as np

STREAM_NAMES = ["persona", "schedule", "disturbance", "noise"]


def make_streams(seed: int) -> dict[str, np.random.Generator]:
    ss = np.random.SeedSequence(seed)
    return {
        name: np.random.default_rng(child)
        for name, child in zip(STREAM_NAMES, ss.spawn(len(STREAM_NAMES)))
    }
