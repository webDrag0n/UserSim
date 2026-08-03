"""Runner 编排器：唯一的组件组装点。

世界不调用 Agent，Agent 不知道世界的存在；Runner 在两者之间转发消息、
执行工具、并把 turn 级全量记录（对话 + x_true + x_hat）写入日志。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from usersim.agents.scripted import ASSISTANT_REPLIES, QUALITY_PRESETS, ScriptedAssistant, ScriptedUser
from usersim.config import Namespace, llm_roles_summary, system_config_hash
from usersim.contracts import RunMeta, StateVec, ToolCall, ToolResult, TurnRecord
from usersim.world import World
from usersim.world.dynamics import DIMS, dim_error


def _write_jsonl(path: Path, obj) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj.model_dump(), ensure_ascii=False) + "\n")


def run_replay(seed: int, days: int, quality: str, cfg: Namespace, out_root: Path,
               on_event=None, archetype: str | None = None,
               resume_dir: Path | None = None, extra_days: int = 0,
               run_id: str | None = None) -> Path:
    """规则回放模式：全程 0 次 LLM 调用，产出完整 run 目录。

    resume_dir 给定时从 run_state.json 恢复世界并续跑 extra_days 天（日志追加）。"""
    if quality not in QUALITY_PRESETS:
        raise ValueError(f"未知助手档位 {quality!r}，可选: {list(QUALITY_PRESETS)}")

    if resume_dir is not None:
        run_dir = resume_dir
        run_id = resume_dir.name
        state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
        world = World.from_snapshot(state["world"], cfg, extra_days)
        sess_counter = state["sess_counter"]
        turn_counter = state["turn_counter"]
    else:
        run_id = run_id or f"replay_{seed}_{quality}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        run_dir = out_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        world = World(seed=seed, days=days, cfg=cfg, archetype=archetype)
        sess_counter = 0
        turn_counter = 0

    _write_meta(run_dir, run_id, world, "replay", quality)  # 开始时即写 meta，运行中可见
    gen = world.streams["noise"]  # 脚本 Agent 共用世界噪声流 → 全程确定
    targets = cfg.state.targets.to_dict()
    band = float(cfg.state.band)
    assistant = ScriptedAssistant(quality, gen, targets, band)
    user = ScriptedUser(gen)

    slots_path = run_dir / "slots.jsonl"
    turns_path = run_dir / "turns.jsonl"
    if resume_dir is None:  # 仅全新运行时清空旧日志；续跑时追加
        for p in (slots_path, turns_path):
            p.unlink(missing_ok=True)

    def emit(speaker: str, text: str, x_true: StateVec, x_hat: StateVec | None,
             session_id: str | None, tool_calls=None, tool_results=None) -> None:
        nonlocal turn_counter
        rec = TurnRecord(
            run_id=run_id, t_logical=world.t, session_id=session_id, turn_id=turn_counter,
            speaker=speaker, text=text, tool_calls=tool_calls or [], tool_results=tool_results or [],
            x_true=x_true, x_hat=x_hat,
        )
        _write_jsonl(turns_path, rec)
        turn_counter += 1
        if on_event:
            on_event({"type": "turn", "data": rec.model_dump()})

    while not world.done:
        ctx = world.current_context()
        x_true = world.x.model_copy(deep=True)
        day = world.day

        # 系列规划（脚本助手）：好助手攒够钱后会安排一次长途旅行
        if world.slot == 0 and not world.series:
            if quality == "good" and day >= 7 and world.money >= 3500 and (world.days - day) >= 8:
                world.plan_series("grand_trip", 1, 6)
            elif quality == "mid" and day >= 7 and world.money >= 2500 and (world.days - day) >= 10:
                world.plan_series("grand_trip", 1, 8)

        # 助手观测（模拟通过对话形成的估计）
        assistant.observe(x_true, day)
        intervene = assistant.should_intervene()

        if ctx.assist_prompt or intervene:
            sess_counter += 1
            sid = f"S{sess_counter:04d}"
            active_names = [e.name for e in ctx.active_events if e.kind != "template"]
            felt = world.felt_state()

            # 用户开启 session（工具调用记录）
            emit("user", f"（开启 Session）{user.opener(felt, active_names)}",
                 x_true, None, sid, tool_calls=[ToolCall(name="open_session")])

            tool_calls, tool_results = [], []
            plan_desc = "今晚好好休息"
            if intervene:
                spent_today = sum(
                    e.cost for e in world.events
                    if e.kind == "recovery" and e.start_slot // world.slots_per_day == day
                )
                # 系列事件抑制收入期间（备考/休假），当日可支配收入为 0
                from usersim.world.series import SERIES_TYPES as _ST
                active_s = world.active_series()
                suppress_inc = bool(active_s and _ST[active_s.type]["suppress_income"])
                daily_income = 0.0 if (suppress_inc or not world.is_workday()) else world.persona.income_per_slot * 2
                choice = assistant.choose_recovery(world.money, spent_today, daily_income)
                if choice is not None:
                    action_name, variant_id = choice
                    # 一个时段长达数小时，助手的建议在此时段内即时生效（与动力学即时控制语义一致）
                    result = world.add_event_todo(
                        name=action_name, day_offset=0, slot=world.slot,
                        goal=f"恢复状态：{action_name}", effect={}, caused_by_session_id=sid,
                        variant_id=variant_id,
                    )
                    plan_name = result.payload.get("event", {}).get("name", action_name) if result.ok else action_name
                    tool_calls = [ToolCall(name="add_event_todo", args={"name": action_name, "variant_id": variant_id, "day_offset": 0, "slot": world.slot})]
                    tool_results = [result]
                    plan_desc = f"「{plan_name}」（已写入日程）" if result.ok else "先好好休息（金钱不足或日程冲突，未写入）"

            reply_tpl = ASSISTANT_REPLIES[int(gen.integers(len(ASSISTANT_REPLIES)))]
            est_now = assistant.hist[-1]
            emit("assistant", reply_tpl.format(plan=plan_desc),
                 x_true, est_now, sid, tool_calls=tool_calls, tool_results=tool_results)

            emit("user", f"（结束 Session）{user.ack()}", x_true, None, sid,
                 tool_calls=[ToolCall(name="close_session")])

            emit("system", f"Session 结算：{'新增恢复事件 1 个' if tool_calls else '无工具调用'}",
                 x_true, None, sid)

        settlement = world.step_slot()
        _write_jsonl(slots_path, settlement)
        if on_event:
            on_event({"type": "slot", "data": settlement.model_dump()})

    _write_meta(run_dir, run_id, world, "replay", quality)
    _save_state(run_dir, world, sess_counter, turn_counter)
    return run_dir


def _write_meta(run_dir: Path, run_id: str, world, mode: str, quality: str | None) -> None:
    """meta.json：run 开始时即写入（运行中也可被列表/打开），结束时可重写。"""
    meta = RunMeta(
        run_id=run_id,
        seed=world.seed,
        started_at=datetime.now(timezone.utc).isoformat(),
        days=world.days,
        mode=mode,  # type: ignore[arg-type]
        assistant_quality=quality,
        config_hash=system_config_hash(),
        persona=world.persona,
        llm_roles=llm_roles_summary(),
    )
    (run_dir / "meta.json").write_text(json.dumps(meta.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")


def _save_state(run_dir: Path, world, sess_counter: int, turn_counter: int,
                harness_notes: str | None = None) -> None:
    """存档：世界快照 + 计数器 + Harness 记忆，供续跑恢复。"""
    state = {
        "world": world.to_snapshot(),
        "sess_counter": sess_counter,
        "turn_counter": turn_counter,
        "harness_notes": harness_notes,
    }
    (run_dir / "run_state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


# ----------------------------------------------------------------
# 真实 LLM 模式
# ----------------------------------------------------------------


def run_live(seed: int, days: int, cfg: Namespace, out_root: Path,
             on_event=None, archetype: str | None = None,
             resume_dir: Path | None = None, extra_days: int = 0,
             run_id: str | None = None) -> Path:
    """真实运行模式：两个 LLM Agent 上线，完整 benchmark。支持续跑。"""
    from pydantic import ValidationError

    from usersim.agents.assistant import ReferenceHarness
    from usersim.agents.user import LLMUserAgent
    from usersim.config import load_llm_role, load_llm_runtime
    from usersim.contracts import UserContext
    from usersim.llm import LLMClient, LLMError

    if resume_dir is not None:
        run_dir = resume_dir
        run_id = resume_dir.name
        state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
        world = World.from_snapshot(state["world"], cfg, extra_days)
        sess_counter = state["sess_counter"]
        turn_counter = state["turn_counter"]
        saved_notes = state.get("harness_notes")
    else:
        run_id = run_id or f"live_{seed}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        run_dir = out_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        world = World(seed=seed, days=days, cfg=cfg, archetype=archetype)
        sess_counter = 0
        turn_counter = 0
        saved_notes = None

    _write_meta(run_dir, run_id, world, "live", None)  # 开始时即写 meta

    runtime = load_llm_runtime()
    user = LLMUserAgent(LLMClient(load_llm_role("user_agent"), runtime))
    assistant = ReferenceHarness(LLMClient(load_llm_role("assistant_agent"), runtime))
    if saved_notes:
        assistant.profile_notes = saved_notes

    slots_path = run_dir / "slots.jsonl"
    turns_path = run_dir / "turns.jsonl"
    if resume_dir is None:
        for p in (slots_path, turns_path):
            p.unlink(missing_ok=True)

    def emit(speaker: str, text: str, x_true: StateVec, x_hat: StateVec | None,
             session_id: str | None, tool_calls=None, tool_results=None,
             violation: str | None = None, degraded: bool = False) -> None:
        nonlocal turn_counter
        rec = TurnRecord(
            run_id=run_id, t_logical=world.t, session_id=session_id, turn_id=turn_counter,
            speaker=speaker, text=text, tool_calls=tool_calls or [], tool_results=tool_results or [],
            x_true=x_true, x_hat=x_hat, contract_violation=violation, degraded=degraded,
        )
        _write_jsonl(turns_path, rec)
        turn_counter += 1
        if on_event:
            on_event({"type": "turn", "data": rec.model_dump()})

    max_turns = int(cfg.user_agent.max_turns_per_session)

    while not world.done:
        ctx = world.current_context()
        if ctx.assist_prompt:
            x_snapshot = world.x.model_copy(deep=True)
            uctx = UserContext(
                persona=world.persona, felt_state=world.felt_state(),
                active_events=ctx.active_events, assist_prompt=ctx.assist_prompt,
                schedule_view=ctx.schedule_view,
            )
            try:
                open_it = user.decide_open(uctx)
            except LLMError as e:
                emit("system", f"用户 Agent 调用失败，本时段跳过：{e}", x_snapshot, None, None, degraded=True)
                open_it = False

            if open_it:
                sess_counter += 1
                sid = f"S{sess_counter:04d}"
                history: list[dict] = []
                tool_results: list = []
                for turn_no in range(max_turns):
                    # ---- 用户说 ----
                    try:
                        ua = user.speak(uctx, [
                            TurnRecord(run_id=run_id, t_logical=world.t, session_id=sid, turn_id=i,
                                       speaker=h["speaker"], text=h["text"], x_true=x_snapshot)
                            for i, h in enumerate(history)
                        ])
                    except LLMError as e:
                        emit("system", f"用户 Agent 降级（{e}）", x_snapshot, None, sid, degraded=True)
                        break
                    emit("user", ua["say"], x_snapshot, None, sid,
                         tool_calls=[ToolCall(name="open_session")] if turn_no == 0 else [])
                    history.append({"speaker": "user", "text": ua["say"]})

                    # ---- 助手回 ----
                    # O3：注入今日已有安排，避免重复安排冲突
                    slot_names = cfg.clock.slot_names
                    today_events = [
                        e for e in world.events
                        if e.kind in ("recovery", "series", "disturbance")
                        and world.t <= e.start_slot < (world.day + 1) * world.slots_per_day
                    ][:8]
                    schedule_hint = "；".join(
                        f"{e.name}（{slot_names[e.start_slot % world.slots_per_day]}）" for e in today_events
                    )
                    try:
                        at = assistant.on_turn(history, ua["say"], tool_results, balance=world.money,
                                               schedule_hint=schedule_hint)
                        violation = None
                    except (LLMError, ValidationError) as e:
                        at = None
                        violation = f"assistant_contract_or_llm_error: {e}"
                    if at is None:
                        emit("system", f"助手契约违约：{violation}", x_snapshot, None, sid,
                             violation=violation)
                        break

                    # ---- 工具执行（世界端） ----
                    tool_results = []
                    for call in at.tool_calls:
                        if call.name == "view_event_todos":
                            tool_results.append(world.view_event_todos())
                        elif call.name == "add_event_todo":
                            a = call.args
                            tool_results.append(world.add_event_todo(
                                name=str(a.get("name", "恢复事件")),
                                day_offset=int(a.get("day_offset", 0)),
                                slot=int(a.get("slot", 2)),
                                goal=str(a.get("goal", a.get("name", "恢复"))),
                                effect={k: float(v) for k, v in (a.get("effect") or {}).items()
                                        if k in ("valence", "energy", "satiety", "stress")},
                                span_slots=max(1, int(a.get("span_slots", 1))),
                                caused_by_session_id=sid,
                                location=str(a["location"]) if a.get("location") else None,
                            ))
                        elif call.name == "plan_series":
                            a = call.args
                            tool_results.append(world.plan_series(
                                series_type=str(a.get("series_type", "staycation")),
                                start_day_offset=int(a.get("start_day_offset", 1)),
                                duration=int(a.get("duration", 5)),
                            ))
                        elif call.name == "set_reminder":
                            a = call.args
                            tool_results.append(world.set_reminder(
                                message=str(a.get("message", a.get("content", ""))),
                                time_str=str(a.get("time", a.get("time_str", ""))),
                            ))
                        else:
                            tool_results.append(ToolResult(name=call.name, ok=False, payload={"error": "未知工具"}))

                    emit("assistant", at.reply, x_snapshot, at.user_belief.to_statevec(), sid,
                         tool_calls=at.tool_calls, tool_results=tool_results)
                    history.append({"speaker": "assistant", "text": at.reply})

                    if ua["end_session"]:
                        break

                emit("system", f"Session 结算：{len(history) // 2} 轮对话", x_snapshot, None, sid,
                     tool_calls=[ToolCall(name="close_session")])

        settlement = world.step_slot()
        _write_jsonl(slots_path, settlement)
        if on_event:
            on_event({"type": "slot", "data": settlement.model_dump()})

    _write_meta(run_dir, run_id, world, "live", None)
    _save_state(run_dir, world, sess_counter, turn_counter, harness_notes=assistant.profile_notes)
    return run_dir
