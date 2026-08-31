"""Benchmark 分数公式（evaluator/score.py）与 run 的 profiles 记录。

纯函数测试不起子进程、不调 LLM；归档集成测试用手写合成 run 目录（全程确定）。
"""

import json
import math

from usersim.config import load_system_config
from usersim.evaluator.score import FORMULA_TEXT, compute_benchmark, report_observations


def _report(**over):
    base = {
        "ess": 0.0, "settling_time_days": 0.0, "overshoot": 0.0,
        "iae": 0.0, "variance": 0.0, "in_band_ratio": 1.0,
        "est_err_final": 0.0, "est_err_slope_per_day": 0.0,
        "persona_err_final": 0.0, "persona_coverage": 1.0,
        "prefs_err_final": 0.0, "prefs_tag_f1": 1.0,
    }
    base.update(over)
    return base


class TestFormula:
    def test_perfect_run_scores_100(self):
        out = compute_benchmark(_report(), {}, days=30)
        assert out["score"] == 100.0
        assert out["formula"] == FORMULA_TEXT
        assert all(t["deduct"] == 0 for t in out["terms"])

    def test_deduction_is_linear_then_capped(self):
        # ess 0.05 × 200 = 10 分（线性区）；ess 0.5 × 200 = 100 → 封顶 30
        out = compute_benchmark(_report(ess=0.05), {}, days=30)
        ess = next(t for t in out["terms"] if t["key"] == "ess")
        assert ess["deduct"] == 10.0
        out2 = compute_benchmark(_report(ess=0.5), {}, days=30)
        ess2 = next(t for t in out2["terms"] if t["key"] == "ess")
        assert ess2["deduct"] == 30.0 == ess2["cap"]

    def test_unsettled_counts_as_full_fraction(self):
        obs = report_observations(_report(settling_time_days=None), days=30)
        assert obs["settle_frac"] == 1.0
        obs2 = report_observations(_report(settling_time_days=6.0), days=30)
        assert obs2["settle_frac"] == 0.2

    def test_iae_normalized_by_days(self):
        # 同样的 mean|e|，30 天与 60 天 run 的 iae_daily 必须相等（否则长 run 吃亏）
        assert (report_observations(_report(iae=3.0), 30)["iae_daily"]
                == report_observations(_report(iae=6.0), 60)["iae_daily"])

    def test_missing_estimates_count_full_error(self):
        obs = report_observations(_report(est_err_final=math.nan,
                                          persona_err_final=math.nan,
                                          prefs_err_final=math.nan), days=30)
        assert obs["est_err"] == obs["persona_err"] == obs["prefs_err"] == 0.5

    def test_score_floors_at_zero(self):
        out = compute_benchmark(_report(ess=1.0, settling_time_days=None, overshoot=1.0,
                                        iae=100.0, variance=1.0, in_band_ratio=0.0,
                                        est_err_final=1.0, est_err_slope_per_day=0.01,
                                        persona_err_final=1.0, persona_coverage=0.0,
                                        prefs_err_final=1.0, prefs_tag_f1=0.0),
                                {"violations": 99}, days=10)
        assert out["score"] == 0.0

    def test_insight_observations_feed_contract_group(self):
        # v3：混杂指标（user_dup/clamp_ratio/wsc）移出 benchmark，传了也不计分
        out = compute_benchmark(_report(), {"violations": 2, "user_dup": 4,
                                            "clamp_ratio": 0.5}, days=30)
        v = next(t for t in out["terms"] if t["key"] == "violations")
        assert v["deduct"] == 10.0 and v["group"] == "contract"
        assert out["groups"]["contract"]["deduct"] == 10.0
        assert "user_dup" not in {t["key"] for t in out["terms"]}

    def test_config_overrides_weights(self):
        cfg = {"ess": [100.0, 5.0]}
        out = compute_benchmark(_report(ess=0.5), {}, days=30, cfg=cfg)
        ess = next(t for t in out["terms"] if t["key"] == "ess")
        assert ess["coef"] == 100.0 and ess["deduct"] == 5.0

    def test_groups_cover_all_terms(self):
        out = compute_benchmark(_report(), {}, days=30)
        assert {t["group"] for t in out["terms"]} == {"control", "belief", "contract"}
        assert set(out["groups"]) == {"control", "belief", "contract"}


class TestArchiveIntegration:
    def test_run_records_profiles_and_benchmark(self, tmp_path):
        """合成 run 目录（手写 meta/slots/turns）经 evaluate_run 的归档结构。

        replay 下线后不再起真实 run：profiles 记录与 benchmark 结构断言不变，
        数据为合成 fixture（0 LLM）。
        """
        from usersim.contracts import Persona, RunMeta, SlotSettlement, StateVec, TurnRecord
        from usersim.evaluator.report import evaluate_run

        cfg = load_system_config()
        run_dir = tmp_path / "synth_run"
        run_dir.mkdir()

        x = StateVec(valence=0.72, energy=0.70, satiety=0.65, stress=0.30)
        with (run_dir / "slots.jsonl").open("w", encoding="utf-8") as f:
            for t in range(5 * 4):
                s = SlotSettlement(t_logical=t, x_before=x, x_after=x, slots_per_day=4)
                f.write(json.dumps(s.model_dump(), ensure_ascii=False) + "\n")
        with (run_dir / "turns.jsonl").open("w", encoding="utf-8") as f:
            t_rec = TurnRecord(run_id="synth_run", t_logical=1, turn_id=0,
                               speaker="assistant", text="好的，我来安排。",
                               x_true=x, x_hat=x)
            f.write(json.dumps(t_rec.model_dump(), ensure_ascii=False) + "\n")

        persona = Persona(name="合成角色", archetype="上班族",
                          big5={"神经质": 50, "外向性": 50, "开放性": 50},
                          likes="喜欢安静", routine="朝九晚五",
                          x0=StateVec(valence=0.7, energy=0.75, satiety=0.6, stress=0.28))
        profiles = {"user": "standard", "assistant": "reference"}
        meta = RunMeta(run_id="synth_run", seed=42, started_at="2026-08-19T00:00:00+00:00",
                       days=5, config_hash="synthetic", persona=persona, profiles=profiles)
        (run_dir / "meta.json").write_text(meta.model_dump_json(indent=2), encoding="utf-8")

        on_disk_meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
        assert on_disk_meta["profiles"] == profiles

        report = evaluate_run(run_dir, cfg)
        bench = report["benchmark"]
        assert 0.0 <= bench["score"] <= 100.0
        assert bench["formula"] == FORMULA_TEXT
        on_disk = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        assert on_disk["benchmark"]["score"] == bench["score"]
        # insights 观测量已导出（benchmark 的契约项数据源）
        stats = json.loads((run_dir / "insights.json").read_text(encoding="utf-8"))["stats"]
        assert "violations" in stats["score_observations"]
