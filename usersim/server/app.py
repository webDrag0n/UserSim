"""FastAPI 后端：运行控制 + 实时推送 + 报告 + 静态托管。

运行模型：每个 run 在后台线程执行（Runner 同步、LLM 调用阻塞），
on_event 回调通过 loop.call_soon_threadsafe 广播给 WebSocket 订阅者。
"""

from __future__ import annotations

import asyncio
import json
import threading
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from usersim.agents import prompt_versions

from usersim.config import PROJECT_ROOT, load_system_config
from usersim.evaluator.report import evaluate_run
from usersim.gateway import BROKER, create_agent_router
from usersim.runner import run_live

app = FastAPI(title="UserSim Server")
app.include_router(create_agent_router(BROKER))  # agent 接入端点（demo 回环与外部 agent 共用）
cfg = load_system_config()
OUT_ROOT = PROJECT_ROOT / str(cfg.run.out_dir)


# ---------------------------------------------------------------
# Run 管理
# ---------------------------------------------------------------


class RunHandle:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.status = "running"  # running | finished | failed
        self.error: str | None = None
        self.run_dir: Path | None = None
        self.progress = {"slot": 0, "total": 0}
        self.subscribers: list[asyncio.Queue] = []
        self.thread: threading.Thread | None = None


RUNS: dict[str, RunHandle] = {}
MAIN_LOOP: asyncio.AbstractEventLoop | None = None


@app.on_event("startup")
async def _startup() -> None:
    global MAIN_LOOP
    MAIN_LOOP = asyncio.get_running_loop()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)


