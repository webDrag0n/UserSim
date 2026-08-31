"""agent 配置与 profiles 加载：根目录 agents/<role>/ 是 usersim 的 agent 插件目录。

每个角色一个文件夹：`config.toml`（顶层 default 选择哪个实现 + [llm] 角色级
provider 绑定）+ `profiles/*.toml`（一个文件一个可选实现，含 type 与实现自有参数）。
密钥规约不变（AGENT.md）：api_key 只在 config/llm.toml 的 [providers.*] 或
同名环境变量；profile/config 里只写 provider 引用与参数覆盖。
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from usersim.config import PROJECT_ROOT, ConfigError, LLMRole, resolve_provider

AGENTS_ROOT = PROJECT_ROOT / "agents"

# agent 角色 → 插件目录
ROLE_DIRS = {"user": "user", "assistant": "assistant"}


def agent_dir(role: str) -> Path:
    if role not in ROLE_DIRS:
        raise ConfigError(f"未知 agent 角色 {role!r}，可选: {sorted(ROLE_DIRS)}")
    return AGENTS_ROOT / ROLE_DIRS[role]


def load_agent_config(role: str) -> dict[str, Any]:
    """读取 agents/<role>/config.toml 的完整内容。"""
    path = agent_dir(role) / "config.toml"
    if not path.exists():
        raise ConfigError(f"agent 配置不存在: {path}")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"TOML 解析失败 {path}: {e}") from e


def load_agent_llm(role: str) -> LLMRole:
    """解析 agent 的 LLM 配置：config.toml [llm] 的 provider 引用 + 参数覆盖。"""
    llm_cfg = load_agent_config(role).get("llm", {})
    provider = llm_cfg.get("provider")
    if not provider:
        raise ConfigError(f"agents/{ROLE_DIRS[role]}/config.toml 的 [llm] 缺少 provider")
    overrides = {k: v for k, v in llm_cfg.items() if k != "provider"}
    return resolve_provider(provider, overrides)


def agent_behavior(role: str) -> dict[str, Any]:
    """agent 行为参数（config.toml [behavior] / [harness] 等，缺省 {}）。"""
    cfg = load_agent_config(role)
    return {k: v for k, v in cfg.items() if k != "llm"}


# ---------------------------------------------------------------
# 可插拔实现：agents/<role>/profiles/*.toml
# 增删一个实现 = 增删一个配置文件，框架代码不动（type 分派见 registry / client）
# ---------------------------------------------------------------

def impl_dir(role: str) -> Path:
    return agent_dir(role) / "profiles"


def list_impls(role: str) -> dict[str, dict[str, Any]]:
    """扫描 profiles/*.toml：文件名（去扩展名）→ spec（含 name/type/description）。

    每个文件必须有字符串 `type` 字段；type 的可选值由角色的构造方定义
    （assistant: package | cli；user: package）。
    """
    d = impl_dir(role)
    if not d.is_dir():
        raise ConfigError(f"profiles 目录不存在: {d}")
    impls: dict[str, dict[str, Any]] = {}
    for path in sorted(d.glob("*.toml")):
        try:
            spec = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"TOML 解析失败 {path}: {e}") from e
        if not isinstance(spec.get("type"), str):
            raise ConfigError(f"{path} 缺少字符串字段 type")
        spec["name"] = path.stem
        impls[path.stem] = spec
    if not impls:
        raise ConfigError(f"{d} 下没有任何 profile（*.toml）")
    return impls


def default_impl(role: str) -> str:
    """默认实现名：config.toml 顶层 default；缺省时若只有一个 profile 则用它。"""
    name = load_agent_config(role).get("default")
    if name:
        return str(name)
    impls = list_impls(role)
    if len(impls) == 1:
        return next(iter(impls))
    raise ConfigError(
        f"agents/{ROLE_DIRS[role]}/config.toml 缺少 default（可选实现: {sorted(impls)}）")


def load_impl(role: str, name: str | None = None) -> dict[str, Any]:
    """按名取实现 spec（缺省取默认实现）。"""
    key = name or default_impl(role)
    impls = list_impls(role)
    if key not in impls:
        raise ConfigError(
            f"未知 {role} 实现 {key!r}，可选: {sorted(impls)}"
            f"（agents/{ROLE_DIRS[role]}/profiles/*.toml，增删文件即增删实现）")
    return impls[key]


def load_impl_llm(role: str, spec: dict[str, Any]) -> LLMRole:
    """实现的 LLM 配置：impl [llm] 覆盖角色 config.toml [llm]（provider 引用 + 参数）。"""
    role_llm = load_agent_config(role).get("llm", {})
    impl_llm = spec.get("llm", {}) or {}
    provider = impl_llm.get("provider") or role_llm.get("provider")
    if not provider:
        raise ConfigError(
            f"实现 {spec.get('name')!r} 与 agents/{ROLE_DIRS[role]}/config.toml 都未给 [llm] provider")
    overrides = {**{k: v for k, v in role_llm.items() if k != "provider"},
                 **{k: v for k, v in impl_llm.items() if k != "provider"}}
    return resolve_provider(str(provider), overrides)
