"""bench 包：多 seed 批量评测与统计聚合（组装点之一，见 docs/00 依赖表）。"""

from usersim.bench.aggregate import METRIC_KEYS, aggregate, cohens_d, summarize
from usersim.bench.suite import (
    BenchSpec,
    EpisodeSpec,
    check_turns_integrity,
    estimate_tokens,
    run_suite,
)

__all__ = [
    "aggregate",
    "summarize",
    "cohens_d",
    "METRIC_KEYS",
    "BenchSpec",
    "EpisodeSpec",
    "run_suite",
    "estimate_tokens",
    "check_turns_integrity",
]
