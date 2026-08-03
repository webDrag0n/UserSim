"""配置加载器：TOML + 环境变量覆盖 + 校验。

- config/system.toml → SystemConfig（嵌套 dict 的属性式访问）
- config/llm.toml    → LLMConfig；api_key 可用 USERSIM_<PROVIDER>_API_KEY 覆盖
"""

from __future__ import annotations

import hashlib
import os
import tomllib
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    pass


class Namespace:
    """把嵌套 dict 包装成属性式访问的只读命名空间。"""

    def __init__(self, data: dict[str, Any]):
        self._data = data
        for k, v in data.items():
            setattr(self, k, Namespace(v) if isinstance(v, dict) else v)

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        return self._data

    def __repr__(self) -> str:  # pragma: no cover
        return f"Namespace({self._data!r})"


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}")
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"TOML 解析失败 {path}: {e}") from e


def load_system_config(path: Path | None = None) -> Namespace:
    path = path or PROJECT_ROOT / "config" / "system.toml"
    return Namespace(_load_toml(path))


def system_config_hash(path: Path | None = None) -> str:
    path = path or PROJECT_ROOT / "config" / "system.toml"
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _resolve_key(provider: str, cfg: dict[str, Any]) -> str:
    env_name = f"USERSIM_{provider.upper()}_API_KEY"
    key = os.environ.get(env_name) or cfg.get("api_key", "")
    if not key or "在此填入" in key or "not-needed" in key:
        raise ConfigError(
            f"provider '{provider}' 缺少有效 api_key：请在 config/llm.toml 填入，"
            f"或设置环境变量 {env_name}"
        )
    return key


class LLMRole(Namespace):
    provider: str
    base_url: str
    api_key: str
    model: str
    temperature: float
    max_tokens: int


def load_llm_role(role: str, path: Path | None = None) -> LLMRole:
    """解析某个角色（user_agent / assistant_agent / reference_user）的完整 LLM 配置。"""
    path = path or PROJECT_ROOT / "config" / "llm.toml"
    cfg = _load_toml(path)
    roles = cfg.get("roles", {})
    role_cfg = roles.get(role)
    provider = (role_cfg or {}).get("provider") or cfg.get("default_provider")
    if not provider or provider not in cfg.get("providers", {}):
        raise ConfigError(f"角色 '{role}' 未绑定有效 provider（config/llm.toml）")
    merged = {**cfg["providers"][provider], **(role_cfg or {})}
    merged.pop("provider", None)
    merged["provider"] = provider
    merged["api_key"] = _resolve_key(provider, merged)
    merged.setdefault("temperature", 0.7)
    merged.setdefault("max_tokens", 4096)
    return LLMRole(merged)


def load_llm_runtime(path: Path | None = None) -> Namespace:
    """读取 config/llm.toml 的 [runtime] 节。"""
    path = path or PROJECT_ROOT / "config" / "llm.toml"
    return Namespace(_load_toml(path).get("runtime", {}))


def llm_roles_summary(path: Path | None = None) -> dict[str, dict[str, str]]:
    """各角色 provider/model 摘要（不含密钥，用于 RunMeta）。"""
    path = path or PROJECT_ROOT / "config" / "llm.toml"
    cfg = _load_toml(path)
    out = {}
    for role in ("user_agent", "assistant_agent", "reference_user"):
        try:
            r = load_llm_role(role, path)
            out[role] = {"provider": r.provider, "model": r.model}
        except ConfigError:
            out[role] = {"provider": "unconfigured", "model": "-"}
    return out
