"""Bench 完整性校验：跨组 turns.jsonl 逐字节相同 = "输出被复制"回归的红灯。

真实事故：nomem 与 pro 两组 116 条 turn 逐字节相同。纯文件 fixture，不起 run。
"""

import json

from usersim.bench.suite import check_turns_integrity


def _make_run(runs_root, run_id: str, turns: list[dict]) -> None:
    d = runs_root / run_id
    d.mkdir(parents=True)
    with (d / "turns.jsonl").open("w", encoding="utf-8") as f:
        for t in turns:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")


def _ep(group: str, seed: int, run_id: str) -> dict:
    return {"group": group, "seed": seed, "archetype": None,
            "label": f"{group}/auto/seed{seed}", "run_id": run_id, "metrics": {}}


def test_identical_turns_across_groups_flagged(tmp_path):
    """两组 episode 的 turns.jsonl 逐字节相同 → integrity.ok=False 并列出重复对。"""
    runs = tmp_path / "runs"
    same = [{"turn_id": i, "speaker": "user", "text": f"第{i}轮"} for i in range(5)]
    _make_run(runs, "nomem_auto_1", same)
    _make_run(runs, "pro_auto_1", same)
    eps = [_ep("nomem", 1, "nomem_auto_1"), _ep("pro", 1, "pro_auto_1")]
    out = check_turns_integrity(eps, runs)
    assert out["ok"] is False
    assert out["duplicates"] == [{"group_a": "nomem", "seed_a": 1,
                                  "group_b": "pro", "seed_b": 1}]


def test_different_turns_pass(tmp_path):
    """各组 turns.jsonl 不同 → integrity.ok=True 且无 duplicates。"""
    runs = tmp_path / "runs"
    _make_run(runs, "reference_auto_1", [{"turn_id": 0, "text": "甲"}])
    _make_run(runs, "stub_auto_1", [{"turn_id": 0, "text": "乙"}])
    eps = [_ep("reference", 1, "reference_auto_1"), _ep("stub", 1, "stub_auto_1")]
    out = check_turns_integrity(eps, runs)
    assert out == {"ok": True}


def test_same_group_identical_turns_not_flagged(tmp_path):
    """同组内相同不报警（跨组复制才是回归信号）。"""
    runs = tmp_path / "runs"
    same = [{"turn_id": 0, "text": "一样"}]
    _make_run(runs, "ref_auto_1", same)
    _make_run(runs, "ref_auto_2", same)
    eps = [_ep("reference", 1, "ref_auto_1"), _ep("reference", 2, "ref_auto_2")]
    out = check_turns_integrity(eps, runs)
    assert out["ok"] is True


def test_missing_turns_file_skipped_with_note(tmp_path):
    """turns.jsonl 缺失的 episode 跳过比对并记 note，不拖垮整体判定。"""
    runs = tmp_path / "runs"
    _make_run(runs, "a_auto_1", [{"turn_id": 0, "text": "甲"}])
    _make_run(runs, "b_auto_1", [{"turn_id": 0, "text": "乙"}])
    eps = [_ep("a", 1, "a_auto_1"), _ep("b", 1, "b_auto_1"),
           _ep("a", 2, "ghost_run")]  # ghost_run 无文件
    out = check_turns_integrity(eps, runs)
    assert out["ok"] is True
    assert len(out["notes"]) == 1 and "turns.jsonl 缺失" in out["notes"][0]
