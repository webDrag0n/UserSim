"""批量 episode 执行器（组装点：允许 import world/agents/evaluator）。

replay 模式零 token，可全量跑；live 模式按预算限制 episode 数。
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from usersim.bench.aggregate import METRIC_KEYS
from usersim.bench.aggregate import aggregate as aggregate_episodes
from usersim.bench.discriminability import compute as compute_discriminability
from usersim.config import PROJECT_ROOT, artifact_hashes, load_llm_runtime, load_system_config
from usersim.evaluator.report import evaluate_run

# live 模式默认上限（防止一条命令烧掉大量 token）
LIVE_EPISODE_HARD_CAP = 20
# 单 episode 的粗略 token 估算（10 天 live 实测量级，用于成本提示）
TOKENS_PER_DAY_ESTIMATE = 12_000


@dataclass
class EpisodeSpec:
    seed: int
    days: int
    mode: str
    group: str                      # 分组键（replay=quality，live=harness）
    quality: str = "good"
    harness: str | None = None
    archetype: str | None = None

    @property
    def label(self) -> str:
        arch = self.archetype or "auto"
        return f"{self.group}/{arch}/seed{self.seed}"


@dataclass
class BenchSpec:
    seeds: list[int]
    days: int
    mode: str
    groups: list[str]                       # replay: quality 档位；live: harness 名
    archetypes: list[str | None] = field(default_factory=lambda: [None])
    concurrency: int = 4

    def episodes(self) -> list[EpisodeSpec]:
        out: list[EpisodeSpec] = []
        for g in self.groups:
            for arch in self.archetypes:
                for s in self.seeds:
                    out.append(EpisodeSpec(
                        seed=s, days=self.days, mode=self.mode, group=g,
                        quality=g if self.mode == "replay" else "good",
                        harness=g if self.mode == "live" else None,
                        archetype=arch,
                    ))
        return out


def _run_one(spec: EpisodeSpec, out_root_str: str) -> dict:
    """子进程入口：跑一个 episode 并返回其指标（必须可 pickle，故用基本类型）。"""
    from usersim.runner import run_live, run_replay

    cfg = load_system_config()
    out_root = Path(out_root_str)
    run_id = f"{spec.group}_{spec.archetype or 'auto'}_{spec.seed}".replace(" ", "")
    if spec.mode == "live":
        run_dir = run_live(seed=spec.seed, days=spec.days, cfg=cfg, out_root=out_root,
                           archetype=spec.archetype, harness=spec.harness, run_id=run_id)
    else:
        run_dir = run_replay(seed=spec.seed, days=spec.days, quality=spec.quality, cfg=cfg,
                             out_root=out_root, archetype=spec.archetype, run_id=run_id)
    report = evaluate_run(run_dir, cfg)
    insights_path = run_dir / "insights.json"
    health = None
    if insights_path.exists():
        health = json.loads(insights_path.read_text(encoding="utf-8")).get("health_score")
    metrics = {k: report.get(k) for k in METRIC_KEYS if k in report}
    metrics["verdict"] = report.get("verdict")
    metrics["health_score"] = health
    return {
        "group": spec.group, "seed": spec.seed, "archetype": spec.archetype,
        "label": spec.label, "run_id": run_dir.name, "metrics": metrics,
    }


def estimate_tokens(spec: BenchSpec) -> int:
    return len(spec.episodes()) * spec.days * TOKENS_PER_DAY_ESTIMATE


def run_suite(spec: BenchSpec, out_root: Path | None = None,
              bench_id: str | None = None, on_progress=None) -> dict:
    """执行批量并落盘 episodes.jsonl / aggregate.json / discriminability.json。"""
    cfg = load_system_config()
    episodes = spec.episodes()

    if spec.mode == "live" and len(episodes) > LIVE_EPISODE_HARD_CAP:
        raise ValueError(
            f"live 模式 episode 数 {len(episodes)} 超过上限 {LIVE_EPISODE_HARD_CAP}"
            f"（预估 {estimate_tokens(spec):,} tokens）。请减少 seeds/archetypes，"
            f"或先用 --mode replay 做零成本批量。"
        )

    bench_id = bench_id or f"bench_{spec.mode}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    root = out_root or (PROJECT_ROOT / "runs" / "_bench")
    bench_dir = root / bench_id
    (bench_dir / "runs").mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    workers = max(1, min(int(spec.concurrency), len(episodes), (os.cpu_count() or 2)))
    ep_root = str(bench_dir / "runs")

    if workers == 1 or spec.mode == "live":
        # live 走串行：避免多进程同时打同一个 provider 触发限流
        for i, ep in enumerate(episodes):
            results.append(_run_one(ep, ep_root))
            if on_progress:
                on_progress(i + 1, len(episodes), results[-1])
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futs = {pool.submit(_run_one, ep, ep_root): ep for ep in episodes}
            for i, fut in enumerate(as_completed(futs)):
                results.append(fut.result())
                if on_progress:
                    on_progress(i + 1, len(episodes), results[-1])

    results.sort(key=lambda r: (r["group"], str(r["archetype"]), r["seed"]))
    aggregated = aggregate_episodes(results)
    aggregated["bench_id"] = bench_id
    aggregated["mode"] = spec.mode
    aggregated["days"] = spec.days
    aggregated["seeds"] = spec.seeds
    aggregated["artifact_hashes"] = artifact_hashes()

    with (bench_dir / "episodes.jsonl").open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    (bench_dir / "aggregate.json").write_text(
        json.dumps(aggregated, ensure_ascii=False, indent=2), encoding="utf-8")

    disc = None
    if spec.mode == "replay" and {"good", "poor"} <= set(spec.groups):
        disc = compute_discriminability(results, cfg.eval)
        (bench_dir / "discriminability.json").write_text(
            json.dumps(disc, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"bench_id": bench_id, "bench_dir": str(bench_dir),
            "aggregate": aggregated, "discriminability": disc, "episodes": results}


def default_concurrency() -> int:
    try:
        return int(load_llm_runtime().get("concurrency", 4))
    except Exception:  # noqa: BLE001 — 配置缺失时退回默认
        return 4
