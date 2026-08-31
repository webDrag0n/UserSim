"""AgentBroker：benchmark 核心与 agent 之间的请求-响应中介（0 LLM，仅依赖 contracts）。

Runner 线程用 `submit()` 阻塞等待响应；agent 侧经 HTTP 长轮询
（`create_agent_router()` 暴露的 /api/agent/* 端点）取走请求并回传响应。

- 每个 (run_id, role) 维护一份不透明 `agent_state`：随请求下发、随响应更新、
  由 Runner 写入 run_state.json 并在续跑时回灌——外部 agent 可对 benchmark 无状态。
- `register_local()` 注册进程内响应函数（测试双 / 备用通道），与 HTTP 路径同协议。
- 超时：submit 超时抛 `AgentTimeout`，并把仍挂在队列里的请求作废（避免下一个
  run 的 agent 捡到无法交付的僵尸请求）。
"""

from __future__ import annotations

import threading
import uuid
from collections import deque
from collections.abc import Callable

from usersim.contracts.agent_api import AgentRequest, AgentResponse

ROLES = ("user", "assistant")


class AgentTimeout(Exception):
    """runner 等待 agent 响应超时。"""


class AgentError(Exception):
    """agent 侧处理失败（响应信封的 error 字段）。"""


class AgentBroker:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._pending: dict[str, deque[AgentRequest]] = {r: deque() for r in ROLES}
        # request_id → (Event, 响应槽)
        self._waiters: dict[str, list] = {}
        # (run_id, role) → agent_state
        self._states: dict[tuple[str, str], dict] = {}
        self._local: dict[str, Callable[[AgentRequest], AgentResponse]] = {}

    # ---- runner 侧 ----

    def submit(self, role: str, run_id: str, rtype: str, payload: dict,
               timeout: float = 120.0, agent_state: dict | None = None) -> AgentResponse:
        """提交一个请求并阻塞等待响应。超时抛 AgentTimeout；agent 报错抛 AgentError。"""
        if role not in ROLES:
            raise ValueError(f"未知 agent 角色 {role!r}，可选: {ROLES}")
        if agent_state is None:
            agent_state = self._states.get((run_id, role), {})
        req = AgentRequest(
            request_id=uuid.uuid4().hex[:12],
            run_id=run_id, role=role, type=rtype,
            payload=payload, agent_state=agent_state,
        )

        local = self._local.get(role)
        if local is not None:
            try:
                resp = local(req)
            except Exception as e:  # noqa: BLE001 — 与 HTTP 路径（client 包装 error）同语义
                raise AgentError(f"{type(e).__name__}: {e}") from e
        else:
            event = threading.Event()
            slot: list = [None]
            with self._cond:
                self._waiters[req.request_id] = [event, slot]
                self._pending[role].append(req)
                self._cond.notify_all()
            if not event.wait(timeout):
                with self._cond:
                    self._waiters.pop(req.request_id, None)
                    try:
                        self._pending[role].remove(req)  # 作废未取走的请求
                    except ValueError:
                        pass  # 已被取走但响应未到——响应到达时无处交付，自然丢弃
                raise AgentTimeout(f"agent({role}) 响应超时（{timeout:.0f}s，type={rtype}）")
            resp = slot[0]

        if resp.agent_state is not None:
            self._states[(run_id, role)] = resp.agent_state
        if resp.error:
            raise AgentError(resp.error)
        return resp

    def get_state(self, run_id: str, role: str) -> dict:
        return self._states.get((run_id, role), {})

    def set_state(self, run_id: str, role: str, state: dict) -> None:
        self._states[(run_id, role)] = state

    def register_local(self, role: str,
                       fn: Callable[[AgentRequest], AgentResponse] | None) -> None:
        """注册/注销进程内响应函数（fn(AgentRequest) -> AgentResponse）。"""
        if fn is None:
            self._local.pop(role, None)
        else:
            self._local[role] = fn

    # ---- agent 侧（HTTP 端点调用） ----

    def poll(self, role: str, timeout: float = 30.0,
             run_id: str | None = None) -> AgentRequest | None:
        """长轮询取下一个请求。run_id 给定时只取该 run 的请求（demo agent 按 run 过滤）。"""
        if role not in ROLES:
            raise ValueError(f"未知 agent 角色 {role!r}，可选: {ROLES}")
        with self._cond:
            if not self._wait_for(role, timeout, run_id):
                return None
            q = self._pending[role]
            if run_id is None:
                return q.popleft()
            for req in list(q):
                if req.run_id == run_id:
                    q.remove(req)
                    return req
            return None

    def _wait_for(self, role: str, timeout: float, run_id: str | None) -> bool:
        def ready() -> bool:
            q = self._pending[role]
            return any(r.run_id == run_id for r in q) if run_id else bool(q)

        return self._cond.wait_for(ready, timeout=timeout)

    def respond(self, resp: AgentResponse) -> bool:
        """交付响应；request_id 未知（已超时/不存在）时返回 False。"""
        with self._cond:
            entry = self._waiters.pop(resp.request_id, None)
        if entry is None:
            return False
        event, slot = entry
        slot[0] = resp
        event.set()
        return True


# 全局单例：server（uvicorn）与 CLI 共用一个进程时使用
BROKER = AgentBroker()


def create_agent_router(broker: AgentBroker | None = None):
    """生成 agent 接入端点的 APIRouter（server 与 CLI 的 ASGI 回环共用同一份定义）。

    端点：
      GET  /api/agent/pending?role=...&timeout=...&run_id=...  → AgentRequest | 204
      POST /api/agent/respond                                   → {ok: true} | 404
      GET  /api/agent/skill/{role}                              → SKILL.md 原文
    """
    from fastapi import APIRouter, HTTPException, Response
    from fastapi.responses import PlainTextResponse

    from usersim.config import PROJECT_ROOT

    broker = broker or BROKER
    router = APIRouter()

    @router.get("/api/agent/pending")
    def agent_pending(role: str, timeout: int = 30, run_id: str | None = None) -> Response:
        req = broker.poll(role, timeout=max(1, min(timeout, 60)), run_id=run_id)
        if req is None:
            return Response(status_code=204)
        return Response(content=req.model_dump_json(), media_type="application/json")

    @router.post("/api/agent/respond")
    def agent_respond(resp: AgentResponse) -> dict:
        if not broker.respond(resp):
            raise HTTPException(status_code=404, detail="未知或已超时的 request_id")
        return {"ok": True}

    @router.get("/api/agent/skill/{role}")
    def agent_skill(role: str) -> PlainTextResponse:
        if role not in ROLES:
            raise HTTPException(status_code=404, detail=f"未知角色 {role!r}")
        path = PROJECT_ROOT / "skills" / f"usersim-{role}" / "SKILL.md"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"skill 文件不存在: {path.name}")
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    return router
