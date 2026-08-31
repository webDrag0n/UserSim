"""Agent 客户端：轮询 benchmark 的 agent 接口并分发处理的通用循环。

两种 transport，同一份 HTTP 协议：
- `base_url`：真实 HTTP（standalone demo 进程 / 外部 agent 参考路径）；
- `app`：`httpx.ASGITransport` 进程内回环（CLI / bench / server 内嵌 demo，不开端口）。

`spawn_demo_agents()` 是组装点（cli / bench / server 调用）：为本进程的 broker
起一个仅含 agent 端点的迷你 ASGI app，再以回环方式跑 demo user / demo assistant 线程。
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from pathlib import Path

import httpx

from usersim.contracts.agent_api import AgentRequest, AgentResponse

Handler = Callable[[AgentRequest], AgentResponse]


class AgentClient:
    """长轮询循环：GET pending → handler → POST respond。

    用 AsyncClient：httpx 0.28 的 ASGITransport 只有异步接口；
    handler 是同步阻塞（LLM 调用），经 asyncio.to_thread 执行。
    """

    def __init__(self, role: str, handler: Handler, *,
                 base_url: str | None = None, app=None,
                 run_id: str | None = None, poll_timeout: int = 30):
        self.role = role
        self.handler = handler
        self.run_id = run_id
        self.poll_timeout = poll_timeout
        self._transport = httpx.ASGITransport(app=app) if app is not None else None
        self._base_url = ("http://agent.local" if app is not None
                          else (base_url or "http://127.0.0.1:8610"))

    def serve_forever(self, stop: threading.Event) -> None:
        asyncio.run(self._serve(stop))

    async def _serve(self, stop: threading.Event) -> None:
        params = {"role": self.role, "timeout": self.poll_timeout}
        if self.run_id:
            params["run_id"] = self.run_id
        async with httpx.AsyncClient(transport=self._transport, base_url=self._base_url,
                                     timeout=self.poll_timeout + 15) as http:
            while not stop.is_set():
                try:
                    r = await http.get("/api/agent/pending", params=params)
                    if r.status_code == 204:
                        continue
                    r.raise_for_status()
                    req = AgentRequest(**r.json())
                except Exception:  # noqa: BLE001 — 网络/服务端暂不可达，退避重试
                    await asyncio.sleep(1.0)
                    continue
                try:
                    resp = await asyncio.to_thread(self.handler, req)
                except Exception as e:  # noqa: BLE001 — handler 崩溃也要交付 error，让 runner 记违约
                    resp = AgentResponse(request_id=req.request_id,
                                         error=f"{type(e).__name__}: {e}")
                try:
                    await http.post("/api/agent/respond", json=resp.model_dump(mode="json"))
                except Exception:  # noqa: BLE001 — 响应丢失由 runner 超时兜底
                    await asyncio.sleep(1.0)


def spawn_demo_agents(*, broker=None, harness_name: str | None = None,
                      user_impl: str | None = None,
                      run_id: str | None = None, log_dir: Path | None = None,
                      roles: tuple[str, ...] = ("user", "assistant"),
                      base_url: str | None = None) -> tuple[threading.Event, list[threading.Thread]]:
    """为本进程 broker spawn demo agent 线程（demo = 与外部 agent 完全同协议的第一方实现）。

    返回 (stop_event, threads)：run 结束后置 stop_event 终止轮询线程。
    """
    from fastapi import FastAPI

    from usersim.config import load_system_config
    from usersim.gateway import BROKER, create_agent_router

    broker = broker or BROKER
    poll_timeout = int((load_system_config().get("agent_api", {}) or {})
                       .get("poll_timeout_sec", 30))
    if base_url is None:
        app = FastAPI(title="UserSim Agent Loopback")
        app.include_router(create_agent_router(broker))
    else:
        app = None

    stop = threading.Event()
    threads: list[threading.Thread] = []
    for role in roles:
        handler = make_demo_handler(role, harness_name=harness_name,
                                    impl_name=user_impl, log_dir=log_dir)
        client = AgentClient(role, handler, app=app, base_url=base_url, run_id=run_id,
                             poll_timeout=poll_timeout)
        t = threading.Thread(target=client.serve_forever, args=(stop,),
                             name=f"demo-{role}", daemon=True)
        t.start()
        threads.append(t)
    return stop, threads


def make_demo_handler(role: str, *, harness_name: str | None = None,
                      impl_name: str | None = None, log_dir: Path | None = None):
    """按角色构造 demo agent 的请求处理函数。

    实现来自 `agents/<role>/profiles/*.toml`（增删文件即增删实现）：
    user 由 `impl_name` 选择（默认 config.toml 的 default）；
    assistant 由 `harness_name` 选择。
    """
    if role == "user":
        import importlib

        from usersim.agents.config import load_impl
        from usersim.config import ConfigError

        spec = load_impl("user", impl_name)
        if spec.get("type") != "package":
            raise ConfigError(
                f"user 实现 {spec['name']!r} 的 type {spec.get('type')!r} 未知（可选: package）")
        folder = str(spec.get("impl", spec["name"]))
        module = importlib.import_module(f"agents.user.{folder}")
        return module.create(_make_llm_client("user", log_dir, spec),
                             spec.get("behavior", {}) or {})
    if role == "assistant":
        from usersim.agents.demo import DemoAssistantAgent

        return DemoAssistantAgent(_make_harness(harness_name, log_dir)).handle
    raise ValueError(f"未知 demo 角色 {role!r}")


def _make_llm_client(role: str, log_dir: Path | None, spec: dict | None = None):
    from usersim.agents.config import load_agent_llm, load_impl_llm
    from usersim.config import load_llm_runtime
    from usersim.llm import LLMClient

    llm_role = load_impl_llm(role, spec) if spec is not None else load_agent_llm(role)
    client = LLMClient(llm_role, load_llm_runtime())
    if log_dir is not None:
        client.set_log_dir(log_dir)
    return client


def _make_harness(harness_name: str | None, log_dir: Path | None):
    from usersim.agents.config import load_impl
    from usersim.agents.registry import create

    # profile 的 [llm] 覆盖必须进 client——此前只传角色级配置，
    # reference_pro 之类"同实现换模型"的 profile 会被静默忽略（R6 实测）
    spec = load_impl("assistant", harness_name)
    return create(harness_name, _make_llm_client("assistant", log_dir, spec))
