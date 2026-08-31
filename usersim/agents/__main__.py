"""standalone 入口：python -m agents user|assistant [--server URL] [--harness NAME]

以 demo agent 身份接入一个运行中的 UserSim server（与外部 agent 完全同路径：
真实 HTTP 轮询 /api/agent/pending）。配置来自 agents/<role>/config.toml。
"""

from __future__ import annotations

import argparse
import threading

from usersim.agents.client import AgentClient, make_demo_handler


def serve_agent(role: str, server: str | None = None, harness: str | None = None,
                impl: str | None = None) -> None:
    handler = make_demo_handler(role, harness_name=harness, impl_name=impl)
    server = server or "http://127.0.0.1:8610"
    print(f"demo {role} agent 已接入 {server}（轮询 /api/agent/pending），Ctrl+C 退出")
    try:
        AgentClient(role, handler, base_url=server).serve_forever(threading.Event())
    except KeyboardInterrupt:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(prog="agents", description="UserSim demo agent 接入器")
    parser.add_argument("role", choices=["user", "assistant"], help="接入角色")
    parser.add_argument("--server", default=None, help="server 地址（默认 http://127.0.0.1:8610）")
    parser.add_argument("--harness", default=None,
                        help="demo 助手所用实现名（仅 role=assistant；默认取 config.toml 的 default）")
    parser.add_argument("--impl", default=None,
                        help="demo 用户所用实现名（仅 role=user；默认取 config.toml 的 default）")
    args = parser.parse_args()
    serve_agent(args.role, server=args.server, harness=args.harness, impl=args.impl)


if __name__ == "__main__":
    main()
