"""深度诊断 v2：免读轨迹的完整优化报告。

设计目标：开发者优化世界真实性 / 拟人性 / 助手能力时，只看本模块输出即可定位问题，
不再需要翻阅超长轨迹日志。结构：
  summary（一段话说清本次运行）
  health_score（0-100 综合健康分）
  findings（含优化建议）
  dims / disturbances / sessions / economy / repetition / slot_profile / series_analysis
"""

from __future__ import annotations

from collections import Counter

from usersim.contracts import SlotSettlement, TurnRecord
from usersim.world.dynamics import DIMS, dim_error, total_error

DIM_LABELS = {"valence": "心情", "energy": "精力", "satiety": "饱腹", "stress": "压力"}
SEVERITY_ORDER = {"error": 0, "warn": 1, "info": 2}


def _f(sev: str, cat: str, title: str, detail: str, suggestion: str = "", evidence: str = "") -> dict:
    return {"severity": sev, "category": cat, "title": title, "detail": detail,
            "suggestion": suggestion, "evidence": evidence}


def compute_insights(
    slots: list[SlotSettlement],
    turns: list[TurnRecord],
    meta: dict,
    targets: dict[str, float],
    band: float,
) -> dict:
    findings: list[dict] = []
    stats: dict = {}
    days_n = max(1, (slots[-1].t_logical // 4 + 1) if slots else 1)

    # ================= 逐维控制指标 =================
    dims = []
    for d in DIMS:
        errs = [dim_error(s.x_after, d, targets) for s in slots]
        vals = [getattr(s.x_after, d) for s in slots]
        hats = [t for t in turns if t.x_hat]
        mae = bias = None
        if hats:
            mae = sum(abs(getattr(t.x_hat, d) - getattr(t.x_true, d)) for t in hats) / len(hats)
            bias = sum(getattr(t.x_hat, d) - getattr(t.x_true, d) for t in hats) / len(hats)
        dims.append({
            "dim": d, "label": DIM_LABELS[d], "target": targets[d],
            "mean_err": round(sum(errs) / max(1, len(errs)), 4),
            "in_band": round(sum(1 for e in errs if e <= band) / max(1, len(errs)), 3),
            "mean": round(sum(vals) / max(1, len(vals)), 3),
            "min": round(min(vals, default=0), 2), "max": round(max(vals, default=0), 2),
            "xhat_mae": round(mae, 4) if mae is not None else None,
            "xhat_bias": round(bias, 4) if bias is not None else None,
        })
    worst_dim = max(dims, key=lambda x: x["mean_err"])
    if worst_dim["mean_err"] > 0.06:
        findings.append(_f("warn", "世界", f"控制最差维度：{worst_dim['label']}（平均误差 {worst_dim['mean_err']:.3f}）",
                           f"该维度带内驻留仅 {worst_dim['in_band']:.0%}，是拖低整体收敛的主因。",
                           f"检查与 {worst_dim['label']} 相关的动力学系数与恢复配表强度（工作消耗/恢复回血/自然漂移平衡）。"))
    bias_dim = max((d for d in dims if d["xhat_bias"] is not None), key=lambda x: abs(x["xhat_bias"]), default=None)
    if bias_dim and abs(bias_dim["xhat_bias"]) > 0.08:
        findings.append(_f("warn", "助手", f"x̂ 系统性偏差：{bias_dim['label']} {'高估' if bias_dim['xhat_bias'] > 0 else '低估'} {abs(bias_dim['xhat_bias']):.2f}",
                           "估计器对该维度存在系统性偏移（所有 turn 的平均符号误差）。",
                           "在 Harness 的 user_model 中加入逐维校准项，或在提示中给出该维度的参考刻度。"))

    # ================= 契约与故障 =================
    violations = [t for t in turns if t.contract_violation]
    degraded = [t for t in turns if t.degraded]
    if violations:
        findings.append(_f("error", "契约", f"助手契约违约 ×{len(violations)}",
                           "AssistantTurn 未按契约输出（缺 user_belief / JSON 失败）。",
                           "检查 provider 的 structured output 兼容性；加强契约修复重试的提示词。",
                           violations[0].contract_violation or ""))
    if degraded:
        findings.append(_f("warn", "故障", f"LLM 调用降级 ×{len(degraded)}",
                           "LLM 超时/失败重试耗尽后跳过 turn。",
                           "检查 provider 稳定性、提高 timeout_s 或 max_retries；评估是否切换更稳定的模型。"))

    tool_fails = Counter()
    for t in turns:
        for r in t.tool_results:
            if not r.ok:
                tool_fails[r.payload.get("error", r.name)] += 1
    fail_total = sum(tool_fails.values())
    call_total = sum(len(t.tool_results) for t in turns)
    for reason, n in tool_fails.most_common(3):
        if "金钱不足" in reason:
            findings.append(_f("info", "工具", f"预算被拒 ×{n}", "助手安排恢复时余额不足。",
                               "这是经济博弈的正常信号；若高频出现，教助手先查余额或优先平价档。"))
        elif "冲突" in reason:
            findings.append(_f("warn", "工具", f"日程冲突 ×{n}",
                               "助手在同一时段重复安排恢复事件（不看已有日程就写）。",
                               "提示助手在 add_event_todo 前先 view_event_todos；或在 Harness 中缓存最近安排。"))
        else:
            findings.append(_f("warn", "工具", f"工具失败：{reason} ×{n}", "非预期失败原因。",
                               "检查工具参数 schema 与世界端校验逻辑。"))
    stats["tool_success_rate"] = round(1 - fail_total / max(1, call_total), 3) if call_total else None

    # ================= 拟人性 =================
    user_texts = [t.text for t in turns if t.speaker == "user"]
    asst_texts = [t.text for t in turns if t.speaker == "assistant"]
    user_dup = sum(1 for a, b in zip(user_texts, user_texts[1:]) if a == b)
    if user_dup >= 2:
        findings.append(_f("warn", "拟人性", f"用户连续重复台词 ×{user_dup}",
                           "同一文本连续出现——用户 LLM 表演同质化。",
                           "prompt 中加入'不要重复上一句'；提高温度或引入更多样化的感受表达模板。"))
    rep_user = Counter(user_texts).most_common(5)
    rep_asst = Counter(asst_texts).most_common(5)
    if rep_user and rep_user[0][1] >= 3:
        findings.append(_f("warn", "拟人性", f"高频台词：「{rep_user[0][0][:20]}…」×{rep_user[0][1]}",
                           "非连续但反复出现的口头禅式表达。",
                           "为 felt_state 分档词典增加同义变体；persona 台词风格化。"))

    # 求助时延与无求助
    dist_slots_sorted = sorted({s.t_logical for s in slots if any(eid.startswith("D") for eid in s.active_event_ids)})
    session_ts = sorted({t.t_logical for t in turns if t.session_id and t.speaker == "user"})
    latencies, missed = [], 0
    for ds in dist_slots_sorted:
        nxt = next((st for st in session_ts if st >= ds), None)
        if nxt is None:
            missed += 1
        else:
            latencies.append(nxt - ds)
    if missed:
        findings.append(_f("warn", "拟人性", f"{missed} 次扰动后用户始终未求助",
                           "状态受损却不开 session。",
                           "检查 decide_open 的 prompt 倾向与 help_seek 阈值；人格中可加入'遇事倾向求助'的权重。"))
    if latencies:
        avg_lat = sum(latencies) / len(latencies)
        if avg_lat > 3:
            findings.append(_f("info", "拟人性", f"平均求助时延 {avg_lat:.1f} 时段",
                               "偏迟钝的求助行为。",
                               "真人通常在状态恶化当期就会寻求支持；可适当提高 assist_prompt 的紧迫感。"))

    # ================= 世界真实性 =================
    clamp_hits = sum(1 for s in slots for v in s.x_after.model_dump().values() if v <= 0.001 or v >= 0.999)
    clamp_ratio = clamp_hits / max(1, len(slots) * 4)
    if clamp_ratio > 0.08:
        findings.append(_f("warn", "世界", f"状态饱和率 {clamp_ratio:.1%}",
                           "状态频繁顶到 [0,1] 边界，损失分辨力。",
                           "检查扰动/恢复/动力学系数的量级平衡，避免极端摆幅。"))
    debt_slots = sum(1 for s in slots if s.money_after < 0)
    if debt_slots:
        findings.append(_f("info", "世界", f"负债 {debt_slots} 时段（{debt_slots // 4} 天）",
                           "金钱为负，负债压力持续作用。",
                           "若负债过长，检查职业收入与生活成本/恢复消费的平衡。"))

    recov_days = {t.t_logical // 4 for t in turns for r in t.tool_results if r.name == "add_event_todo" and r.ok}
    high_no_rec = 0
    for d in range(days_n):
        day_slots = slots[d * 4:(d + 1) * 4]
        if day_slots and sum(s.x_after.stress for s in day_slots) / len(day_slots) > 0.55 and d not in recov_days:
            high_no_rec += 1
    if high_no_rec >= 3:
        findings.append(_f("warn", "助手", f"高压无恢复日 ×{high_no_rec}",
                           "日均压力 >0.55 却全天无恢复安排——干预缺失。",
                           "检查干预触发链路（求助→估计→安排）；压力高时应有更强的主动建议。"))

    # ================= 扰动-恢复配对分析 =================
    disturbances = []
    for t_logical in dist_slots_sorted:
        s0 = slots[t_logical].x_after if t_logical < len(slots) else None
        s1 = slots[t_logical + 1].x_after if t_logical + 1 < len(slots) else None
        if not s0 or not s1:
            continue
        stress_jump = s1.stress - s0.stress
        rec_t = next((tt.t_logical for tt in turns
                      if tt.t_logical >= t_logical
                      for r in tt.tool_results if r.name == "add_event_todo" and r.ok), None)
        t2b = None
        for k in range(t_logical, min(len(slots), t_logical + 32)):
            if dim_error(slots[k].x_after, "stress", targets) <= band:
                t2b = k - t_logical
                break
        dname = next((eid for eid in slots[t_logical].active_event_ids if eid.startswith("D")), "D?")
        disturbances.append({
            "t": t_logical, "day": t_logical // 4 + 1, "event": dname,
            "stress_jump": round(stress_jump, 3),
            "recover_in_slots": (rec_t - t_logical) if rec_t is not None else None,
            "time_to_band_slots": t2b,
        })
    no_recover = [d for d in disturbances if d["recover_in_slots"] is None]
    if len(no_recover) >= max(2, len(disturbances) // 3):
        findings.append(_f("warn", "助手", f"{len(no_recover)}/{len(disturbances)} 次扰动后无恢复安排",
                           "扰动响应覆盖率过低。",
                           "扰动是最明确的干预时机——提高 assist_prompt 触发后的安排率。"))
    slow = [d for d in disturbances if d["time_to_band_slots"] is not None and d["time_to_band_slots"] > 6]
    if slow:
        findings.append(_f("info", "助手", f"恢复缓慢扰动 ×{len(slow)}",
                           "部分扰动超过 6 个时段才回到带内。",
                           "恢复强度不足（选档太低）或恢复时机过晚；检查配表档位的减压幅度。"))

    # ================= session 分析 =================
    sessions = []
    sess_map: dict[str, list[TurnRecord]] = {}
    for t in turns:
        if t.session_id:
            sess_map.setdefault(t.session_id, []).append(t)
    for sid, ts in sess_map.items():
        asst = [t for t in ts if t.x_hat]
        tools = [c.name for t in ts for c in t.tool_calls]
        added = any(r.name == "add_event_todo" and r.ok for t in ts for r in t.tool_results)
        sessions.append({
            "id": sid, "day": ts[0].t_logical // 4 + 1, "t": ts[0].t_logical,
            "turns": len(ts),
            "tools": sorted(set(tools)),
            "belief_err_start": _bel_err(asst[0]) if asst else None,
            "belief_err_end": _bel_err(asst[-1]) if asst else None,
            "added_recovery": added,
        })
    no_action = [s for s in sessions if not s["added_recovery"] and s["turns"] >= 4]
    if len(no_action) >= 3:
        findings.append(_f("info", "助手", f"纯聊天 session ×{len(no_action)}",
                           "多轮对话但没有任何恢复行动（只安慰不解决）。",
                           "鼓励助手在共情后落到具体安排；检查工具使用的提示权重。"))
    frozen_sess = [s for s in sessions if s["belief_err_start"] is not None and s["belief_err_end"] is not None
                   and s["belief_err_end"] > s["belief_err_start"] + 0.05]
    if len(frozen_sess) >= 2:
        findings.append(_f("warn", "助手", f"session 内估计反而变差 ×{len(frozen_sess)}",
                           "对话深入后 x̂ 与真实状态的距离反而增大——估计器在带偏自己。",
                           "检查 Harness 的 belief 更新逻辑：新信息应单调改善估计，而不是被先验锚定。"))

    # ================= 经济分析 =================
    money = [s.money_after for s in slots]
    income_events = Counter()
    cost_events = Counter()
    for t in turns:
        for r in t.tool_results:
            if r.name == "add_event_todo" and r.ok and "event" in r.payload:
                ev = r.payload["event"]
                nm = ev.get("name", "?").split(" · ")[0]
                cost_events[nm] += ev.get("cost", 0)
    for s in slots:
        for eid in s.active_event_ids:
            if eid.startswith("D"):
                income_events["扰动收入"] += 0  # 占位（明细在事件表）
    stats["economy"] = {
        "money_start": round(money[0]) if money else 0,
        "money_end": round(money[-1]) if money else 0,
        "money_min": round(min(money, default=0)),
        "money_max": round(max(money, default=0)),
        "debt_days": debt_slots // 4,
        "recovery_spend_by_action": dict(sorted(cost_events.items(), key=lambda x: -x[1])[:8]),
    }

    # ================= 时段画像 =================
    slot_profile = []
    for sl in range(4):
        xs = [slots[i].x_after for i in range(sl, len(slots), 4)]
        if xs:
            slot_profile.append({
                "slot": sl, "name": ["上午", "下午", "晚上", "深夜"][sl],
                "stress": round(sum(x.stress for x in xs) / len(xs), 3),
                "energy": round(sum(x.energy for x in xs) / len(xs), 3),
                "valence": round(sum(x.valence for x in xs) / len(xs), 3),
                "satiety": round(sum(x.satiety for x in xs) / len(xs), 3),
            })
    worst_slot = max(slot_profile, key=lambda x: x["stress"], default=None)
    if worst_slot and worst_slot["stress"] > 0.5:
        findings.append(_f("info", "世界", f"压力高峰时段：{worst_slot['name']}（均 {worst_slot['stress']:.2f}）",
                           "压力呈明显日内节律。",
                           "若节律过强说明工作扰动集中在该时段；可建议助手在该时段前预防性安排。"))

    # ================= 系列事件分析 =================
    series_analysis = []
    for sid in {e.series_id for t in turns for r in t.tool_results if "event" in r.payload for e in [r.payload["event"]] if e.get("series_id")}:
        pass  # 系列经由 run_state 更可靠，此处从 slots 的 active_series 统计
    series_spans: dict[str, list[int]] = {}
    for s in slots:
        if s.active_series:
            series_spans.setdefault(s.active_series, []).append(s.t_logical)
    for name, ts in series_spans.items():
        first, last = ts[0], ts[-1]
        v_before = slots[first].x_before.valence if first < len(slots) else None
        v_during = sum(slots[t].x_after.valence for t in ts) / len(ts)
        v_after = slots[last + 4].x_after.valence if last + 4 < len(slots) else None
        series_analysis.append({
            "name": name, "days": f"第 {first // 4 + 1}~{last // 4 + 1} 天",
            "valence_before": round(v_before, 3) if v_before is not None else None,
            "valence_during": round(v_during, 3),
            "valence_after": round(v_after, 3) if v_after is not None else None,
        })
    for sa in series_analysis:
        if sa["valence_after"] is not None and sa["valence_before"] is not None and sa["valence_after"] < sa["valence_before"] - 0.05:
            findings.append(_f("info", "世界", f"系列「{sa['name']}」后心情反而下降",
                               "系列结束后的后效为负（期待落空/疲惫/空虚）。",
                               "检查该系列的后效定义与期间强度（是否过累或预算失控）。"))

    # ================= 重复文本样本 =================
    stats["repetition"] = {
        "user_top": [{"text": t[:40], "count": c} for t, c in rep_user if c >= 2],
        "assistant_top": [{"text": t[:40], "count": c} for t, c in rep_asst if c >= 2],
        "user_dup_consecutive": user_dup,
        "avg_user_len": round(sum(len(x) for x in user_texts) / max(1, len(user_texts)), 1),
        "avg_asst_len": round(sum(len(x) for x in asst_texts) / max(1, len(asst_texts)), 1),
    }

    # ================= 估计器细节 =================
    hats = [t for t in turns if t.x_hat]
    if hats:
        frozen = sum(1 for a, b in zip(hats, hats[1:]) if a.x_hat == b.x_hat) / max(1, len(hats) - 1)
        if frozen > 0.3:
            findings.append(_f("warn", "助手", f"估计更新停滞率 {frozen:.0%}",
                               "相邻 turn 的 user_belief 大量不变。",
                               "Harness 应在每条新信息后刷新估计；检查 user_model 是否真的被调用。"))
        stats["belief_frozen_ratio"] = round(frozen, 3)

    # ================= 健康分与摘要 =================
    ess = sum(total_error(s.x_after, targets) for s in slots[-12:]) / max(1, len(slots[-12:]))
    max_bias = max((abs(d["xhat_bias"]) for d in dims if d["xhat_bias"] is not None), default=0)
    health = 100.0
    health -= min(40, ess * 200)
    health -= min(15, len(violations) * 5)
    health -= min(10, max_bias * 80)
    health -= min(10, user_dup * 1.5)
    health -= min(10, clamp_ratio * 80)
    health -= min(10, len(no_recover) * 2)
    health = max(0, round(health))
    stats["health_score"] = health
    stats["ess"] = round(ess, 4)
    stats["n_turns"] = len(turns)
    stats["n_sessions"] = len(sessions)
    stats["days"] = days_n

    n_err = sum(1 for f in findings if f["severity"] == "error")
    n_warn = sum(1 for f in findings if f["severity"] == "warn")
    persona = meta.get("persona", {})
    top_sugs = [f for f in findings if f["suggestion"]][:3]
    summary = (
        f"本次运行 {days_n} 天 · 角色 {persona.get('name', '?')}（{persona.get('archetype', '?')}）· "
        f"{len(sessions)} 个 session / {len(turns)} 个 turn · 健康分 {health}/100。"
        f"最差维度：{worst_dim['label']}（带内 {worst_dim['in_band']:.0%}）；"
        f"扰动 {len(disturbances)} 次，{len(no_recover)} 次无恢复响应；"
        f"发现 {n_err} 个故障、{n_warn} 个警告。"
        + ("首要建议：" + top_sugs[0]["suggestion"] if top_sugs else "整体健康，无紧急问题。")
    )

    findings.sort(key=lambda f: SEVERITY_ORDER.get(f["severity"], 3))
    return {
        "summary": summary,
        "health_score": health,
        "findings": findings,
        "dims": dims,
        "disturbances": disturbances,
        "sessions": sessions[:50],
        "sessions_total": len(sessions),
        "slot_profile": slot_profile,
        "series_analysis": series_analysis,
        "stats": stats,
    }


def _bel_err(t: TurnRecord) -> float | None:
    if not t.x_hat:
        return None
    return round(((t.x_true.valence - t.x_hat.valence) ** 2 + (t.x_true.energy - t.x_hat.energy) ** 2
                  + (t.x_true.satiety - t.x_hat.satiety) ** 2 + (t.x_true.stress - t.x_hat.stress) ** 2) ** 0.5, 4)
