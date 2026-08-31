"""AgentBroker 与 agent HTTP 接入端点测试。"""

from __future__ import annotations

import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from usersim.contracts.agent_api import AgentRequest, AgentResponse
from usersim.gateway import AgentBroker, AgentError, AgentTimeout, create_agent_router


def _submit_async(broker: AgentBroker, out: dict, **kw) -> threading.Thread:
    def _go() -> None:
        try:
            out["resp"] = broker.submit(**kw)
        except Exception as e:  # noqa: BLE001
            out["err"] = e

    t = threading.Thread(target=_go, daemon=True)
    t.start()
    return t


def test_submit_poll_respond_roundtrip() -> None:
    broker = AgentBroker()
    out: dict = {}
    t = _submit_async(broker, out, role="user", run_id="r1", rtype="speak",
                      payload={"a": 1}, timeout=5)
    req = broker.poll("user", timeout=2)
    assert req is not None
    assert req.type == "speak" and req.payload == {"a": 1} and req.run_id == "r1"
    assert broker.respond(AgentResponse(request_id=req.request_id, result={"say": "hi"}))
    t.join(5)
    assert out["resp"].result == {"say": "hi"}
    # 已交付的 request_id 不能重复响应
    assert not broker.respond(AgentResponse(request_id=req.request_id, result={}))


def test_submit_timeout_and_zombie_cleanup() -> None:
    broker = AgentBroker()
    with pytest.raises(AgentTimeout):
        broker.submit("user", "r1", "speak", {}, timeout=0.2)
    # 超时时未被取走的请求已作废，后续 poll 拿不到僵尸请求
    assert broker.poll("user", timeout=0.1) is None


def test_poll_run_id_filter() -> None:
    broker = AgentBroker()
    out: dict = {}
    t = _submit_async(broker, out, role="user", run_id="runA", rtype="speak",
                      payload={}, timeout=5)
    # 过滤到其他 run_id 时拿不到
    assert broker.poll("user", timeout=0.2, run_id="runB") is None
    req = broker.poll("user", timeout=2, run_id="runA")
    assert req is not None and req.run_id == "runA"
    broker.respond(AgentResponse(request_id=req.request_id, result={}))
    t.join(5)


def test_local_responder_and_agent_state() -> None:
    broker = AgentBroker()

    def echo(req: AgentRequest) -> AgentResponse:
        n = req.agent_state.get("n", 0) + 1
        return AgentResponse(request_id=req.request_id, result={"n": n},
                             agent_state={"n": n})

    broker.register_local("assistant", echo)
    r1 = broker.submit("assistant", "r1", "on_turn", {}, timeout=1)
    assert r1.result == {"n": 1}
    assert broker.get_state("r1", "assistant") == {"n": 1}
    # 下一次请求自动携带最新 agent_state
    r2 = broker.submit("assistant", "r1", "on_turn", {}, timeout=1)
    assert r2.result == {"n": 2}


def test_local_responder_exception_becomes_agent_error() -> None:
    broker = AgentBroker()

    def boom(req: AgentRequest) -> AgentResponse:
        raise ValueError("炸了")

    broker.register_local("user", boom)
    with pytest.raises(AgentError, match="ValueError: 炸了"):
        broker.submit("user", "r1", "speak", {}, timeout=1)


def test_error_response_raises_agent_error() -> None:
    broker = AgentBroker()
    broker.register_local("user", lambda req: AgentResponse(
        request_id=req.request_id, error="LLMError: 限流"))
    with pytest.raises(AgentError, match="LLMError"):
        broker.submit("user", "r1", "speak", {}, timeout=1)


# ---------------------------------------------------------------
# HTTP 端点（create_agent_router）
# ---------------------------------------------------------------


@pytest.fixture
def http_client():
    broker = AgentBroker()
    app = FastAPI()
    app.include_router(create_agent_router(broker))
    return TestClient(app), broker


def test_http_pending_respond_roundtrip(http_client) -> None:
    client, broker = http_client
    out: dict = {}
    t = _submit_async(broker, out, role="assistant", run_id="r1", rtype="on_turn",
                      payload={"user_say": "好累"}, timeout=10)

    r = client.get("/api/agent/pending", params={"role": "assistant", "timeout": 5})
    assert r.status_code == 200
    req = r.json()
    assert req["type"] == "on_turn" and req["payload"]["user_say"] == "好累"

    r2 = client.post("/api/agent/respond", json={
        "request_id": req["request_id"],
        "result": {"reply": "休息一下", "user_belief": {
            "valence": 0.5, "energy": 0.3, "satiety": 0.5, "stress": 0.6}},
    })
    assert r2.status_code == 200 and r2.json() == {"ok": True}
    t.join(5)
    assert out["resp"].result["reply"] == "休息一下"

    # 未知 request_id → 404
    r3 = client.post("/api/agent/respond", json={"request_id": "nope", "result": {}})
    assert r3.status_code == 404


def test_http_pending_204_when_idle(http_client) -> None:
    client, _ = http_client
    r = client.get("/api/agent/pending", params={"role": "user", "timeout": 1})
    assert r.status_code == 204


def test_http_skill_endpoint(http_client) -> None:
    client, _ = http_client
    for role in ("user", "assistant"):
        r = client.get(f"/api/agent/skill/{role}")
        assert r.status_code == 200
        assert f"usersim-{role}" in r.text
    assert client.get("/api/agent/skill/nobody").status_code == 404


def test_asgi_loopback_agent_client() -> None:
    """demo agent 的真实接入路径：AgentClient 经 ASGI 回环轮询 mini app（不开端口）。"""
    from usersim.agents.client import AgentClient

    broker = AgentBroker()
    app = FastAPI()
    app.include_router(create_agent_router(broker))

    handled: list[str] = []

    def handler(req: AgentRequest) -> AgentResponse:
        handled.append(req.type)
        return AgentResponse(request_id=req.request_id, result={"ok": req.type})

    stop = threading.Event()
    client = AgentClient("assistant", handler, app=app, run_id="r1", poll_timeout=1)
    t = threading.Thread(target=client.serve_forever, args=(stop,), daemon=True)
    t.start()
    try:
        resp = broker.submit("assistant", "r1", "on_turn", {"user_say": "x"}, timeout=10)
        assert resp.result == {"ok": "on_turn"}
        assert handled == ["on_turn"]
        # run_id 过滤：其他 run 的请求不会被这个 client 取走
        assert broker.poll("assistant", timeout=0.1, run_id="r1") is None
    finally:
        stop.set()
        t.join(5)
