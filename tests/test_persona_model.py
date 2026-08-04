"""大五 30 facet 人格 + 结构化喜好：生成 / 冻结 / 动力学 / 画像估计 / 评估。

覆盖四条关键不变量：
1. 人格与喜好**冻结**（运行期不可改写）；
2. facet 粒度**真的生效**（同域分不同 facet → 不同行为）；
3. 画像估计逐 turn 落盘且**可评估**（误差随时间下降）；
4. 旧存档（无 facets/prefs/persona_hat）仍可读、可续跑、可评估。
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from usersim.agents.assistant.profile import ProfileTracker
from usersim.config import load_system_config
from usersim.contracts import (
    FACET_KEYS,
    PREF_CATEGORIES,
    Persona,
    PersonaBelief,
    PersonaBeliefDelta,
    Preferences,
    StateVec,
    facet_error,
    prefs_error,
    tag_hit_rate,
    trait,
)
from usersim.world import World
from usersim.world.anthro import persona_modifiers, preference_modifiers, reversion_rate_mult


def _world(seed=1, days=10, archetype=None):
    return World(seed=seed, days=days, cfg=load_system_config(), archetype=archetype)


# ---------------------------------------------------------------
# 1. 生成：30 facet 全覆盖 + 域内落差 + 确定性
# ---------------------------------------------------------------


def test_persona_has_all_30_facets() -> None:
    p = _world().persona
    assert set(p.facets) == set(FACET_KEYS), "大五细分特质必须全部实现（30 项）"
    assert all(0 <= v <= 100 for v in p.facets.values())
    # 域分是 facet 的聚合，不是独立随机数
    for domain, score in p.domains().items():
        vals = [v for k, v in p.facets.items() if k.startswith(f"{domain}.")]
        assert abs(score - round(sum(vals) / len(vals))) <= 1


def test_facets_vary_within_domain() -> None:
    """域内必须有落差：否则 30 facet 只是域分的复制，助手无从细分估计。"""
    spreads = []
    for seed in range(1, 6):
        p = _world(seed=seed).persona
        for domain in p.domains():
            vals = [v for k, v in p.facets.items() if k.startswith(f"{domain}.")]
            spreads.append(max(vals) - min(vals))
    assert sum(spreads) / len(spreads) > 10, "域内 facet 落差过小，细分特质形同虚设"


def test_prefs_cover_all_categories_and_are_self_consistent() -> None:
    p = _world().persona
    assert set(p.prefs.categories) == set(PREF_CATEGORIES)
    assert all(-1.0 <= v <= 1.0 for v in p.prefs.categories.values())
    assert p.prefs.loves and p.prefs.hates, "喜好模板必须给出明确的爱憎标签"
    # 自陈述文本与结构化标签同源，必须一致（否则助手无论怎么听都会被判错）
    assert any(tag[:2] in p.likes for tag in p.prefs.loves)


def test_persona_generation_is_deterministic_per_seed() -> None:
    a, b = _world(seed=9).persona, _world(seed=9).persona
    assert a.facets == b.facets and a.prefs == b.prefs
    assert _world(seed=10).persona.facets != a.facets


def test_archetype_override_still_derives_persona() -> None:
    """前端指定职业时，人格仍由 seed 派生（且收入随职业变）。"""
    p = _world(archetype="备考研究生").persona
    assert p.archetype == "备考研究生"
    assert p.income_per_slot == 80
    assert set(p.facets) == set(FACET_KEYS)


# ---------------------------------------------------------------
# 2. 冻结：人格与喜好不可改变
# ---------------------------------------------------------------


@pytest.mark.parametrize("field,value", [
    ("facets", {}),
    ("big5", {"开放性": 1}),
    ("likes", "改了"),
    ("prefs", Preferences()),
])
def test_persona_and_prefs_are_frozen(field: str, value) -> None:
    p = _world().persona
    with pytest.raises(ValidationError):
        setattr(p, field, value)


def test_world_run_does_not_mutate_persona() -> None:
    w = _world(days=5)
    before = w.persona.model_dump()
    w.add_event_todo("吃好吃的", 0, 0, "回血", {}, location="楼下快餐")
    while not w.done:
        w.step_slot()
    assert w.persona.model_dump() == before, "跑完一个 episode 后人格/喜好被改写了"


# ---------------------------------------------------------------
# 3. facet 粒度真的生效（动力学）
# ---------------------------------------------------------------


def test_same_domain_score_different_facets_changes_behavior() -> None:
    """群居性 vs 热情：域分相同、facet 相反 → 社交事件效果必须不同。"""
    dom = {"外向性": 50, "神经质": 50, "开放性": 50}
    eff = {"valence": 0.10, "energy": -0.03}
    gregarious = persona_modifiers(dom, "朋友小聚", eff,
                                   facets={"外向性.群居性": 90, "外向性.热情": 10})
    warm = persona_modifiers(dom, "朋友小聚", eff,
                             facets={"外向性.群居性": 10, "外向性.热情": 90})
    assert gregarious["energy"] > warm["energy"], "群居性高者社交耗电应更少"
    assert warm["valence"] > gregarious["valence"], "热情高者社交心情加成更大"


def test_neuroticism_facets_drive_stress_and_reversion() -> None:
    calm = {"神经质.焦虑": 10, "神经质.脆弱": 10}
    anxious = {"神经质.焦虑": 90, "神经质.脆弱": 90}
    dom = {"神经质": 50}
    assert (persona_modifiers(dom, "项目截止压缩", {"stress": 0.2}, facets=anxious)["stress"]
            > persona_modifiers(dom, "项目截止压缩", {"stress": 0.2}, facets=calm)["stress"])
    assert reversion_rate_mult(dom, anxious) < reversion_rate_mult(dom, calm)


def test_facet_fallback_to_domain_when_missing() -> None:
    """旧存档只有域分时，facet 读取回退到域分（行为与升级前一致）。"""
    assert trait({"神经质": 80}, None, "神经质.焦虑") == 80
    assert trait({"神经质": 80}, {}, "神经质.焦虑") == 80
    assert trait({}, {"神经质.焦虑": 33}, "神经质.焦虑") == 33


# ---------------------------------------------------------------
# 4. 喜好调节事件效果
# ---------------------------------------------------------------


def test_preferences_scale_recovery_effects() -> None:
    loved = Preferences(categories={"运动": 0.9})
    hated = Preferences(categories={"运动": -0.9})
    eff = {"valence": 0.10, "stress": -0.10}
    up = preference_modifiers(loved, "运动健身", eff)
    down = preference_modifiers(hated, "运动健身", eff)
    assert up["valence"] > eff["valence"] > down["valence"]
    assert abs(up["stress"]) > abs(eff["stress"]) > abs(down["stress"])


def test_disliked_activity_is_less_helpful_not_more_harmful() -> None:
    """讨厌的活动只是"没那么回血"，不会反过来伤身。"""
    hated = Preferences(categories={"社交": -1.0})
    out = preference_modifiers(hated, "朋友小聚", {"valence": 0.10, "stress": -0.10})
    assert out["valence"] > 0 and out["stress"] < 0


def test_pull_effects_are_not_scaled_by_preference() -> None:
    """pull 是"拉向准稳态"，喜好不应改变目标值（否则爱睡觉的人能睡出 1.2 精力）。"""
    p = Preferences(categories={"休息": 1.0})
    out = preference_modifiers(p, "好好休息", {"energy": {"pull": [0.8, 0.5]}})
    assert out["energy"] == {"pull": [0.8, 0.5]}


def test_love_and_hate_tags_give_valence_impulse() -> None:
    p = Preferences(categories={}, loves=["寿喜烧"], hates=["应酬"])
    assert preference_modifiers(p, "吃好吃的 · 寿喜烧", {"valence": 0.05})["valence"] > 0.05
    assert preference_modifiers(p, "应酬饭局", {"valence": 0.05})["valence"] < 0.05


def test_preferences_do_not_affect_work_events() -> None:
    """不喜欢也得上班：模板事件不受喜好调节（world._effective_events 只调恢复/系列）。"""
    w = _world(days=3)
    while not w.done:
        s = w.step_slot()
        assert all(abs(v) < 1.0 for v in s.event_effects.values())


# ---------------------------------------------------------------
# 5. 助手侧累积器（ProfileTracker）
# ---------------------------------------------------------------


def test_tracker_merges_increments_and_ignores_bogus_keys() -> None:
    t = ProfileTracker()
    t.update(PersonaBeliefDelta(
        facets={"神经质.焦虑": 80, "不存在.特质": 50},
        categories={"社交": -0.7, "瞎造类目": 0.9},
        loves=["寿喜烧"], confidence=0.3, notes="高压工作"))
    assert t.facets == {"神经质.焦虑": 80}, "未知 facet 名必须被丢弃"
    assert t.categories == {"社交": -0.7}
    assert t.loves == ["寿喜烧"] and t.notes == "高压工作"


def test_tracker_blends_toward_new_evidence() -> None:
    """新证据占主导但不完全覆盖——助手能修正第一印象，又不被单句话带跑。"""
    t = ProfileTracker()
    t.update(PersonaBeliefDelta(facets={"神经质.焦虑": 80}))
    t.update(PersonaBeliefDelta(facets={"神经质.焦虑": 40}))
    assert 40 < t.facets["神经质.焦虑"] < 80


def test_tracker_keeps_unmentioned_facets() -> None:
    """本轮没提到的 facet 必须保留（增量语义的核心）。"""
    t = ProfileTracker()
    t.update(PersonaBeliefDelta(facets={"神经质.焦虑": 70, "尽责性.条理性": 60}))
    t.update(PersonaBeliefDelta(facets={"尽责性.条理性": 65}))
    assert t.facets["神经质.焦虑"] == 70


def test_tracker_snapshot_restore_roundtrip() -> None:
    t = ProfileTracker()
    t.update(PersonaBeliefDelta(facets={"外向性.热情": 30}, categories={"饮食": 0.6},
                                loves=["寿喜烧"], hates=["应酬"], planning_style="提前规划",
                                interruption_tolerance=0.2, confidence=0.5, notes="n"))
    fresh = ProfileTracker()
    fresh.restore(t.snapshot())
    assert fresh.to_belief() == t.to_belief()


def test_tracker_caps_tag_spam() -> None:
    """防止 Harness 堆一百个标签刷命中率。"""
    t = ProfileTracker()
    t.update(PersonaBeliefDelta(loves=[f"t{i}" for i in range(50)]))
    assert len(t.loves) <= 12


# ---------------------------------------------------------------
# 6. 画像度量
# ---------------------------------------------------------------


def test_facet_error_only_counts_estimated_facets() -> None:
    truth = {k: 60 for k in FACET_KEYS}
    assert facet_error(truth, {}) is None, "没有估计不能算 0 误差"
    assert facet_error(truth, {FACET_KEYS[0]: 60}) == 0.0
    assert facet_error(truth, {FACET_KEYS[0]: 80}) == pytest.approx(0.2)


def test_prefs_error_and_tag_f1() -> None:
    assert prefs_error({"饮食": 1.0}, {"饮食": -1.0}) == pytest.approx(1.0)
    assert prefs_error({"饮食": 0.5}, {}) is None
    # 双向包含即命中：不要求助手复现角色卡原文
    assert tag_hit_rate(["寿喜烧"], ["喜欢吃寿喜烧"]) == pytest.approx(1.0)
    assert tag_hit_rate(["寿喜烧"], ["跑步"]) == 0.0


# ---------------------------------------------------------------
# 7. 端到端：逐 turn 落盘 + 可评估 + 三档可分辨
# ---------------------------------------------------------------


@pytest.fixture(scope="module")
def replay_runs(tmp_path_factory):
    from usersim.evaluator.report import evaluate_run
    from usersim.runner import run_replay

    cfg = load_system_config()
    out = tmp_path_factory.mktemp("persona_runs")
    result = {}
    for q in ("good", "poor"):
        run_dir = run_replay(seed=7, days=14, quality=q, cfg=cfg, out_root=out, run_id=f"p_{q}")
        result[q] = (run_dir, evaluate_run(run_dir, cfg))
    return result


def test_every_assistant_turn_records_persona_hat(replay_runs) -> None:
    run_dir, _ = replay_runs["good"]
    turns = [json.loads(l) for l in (run_dir / "turns.jsonl").read_text(encoding="utf-8").splitlines()]
    asst = [t for t in turns if t["speaker"] == "assistant"]
    assert asst and all(t.get("persona_hat") for t in asst), "每个助手 turn 都应落盘画像估计"
    # 画像随 turn 增长（覆盖率单调不减）
    covs = [len(t["persona_hat"]["facets"]) for t in asst]
    assert covs[-1] > covs[0] and covs == sorted(covs)


def test_report_exposes_profile_metrics(replay_runs) -> None:
    _, report = replay_runs["good"]
    for key in ("persona_err_final", "persona_err_slope_per_day", "persona_coverage",
                "prefs_err_final", "prefs_tag_f1", "daily_persona_err"):
        assert key in report
    assert report["daily_persona_err"], "画像学习曲线为空"
    assert 0 <= report["persona_coverage"] <= 1


def test_good_harness_profiles_better_than_poor(replay_runs) -> None:
    """画像精度必须能分辨助手质量——否则这个指标没有意义。"""
    _, good = replay_runs["good"]
    _, poor = replay_runs["poor"]
    assert good["persona_err_final"] < poor["persona_err_final"]


def test_good_harness_learns_over_time(replay_runs) -> None:
    """越聊越懂用户：误差斜率应为负。"""
    _, good = replay_runs["good"]
    assert good["persona_err_slope_per_day"] < 0


def test_health_score_penalizes_missing_profile(replay_runs) -> None:
    """不做画像的助手要被扣分（否则 stub 反而占便宜）。"""
    run_dir, _ = replay_runs["good"]
    insights = json.loads((run_dir / "insights.json").read_text(encoding="utf-8"))
    assert "persona_err" in insights["stats"]["score_deductions"]
    assert insights["stats"]["persona_turns"] > 0


# ---------------------------------------------------------------
# 8. 向后兼容：旧存档
# ---------------------------------------------------------------


def test_legacy_persona_without_facets_still_loads() -> None:
    p = Persona(name="n", archetype="a", big5={"神经质": 80, "外向性": 30}, likes="l",
                routine="r", x0=StateVec(valence=.5, energy=.5, satiety=.5, stress=.5))
    assert p.facets == {} and p.prefs.categories == {}
    assert p.facet("神经质.焦虑") == 80  # 回退域分
    assert p.domains() == {"神经质": 80, "外向性": 30}


def test_legacy_world_snapshot_resumes(tmp_path) -> None:
    """旧存档（persona 无 facets/prefs、needs 无变化）必须能续跑。"""
    w = _world(days=4)
    snap = w.to_snapshot()
    snap["persona"] = {k: v for k, v in snap["persona"].items() if k not in ("facets", "prefs")}
    revived = World.from_snapshot(snap, w.cfg, extra_days=1)
    assert revived.persona.facets == {}
    revived.step_slot()  # 动力学在无 facets 时仍可推进（回退域分）


def test_metrics_tolerate_missing_persona_and_hats() -> None:
    """旧日志没有 persona_hat / 无冻结维度真值时，指标为 NaN 而不是崩溃。"""
    from usersim.evaluator.metrics import compute_metrics

    cfg = load_system_config()
    w = _world(days=2)
    slots = []
    while not w.done:
        slots.append(w.step_slot())
    report = compute_metrics(slots, [], cfg.state.targets.to_dict(), float(cfg.state.band),
                             cfg.eval, persona=None)
    assert report["persona_coverage"] == 0.0
    assert report["daily_persona_err"] == []
