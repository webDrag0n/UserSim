"""评估报告：report.json 生成与终端摘要。"""

from __future__ import annotations

import json
from pathlib import Path

from usersim.evaluator.metrics import compute_metrics, load_run

VERDICT_LABELS = {
    "converged": "收敛稳定",
    "oscillating": "欠阻尼振荡",
    "diverged": "发散失控",
}


def evaluate_run(run_dir: Path, cfg, write_insights: bool = True) -> dict:
    """对单个 run 目录离线计算指标，写 report.json（+insights.json）并返回报告 dict。

    insights 一并落盘：此前它只由 API 按需计算、从不持久化，导致批量评测拿不到
    health_score，且同一 run 的诊断结论无法归档比对。
    """
    from usersim.evaluator.insights import compute_insights

    slots, turns, meta = load_run(run_dir)
    targets = cfg.state.targets.to_dict()
    band = float(cfg.state.band)
    report = compute_metrics(slots, turns, targets, band, cfg.eval, persona=meta.get("persona"))
    # 契约违约拆分（v5）：超时（assistant_timeout，provider 延迟/容量问题）与
    # 协议违约（schema/JSON/crash，被测件真实协议能力）分开计数——
    # 此前合并计数导致并发/慢 provider 下 reference 组"违约率"12-16% 的假象。
    # benchmark 只扣协议违约；超时进 health_score 的故障诊断。
    n_assistant_turns = sum(1 for t in turns if t.speaker == "assistant")
    n_timeouts = sum(1 for t in turns
                     if t.contract_violation and t.contract_violation.startswith("assistant_timeout"))
    report["contract_timeouts"] = n_timeouts
    report["contract_violations"] = sum(
        1 for t in turns if t.contract_violation
        and not t.contract_violation.startswith("assistant_timeout"))
    report["contract_violation_rate"] = round(
        report["contract_violations"] / max(1, n_assistant_turns), 4)
    report["contract_timeout_rate"] = round(n_timeouts / max(1, n_assistant_turns), 4)
    # 对话形态指标（0-LLM 纯字符串统计）：复读率/口癖率/熔断数，供 prompt 改动做 before/after 对照
    from usersim.evaluator.dialogue import compute_dialogue_stats

    report["dialogue"] = compute_dialogue_stats(turns)
    report["run_id"] = meta["run_id"]
    report["seed"] = meta["seed"]
    report["mode"] = meta.get("mode")
    report["assistant_quality"] = meta.get("assistant_quality")
    report["harness"] = meta.get("harness")
    report["verdict_label"] = VERDICT_LABELS.get(report["verdict"], report["verdict"])

    if write_insights:
        insights = compute_insights(slots, turns, meta, targets, band, score_cfg=cfg.get("score"))
        report["health_score"] = insights.get("health_score")
        # benchmark 分：全部存档指标 → 单一百分制（公式与理由见 docs/04-evaluator.md 第 8 节）
        from usersim.evaluator.score import compute_benchmark

        report["benchmark"] = compute_benchmark(
            report, insights.get("stats", {}).get("score_observations", {}),
            days=int(meta.get("days") or 1), cfg=cfg.get("benchmark"))
        (run_dir / "insights.json").write_text(
            json.dumps(insights, ensure_ascii=False, indent=2), encoding="utf-8")

    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def format_summary(report: dict) -> str:
    st = report["settling_time_days"]
    lines = [
        f"run: {report['run_id']}  seed={report['seed']}  mode={report['mode']}  quality={report.get('assistant_quality')}",
        f"判定: {report['verdict_label']} ({report['verdict']})",
        f"  e_ss        = {report['ess']:.4f}   (稳态误差)",
        f"  t_s         = {('未稳定' if st is None else f'{st:.2f} 天')}   (调节时间)",
        f"  M_p         = {report['overshoot']:.4f}   (超调量)",
        f"  IAE/ISE/ITAE= {report['iae']:.2f} / {report['ise']:.2f} / {report['itae']:.2f}",
        f"  σ²          = {report['variance']:.5f}   (状态方差)",
        f"  带内驻留比  = {report['in_band_ratio'] * 100:.0f}%",
        f"  ‖x−x̂‖ 终值  = {report['est_err_final']:.4f}  斜率 = {report['est_err_slope_per_day']:.5f}/天",
    ]
    bench = report.get("benchmark")
    if bench:
        lines.append(f"  benchmark   = {bench['score']:.1f}/100 ({bench['version']}，明细见 report.json benchmark)")
    if report.get("persona_err_final") == report.get("persona_err_final"):  # 非 NaN
        lines.append(
            f"  画像误差    = {report['persona_err_final']:.4f}  斜率 = "
            f"{report.get('persona_err_slope_per_day', 0.0):.5f}/天  "
            f"覆盖 {report.get('persona_coverage', 0) * 100:.0f}%"
        )
        lines.append(
            f"  喜好误差    = {report['prefs_err_final']:.4f}  爱憎命中 F1 = {report['prefs_tag_f1']:.2f}"
        )
    return "\n".join(lines)
