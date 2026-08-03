"""命令行入口：python -m usersim run / eval"""

from __future__ import annotations

import argparse
from pathlib import Path

from usersim.config import PROJECT_ROOT, load_system_config
from usersim.evaluator.report import evaluate_run, format_summary
from usersim.runner import run_live, run_replay


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
                run_dir = run_live(seed=seed + ep, days=days, cfg=cfg, out_root=out_root, archetype=args.archetype)
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
                               out_root=args.run_dir.parent, resume_dir=args.run_dir, extra_days=args.extra_days)
        else:
            run_dir = run_replay(seed=meta["seed"], days=meta["days"] + args.extra_days,
                                 quality=meta.get("assistant_quality") or "good", cfg=cfg,
                                 out_root=args.run_dir.parent, resume_dir=args.run_dir, extra_days=args.extra_days)
        report = evaluate_run(run_dir, cfg)
        print(format_summary(report))
    elif args.cmd == "eval":
        report = evaluate_run(args.run_dir, cfg)
        print(format_summary(report))


if __name__ == "__main__":
    main()
