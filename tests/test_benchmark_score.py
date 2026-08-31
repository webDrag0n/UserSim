"""Benchmark 分数公式 v4（evaluator/score.py）与 run 的 profiles 记录。

v4 精简为 3 个扣分项：ess / band_deficit / coverage_deficit（依据：历史 bench
数据的区分度分析）。纯函数测试不起子进程、不调 LLM；归档集成测试用手写合成
run 目录（全程确定）。
"""

import json

from usersim.config import load_system_config
from usersim.evaluator.score import FORMULA_TEXT, compute_benchmark, report_observations


def _report(**over):
    base = {
        "ess": 0.0, "in_band_ratio": 1.0, "persona_coverage": 1.0,
    }
    base.update(over)
    return base


class TestFormula:
    def test_perfect_run_scores_100(self):
        out = compute_benchmark(_report(), days=30)
        assert out["score"] == 100.0
        assert out["formula"] == FORMULA_TEXT
        assert all(t["deduct"] == 0 for t in out["terms"])
        assert {t["key"] for t in out["terms"]} == {"ess", "band_deficit", "coverage_deficit"}

    def test_ess_linear_then_capped(self):
        # ess 0.1 × 200 = 20 分（线性区）；ess 0.5 × 200 = 100 → 封顶 40
        out = compute_benchmark(_report(ess=0.1), days=30)
        ess = next(t for t in out["terms"] if t["key"] == "ess")
        assert ess["deduct"] == 20.0
        out2 = compute_benchmark(_report(ess=0.5), days=30)
        ess2 = next(t for t in out2["terms"] if t["key"] == "ess")
        assert ess2["deduct"] == 40.0 == ess2["cap"]

    def test_band_deficit_linear_then_capped(self):
        # in_band_ratio 0.5 → 缺口 0.5 × 30 = 15；in_band_ratio 0 → 缺口 1.0 → 封顶 30
        out = compute_benchmark(_report(in_band_ratio=0.5), days=30)
        band = next(t for t in out["terms"] if t["key"] == "band_deficit")
        assert band["obs"] == 0.5 and band["deduct"] == 15.0 and band["group"] == "control"
        out2 = compute_benchmark(_report(in_band_ratio=0.0), days=30)
        band2 = next(t for t in out2["terms"] if t["key"] == "band_deficit")
        assert band2["deduct"] == 30.0 == band2["cap"]

    def test_coverage_deficit_linear_then_capped(self):
        # persona_coverage 0.5 → 缺口 0.5 × 30 = 15；覆盖 0 → 封顶 30
        out = compute_benchmark(_report(persona_coverage=0.5), days=30)
        cov = next(t for t in out["terms"] if t["key"] == "coverage_deficit")
        assert cov["obs"] == 0.5 and cov["deduct"] == 15.0 and cov["group"] == "belief"
        out2 = compute_benchmark(_report(persona_coverage=0.0), days=30)
        cov2 = next(t for t in out2["terms"] if t["key"] == "coverage_deficit")
        assert cov2["deduct"] == 30.0 == cov2["cap"]

    def test_missing_values_count_full_penalty(self):
        # 缺失规约：ess 按 1.0、in_band_ratio/persona_coverage 按 0.0 → 三项全封顶
        obs = report_observations({}, days=30)
        assert obs == {"ess": 1.0, "band_deficit": 1.0, "coverage_deficit": 1.0}
        out = compute_benchmark({}, days=30)
        assert all(t["deduct"] == t["cap"] for t in out["terms"])
        assert out["score"] == 0.0

    def test_score_floors_at_zero(self):
        out = compute_benchmark(_report(ess=99.0, in_band_ratio=0.0, persona_coverage=0.0),
                                days=10)
        assert out["score"] == 0.0

    def test_config_overrides_weights(self):
        cfg = {"ess": [100.0, 5.0]}
        out = compute_benchmark(_report(ess=0.5), days=30, cfg=cfg)
        ess = next(t for t in out["terms"] if t["key"] == "ess")
        assert ess["coef"] == 100.0 and ess["deduct"] == 5.0

    def test_groups_cover_all_terms(self):
        out = compute_benchmark(_report(), days=30)
        assert {t["group"] for t in out["terms"]} == {"control", "belief"}
        assert set(out["groups"]) == {"control", "belief"}


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
        assert bench["version"] == "v4"
        assert bench["formula"] == FORMULA_TEXT
        assert {t["key"] for t in bench["terms"]} == {"ess", "band_deficit", "coverage_deficit"}
        on_disk = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
        assert on_disk["benchmark"]["score"] == bench["score"]
        # insights 观测量仍导出（M1-M5 manipulation check 报告项，不再参与 benchmark 计分）
        stats = json.loads((run_dir / "insights.json").read_text(encoding="utf-8"))["stats"]
        assert "violations" in stats["score_observations"]
