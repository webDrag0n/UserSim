"""评估器包：0 LLM，只读 runs/ 日志，可离线重放。"""

from usersim.evaluator.metrics import compute_metrics, load_run

__all__ = ["compute_metrics", "load_run"]
