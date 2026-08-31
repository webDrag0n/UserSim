"""Server API 测试（此前 server 层零回归保护）。

只覆盖不启动真实 run 的只读端点与校验路径——启动 run 的并发行为由
test_runner.py 覆盖，避免测试里跑后台线程造成不确定性。
"""

from __future__ import annotations

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")
TestClient = fastapi_testclient.TestClient


@pytest.fixture(scope="module")
def client():
    from usersim.server.app import app

    with TestClient(app) as c:
        yield c


def test_harnesses_endpoint_lists_registry(client) -> None:
    """前端启动表单依赖此端点；registry 新增项应自动出现。"""
    r = client.get("/api/harnesses")
    assert r.status_code == 200
    body = r.json()
    names = {item["name"] for item in body["items"]}
    assert {"reference", "stub"} <= names
    assert body["default"] == "openclaw"
    assert all(item["doc"] for item in body["items"]), "每个 harness 应有一行说明"


def test_runs_listing_is_available(client) -> None:
    r = client.get("/api/runs")
    assert r.status_code == 200
    assert "runs" in r.json()


def test_catalog_endpoint(client) -> None:
    r = client.get("/api/catalog")
    assert r.status_code == 200


def test_balance_endpoint(client) -> None:
    r = client.get("/api/balance/config")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] in ("json", "default")
    # 事件表：无 variants、无效果；地点表：supports 携带价格与效果
    for action in body["files"].get("recovery_actions", []):
        assert "variants" not in action and "base_effect" not in action
        for f in ("id", "action", "category", "design_intent"):
            assert f in action
    for venue in body["files"].get("venues", []):
        assert venue["supports"], f"{venue.get('id')} 无支持条目"
        for s in venue["supports"]:
            assert "event" in s and "cost" in s and "effect" in s


def test_eval_formula_endpoint(client) -> None:
    r = client.post("/api/balance/eval_formula", json={"formula": "x**2", "var_name": "x", "points": 11})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["points"]) == 11
    assert body["points"][0]["y"] == 0.0
    assert abs(body["points"][-1]["y"] - 1.0) < 1e-9

    r = client.post("/api/balance/eval_formula", json={"formula": "import os", "var_name": "x"})
    assert r.json()["ok"] is False


def test_config_validation_endpoint(client) -> None:
    r = client.get("/api/config/validation")
    assert r.status_code == 200


def test_unknown_run_is_not_a_500(client) -> None:
    """未知 run_id 应是 4xx 而非 500（此前 _find_run_dir 的行为未被测试锁定）。"""
    r = client.get("/api/runs/definitely-not-a-real-run/report")
    assert r.status_code in (400, 404), f"期望 4xx，实际 {r.status_code}"


def test_bench_listing(client) -> None:
    r = client.get("/api/bench")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body and "jobs" in body


def test_unknown_bench_is_404(client) -> None:
    r = client.get("/api/bench/not-a-bench")
    assert r.status_code == 404


def test_live_bench_requires_explicit_cost_confirmation(client) -> None:
    """live 批量不得在未确认成本时启动——这是烧 token 的闸门。"""
    r = client.post("/api/bench", json={"seeds": "1-8", "days": 30, "mode": "live"})
    assert r.status_code == 200
    body = r.json()
    assert body["started"] is False
    assert body["estimated_tokens"] > 0
    assert "max_episodes" in body["error"]


def test_spa_fallback_serves_index_or_404(client) -> None:
    """未构建前端时不应 500。"""
    r = client.get("/some/frontend/route")
    assert r.status_code in (200, 404)
