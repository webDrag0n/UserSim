"""命令行入口：python -m usersim run / bench / eval / continue / serve / agent

replay 模式已下线：run/bench 只跑 live（真实 LLM 经 agent 接口接入）。
"""

from __future__ import annotations

import argparse
from pathlib import Path

from usersim.config import PROJECT_ROOT, load_system_config
from usersim.evaluator.report import evaluate_run, format_summary
from usersim.runner import run_live


def _run_live_demo(seed: int, days: int, cfg, out_root: Path, *,
                   archetype=None, harness=None, user_impl=None, resume_dir=None,
                   extra_days=0, run_id=None) -> Path:
    """live + demo agent：预生成 run_id，spawn demo 回环线程，跑 episode。

    demo agent 与外部 agent 走同一 HTTP 协议（ASGI 回环，不开端口）；
    外部接入（OpenClaw、Hermes 等）请用 serve + python -m usersim agent。
    """
    from datetime import datetime, timezone

    from usersim.agents import prompt_versions
    from usersim.agents.client import spawn_demo_agents
    from usersim.agents.config import default_impl
    from usersim.gateway import BROKER

    # 未指定时解析 profiles 默认实现，并显式记入 meta（可复现性凭证）
    harness = harness or default_impl("assistant")
    user_impl = user_impl or default_impl("user")
    if resume_dir is not None:
        run_id = resume_dir.name
    run_id = run_id or f"live_{seed}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    stop, _threads = spawn_demo_agents(
        broker=BROKER, harness_name=harness, user_impl=user_impl, run_id=run_id,
        log_dir=out_root / run_id)
    try:
        return run_live(seed=seed, days=days, cfg=cfg, out_root=out_root,
                        archetype=archetype, resume_dir=resume_dir, extra_days=extra_days,
                        run_id=run_id, harness=harness, broker=BROKER, attach="demo",
                        prompt_versions=prompt_versions(),
                        profiles={"user": user_impl, "assistant": harness})
    finally:
        stop.set()


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
    from usersim.bench import BenchSpec, estimate_tokens, run_suite
    from usersim.world.catalog import PROFESSIONS

    seeds = _parse_seeds(args.seeds)
    if args.groups:
        groups = [g.strip() for g in args.groups.split(",") if g.strip()]
    else:
        # 默认锚点对：reference（好锚点）vs stub（失能下界）→ 自动附带量程守护
        groups = ["reference", "stub"]

    if args.archetypes == "all":
        archetypes: list = [p["archetype"] for p in PROFESSIONS]
    elif args.archetypes:
        archetypes = [a.strip() for a in args.archetypes.split(",") if a.strip()]
    else:
        archetypes = [None]

    spec = BenchSpec(
        seeds=seeds, days=args.days, groups=groups,
        archetypes=archetypes,
        concurrency=args.concurrency,  # None = 全部 episode 同时启动（LLM 侧另有信号量限流）
    )
    episodes = spec.episodes()
    print(f"批量规模：{len(episodes)} episodes = {len(groups)} 组 × {len(archetypes)} 职业 × {len(seeds)} seeds"
          f"，每个 {args.days} 天")
    est = estimate_tokens(spec)
    print(f"⚠️  批量为 live 模式，预估消耗 ≈ {est:,} tokens")
    if args.max_episodes is None:
        print("   需显式指定 --max-episodes 以确认成本。已中止。")
        return
    if len(episodes) > args.max_episodes:
        print(f"   episode 数 {len(episodes)} 超过 --max-episodes {args.max_episodes}。已中止。")
        return

    def on_progress(done: int, total: int, last: dict) -> None:
        m = last["metrics"]
        ess = m.get("ess")
        print(f"  [{done}/{total}] {last['label']:<38} verdict={m.get('verdict'):<12} "
              f"ess={ess:.4f}" if isinstance(ess, float) else f"  [{done}/{total}] {last['label']}")

    result = run_suite(spec, bench_id=args.bench_id, on_progress=on_progress)
    print()
    print(_format_bench(result))
    print(f"\n产物：{result['bench_dir']}")


