"""Runner 编排器：唯一的组件组装点。

世界不调用 Agent，Agent 不知道世界的存在；Runner 在两者之间转发消息、
执行工具、并把 turn 级全量记录（对话 + x_true + x_hat）写入日志。

agent 的接入已解耦：Runner 不 import 任何 live agent 实现，
只经 AgentBroker（usersim.gateway）提交 plan_slot / decide_open / speak /
on_turn 等请求（docs/15-agent-api.md）。demo agent 与外部 agent 走同一协议。
（replay 脚本模式已于 R4 下线：量程守护改用 live 锚点对 reference vs stub。）
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from usersim.config import Namespace, artifact_hashes, llm_roles_summary, system_config_hash
from usersim.contracts import RunMeta, StateVec, ToolCall, ToolResult, TurnRecord
from usersim.world import World
from usersim.world.dynamics import DIMS, dim_error

# 复读熔断（0-LLM 纯字符串规则）：同一说话人相邻两轮相似度超过阈值即计一次复读；
# 用户连续 2 次 → 注入强收尾提示；连续 3 次 → runner 强制收尾；助手连续 2 次 → 强制收尾。
# 实测教训：低温/弱模型下 user 与 assistant 会互相回声，对话死循环到 max_turns 才被切断。
_REPEAT_RATIO = 0.75
_REPEAT_HINT_AFTER = 2
_REPEAT_FUSE_AFTER = 3


def _similar(a: str | None, b: str | None) -> bool:
    """相邻发言是否复读（纯字符串相似度，不读语义）。"""
    if not a or not b:
        return False
    return SequenceMatcher(None, a, b).ratio() > _REPEAT_RATIO


def _write_jsonl(path: Path, obj) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj.model_dump(), ensure_ascii=False) + "\n")


def _recovery_catalog(world) -> list[dict]:
    """把世界的恢复动作目录摊平成被测件可见的候选清单。

    Runner 是唯一组装点：agents 不得直连 world.catalog（docs/00 依赖表）。
    """
    from usersim.world.catalog import affordable_variants

    out: list[dict] = []
    for action, variant in affordable_variants(max(0.0, world.money)):
        out.append({
            "action": action["action"],
            "vid": variant.get("vid", ""),
            "location": variant.get("location") or variant.get("name", ""),
            "cost": float(variant.get("cost", 0)),
            "span": int(variant.get("span", 1)),
            "category": action.get("category", ""),
            "cuisine": variant.get("cuisine", ""),  # 非餐饮场所为空字符串
        })
    return out


def _write_meta(run_dir: Path, run_id: str, world, mode: str, quality: str | None,
                harness: str = "reference", prompt_versions: dict | None = None,
                profiles: dict | None = None) -> None:
    """meta.json：run 开始时即写入（运行中也可被列表/打开），结束时可重写。

    重写时合并 demo agent 侧 LLMClient 落盘的 reported_models.json（provider 实际
    应答的模型版本，溯源滚动别名漂移）；外部 agent 的模型由其自报（agent_state 存档）。
    """
    reported_path = run_dir / "reported_models.json"
    llm_reported: dict = {}
    if reported_path.exists():
        try:
            llm_reported = json.loads(reported_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            llm_reported = {}
    meta = RunMeta(
        run_id=run_id,
        seed=world.seed,
        started_at=datetime.now(timezone.utc).isoformat(),
        days=world.days,
        mode=mode,  # type: ignore[arg-type]
        assistant_quality=quality,
        config_hash=system_config_hash(),
        harness=harness,
        artifact_hashes=artifact_hashes(),
        prompt_versions=prompt_versions or {},
        profiles=profiles or {},
        persona=world.persona,
        llm_roles=llm_roles_summary(),
        llm_reported=llm_reported,
    )
    (run_dir / "meta.json").write_text(json.dumps(meta.model_dump(), ensure_ascii=False, indent=2), encoding="utf-8")


def _save_state(run_dir: Path, world, sess_counter: int, turn_counter: int,
                agent_state: dict | None = None) -> None:
    """存档：世界快照 + 计数器 + 各角色 agent_state（经 broker 汇总），供续跑恢复。

    agent_state 按角色分桶（{"user": {...}, "assistant": {...}}）：
    demo / 外部 agent 的记忆都是经 agent 接口回传的不透明 blob，Runner 不再假设
    它是 harness 的 profile_notes 文本（旧存档的 harness_state 读取兼容见 run_live）。
    """
    state = {
        "world": world.to_snapshot(),
        "sess_counter": sess_counter,
        "turn_counter": turn_counter,
        "agent_state": agent_state or {},
    }
    (run_dir / "run_state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


# ----------------------------------------------------------------
# 真实 LLM 模式（agent 经统一接口接入，Runner 不 import 任何 live agent 实现）
# ----------------------------------------------------------------


def _assistant_violation(e: Exception) -> str:
    """把 broker 异常映射为违约标签（与重构前的分类口径一致）。"""
    from pydantic import ValidationError

    from usersim.gateway import AgentTimeout

    if isinstance(e, AgentTimeout):
        return f"assistant_timeout: {e}"
    if isinstance(e, ValidationError):
        return f"assistant_contract_or_llm_error: {e}"
    head = str(e).split(":", 1)[0]
    if head in ("LLMError", "ValidationError"):
        return f"assistant_contract_or_llm_error: {e}"
    return f"assistant_harness_crash: {e}"


def _recover_hat_fallback(turns_path: Path) -> "PersonaBelief":
    """续跑时从日志重建 Runner 侧画像累积器的基线（最后一条 assistant 的 persona_hat）。

    只在外部 agent 不回 persona_hat 快照的退化路径上使用；日志即存档，
    因此无需改动 run_state.json 的 schema。
    """
    from usersim.contracts import PersonaBelief

    last: PersonaBelief | None = None
    if turns_path.exists():
        with turns_path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("speaker") == "assistant" and d.get("persona_hat"):
                    last = PersonaBelief(**d["persona_hat"])
    return last or PersonaBelief()


def run_live(seed: int, days: int, cfg: Namespace, out_root: Path,
             on_event=None, archetype: str | None = None,
             resume_dir: Path | None = None, extra_days: int = 0,
             run_id: str | None = None, harness: str | None = None,
             broker=None, attach: str = "demo",
             prompt_versions: dict | None = None,
             profiles: dict | None = None) -> Path:
    """真实运行模式：用户/助手 agent 经 AgentBroker（agent 接口）接入。支持续跑。

    agent 的接入由调用方负责（见 docs/15-agent-api.md）：
      - demo：cli / bench / server 用 agents.client.spawn_demo_agents 起回环线程；
      - external：外部 agent（OpenClaw、Hermes 等）轮询同一 broker 的 HTTP 端点；
      - 测试：broker.register_local 注册假响应函数。

    harness: meta 记录的助手标识（demo 时为 registry 名，仅作可复现性凭证）。
    attach: "demo" | "external"，记入 meta.harness（如 "demo:reference" / "external"）。
    profiles: meta 记录的各角色 profile（{"user": ..., "assistant": ...}，调用方解析默认值后传入）。
    """
    from pydantic import ValidationError

    from usersim.contracts import (
        AssistantTurn,
        DecideOpenRequest,
        DecideOpenResult,
        DialogueTurn,
        HarnessObs,
        PersonaBelief,
        PersonaBeliefDelta,
        PlanSlotRequest,
        PlanSlotResult,
        SessionClosedNotice,
        SpeakRequest,
        UserAction,
        UserContext,
        merge_persona_delta,
    )
    from usersim.gateway import BROKER, AgentError, AgentTimeout

    broker = broker or BROKER
    meta_harness = f"demo:{harness or 'reference'}" if attach == "demo" else "external"

    if resume_dir is not None:
        run_dir = resume_dir
        run_id = resume_dir.name
        state = json.loads((run_dir / "run_state.json").read_text(encoding="utf-8"))
        world = World.from_snapshot(state["world"], cfg, extra_days)
        sess_counter = state["sess_counter"]
        turn_counter = state["turn_counter"]
        saved_agent_state = state.get("agent_state") or {}
        if not saved_agent_state and state.get("harness_state"):
            # 旧存档兼容：harness_state → assistant 桶
            saved_agent_state = {"assistant": state["harness_state"]}
    else:
        run_id = run_id or f"live_{seed}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        run_dir = out_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        world = World(seed=seed, days=days, cfg=cfg, archetype=archetype)
        sess_counter = 0
        turn_counter = 0
        saved_agent_state = {}

    _write_meta(run_dir, run_id, world, "live", None, harness=meta_harness,
                prompt_versions=prompt_versions,
                profiles=profiles)  # 开始时即写 meta

    # 续跑：把存档的 agent_state 回灌 broker，agent 的首个请求即可拿到
    for role, st in saved_agent_state.items():
        broker.set_state(run_id, role, st)

    slots_path = run_dir / "slots.jsonl"
    turns_path = run_dir / "turns.jsonl"
    if resume_dir is None:
        for p in (slots_path, turns_path):
            p.unlink(missing_ok=True)

    # Runner 侧画像累积器（退化路径）：agent 未回 persona_hat 快照时，把本轮
    # user_belief.persona_belief 增量按 EMA 合并落盘（skills/usersim-assistant 承诺的
    # "系统退化为只用本轮增量"语义）；agent 回快照时以快照为新基线。
    hat_fallback = (_recover_hat_fallback(turns_path)
                    if resume_dir is not None else PersonaBelief())

    def emit(speaker: str, text: str, x_true: StateVec, x_hat: StateVec | None,
             session_id: str | None, tool_calls=None, tool_results=None,
             violation: str | None = None, degraded: bool = False,
             persona_hat=None, felt_state=None) -> None:
        nonlocal turn_counter
        rec = TurnRecord(
            run_id=run_id, t_logical=world.t, session_id=session_id, turn_id=turn_counter,
            speaker=speaker, text=text, tool_calls=tool_calls or [], tool_results=tool_results or [],
            x_true=x_true, x_hat=x_hat, persona_hat=persona_hat,
            contract_violation=violation, degraded=degraded, felt_state=felt_state,
        )
        _write_jsonl(turns_path, rec)
        turn_counter += 1
        if on_event:
            on_event({"type": "turn", "data": rec.model_dump()})

    max_turns = int(cfg.user_agent.max_turns_per_session)
    max_sessions_per_slot = int(cfg.clock.get("max_sessions_per_slot", 5) or 5)
    # soft_turn_limit：接近此轮数时在 prompt 中提示用户考虑收尾
    soft_turn_limit = max(4, max_turns - 5)
    # agent 响应超时（外部 agent 可能很慢；demo 回环通常毫秒级）
    resp_timeout = float((cfg.get("agent_api", {}) or {}).get("response_timeout_sec", 120))

    # 跨 session 的未消费工具结果：session 末轮 assistant 落单后，执行结果本应
    # 由下一 session 首轮的 HarnessObs.tool_results 呈现——此前在 session 开头
    # 被清空丢弃，harness 对账（成功剂量登记/失败重试）永远缺最后一单。
    # 该修复对所有 harness 一致生效（同一 runner），属信息通道完整性修复。
    pending_results: list = []

    while not world.done:
        ctx = world.current_context()

        # ---- 步骤 3：用户主动规划（agent 接口 plan_slot；紧急意图注入在 agent 侧完成）----
        # LLM 用户 agent 的规划输入是语义化 context（felt_state，不含数值）
        plan_uctx = UserContext(
            persona=world.persona,
            felt_state=world.felt_state(),
            active_events=ctx.active_events,
            assist_prompt=ctx.assist_prompt,
            schedule_view=ctx.schedule_view,
            weather=ctx.weather,
            satiation_note=ctx.satiation_note,
            utility_menu=ctx.utility_menu,
        )
        try:
            resp = broker.submit("user", run_id, "plan_slot", PlanSlotRequest(
                urges=world.needs.urges(world.overrides),   # 传 urges dict 而非 Needs 对象
                stress=world.x.stress,
                energy=world.x.energy,
                slot=world.slot,
                day=world.day,
                money=world.money,
                event_library=world.persona.event_library,
                assist_prompt=ctx.assist_prompt,
                max_intents=max_sessions_per_slot,
                context=plan_uctx,
            ).model_dump(mode="json"), timeout=resp_timeout)
            intents = PlanSlotResult(**resp.result).intents
        except (AgentTimeout, AgentError, ValidationError) as e:
            emit("system", f"用户 Agent 规划失败，本 slot 无 session：{e}",
                 world.x.model_copy(deep=True), None, None, degraded=True)
            intents = []

        # ---- 步骤 4：逐个意图开 session ----
        for intent in intents:
            x_snapshot = world.x.model_copy(deep=True)
            uctx = UserContext(
                persona=world.persona,
                felt_state=world.felt_state(),
                active_events=ctx.active_events,
                assist_prompt=ctx.assist_prompt if intent.type == "emergency" else None,
                schedule_view=ctx.schedule_view,
                weather=ctx.weather,
                satiation_note=ctx.satiation_note,
                utility_menu=ctx.utility_menu,
            )

            # 用户决定是否开启这个 session（带意图上下文）
            try:
                resp = broker.submit("user", run_id, "decide_open",
                                     DecideOpenRequest(context=uctx, intent=intent)
                                     .model_dump(mode="json"), timeout=resp_timeout)
                open_it = DecideOpenResult(**resp.result).open
            except (AgentTimeout, AgentError, ValidationError) as e:
                emit("system", f"用户 Agent 调用失败，跳过意图 {intent.type}：{e}",
                     x_snapshot, None, None, degraded=True)
                continue

            if not open_it:
                continue

            sess_counter += 1
            sid = f"S{sess_counter:04d}"
            history: list[dict] = []
            # 恢复上一 session 末轮未消费的工具结果（首轮 obs 消费后随即失效）
            tool_results: list = list(pending_results)
            pending_results.clear()
            results_fresh = bool(tool_results)
            # 复读熔断状态（每 session 重置）：相邻发言相似度超阈值的连续计数
            prev_user_say: str | None = None
            prev_asst_reply: str | None = None
            user_repeats = 0
            asst_repeats = 0
            booked: list[str] = []  # 本 session 实际落单的事件名（close 时通知用户记忆）

            for turn_no in range(max_turns):
                # ---- 软上限提示（接近轮数上限时暗示收尾）----
                hint = ""
                if turn_no >= soft_turn_limit:
                    hint = "（你们聊了挺久了，如果事情办好了可以结束对话了）"
                if user_repeats >= _REPEAT_HINT_AFTER:
                    hint += "（你刚才已经说过同样的话了——如果没有新的事，就说再见结束对话）"

                # ---- 用户说 ----
                try:
                    resp = broker.submit("user", run_id, "speak", SpeakRequest(
                        context=uctx,
                        history=[DialogueTurn(speaker=h["speaker"], text=h["text"]) for h in history],
                        intent_description=intent.description + (f"\n{hint}" if hint else ""),
                    ).model_dump(mode="json"), timeout=resp_timeout)
                    ua = UserAction(**resp.result)
                except (AgentTimeout, AgentError, ValidationError) as e:
                    emit("system", f"用户 Agent 降级（{e}）", x_snapshot, None, sid, degraded=True)
                    break

                user_repeats = user_repeats + 1 if _similar(prev_user_say, ua.say) else 0
                prev_user_say = ua.say
                emit("user", ua.say, x_snapshot, None, sid,
                     tool_calls=[ToolCall(name="open_session")] if turn_no == 0 else [],
                     felt_state=uctx.felt_state if turn_no == 0 else None)
                history.append({"speaker": "user", "text": ua.say})

                if user_repeats >= _REPEAT_FUSE_AFTER:
                    emit("system", "复读熔断：用户连续复述同一内容，session 由 runner 强制收尾",
                         x_snapshot, None, sid)
                    break

                if ua.end_session:
                    break

                # ---- 助手回 ----
                slot_names = list(cfg.clock.slot_names)
                today_events = [
                    e for e in world.events
                    if e.kind in ("recovery", "series", "disturbance")
                    and world.t <= e.start_slot < (world.day + 1) * world.slots_per_day
                ][:8]
                schedule_hint = "；".join(
                    f"{e.name}（{slot_names[e.start_slot % world.slots_per_day]}）"
                    for e in today_events
                )
                obs = HarnessObs(
                    user_say=ua.say,
                    history=[DialogueTurn(speaker=h["speaker"], text=h["text"]) for h in history],
                    tool_results=tool_results,
                    balance=world.money,
                    schedule_hint=schedule_hint,
                    recovery_catalog=_recovery_catalog(world),
                    slot_names=slot_names,
                    day=world.day,
                    slot=world.slot,
                )
                results_fresh = False  # obs 已消费当前 tool_results
                try:
                    resp = broker.submit("assistant", run_id, "on_turn",
                                         obs.model_dump(mode="json"), timeout=resp_timeout)
                    at = AssistantTurn(**resp.result)
                    # 画像快照：agent 回了 persona_hat 就直接落盘并作为新基线；
                    # 否则退化为本轮 user_belief.persona_belief 增量的 Runner 侧 EMA 累积
                    # （persona_notes 作为 notes 一并并入，与第一方 Harness 语义一致）。
                    if resp.persona_hat is not None:
                        persona_hat = resp.persona_hat
                        hat_fallback = resp.persona_hat
                    else:
                        delta = at.user_belief.persona_belief
                        if delta is not None:
                            if not delta.notes and at.user_belief.persona_notes:
                                delta = delta.model_copy(
                                    update={"notes": at.user_belief.persona_notes})
                        elif at.user_belief.persona_notes:
                            delta = PersonaBeliefDelta(notes=at.user_belief.persona_notes)
                        if delta is not None:
                            hat_fallback = merge_persona_delta(hat_fallback, delta)
                            persona_hat = hat_fallback
                        else:
                            persona_hat = None
                    violation = None
                except (AgentTimeout, AgentError, ValidationError) as e:
                    at = None
                    persona_hat = None
                    violation = _assistant_violation(e)

                if at is None:
                    emit("system", f"助手契约违约：{violation}", x_snapshot, None, sid,
                         violation=violation)
                    break

                # ---- 工具执行 ----
                tool_results = []
                for call in at.tool_calls:
                    if call.name == "view_event_todos":
                        tool_results.append(world.view_event_todos())
                    elif call.name == "add_event_todo":
                        a = call.args
                        res = world.add_event_todo(
                            name=str(a.get("name", "恢复事件")),
                            day_offset=int(a.get("day_offset", 0)),
                            slot=int(a.get("slot", 2)),
                            goal=str(a.get("goal", a.get("name", "恢复"))),
                            effect={k: float(v) for k, v in (a.get("effect") or {}).items()
                                    if k in ("valence", "energy", "satiety", "stress")},
                            span_slots=max(1, int(a.get("span_slots", 1))),
                            caused_by_session_id=sid,
                            location=str(a["location"]) if a.get("location") else None,
                        )
                        tool_results.append(res)
                        if res.ok:
                            booked.append(str((res.payload or {}).get("name")
                                              or a.get("name", "恢复事件")))
                    elif call.name == "plan_series":
                        a = call.args
                        res = world.plan_series(
                            series_type=str(a.get("series_type", "staycation")),
                            start_day_offset=int(a.get("start_day_offset", 1)),
                            duration=int(a.get("duration", 5)),
                        )
                        tool_results.append(res)
                        if res.ok:
                            booked.append(str((res.payload or {}).get("name")
                                              or a.get("series_type", "staycation")))
                    elif call.name == "set_reminder":
                        a = call.args
                        tool_results.append(world.set_reminder(
                            message=str(a.get("message", a.get("content", ""))),
                            time_str=str(a.get("time", a.get("time_str", ""))),
                        ))
                    else:
                        tool_results.append(ToolResult(name=call.name, ok=False,
                                                        payload={"error": "未知工具"}))
                results_fresh = True  # 本轮执行结果尚未被任何 obs 消费

                asst_repeats = asst_repeats + 1 if _similar(prev_asst_reply, at.reply) else 0
                prev_asst_reply = at.reply
                emit("assistant", at.reply, x_snapshot, at.user_belief.to_statevec(), sid,
                     tool_calls=at.tool_calls, tool_results=tool_results,
                     persona_hat=persona_hat)
                history.append({"speaker": "assistant", "text": at.reply})

                if asst_repeats >= _REPEAT_HINT_AFTER:
                    emit("system", "复读熔断：助手连续复述同一内容，session 由 runner 强制收尾",
                         x_snapshot, None, sid)
                    break

            # session 结束：通知用户 agent 更新自己的记忆（失败不中断 episode）
            turns_in_session = len(history) // 2
            emit("system", f"Session 结算：{turns_in_session} 轮对话",
                 x_snapshot, None, sid,
                 tool_calls=[ToolCall(name="close_session")])
            try:
                broker.submit("user", run_id, "session_closed",
                              SessionClosedNotice(session_id=sid, intent_type=intent.type,
                                                  turns=turns_in_session, day=world.day,
                                                  activities=booked)
                              .model_dump(mode="json"),
                              timeout=min(10.0, resp_timeout))
            except Exception:  # noqa: BLE001 — 记忆通知丢失不影响世界推进
                pass
            # 末轮 assistant 的执行结果若未被消费，带入下一 session 首轮
            if results_fresh and tool_results:
                pending_results = list(tool_results)

        # ---- 步骤 5：推进时间 ----
        settlement = world.step_slot()
        _write_jsonl(slots_path, settlement)
        if on_event:
            on_event({"type": "slot", "data": settlement.model_dump()})

    _write_meta(run_dir, run_id, world, "live", None, harness=meta_harness,
                prompt_versions=prompt_versions, profiles=profiles)
    agent_state = {role: broker.get_state(run_id, role) for role in ("user", "assistant")}
    _save_state(run_dir, world, sess_counter, turn_counter, agent_state=agent_state)
    return run_dir
