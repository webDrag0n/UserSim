"""批量 episode 执行器（组装点：允许 import world/agents/evaluator）。

replay 模式已下线：批量只跑 live（真实 LLM），按预算限制 episode 数。
episode 默认全并发（未显式指定 concurrency 时 = 本次全部组合数，线程池
同时启动）；provider 侧由 llm/client.py 的进程级信号量按 llm.toml
[runtime].concurrency 限流，chat_json 的指数退避重试兜底。
断点续跑：run 目录下已有 report.json 的 episode 直接复用存档重评估，
不重复烧 token。
"""

from __future__ import annotations

import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from usersim.bench.aggregate import METRIC_KEYS
from usersim.bench.aggregate import aggregate as aggregate_episodes
from usersim.bench.discriminability import compute as compute_discriminability
from usersim.config import PROJECT_ROOT, artifact_hashes, load_system_config
from usersim.evaluator.report import evaluate_run

# live 批量硬上限（防止一条命令烧掉大量 token）
LIVE_EPISODE_HARD_CAP = 20
# 单 episode 的粗略 token 估算（10 天 live 实测量级，用于成本提示）
TOKENS_PER_DAY_ESTIMATE = 12_000

# 量程守护锚点：groups 含 reference（好锚点/阳性对照）即自动计算分辨力；
# 同时含 stub（失能下界）时走全套锚点对校验，否则仅阳性对照校验
GUARD_GOOD_GROUP = "reference"
GUARD_POOR_GROUP = "stub"


@dataclass
class EpisodeSpec:
    seed: int
    days: int
    group: str                      # 分组键 = 被测 harness 名（profiles/ 文件名）
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
    groups: list[str]                       # harness 名列表
    archetypes: list[str | None] = field(default_factory=lambda: [None])
    concurrency: int | None = None        # episode 并发数；None = 全部组合同时启动

    def episodes(self) -> list[EpisodeSpec]:
        out: list[EpisodeSpec] = []
        for g in self.groups:
            for arch in self.archetypes:
                for s in self.seeds:
                    out.append(EpisodeSpec(
                        seed=s, days=self.days, group=g, harness=g, archetype=arch,
                    ))
        return out


def _run_one(spec: EpisodeSpec, out_root_str: str) -> dict:
    """跑一个 episode 并返回其指标。

    断点续跑：run 目录已有 report.json（世界循环完整跑完）时跳过 live，
    直接复用存档重评估——重跑 bench 不重复烧已完成 episode 的 token。
    """
    from usersim.cli import _run_live_demo

    cfg = load_system_config()
    out_root = Path(out_root_str)
    run_id = f"{spec.group}_{spec.archetype or 'auto'}_{spec.seed}".replace(" ", "")
    run_dir = out_root / run_id
    if not (run_dir / "report.json").exists():
        run_dir = _run_live_demo(seed=spec.seed, days=spec.days, cfg=cfg, out_root=out_root,
                                 archetype=spec.archetype, harness=spec.harness, run_id=run_id)
    report = evaluate_run(run_dir, cfg)
    insights_path = run_dir / "insights.json"
    health = None
    if insights_path.exists():
        health = json.loads(insights_path.read_text(encoding="utf-8")).get("health_score")
    metrics = {k: report.get(k) for k in METRIC_KEYS if k in report}
    metrics["verdict"] = report.get("verdict")
    metrics["health_score"] = health
    # benchmark 总分不在 report 顶层，单独抽取（旧存档无该字段则为 None，聚合时跳过）
    metrics["benchmark_score"] = (report.get("benchmark") or {}).get("score")
    return {
        "group": spec.group, "seed": spec.seed, "archetype": spec.archetype,
        "label": spec.label, "run_id": run_dir.name, "metrics": metrics,
    }


def estimate_tokens(spec: BenchSpec) -> int:
    return len(spec.episodes()) * spec.days * TOKENS_PER_DAY_ESTIMATE


def check_turns_integrity(episodes: list[dict], runs_root: Path) -> dict:
    """跨组 turns.jsonl 哈希比对：不同组 episode 逐字节相同 = 输出被复制的回归信号。

    真实事故：nomem 与 pro 两组 116 条 turn 逐字节相同。对 ok 的 episode 算
    turns.jsonl 的 sha256，按哈希分组，同一哈希跨组出现即记 duplicates。
    turns.jsonl 缺失的 episode 跳过并记 note。
    """
    by_hash: dict[str, list[dict]] = {}
    notes: list[str] = []
    for ep in episodes:
        run_id = ep.get("run_id")
        path = (runs_root / run_id / "turns.jsonl") if run_id else None
        if path is None or not path.exists():
            notes.append(f"{ep.get('label', run_id)}: turns.jsonl 缺失，跳过完整性比对")
            continue
        h = hashlib.sha256(path.read_bytes()).hexdigest()
        by_hash.setdefault(h, []).append(ep)
    duplicates: list[dict] = []
    for eps in by_hash.values():
        eps = sorted(eps, key=lambda e: (e["group"], e["seed"]))
        for i, a in enumerate(eps):
            for b in eps[i + 1:]:
                if a["group"] != b["group"]:
                    duplicates.append({"group_a": a["group"], "seed_a": a["seed"],
                                       "group_b": b["group"], "seed_b": b["seed"]})
    out: dict = {"ok": not duplicates}
    if duplicates:
        out["duplicates"] = duplicates
    if notes:
        out["notes"] = notes
    return out


