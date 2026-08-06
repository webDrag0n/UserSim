#!/usr/bin/env python3
"""Balance 配置 schema 归一化脚本（幂等）。

把 effect 相关字段统一为包含 valence/energy/satiety/stress 四维的字典；
把 template_events.implicit_effect 从文本迁移为结构化 effect；
把 persona_modulation.rule 迁移为可执行 formula。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config" / "balance"
DIMS = ("valence", "energy", "satiety", "stress")
DIM_LABELS = {"valence": "心情", "energy": "精力", "satiety": "饱腹", "stress": "压力"}


def normalize_effect(d: dict | None) -> dict:
    if d is None:
        d = {}
    out = {}
    for dim in DIMS:
        v = d.get(dim)
        if isinstance(v, dict) and "pull" in v:
            try:
                out[dim] = {"pull": [float(v["pull"][0]), float(v["pull"][1])]}
            except (IndexError, ValueError, TypeError):
                out[dim] = 0.0
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            out[dim] = float(v)
        else:
            out[dim] = 0.0
    return out


def parse_text_effect(text: str) -> dict:
    out = {}
    text = text.replace("·", " ").replace("，", " ").replace(",", " ")
    tokens = text.split()
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        for cn, key in DIM_LABELS.items():
            if cn in tok:
                # 数字可能在同一 token，也可能在下一个 token
                num_str = "".join(c for c in tok if c in "0123456789.-+")
                if not num_str and i + 1 < len(tokens):
                    num_str = "".join(c for c in tokens[i + 1] if c in "0123456789.-+")
                    if num_str:
                        i += 1
                if num_str:
                    try:
                        out[key] = float(num_str)
                    except ValueError:
                        pass
                break
        i += 1
    return out


def migrate_file(path: Path) -> bool:
    key = path.stem
    raw = json.loads(path.read_text(encoding="utf-8"))
    changed = False

    if key == "recovery_actions":
        for action in raw:
            action["base_effect"] = normalize_effect(action.get("base_effect"))
            for v in action.get("variants", []):
                v["weight"] = normalize_effect(v.get("weight"))
                total = dict(action["base_effect"])
                for k, val in v["weight"].items():
                    if isinstance(val, (int, float)):
                        total[k] = total.get(k, 0) + val
                    else:
                        total[k] = val
                v["effect"] = normalize_effect(total)
            changed = True

    elif key in ("disturbances", "meal_tiers", "sleep_tiers", "custom_activities"):
        for item in raw:
            item["effect"] = normalize_effect(item.get("effect"))
        changed = True

    elif key == "template_events":
        for item in raw:
            eff = item.get("implicit_effect")
            if isinstance(eff, dict):
                item["implicit_effect"] = normalize_effect(eff)
            elif isinstance(eff, str) and eff.strip():
                parsed = parse_text_effect(eff)
                item["implicit_effect"] = normalize_effect(parsed)
                if "note" not in item:
                    item["note"] = eff
            else:
                item["implicit_effect"] = normalize_effect({})
            changed = True

    elif key == "persona_modulation":
        # 补齐大五人格全部五个维度
        big5_defaults = {
            "外向性": {"rule": "社交事件精力×(1+1.2E)/(1.6-1.2E)；E>0.7 额外心情+0.03", "intent": "社交电池：内向耗电、外向回血", "formula": "1 + 1.2*E"},
            "神经质": {"rule": "压力事件效果×(1+N-0.5)；压力均值回归速率×(1-0.4N)", "intent": "高神经质更敏感、恢复更慢", "formula": "1 + (N - 0.5)"},
            "开放性": {"rule": "文化/新异事件效果×(0.7+0.6O)", "intent": "高开放性更享受新刺激", "formula": "0.7 + 0.6*O"},
            "尽责性": {"rule": "工作/成就事件的负面压力×(1-0.3C)", "intent": "高尽责性更能承压、推进任务", "formula": "1 - 0.3*C"},
            "宜人性": {"rule": "社交事件正面心情×(1+0.3A)", "intent": "高宜人性社交更融洽", "formula": "1 + 0.3*A"},
        }
        for dim, defaults in big5_defaults.items():
            if dim not in raw:
                raw[dim] = dict(defaults)
                changed = True
        for dim, entry in raw.items():
            rule = entry.get("rule", "")
            formula = entry.get("formula", "")
            if formula:
                pass
            elif rule:
                formula = _rule_to_formula(dim, rule)
                entry["formula"] = formula
                entry["intent"] = entry.get("intent", rule)
                changed = True
            if "intent" not in entry:
                entry["intent"] = ""
        changed = True

    elif key == "needs":
        for name, entry in raw.items():
            for field in ("urge_curve", "satisfy_curve"):
                val = entry.get(field, "")
                if isinstance(val, str):
                    cleaned = _clean_formula(val)
                    # 成就满足曲线旧文本不是公式，强制给默认可执行表达式
                    if name == "成就" and field == "satisfy_curve":
                        if not _looks_like_formula(cleaned) or any(c in cleaned for c in "∝ release 完成时"):
                            cleaned = "1+1.2*u"
                    entry[field] = cleaned
        changed = True

    elif key == "habituation":
        # 为合并后的事件配置表补齐餐饮/睡眠/自定义活动的默认习惯化参数
        defaults = {
            "三餐": {"w_min": 0.50, "tau": 12, "curve": "exp"},
            "睡眠": {"w_min": 0.55, "tau": 8, "curve": "exp"},
            "自定义活动": {"w_min": 0.40, "tau": 8, "curve": "exp"},
        }
        for name, params in defaults.items():
            if name not in raw:
                raw[name] = dict(params)
                changed = True
        for entry in raw.values():
            for field in ("w_min", "tau"):
                if field in entry:
                    entry[field] = float(entry[field])
            if "curve" in entry:
                entry["curve"] = str(entry["curve"])
        changed = True

    if changed:
        new_text = json.dumps(raw, ensure_ascii=False, indent=2) + "\n"
        if new_text != path.read_text(encoding="utf-8"):
            path.write_text(new_text, encoding="utf-8")
        else:
            changed = False
    return changed


def _clean_formula(expr: str) -> str:
    expr = expr.replace("u=", "").replace("s=", "").replace("·", "*").strip()
    # 把 Unicode 上标换成 **
    expr = expr.replace("²", "**2").replace("³", "**3")
    # 把 ^ 换成 **
    expr = expr.replace("^", "**")
    # 把 |x| 转成 abs(x)
    expr = re.sub(r"\|([^|]+)\|", r"abs(\1)", expr)
    # 隐式乘法：2x → 2*x
    expr = re.sub(r"(\d)([a-zA-Z])", r"\1*\2", expr)
    return expr


def _rule_to_formula(dim: str, rule: str) -> str:
    """把旧规则文本尽量转换为可执行公式；转换不了就保留原文让前端展示。"""
    rule = rule.strip()
    if dim == "外向性":
        return "1 + 1.2*E"
    if dim == "神经质":
        return "1 + (N - 0.5)"
    if dim == "开放性":
        return "0.7 + 0.6*O"
    if dim == "尽责性":
        return "1 - 0.3*C"
    if dim == "宜人性":
        return "1 + 0.3*A"
    return rule


def _looks_like_formula(expr: str) -> bool:
    """粗略判断字符串是否像可执行公式（含数字、变量或运算符）。"""
    expr = expr.strip()
    if not expr:
        return False
    return any(c in expr for c in "0123456789xXuUnNeEoOcCaA+-*/()") or "abs" in expr or "sqrt" in expr


def main() -> None:
    if not CONFIG_DIR.exists():
        print(f"配置目录不存在: {CONFIG_DIR}")
        return

    for path in sorted(CONFIG_DIR.glob("*.json")):
        changed = migrate_file(path)
        status = "已更新" if changed else "无需改动"
        print(f"{path.name}: {status}")


if __name__ == "__main__":
    main()
