"""usersim.agents：agent 接口框架层（属于 benchmark 系统）。

与根目录 `agents/` 的分工：
- **本包（接口框架，usersim 内）**：Harness 协议（base）、画像累积器（profile）、
  通用 CLI 驱动（cli_agent）、demo 装配（demo / client）、profiles 与配置的加载
  （config / registry）、轮询客户端与 standalone 入口（__main__）；
- **根目录 agents/（可插拔实现，usersim 外）**：只含 profiles/*.toml（一个文件一个
  可选实现）与默认实现包（assistant: reference/ stub/；user: standard/）——
  增删实现 = 增删 profiles 里的 toml 或实现文件夹，框架代码不动。

runner 不 import 本包（live agent 只经 AgentBroker 接入；依赖测试强制）。
"""

from __future__ import annotations


def prompt_versions() -> dict[str, str]:
    """各角色默认实现的 prompt 版本（可复现性凭证；取自 profiles/*.toml 的 prompt_version）。"""
    from usersim.agents.config import load_impl

    return {role: str(load_impl(role).get("prompt_version", "?"))
            for role in ("user", "assistant")}
