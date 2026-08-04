"""Harness 注册表：让被测件可插拔（此前 Runner 硬编码 ReferenceHarness）。

新增被测 Harness 只需实现 base.Harness 协议并在此登记；
run 的 meta.json 会记录所用 harness 名，构成可复现性凭证的一部分。
"""

from __future__ import annotations

from usersim.agents.assistant.reference import ReferenceHarness
from usersim.agents.assistant.stub import StubHarness

REGISTRY: dict[str, type] = {
    "reference": ReferenceHarness,   # 参考实现（benchmark 及格线）
    "stub": StubHarness,             # 失能对照：恒定估计、从不安排（应被判 diverged）
}

DEFAULT_HARNESS = "reference"


def resolve(name: str | None) -> type:
    """名 → Harness 类。未知名给出可选项列表（友好报错，与配置加载器风格一致）。"""
    key = name or DEFAULT_HARNESS
    if key not in REGISTRY:
        raise ValueError(f"未知 harness {key!r}，可选: {sorted(REGISTRY)}")
    return REGISTRY[key]


def available() -> list[dict[str, str]]:
    """供 GET /api/harnesses 使用的清单。"""
    return [
        {"name": name, "doc": (cls.__doc__ or "").strip().split("\n")[0]}
        for name, cls in sorted(REGISTRY.items())
    ]
