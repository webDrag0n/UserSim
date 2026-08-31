"""assistant 实现注册表：扫描 `agents/assistant/profiles/*.toml` 并分派构造。

可供选择的被测实现 = profiles 目录下的文件清单：**新增一个实现 = 放一个
<name>.toml，删除文件即下线**，框架代码不动。type 分派：
  package → 导入同级实现包 `agents/assistant/<name>/`（可用 `impl = "<文件夹>"`
            另指），调用其 `create(client)` 得到 Harness；
  cli     → 本包 cli_agent 的通用 CLI 驱动（openclaw / hermes / 任何 agent CLI）。

run 的 meta.json 会记录所用实现名，构成可复现性凭证的一部分。
"""

from __future__ import annotations

import importlib

from usersim.agents.config import default_impl, list_impls, load_impl
from usersim.config import ConfigError

_KNOWN_TYPES = ("package", "cli")


def available() -> list[dict[str, str]]:
    """供 GET /api/harnesses 使用的清单（name + type + 简述）。"""
    return [
        {"name": name,
         "type": str(spec.get("type", "?")),
         "doc": str(spec.get("description", ""))}
        for name, spec in sorted(list_impls("assistant").items())
    ]


def default_name() -> str:
    """默认实现名（agents/assistant/config.toml 顶层 default）。"""
    return default_impl("assistant")


def create(name: str | None, client):
    """按实现名构造 Harness 实例（缺省取默认实现）。"""
    spec = load_impl("assistant", name)
    typ = spec.get("type")
    if typ == "package":
        folder = str(spec.get("impl", spec["name"]))
        module = importlib.import_module(f"agents.assistant.{folder}")
        return module.create(client)
    if typ == "cli":
        from usersim.agents.cli_agent import CliHarness

        return CliHarness(spec, client)
    raise ConfigError(
        f"实现 {spec['name']!r} 的 type {typ!r} 未知（可选: {' | '.join(_KNOWN_TYPES)}）")
