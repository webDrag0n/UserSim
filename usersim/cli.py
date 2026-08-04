"""命令行入口：python -m usersim run / eval"""

from __future__ import annotations

import argparse
from pathlib import Path

from usersim.config import PROJECT_ROOT, load_system_config
from usersim.evaluator.report import evaluate_run, format_summary
from usersim.runner import run_live, run_replay


def _parse_seeds(text: str) -> list[int]:
    """'1-8' 或 '1,4,7' 或 '1-4,9' → seed 列表。"""
    out: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            out.extend(range(int(lo), int(hi) + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def _cmd_bench(args, cfg) -> None:
    from usersim.bench import BenchSpec, default_concurrency, estimate_tokens, run_suite
    from usersim.world.catalog import PROFESSIONS

    seeds = _parse_seeds(args.seeds)
    if args.groups:
        groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    else:
        groups = ["good", "mid", "poor"] if args.mode == "replay" else ["reference"]

    if args.archetypes == "all":
        archetypes: list = [p["archetype"] for p in PROFESSIONS]
    elif args.archetypes:
        archetypes = [a.strip() for a in args.archetypes.split(",") if a.strip()]
    else:
        archetypes = [None]

    spec = BenchSpec(
        seeds=seeds, days=args.days, mode=args.mode, groups=groups,
        archetypes=archetypes,
        concurrency=args.concurrency or default_concurrency(),
    )
    episodes = spec.episodes()
    print(f"批量规模：{len(episodes)} episodes = {len(groups)} 组 × {len(archetypes)} 职业 × {len(seeds)} seeds"
          f"，每个 {args.days} 天")
    if args.mode == "live":
        est = estimate_tokens(spec)
        print(f"⚠️  live 模式预估消耗 ≈ {est:,} tokens")
        if args.max_episodes is None:
            print("   live 批量需显式指定 --max-episodes 以确认成本。已中止。")
            return
        if len(episodes) > args.max_episodes:
            print(f"   episode 数 {len(episodes)} 超过 --max-episodes {args.max_episodes}。已中止。")
            return

    def on_progress(done: int, total: int, last: dict) -> None:
        m = last["metrics"]
        ess = m.get("ess")
        print(f"  [{done}/{total}] {last['label']:<38} verdict={m.get('verdict'):<12} "
              f"ess={ess:.4f}" if isinstance(ess, float) else f"  [{done}/{total}] {last['label']}")

    result = run_suite(spec, on_progress=on_progress)
    print()
    print(_format_bench(result))
    print(f"\n产物：{result['bench_dir']}")


def _format_bench(result: dict) -> str:
    lines = ["=" * 72, f"批量聚合 · {result['bench_id']}", "=" * 72]
    for name, g in result["aggregate"]["groups"].items():
        lines.append(f"\n[{name}]  n={g['n']}  判定众数={g['verdict_mode']}  "
                     f"占比={g['verdict_share']}  从未回带={g['never_settled']}")
        for key in ("ess", "in_band_ratio", "est_err_final", "est_err_slope_per_day", "health_score"):
            s = g["metrics"].get(key) or {}
            if s.get("mean") is None:
                continue
            ci = f" ±{s['ci95']:.4f}" if s.get("ci95") is not None else ""
            lines.append(f"    {key:<24} {s['mean']:.4f}{ci}   (n={s['n']})")
    disc = result.get("discriminability")
    if disc:
        mark = "✅ 通过" if disc["ok"] else "❌ 未通过"
        lines += ["", "-" * 72, f"量程守护：{mark}"]
        lines.append(f"    ess good={disc['ess_good_mean']:.4f}  poor={disc['ess_poor_mean']:.4f}")
        lines.append(f"    margin_good={disc['margin_good']:+.4f}  margin_poor={disc['margin_poor']:+.4f}"
                     f"  separation={disc['separation']:.2f}")
        for k, v in disc["checks"].items():
            lines.append(f"    {'✓' if v else '✗'} {k}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(prog="usersim", description="UserSim · 长程用户-助手模拟与 Benchmark")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="运行模拟")
    p_run.add_argument("--mode", default="replay", choices=["replay", "live"], help="replay=规则回放(0 LLM)；live=真实 LLM")
    p_run.add_argument("--seed", type=int, default=None, help="覆盖配置中的 seed")
    p_run.add_argument("--days", type=int, default=None, help="覆盖配置中的天数")
    p_run.add_argument("--quality", default=None, choices=["good", "mid", "poor"], help="回放助手档位（仅 replay）")
    p_run.add_argument("--episodes", type=int, default=None)
    p_run.add_argument("--archetype", default=None, help="指定职业（收入随之改变）")
    p_run.add_argument("--harness", default=None, help="被测 Harness 名（仅 live；默认 reference）")

    p_bench = sub.add_parser("bench", help="多 seed 批量评测（带置信区间）")
    p_bench.add_argument("--seeds", default="1-8", help="种子范围，如 1-20 或 1,4,7")
    p_bench.add_argument("--days", type=int, default=30)
    p_bench.add_argument("--mode", default="replay", choices=["replay", "live"])
    p_bench.add_argument("--groups", default=None,
                         help="replay: good,mid,poor（默认三档）；live: harness 名列表（默认 reference）")
    p_bench.add_argument("--archetypes", default=None, help="职业列表，或 all（默认 auto=由 seed 决定）")
    p_bench.add_argument("--concurrency", type=int, default=None)
    p_bench.add_argument("--max-episodes", type=int, default=None, help="live 模式的显式 episode 上限")

    p_eval = sub.add_parser("eval", help="对既有 run 离线重算指标")
    p_eval.add_argument("run_dir", type=Path)

    p_cont = sub.add_parser("continue", help="续跑既有 run（追加天数）")
    p_cont.add_argument("run_dir", type=Path)
    p_cont.add_argument("--extra-days", type=int, default=10)

    sub.add_parser("serve", help="启动 FastAPI 后端（托管 web/dist）")

    args = parser.parse_args()
    cfg = load_system_config()

    if args.cmd == "serve":
        import os
        import uvicorn
        port = int(os.environ.get("USERSIM_PORT", cfg.server.port))
        uvicorn.run("usersim.server.app:app", host=str(cfg.server.host), port=port)
        return

    if args.cmd == "run":
        seed = args.seed if args.seed is not None else int(cfg.run.seed)
        days = args.days if args.days is not None else int(cfg.run.days)
        quality = args.quality or str(cfg.run.assistant_quality)
        episodes = args.episodes if args.episodes is not None else int(cfg.run.episodes)
        out_root = PROJECT_ROOT / str(cfg.run.out_dir)
        for ep in range(episodes):
            if args.mode == "live":
                run_dir = run_live(seed=seed + ep, days=days, cfg=cfg, out_root=out_root,
                                   archetype=args.archetype, harness=args.harness)
            else:
                run_dir = run_replay(seed=seed + ep, days=days, quality=quality, cfg=cfg, out_root=out_root, archetype=args.archetype)
            report = evaluate_run(run_dir, cfg)
            print(format_summary(report))
            print()
    elif args.cmd == "continue":
        import json as _json
        meta = _json.loads((args.run_dir / "meta.json").read_text(encoding="utf-8"))
        if meta.get("mode") == "live":
            run_dir = run_live(seed=meta["seed"], days=meta["days"] + args.extra_days, cfg=cfg,
                               out_root=args.run_dir.parent, resume_dir=args.run_dir, extra_days=args.extra_days,
                               harness=meta.get("harness"))
        else:
            run_dir = run_replay(seed=meta["seed"], days=meta["days"] + args.extra_days,
                                 quality=meta.get("assistant_quality") or "good", cfg=cfg,
                                 out_root=args.run_dir.parent, resume_dir=args.run_dir, extra_days=args.extra_days)
        report = evaluate_run(run_dir, cfg)
        print(format_summary(report))
    elif args.cmd == "bench":
        _cmd_bench(args, cfg)
    elif args.cmd == "eval":
        report = evaluate_run(args.run_dir, cfg)
        print(format_summary(report))


if __name__ == "__main__":
    main()
