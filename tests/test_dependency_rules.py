"""依赖规则 CI 检查（docs/00-architecture.md 第 2 节依赖表）。

第一公理的第 3 条要求四个组件只能通过 contracts 通信。此前该规则仅由
code review 维护，实际已被违反（agents/evaluator 都曾 import world.dynamics）。
本测试把依赖表变成可机器检查的断言。
"""

from __future__ import annotations

import ast
from pathlib import Path

PKG_ROOT = Path(__file__).resolve().parent.parent / "usersim"

# 包 → 禁止 import 的包集合（docs/00 依赖表）
FORBIDDEN: dict[str, set[str]] = {
    "contracts": {"world", "agents", "evaluator", "llm", "server", "bench", "config", "runner"},
    "world": {"agents", "evaluator", "llm", "server", "bench", "runner"},
    "agents": {"world", "evaluator", "server", "bench", "runner"},
    "evaluator": {"world", "agents", "llm", "server", "bench", "runner"},
    "llm": {"world", "agents", "evaluator", "server", "bench", "runner"},
}

# 组装点：允许 import 一切（唯一豁免，见 docs/00 第 3.1 节编排者模式）
ASSEMBLY_POINTS = {"server", "bench", "runner", "cli"}


def _imported_subpackages(py_file: Path) -> set[str]:
    """提取该文件 import 的 usersim 子包名（含函数内的延迟 import）。"""
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("usersim"):
            parts = node.module.split(".")
            if len(parts) >= 2:
                found.add(parts[1])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith("usersim."):
                    parts = alias.name.split(".")
                    if len(parts) >= 2:
                        found.add(parts[1])
    return found


def _iter_package_files(pkg: str):
    root = PKG_ROOT / pkg
    if root.is_dir():
        yield from (p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_dependency_table_is_respected() -> None:
    violations: list[str] = []
    for pkg, forbidden in FORBIDDEN.items():
        for py in _iter_package_files(pkg):
            for imported in _imported_subpackages(py) & forbidden:
                rel = py.relative_to(PKG_ROOT.parent)
                violations.append(f"{rel} 违规 import usersim.{imported}（{pkg} 不得依赖 {imported}）")
    assert not violations, "依赖规则违规：\n" + "\n".join(violations)


def test_world_and_evaluator_have_no_llm_calls() -> None:
    """第一公理第 1 条：world 与 evaluator 禁止任何 LLM 调用。"""
    offenders: list[str] = []
    for pkg in ("world", "evaluator"):
        for py in _iter_package_files(pkg):
            text = py.read_text(encoding="utf-8")
            for needle in ("openai", "OpenAI", "chat_json", "LLMClient"):
                if needle in text:
                    offenders.append(f"{py.relative_to(PKG_ROOT.parent)} 含 LLM 痕迹: {needle}")
    assert not offenders, "world/evaluator 出现 LLM 调用：\n" + "\n".join(offenders)


def test_no_unregistered_cross_package_assembler() -> None:
    """组装点集合封闭：任何同时 import world 与 agents 的模块必须已登记为组装点。

    方向很重要——断言"登记项都存在"会在删包时误报，而真正要防的是
    **新增未登记的组装者**绕过依赖表。
    """
    unregistered: list[str] = []
    for py in PKG_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        top = py.relative_to(PKG_ROOT).parts[0]
        top_name = top[:-3] if top.endswith(".py") else top
        if top_name in ASSEMBLY_POINTS:
            continue
        imported = _imported_subpackages(py)
        if {"world", "agents"} <= imported:
            unregistered.append(str(py.relative_to(PKG_ROOT.parent)))
    assert not unregistered, (
        "以下模块同时组装 world 与 agents，但未登记为组装点：\n" + "\n".join(unregistered)
    )