def run_suite(spec: BenchSpec, out_root: Path | None = None,
              bench_id: str | None = None, on_progress=None) -> dict:
    """执行批量并落盘 episodes.jsonl / aggregate.json / discriminability.json。"""
    cfg = load_system_config()
    episodes = spec.episodes()

    bench_id = bench_id or f"bench_live_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    root = out_root or (PROJECT_ROOT / "runs" / "_bench")
    bench_dir = root / bench_id
    (bench_dir / "runs").mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    ep_root = str(bench_dir / "runs")
    ep_path = bench_dir / "episodes.jsonl"

    # 断点续跑：已有非 error 记录的 episode 直接复用旧记录，不重跑也不重复写
    done_keys: set[tuple] = set()
    if ep_path.exists():
        for line in ep_path.read_text(encoding="utf-8").splitlines():
            try:
                old = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not old.get("error"):
                done_keys.add((old.get("group"), str(old.get("archetype")), old.get("seed")))
    todo = [ep for ep in episodes
            if (ep.group, str(ep.archetype), ep.seed) not in done_keys]

    # 成本闸门只计实际要烧 token 的 todo（续跑/重评估的 episode 零成本，
    # 不应把已完成的存量算进上限——否则补种子会被存量挤爆硬上限）
    if len(todo) > LIVE_EPISODE_HARD_CAP:
        raise ValueError(
            f"待跑 episode 数 {len(todo)} 超过上限 {LIVE_EPISODE_HARD_CAP}"
            f"（预估 {len(todo) * spec.days * TOKENS_PER_DAY_ESTIMATE:,} tokens）。"
            f"请减少 seeds/archetypes，或分批多次运行后复用同一 bench-id 续跑合并。"
        )

    for ep in episodes:
        key = (ep.group, str(ep.archetype), ep.seed)
        if key in done_keys:
            for line in ep_path.read_text(encoding="utf-8").splitlines():
                old = json.loads(line)
                if (old.get("group"), str(old.get("archetype")), old.get("seed")) == key \
                        and not old.get("error"):
                    results.append(old)
                    break

    # episode 并发：broker 按 (run_id, role) 键控且带锁，server 原生支持多 run
    # 并行；未显式指定时默认全并发（全部组合同时启动），LLM 侧由 llm/client.py
    # 进程级信号量按 llm.toml [runtime].concurrency 限流，指数退避重试兜底。
    # episodes.jsonl 逐条落盘（写锁保护）：批量跑十几小时，攒到最后才写 =
    # 中途崩溃全丢；单 episode 失败记 error 条目继续跑，不拖死整批。
    write_lock = threading.Lock()
    workers = max(1, spec.concurrency or len(episodes))
    done = len(results)

    def _guarded(ep: EpisodeSpec) -> dict:
        nonlocal done
        try:
            rec = _run_one(ep, ep_root)
        except Exception as e:  # noqa: BLE001 — 单点失败不中断批量
            rec = {"group": ep.group, "seed": ep.seed, "archetype": ep.archetype,
                   "label": ep.label, "run_id": None, "metrics": {},
                   "error": f"{type(e).__name__}: {e}"}
        with write_lock:
            results.append(rec)
            with ep_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            done += 1
            if on_progress:
                on_progress(done, len(episodes), rec)
        return rec

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(_guarded, todo))
    else:
        for ep in todo:
            _guarded(ep)

    results.sort(key=lambda r: (r["group"], str(r["archetype"]), r["seed"]))
    ok_results = [r for r in results if not r.get("error")]
    aggregated = aggregate_episodes(ok_results)
    aggregated["bench_id"] = bench_id
    aggregated["mode"] = "live"
    aggregated["days"] = spec.days
    aggregated["seeds"] = spec.seeds
    aggregated["artifact_hashes"] = artifact_hashes()
    aggregated["failed_episodes"] = len(results) - len(ok_results)
    aggregated["integrity"] = check_turns_integrity(ok_results, bench_dir / "runs")

    (bench_dir / "aggregate.json").write_text(
        json.dumps(aggregated, ensure_ascii=False, indent=2), encoding="utf-8")

    disc = None
    if GUARD_GOOD_GROUP in set(spec.groups):
        disc = compute_discriminability(ok_results, cfg.eval,
                                        good_group=GUARD_GOOD_GROUP,
                                        poor_group=GUARD_POOR_GROUP)
        (bench_dir / "discriminability.json").write_text(
            json.dumps(disc, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"bench_id": bench_id, "bench_dir": str(bench_dir),
            "aggregate": aggregated, "discriminability": disc, "episodes": results}