def _format_bench(result: dict) -> str:
    lines = ["=" * 72, f"批量聚合 · {result['bench_id']}", "=" * 72]
    for name, g in result["aggregate"]["groups"].items():
        cv = (g["metrics"].get("contract_violations") or {}).get("mean")
        cv_s = f"  违约={cv:.1f}" if cv is not None else ""
        lines.append(f"\n[{name}]  n={g['n']}  判定众数={g['verdict_mode']}  "
                     f"占比={g['verdict_share']}  从未回带={g['never_settled']}{cv_s}")
        for key in ("ess", "in_band_ratio", "est_err_final", "est_err_slope_per_day",
                    "health_score", "benchmark_score"):
            s = g["metrics"].get(key) or {}
            if s.get("mean") is None:
                continue
            ci = f" ±{s['ci95']:.4f}" if s.get("ci95") is not None else ""
            lines.append(f"    {key:<24} {s['mean']:.4f}{ci}   (n={s['n']})")
    disc = result.get("discriminability")
    if disc and disc.get("mode") == "positive_control":
        # 仅阳性对照（无 stub 锚点）：好锚点自身不健康 = 疑世界侧/管线回归
        mark = "✅ 通过" if disc["ok"] else "❌ 未通过（疑世界侧/管线回归，本 bench 分数不可信）"
        med = disc.get("ess_good_median")
        med_s = f"{med:.4f}" if isinstance(med, (int, float)) else "—"
        lines += ["", "-" * 72, f"阳性对照（{disc['groups']['good']} 自检）：{mark}",
                  f"    ess 中位数={med_s}（阈值 diverged_ess_min={disc['thresholds']['diverged_ess_min']}）"
                  f"  全员 diverged={disc.get('all_diverged')}"]
    elif disc:
        def _num(v, spec: str) -> str:
            # n<2 时 separation/margin 为 None（单 seed 冒烟等场景），显示 — 而非崩
            return format(v, spec) if isinstance(v, (int, float)) else "—"

        groups = disc.get("groups") or {"good": "good", "poor": "poor"}
        status = disc.get("status") or ("ok" if disc["ok"] else "fail")
        mark = {"ok": "✅ 通过", "borderline": "⚠️ 通过（边缘：ess 均值±SEM 跨阈）", "fail": "❌ 未通过"}[status]
        lines += ["", "-" * 72, f"量程守护（{groups['good']} vs {groups['poor']}）：{mark}"]
        lines.append(f"    ess {groups['good']}={_num(disc['ess_good_mean'], '.4f')}  "
                     f"{groups['poor']}={_num(disc['ess_poor_mean'], '.4f')}")
        lines.append(f"    margin_good={_num(disc['margin_good'], '+.4f')}  "
                     f"margin_poor={_num(disc['margin_poor'], '+.4f')}  "
                     f"separation={_num(disc['separation'], '.2f')}")
        cstat = disc.get("check_status") or {}
        for k, v in disc["checks"].items():
            st = cstat.get(k.replace("_positive", "").replace("_large", ""))
            sym = "⚠" if st == "borderline" else ("✓" if v else "✗")
            lines.append(f"    {sym} {k}")
    integ = (result.get("aggregate") or {}).get("integrity")
    if integ and not integ.get("ok", True):
        # 跨组 turns.jsonl 逐字节相同：疑"输出被复制"回归，本 bench 结果不可信
        lines += ["", "!" * 72,
                  f"🚨 完整性告警：{len(integ['duplicates'])} 对跨组 episode 的 turns.jsonl 逐字节相同"
                  "（疑跨组输出被复制，分数不可信）", "!" * 72]
        for d in integ["duplicates"]:
            lines.append(f"    {d['group_a']}/seed{d['seed_a']}  ≡  {d['group_b']}/seed{d['seed_b']}")
    mde = (result.get("aggregate") or {}).get("mde")
    if disc and mde:
        # 锚点对的统计效力：主 KPI 最小可检测均值差/方差比
        groups = disc.get("groups") or {"good": "good", "poor": "poor"}
        pair = next((p for p in mde.get("pairs", [])
                     if {p["a"], p["b"]} == {groups["good"], groups["poor"]}), None)
        bs = (pair or {}).get("metrics", {}).get("benchmark_score") or {}
        if bs.get("mde_mean") is not None:
            lines.append(f"    MDE（{groups['good']} vs {groups['poor']}，benchmark）："
                         f"均值差 ≥{bs['mde_mean']:.1f} · 方差比 ≥{bs['mde_var_ratio']:.1f}"
                         f"（α={mde['alpha']}，power={mde['power']}）")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(prog="usersim", description="UserSim · 长程用户-助手模拟与 Benchmark")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="运行模拟（live：真实 LLM 经 agent 接口接入）")
    p_run.add_argument("--seed", type=int, default=None, help="覆盖配置中的 seed")
    p_run.add_argument("--days", type=int, default=None, help="覆盖配置中的天数")
    p_run.add_argument("--episodes", type=int, default=None)
    p_run.add_argument("--archetype", default=None, help="指定职业（收入随之改变）")
    p_run.add_argument("--harness", default=None, help="被测助手实现名（profiles/ 文件名，默认取 config.toml 的 default）")
    p_run.add_argument("--user-impl", default=None, help="demo 用户实现名（profiles/ 文件名，默认取 config.toml 的 default）")

    p_bench = sub.add_parser("bench", help="多 seed 批量评测（带置信区间；live，需 --max-episodes 确认成本）")
    p_bench.add_argument("--seeds", default="1-8", help="种子范围，如 1-20 或 1,4,7")
    p_bench.add_argument("--days", type=int, default=30)
    p_bench.add_argument("--groups", default=None,
                         help="harness 名列表（profiles/ 文件名），默认 reference,stub（锚点对，附带量程守护）")
    p_bench.add_argument("--archetypes", default=None, help="职业列表，或 all（默认 auto=由 seed 决定）")
    p_bench.add_argument("--concurrency", type=int, default=None,
                         help="episode 并发数（默认=全部组合同时启动；LLM 限流见 llm.toml [runtime].concurrency）")
    p_bench.add_argument("--bench-id", default=None,
                         help="复用已有 bench 目录（断点续跑：已有 report.json 的 episode 自动跳过）")
    p_bench.add_argument("--max-episodes", type=int, default=None, help="显式 episode 上限（确认成本，硬上限 20）")

    p_eval = sub.add_parser("eval", help="对既有 run 离线重算指标")
    p_eval.add_argument("run_dir", type=Path)

    p_cont = sub.add_parser("continue", help="续跑既有 run（追加天数）")
    p_cont.add_argument("run_dir", type=Path)
    p_cont.add_argument("--extra-days", type=int, default=10)

    sub.add_parser("serve", help="启动 FastAPI 后端（托管 web/dist + agent 接入端点）")

    p_agent = sub.add_parser("agent", help="以 demo agent 身份接入运行中的 server（与外部 agent 同一路径）")
    p_agent.add_argument("role", choices=["user", "assistant"], help="接入角色")
    p_agent.add_argument("--server", default=None, help="server 地址（默认 http://127.0.0.1:8610）")
    p_agent.add_argument("--harness", default=None, help="demo 助手所用实现名（仅 role=assistant；默认取 config.toml 的 default）")
    p_agent.add_argument("--impl", default=None, help="demo 用户所用实现名（仅 role=user；默认取 config.toml 的 default）")

    args = parser.parse_args()
    cfg = load_system_config()

    if args.cmd == "serve":
        import os
        import uvicorn
        port = int(os.environ.get("USERSIM_PORT", cfg.server.port))
        uvicorn.run("usersim.server.app:app", host=str(cfg.server.host), port=port)
        return

    if args.cmd == "agent":
        from usersim.agents.__main__ import serve_agent

        serve_agent(args.role, server=args.server, harness=args.harness, impl=args.impl)
        return

    if args.cmd == "run":
        seed = args.seed if args.seed is not None else int(cfg.run.seed)
        days = args.days if args.days is not None else int(cfg.run.days)
        episodes = args.episodes if args.episodes is not None else int(cfg.run.episodes)
        out_root = PROJECT_ROOT / str(cfg.run.out_dir)
        for ep in range(episodes):
            run_dir = _run_live_demo(seed=seed + ep, days=days, cfg=cfg, out_root=out_root,
                                     archetype=args.archetype, harness=args.harness,
                                     user_impl=args.user_impl)
            report = evaluate_run(run_dir, cfg)
            print(format_summary(report))
            print()
    elif args.cmd == "continue":
        import json as _json
        meta = _json.loads((args.run_dir / "meta.json").read_text(encoding="utf-8"))
        if meta.get("mode") != "live":
            raise SystemExit(
                "该存档是已下线的 replay 模式（R4 起仅支持 live 续跑）。"
                "可继续用 eval / 前端回放查看，但不能追加天数。")
        h = meta.get("harness") or "reference"
        if h == "external":
            raise SystemExit("该 run 的助手为外部接入：请用 serve + python -m usersim agent 续跑")
        harness_name = h.split(":", 1)[1] if ":" in h else h
        run_dir = _run_live_demo(seed=meta["seed"], days=meta["days"] + args.extra_days, cfg=cfg,
                                 out_root=args.run_dir.parent, resume_dir=args.run_dir,
                                 extra_days=args.extra_days, harness=harness_name,
                                 user_impl=(meta.get("profiles") or {}).get("user"))
        report = evaluate_run(run_dir, cfg)
        print(format_summary(report))
    elif args.cmd == "bench":
        _cmd_bench(args, cfg)
    elif args.cmd == "eval":
        report = evaluate_run(args.run_dir, cfg)
        print(format_summary(report))


if __name__ == "__main__":
    main()