def _broadcast(handle: RunHandle, event: dict) -> None:
    if MAIN_LOOP is None:
        return

    def _put() -> None:
        for q in list(handle.subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass

    MAIN_LOOP.call_soon_threadsafe(_put)


def _execute(handle: RunHandle, seed: int, days: int,
             archetype: str | None = None, resume_dir: Path | None = None, extra_days: int = 0,
             harness: str | None = None, user_impl: str | None = None,
             user_agent: str = "demo",
             assistant_agent: str = "demo") -> None:
    def on_event(ev: dict) -> None:
        if ev["type"] == "slot":
            handle.progress["slot"] = ev["data"]["t_logical"] + 1
        _broadcast(handle, ev)

    stop = None
    try:
        # demo 角色：在本进程 spawn demo agent 线程（与外部 agent 同一 HTTP 协议的回环）
        # 未指定实现时解析 profiles 默认值，显式记入 meta（可复现性凭证）
        from usersim.agents.config import default_impl

        harness_name = harness or default_impl("assistant")
        impl_name = user_impl or default_impl("user")
        profiles = {
            "user": impl_name if user_agent == "demo" else "external",
            "assistant": harness_name if assistant_agent == "demo" else "external",
        }
        roles = tuple(r for r, m in (("user", user_agent), ("assistant", assistant_agent))
                      if m == "demo")
        if roles:
            from usersim.agents.client import spawn_demo_agents

            stop, _threads = spawn_demo_agents(
                broker=BROKER, harness_name=harness_name, user_impl=impl_name,
                run_id=handle.run_id,
                log_dir=OUT_ROOT / handle.run_id, roles=roles)
        run_dir = run_live(seed=seed, days=days, cfg=cfg, out_root=OUT_ROOT, on_event=on_event,
                           archetype=archetype, resume_dir=resume_dir, extra_days=extra_days,
                           run_id=handle.run_id, harness=harness_name, broker=BROKER,
                           attach="demo" if assistant_agent == "demo" else "external",
                           prompt_versions=prompt_versions(), profiles=profiles)
        handle.run_dir = run_dir
        report = evaluate_run(run_dir, cfg)
        handle.status = "finished"
        _broadcast(handle, {"type": "done", "data": {"run_id": run_dir.name, "verdict": report["verdict"]}})
    except Exception as e:  # noqa: BLE001
        handle.status = "failed"
        handle.error = str(e)
        _broadcast(handle, {"type": "error", "data": {"error": str(e)}})
    finally:
        if stop is not None:
            stop.set()


class StartRunRequest(BaseModel):
    # replay 模式已下线：启动即 live（真实 LLM 经 agent 接口接入）
    seed: int | None = None
    days: int | None = None
    archetype: str | None = None
    harness: str | None = None  # 被测助手实现（assistant_agent=demo 时；profiles/ 文件名）
    user_impl: str | None = None   # demo 用户实现（profiles/ 文件名，默认 config 的 default）
    user_agent: str = "demo"       # demo=服务端起回环 demo；external=等待外部 agent 轮询接入
    assistant_agent: str = "demo"  # 同上（OpenClaw、Hermes 等经 /api/agent/* 接入）


@app.post("/api/runs")
def start_run(req: StartRunRequest) -> dict:
    seed = req.seed if req.seed is not None else int(cfg.run.seed)
    days = req.days if req.days is not None else int(cfg.run.days)
    # run_id 前置生成：启动即可见、可进入实时观看
    from datetime import datetime, timezone
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    run_id = f"live_{seed}_{ts}"
    handle = RunHandle(run_id)
    handle.progress["total"] = days * int(cfg.clock.slots_per_day)
    RUNS[run_id] = handle

    def _wrap() -> None:
        _execute(handle, seed, days, archetype=req.archetype,
                 harness=req.harness, user_impl=req.user_impl, user_agent=req.user_agent,
                 assistant_agent=req.assistant_agent)

    handle.thread = threading.Thread(target=_wrap, daemon=True)
    handle.thread.start()
    return {"started": True, "run_id": run_id, "seed": seed, "days": days, "mode": "live"}


@app.get("/api/harnesses")
def list_harnesses() -> dict:
    """可选被测助手实现清单（前端启动表单的下拉数据源）。"""
    from usersim.agents.registry import available, default_name

    return {"items": available(), "default": default_name()}


@app.get("/api/user-impls")
def list_user_impls() -> dict:
    """可选 demo 用户实现清单。"""
    from usersim.agents.config import default_impl, list_impls

    return {"items": [{"name": n,
                       "type": str(s.get("type", "?")),
                       "doc": str(s.get("description", ""))}
                      for n, s in sorted(list_impls("user").items())],
            "default": default_impl("user")}


# ---------------------------------------------------------------
# Bench：多 seed 批量与置信区间
# ---------------------------------------------------------------

BENCH_ROOT = OUT_ROOT / "_bench"
BENCH_JOBS: dict[str, dict] = {}


class StartBenchRequest(BaseModel):
    seeds: str = "1-8"
    days: int = 30
    # replay 模式已下线：批量恒为 live；groups = harness 名列表
    groups: list[str] | None = None
    archetypes: list[str] | None = None
    max_episodes: int | None = None
    concurrency: int | None = None   # episode 并发数（默认取 llm.toml）
    bench_id: str | None = None      # 复用已有 bench 目录断点续跑（补种子/重评估）


@app.post("/api/bench")
def start_bench(req: StartBenchRequest) -> dict:
    from usersim.bench import BenchSpec, default_concurrency, estimate_tokens, run_suite
    from usersim.cli import _parse_seeds

    seeds = _parse_seeds(req.seeds)
    groups = req.groups or ["reference", "stub"]
    archetypes: list = list(req.archetypes) if req.archetypes else [None]
    spec = BenchSpec(seeds=seeds, days=req.days, groups=groups,
                     archetypes=archetypes,
                     concurrency=req.concurrency or default_concurrency())
    n_ep = len(spec.episodes())

    cap = req.max_episodes
    if cap is None or n_ep > cap:
        return {"started": False, "n_episodes": n_ep,
                "estimated_tokens": estimate_tokens(spec),
                "error": "live 批量需显式确认 max_episodes 且不得超过它"}

    from datetime import datetime, timezone
    bench_id = req.bench_id or f"bench_live_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    # 幂等防护：同一 bench 目录已有在跑任务时拒绝重复启动（episodes.jsonl 会串写）
    running = BENCH_JOBS.get(bench_id)
    if running and running.get("status") == "running":
        return {"started": False, "bench_id": bench_id,
                "error": "该 bench 正在运行中，拒绝重复启动"}
    job = {"bench_id": bench_id, "status": "running", "done": 0, "total": n_ep, "error": None}
    BENCH_JOBS[bench_id] = job

    def _work() -> None:
        def on_progress(done: int, total: int, last: dict) -> None:
            job["done"] = done
            job["total"] = total

        try:
            run_suite(spec, out_root=BENCH_ROOT, bench_id=bench_id, on_progress=on_progress)
            job["status"] = "finished"
        except Exception as e:  # noqa: BLE001
            job["status"] = "failed"
            job["error"] = str(e)

    threading.Thread(target=_work, daemon=True).start()
    return {"started": True, "bench_id": bench_id, "n_episodes": n_ep}


@app.get("/api/bench")
def list_bench() -> dict:
    """已有批量结果列表（含运行中的任务进度）。

    运行中的 bench 尚无 aggregate.json——以 runs/ 目录或 episodes.jsonl 存在为准，
    附带 episodes 完成数，否则前端在跑到结束前几小时都看不见它。
    """
    items = []
    if BENCH_ROOT.exists():
        for d in sorted(BENCH_ROOT.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            agg = d / "aggregate.json"
            job = BENCH_JOBS.get(d.name)
            ep_file = d / "episodes.jsonl"
            n_eps = sum(1 for l in ep_file.open(encoding="utf-8") if l.strip()) \
                if ep_file.exists() else 0
            if agg.exists():
                data = json.loads(agg.read_text(encoding="utf-8"))
                items.append({
                    "bench_id": d.name,
                    "mode": data.get("mode"),
                    "days": data.get("days"),
                    "n_episodes": data.get("n_episodes"),
                    "groups": sorted(data.get("groups", {})),
                    "has_guard": (d / "discriminability.json").exists(),
                    "status": (job or {}).get("status") or "finished",
                    "episodes_done": n_eps,
                })
            elif (d / "runs").is_dir() or ep_file.exists():
                items.append({
                    "bench_id": d.name, "mode": "live", "days": None,
                    "n_episodes": (job or {}).get("total") or n_eps,
                    "groups": [], "has_guard": False,
                    "status": (job or {}).get("status") or "running",
                    "episodes_done": n_eps,
                })
    return {"items": items, "jobs": list(BENCH_JOBS.values())}


def _episode_progress(d: Path) -> dict | None:
    """bench 内单个 episode 目录 → 进行中条目（report.json 未出 = 还在跑）。

    bench episode 走 suite._run_one（CLI 路径），不注册 RUNS handle——
    进度只能从 slots.jsonl 行数推导。
    """
    meta_file = d / "meta.json"
    if not meta_file.exists() or (d / "report.json").exists():
        return None
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    slots_file = d / "slots.jsonl"
    n_slots = sum(1 for _ in slots_file.open()) if slots_file.exists() else 0
    total = int(meta.get("days") or 0) * int(cfg.clock.slots_per_day)
    return {"run_id": d.name, "status": "running",
            "progress": {"slot": n_slots, "total": total},
            "days": meta.get("days"), "seed": meta.get("seed"),
            "profiles": meta.get("profiles") or None}


@app.get("/api/bench/{bench_id}")
def bench_detail(bench_id: str) -> dict:
    from fastapi import HTTPException

    d = BENCH_ROOT / bench_id
    out: dict = {}
    agg = d / "aggregate.json"
    if agg.exists():
        out["aggregate"] = json.loads(agg.read_text(encoding="utf-8"))
    guard = d / "discriminability.json"
    if guard.exists():
        out["discriminability"] = json.loads(guard.read_text(encoding="utf-8"))
    eps = d / "episodes.jsonl"
    if eps.exists():
        out["episodes"] = [
            json.loads(l) for l in eps.read_text(encoding="utf-8").splitlines() if l.strip()
        ]
    # 进行中的 episode（有目录无 report.json）逐个给进度
    ep_root = d / "runs"
    running = []
    if ep_root.is_dir():
        for child in sorted(ep_root.iterdir()):
            if child.is_dir():
                p = _episode_progress(child)
                if p is not None:
                    running.append(p)
    out["running"] = running
    out["job"] = BENCH_JOBS.get(bench_id)
    if not agg.exists() and not eps.exists() and out["job"] is None and not running:
        raise HTTPException(status_code=404, detail=f"未知 bench {bench_id}")
    if not agg.exists():
        out["pending"] = True
    return out


class ContinueRunRequest(BaseModel):
    extra_days: int = 10


@app.post("/api/runs/{run_id}/continue")
def continue_run(run_id: str, req: ContinueRunRequest) -> dict:
    """续跑：从 run_state.json 恢复世界，追加 extra_days 天。"""
    d = _find_run_dir(run_id)
    if not (d / "run_state.json").exists():
        from fastapi import HTTPException
        raise HTTPException(400, "该 run 无存档（run_state.json），无法续跑")
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    if meta.get("mode") != "live":
        from fastapi import HTTPException
        raise HTTPException(400, "该存档是已下线的 replay 模式（R4 起仅支持 live 续跑）；"
                                 "仍可回放与离线 eval，但不能追加天数")
    total_days = meta["days"] + req.extra_days
    handle = RunHandle(run_id)
    handle.run_dir = d
    handle.progress["total"] = total_days * int(cfg.clock.slots_per_day)
    handle.progress["slot"] = meta["days"] * int(cfg.clock.slots_per_day)
    RUNS[run_id] = handle

    def _wrap() -> None:
        # meta.harness 形如 "demo:reference" / "external"（旧格式 "reference" 按 demo 处理）
        h = meta.get("harness") or "reference"
        attach = "external" if h == "external" else "demo"
        harness_name = h.split(":", 1)[1] if ":" in h else h
        _execute(handle, meta["seed"], total_days,
                 resume_dir=d, extra_days=req.extra_days,
                 harness=harness_name, user_agent=attach, assistant_agent=attach)

    handle.thread = threading.Thread(target=_wrap, daemon=True)
    handle.thread.start()
    return {"continued": True, "run_id": run_id, "extra_days": req.extra_days, "total_days": total_days}


@app.get("/api/balance/config")
def get_balance_config() -> dict:
    """配表编辑器数据：返回所有 JSON 配置文件内容供前端编辑。"""
    from usersim.world.balance import load_overrides, list_config_files, _load_json

    ov = load_overrides()
    files: dict = {}
    for fname in list_config_files():
        key = fname.replace(".json", "")
        data = _load_json(fname)
        if data is not None:
            files[key] = data
    return {"source": ov["source"], "files": files}


class BalanceSaveRequest(BaseModel):
    file: str   # e.g. "recovery_actions"
    content: object  # full JSON content


@app.post("/api/balance/save")
def save_balance_config(req: BalanceSaveRequest) -> dict:
    """保存整个配置文件并热加载（新 run 立即使用新数值）。"""
    from fastapi import HTTPException
    from usersim.world.balance import save_config_file, load_overrides, get_config_dir

    ALLOWED = {
        "recovery_actions", "meal_tiers", "sleep_tiers", "custom_activities",
        "professions", "disturbances", "template_events", "economy",
        "dynamics", "habituation", "needs", "persona_modulation", "weather",
        "venues",
    }
    if req.file not in ALLOWED:
        raise HTTPException(400, f"未知配置文件: {req.file}")
    save_config_file(f"{req.file}.json", req.content)
    ov = load_overrides()
    return {"ok": True, "source": ov["source"], "file": req.file}


class BalanceResetRequest(BaseModel):
    file: str | None = None  # None → 重置全部


@app.post("/api/balance/reset")
def reset_balance_config(req: BalanceResetRequest) -> dict:
    """从代码默认值重置一个或所有配置文件并热加载。"""
    from fastapi import HTTPException
    from usersim.world.balance import reset_config_file, reload, list_config_files

    RESETABLE = {
        "recovery_actions.json", "meal_tiers.json", "sleep_tiers.json",
        "custom_activities.json", "professions.json", "disturbances.json",
        "template_events.json", "economy.json", "habituation.json",
        "venues.json", "dynamics.json",
    }
    if req.file:
        fname = f"{req.file}.json"
        if fname not in RESETABLE:
            raise HTTPException(400, f"无法重置: {req.file}（不在可重置列表或没有默认值）")
        ok = reset_config_file(fname)
        if not ok:
            raise HTTPException(500, f"重置失败: {req.file}")
        ov = reload()
        return {"ok": True, "reset": [req.file], "source": ov["source"]}
    else:
        reset_ok = [f.replace(".json", "") for f in RESETABLE if reset_config_file(f)]
        ov = reload()
        return {"ok": True, "reset": reset_ok, "source": ov["source"]}


class FormulaEvalRequest(BaseModel):
    formula: str
    var_name: str = "x"
    points: int = 50


@app.post("/api/balance/eval_formula")
def eval_formula(req: FormulaEvalRequest) -> dict:
    """评估公式并返回曲线数据点（用于前端实时预览）。"""
    from usersim.world.anthro import parse_formula

    func = parse_formula(req.formula, req.var_name)
    if func is None:
        return {"ok": False, "error": "公式语法错误或包含不安全操作"}

    try:
        points = []
        for i in range(req.points):
            x = i / (req.points - 1)
            y = func(x)
            points.append({"x": x, "y": y})
        return {"ok": True, "points": points}
    except Exception as e:
        return {"ok": False, "error": f"执行错误: {str(e)}"}


# ── 兼容旧端点（已废弃，保留 30 天供过渡）──────────────────────────────────
@app.get("/api/balance")
def get_balance_legacy() -> dict:
    """[已废弃] 旧 Excel 配表接口，改用 /api/balance/config。"""
    return get_balance_config()


@app.get("/api/runs/{run_id}/insights")
def run_insights(run_id: str) -> dict:
    """深度诊断：故障/拟人性/世界真实性/助手能力的结构化发现。"""
    from usersim.evaluator.insights import compute_insights
    from usersim.evaluator.metrics import load_run

    d = _find_run_dir(run_id)
    slots, turns, meta = load_run(d)
    return compute_insights(slots, turns, meta, cfg.state.targets.to_dict(), float(cfg.state.band),
                            score_cfg=cfg.get("score"))


@app.get("/api/runs/{run_id}/events")
def run_events(run_id: str) -> dict:
    """完整事件记录（模板/扰动/恢复/系列子事件）+ 系列列表，来自世界存档。"""
    d = _find_run_dir(run_id)
    state_file = d / "run_state.json"
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        return {"items": state["world"]["events"], "series": state["world"].get("series", [])}
    # 兼容无存档的旧 run：从 turns 重建恢复事件
    events = []
    f = d / "turns.jsonl"
    if f.exists():
        for l in f.read_text(encoding="utf-8").splitlines():
            t = json.loads(l)
            for r in t.get("tool_results", []):
                if r.get("name") == "add_event_todo" and r.get("ok") and "event" in r.get("payload", {}):
                    events.append(r["payload"]["event"])
    return {"items": events, "series": []}


@app.get("/api/catalog")
def catalog_summary() -> dict:
    """配表摘要（前端参数选择与事件图例用）：事件表 + 统一地点表。"""
    from usersim.world.catalog import MEAL_TIERS, PROFESSIONS, RECOVERY_ACTIONS, SLEEP_TIERS, VENUES
    return {
        "professions": PROFESSIONS,
        "recovery_actions": [
            {
                "id": a["id"], "action": a["action"], "category": a["category"],
                "design_intent": a.get("design_intent", ""),
                "default_span": a.get("default_span", 1),
            }
            for a in RECOVERY_ACTIONS
        ],
        "venues": [
            {
                "id": v["id"], "name": v["name"], "category": v.get("category", ""),
                "cuisine": v.get("cuisine", ""),
                "supports": [
                    {"event": s["event"], "cost": s.get("cost", 0), "span": s.get("span", 1)}
                    for s in v.get("supports", [])
                ],
            }
            for v in VENUES
        ],
        "meal_tiers": [{"vid": m["vid"], "name": m["name"], "cost": m["cost"]} for m in MEAL_TIERS],
        "sleep_tiers": [{"vid": s["vid"], "name": s["name"], "cost": s["cost"]} for s in SLEEP_TIERS],
    }


def _run_item(d: Path) -> dict | None:
    """单个 run 目录 → 列表条目（顶层与 bench 嵌套目录共用）。"""
    meta_file = d / "meta.json"
    if not meta_file.exists():
        return None
    meta = json.loads(meta_file.read_text(encoding="utf-8"))
    report_file = d / "report.json"
    verdict = None
    benchmark_score = None
    if report_file.exists():
        rep = json.loads(report_file.read_text(encoding="utf-8"))
        verdict = rep.get("verdict")
        benchmark_score = (rep.get("benchmark") or {}).get("score")
    handle = RUNS.get(d.name)
    persona = meta.get("persona", {})
    item = {
        "run_id": d.name,
        "seed": meta.get("seed"),
        "days": meta.get("days"),
        "mode": meta.get("mode"),
        "assistant_quality": meta.get("assistant_quality"),
        "status": handle.status if handle else "finished",
        "verdict": verdict,
        "benchmark_score": benchmark_score,
        "profiles": meta.get("profiles") or None,
        "persona_name": persona.get("name"),
        "archetype": persona.get("archetype"),
        "income_per_slot": persona.get("income_per_slot"),
        "started_at": meta.get("started_at"),
    }
    if handle is not None and handle.status == "running":
        item["progress"] = dict(handle.progress)
    elif not report_file.exists():
        # bench episode 走 suite（CLI 路径）不注册 RUNS handle：report.json 未出即还在跑，
        # 进度从 slots.jsonl 行数推导，否则控制台文件夹里的进行中 run 显示为"已完成"
        slots_file = d / "slots.jsonl"
        n_slots = sum(1 for _ in slots_file.open()) if slots_file.exists() else 0
        item["status"] = "running"
        item["progress"] = {"slot": n_slots,
                            "total": int(meta.get("days") or 0) * int(cfg.clock.slots_per_day)}
    return item


@app.get("/api/runs")
def list_runs() -> dict:
    out = []
    for d in sorted(OUT_ROOT.iterdir() if OUT_ROOT.exists() else [], reverse=True):
        item = _run_item(d)
        if item is not None:
            out.append(item)
    # 进行中的 run（目录/meta 可能尚未创建，列表兜底）
    seen = {r["run_id"] for r in out}
    for rid, h in RUNS.items():
        if h.run_dir is None and rid not in seen:
            out.append({"run_id": rid, "status": h.status, "mode": None, "verdict": None})
    # bench 分组：runs/_bench/<bench_id>/runs/<episode>/ 以文件夹形式暴露给前端
    groups = []
    if BENCH_ROOT.exists():
        for bench_dir in sorted((p for p in BENCH_ROOT.iterdir() if p.is_dir()),
                                key=lambda p: p.name, reverse=True):
            ep_root = bench_dir / "runs"
            if not ep_root.is_dir():
                continue
            children = []
            for d in sorted((p for p in ep_root.iterdir() if p.is_dir()),
                            key=lambda p: p.name):
                item = _run_item(d)
                if item is not None:
                    children.append(item)
            if children:
                groups.append({
                    "bench_id": bench_dir.name,
                    "n_runs": len(children),
                    "harnesses": sorted({(c.get("profiles") or {}).get("assistant", "?")
                                         for c in children}),
                    "runs": children,
                })
    return {"runs": out, "groups": groups}


def _find_run_dir(run_id: str) -> Path:
    d = OUT_ROOT / run_id
    if d.exists():
        return d
    # bench 嵌套存档：runs/_bench/<bench_id>/runs/<run_id>
    if BENCH_ROOT.exists() and "/" not in run_id and "\\" not in run_id:
        for bench_dir in BENCH_ROOT.iterdir():
            cand = bench_dir / "runs" / run_id
            if cand.exists():
                return cand
    from fastapi import HTTPException
    raise HTTPException(404, f"run 不存在: {run_id}")


class DeleteRunsRequest(BaseModel):
    run_ids: list[str]


def _find_bench_run_dir(run_id: str) -> Path | None:
    """在 runs/_bench/*/runs/ 下查找嵌套存档目录（带路径安全检查）。"""
    if not BENCH_ROOT.exists():
        return None
    root = BENCH_ROOT.resolve()
    for bench_dir in BENCH_ROOT.iterdir():
        cand = (bench_dir / "runs" / run_id).resolve()
        if cand.is_dir() and root in cand.parents:
            return cand
    return None


@app.post("/api/runs/delete")
def delete_runs(req: DeleteRunsRequest) -> dict:
    """批量删除存档（顶层与 bench 分组内的 run）。运行中的 run 拒绝删除；严格限制在 runs 目录内。"""
    import shutil

    deleted, skipped = [], []
    for rid in req.run_ids:
        # 防路径穿越：run_id 必须是不含分隔符的纯目录名
        if not rid or "/" in rid or "\\" in rid or rid.startswith("."):
            skipped.append({"run_id": rid, "reason": "非法 run_id"})
            continue
        handle = RUNS.get(rid)
        if handle is not None and handle.status == "running":
            skipped.append({"run_id": rid, "reason": "运行中，无法删除"})
            continue
        d = (OUT_ROOT / rid).resolve()
        if d.is_dir() and OUT_ROOT.resolve() in d.parents:
            pass  # 顶层存档
        else:
            # bench 嵌套存档：runs/_bench/<bench_id>/runs/<run_id>
            d = _find_bench_run_dir(rid)
            if d is None:
                skipped.append({"run_id": rid, "reason": "存档不存在"})
                continue
            # bench episode 走 suite（CLI 路径）不注册 RUNS handle：
            # report.json 未出即视为还在跑，拒绝删除
            if not (d / "report.json").exists():
                skipped.append({"run_id": rid, "reason": "运行中，无法删除"})
                continue
        RUNS.pop(rid, None)
        shutil.rmtree(d)
        deleted.append(rid)
    return {"deleted": deleted, "skipped": skipped}


class DeleteBenchRequest(BaseModel):
    bench_ids: list[str]


@app.post("/api/bench/delete")
def delete_bench(req: DeleteBenchRequest) -> dict:
    """批量删除 bench 分组（整个 runs/_bench/<bench_id>/ 目录）。含运行中 episode 的分组拒绝删除。"""
    import shutil

    deleted, skipped = [], []
    for bid in req.bench_ids:
        # 防路径穿越：bench_id 必须是不含分隔符的纯目录名
        if not bid or "/" in bid or "\\" in bid or bid.startswith("."):
            skipped.append({"bench_id": bid, "reason": "非法 bench_id"})
            continue
        d = (BENCH_ROOT / bid).resolve()
        if not d.is_dir() or BENCH_ROOT.resolve() not in d.parents:
            skipped.append({"bench_id": bid, "reason": "分组不存在"})
            continue
        ep_root = d / "runs"
        running = ep_root.is_dir() and any(
            ep.is_dir() and (ep / "meta.json").exists() and not (ep / "report.json").exists()
            for ep in ep_root.iterdir()
        )
        if running:
            skipped.append({"bench_id": bid, "reason": "含运行中的 run，无法删除"})
            continue
        shutil.rmtree(d)
        deleted.append(bid)
    return {"deleted": deleted, "skipped": skipped}


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict:
    d = _find_run_dir(run_id)
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    slots_file = d / "slots.jsonl"
    n_slots = sum(1 for _ in slots_file.open()) if slots_file.exists() else 0
    handle = RUNS.get(run_id)
    return {
        "meta": meta,
        "status": handle.status if handle else "finished",
        "error": handle.error if handle else None,
        "n_slots": n_slots,
        "total_slots": meta["days"] * int(cfg.clock.slots_per_day),
    }


@app.get("/api/runs/{run_id}/turns")
def run_turns(run_id: str, offset: int = 0, limit: int = 200) -> dict:
    d = _find_run_dir(run_id)
    f = d / "turns.jsonl"
    lines = f.read_text(encoding="utf-8").splitlines() if f.exists() else []
    items = [json.loads(l) for l in lines[offset:offset + limit]]
    return {"total": len(lines), "offset": offset, "items": items}


@app.get("/api/runs/{run_id}/slots")
def run_slots(run_id: str) -> dict:
    d = _find_run_dir(run_id)
    f = d / "slots.jsonl"
    items = [json.loads(l) for l in f.read_text(encoding="utf-8").splitlines()] if f.exists() else []
    return {"items": items}


@app.get("/api/runs/{run_id}/report")
def run_report(run_id: str) -> dict:
    d = _find_run_dir(run_id)
    report_file = d / "report.json"
    if report_file.exists():
        return json.loads(report_file.read_text(encoding="utf-8"))
    return evaluate_run(d, cfg)


@app.get("/api/config/validation")
def config_validation() -> dict:
    import tomllib
    llm = tomllib.loads((PROJECT_ROOT / "config" / "llm.toml").read_text(encoding="utf-8"))
    providers = {}
    for name, p in llm.get("providers", {}).items():
        key = p.get("api_key", "")
        providers[name] = {
            "model": p.get("model"),
            "key_filled": bool(key) and "在此填入" not in key and len(key) > 10,
        }
    return {
        "system_config_ok": True,
        "providers": providers,
        "roles": {k: v.get("provider") for k, v in llm.get("roles", {}).items()},
    }


# ---------------------------------------------------------------
# WebSocket：先补发积压，再实时推送
# ---------------------------------------------------------------


@app.websocket("/ws/runs/{run_id}")
async def ws_run(ws: WebSocket, run_id: str) -> None:
    await ws.accept()
    d = OUT_ROOT / run_id
    # 补发积压
    if d.exists():
        tf = d / "turns.jsonl"
        if tf.exists():
            for l in tf.read_text(encoding="utf-8").splitlines():
                await ws.send_json({"type": "turn", "data": json.loads(l)})
        sf = d / "slots.jsonl"
        if sf.exists():
            for l in sf.read_text(encoding="utf-8").splitlines():
                await ws.send_json({"type": "slot", "data": json.loads(l)})
    handle = RUNS.get(run_id)
    if handle is None or handle.status != "running":
        await ws.send_json({"type": "done", "data": {"run_id": run_id}})
        await ws.close()
        return
    q: asyncio.Queue = asyncio.Queue(maxsize=2000)
    handle.subscribers.append(q)
    try:
        while True:
            ev = await q.get()
            await ws.send_json(ev)
            if ev["type"] in ("done", "error"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        if q in handle.subscribers:
            handle.subscribers.remove(q)


# ---------------------------------------------------------------
# 静态托管（生产模式：web/dist）
# ---------------------------------------------------------------

DIST = PROJECT_ROOT / str(cfg.frontend.build_dir)
if DIST.exists():
    app.mount("/", StaticFiles(directory=str(DIST), html=True), name="web")


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if DIST.exists():
        candidate = DIST / full_path
        if candidate.is_file():
            return FileResponse(str(candidate))
        return FileResponse(str(DIST / "index.html"))
    return {"hint": "前端未构建：cd web && npm run build，或使用 vite dev 模式"}
