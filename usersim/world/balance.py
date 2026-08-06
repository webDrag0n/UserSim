"""JSON 数值配置加载器：config/balance/*.json 为运行时数据源。

加载并覆盖：恢复事件配表 / 扰动事件配表 / 经济与全局参数 / 习惯化曲线 / 需求参数 / 人格调节；
文件或键缺失时回退代码默认（向后兼容）。进程内缓存 + reload 热更新。
"""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_DIR = Path(__file__).resolve().parent.parent.parent / "config" / "balance"

DIMS = ("valence", "energy", "satiety", "stress")

_cache: dict | None = None


def _load_json(filename: str) -> any:
    path = CONFIG_DIR / filename
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _normalize_effect(d: dict | None) -> dict:
    """把任意 effect 字典归一化为包含四个固定维度的字典；缺失维度补 0。"""
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


def _normalize_template_events(data: list[dict] | None) -> list[dict] | None:
    """把旧版字符串 implicit_effect 迁移为结构化的 EffectDict。"""
    if data is None:
        return None
    for item in data:
        eff = item.get("implicit_effect")
        if isinstance(eff, dict):
            item["implicit_effect"] = _normalize_effect(eff)
        elif isinstance(eff, str) and eff.strip():
            # 尽力解析文本中的“维度 +数值”模式，否则全 0 并把原文放入 note
            parsed = _parse_text_effect(eff)
            item["implicit_effect"] = _normalize_effect(parsed)
            if "note" not in item:
                item["note"] = eff
        else:
            item["implicit_effect"] = _normalize_effect({})
    return data


def _parse_text_effect(text: str) -> dict:
    """从中文文本中解析 effect，如 '精力 -0.06 · 压力 +0.048'。"""
    mapping = {"心情": "valence", "精力": "energy", "饱腹": "satiety", "压力": "stress"}
    out = {}
    # 按常见分隔符切分
    for part in text.replace("·", " ").replace("，", " ").replace(",", " ").split():
        for cn, key in mapping.items():
            if cn in part:
                try:
                    # 提取数字：支持 +0.06 / -0.048 / 0.06
                    num = float("".join(c for c in part if c in "0123456789.-+"))
                    out[key] = num
                except ValueError:
                    pass
    return out


def _normalize_effects_in_list(items: list[dict] | None, key: str = "effect") -> list[dict] | None:
    if items is None:
        return None
    for item in items:
        if key in item:
            item[key] = _normalize_effect(item[key])
    return items


def _normalize_weather(data: dict | None) -> dict | None:
    """归一化天气配置：确保 state_effects 包含四维。"""
    if data is None:
        return None
    effects = data.get("state_effects", {})
    for state, eff in effects.items():
        effects[state] = _normalize_effect(eff)
    return data


def _compute_effects(actions: list[dict]) -> list[dict]:
    """确保每个 variant 有合计 effect（base_effect + weight），并归一化维度。"""
    for a in actions:
        a["base_effect"] = _normalize_effect(a.get("base_effect"))
        for v in a.get("variants", []):
            v["weight"] = _normalize_effect(v.get("weight"))
            total = dict(a["base_effect"])
            for k, val in v["weight"].items():
                if isinstance(val, (int, float)):
                    total[k] = total.get(k, 0) + val
                else:
                    total[k] = val
            v["effect"] = total
    return actions


def load_overrides(force: bool = False) -> dict:
    """返回覆盖表；source ∈ json|default|default(error)。"""
    global _cache
    if _cache is not None and not force:
        return _cache

    out: dict = {"habituation": {}, "needs": {}, "persona_mod": {}, "source": "default"}

    try:
        hab = _load_json("habituation.json")
        if hab:
            out["habituation"] = hab
            out["source"] = "json"

        needs = _load_json("needs.json")
        if needs:
            out["needs"] = needs
            out["source"] = "json"

        persona_mod = _load_json("persona_modulation.json")
        if persona_mod:
            out["persona_mod"] = persona_mod
            out["source"] = "json"

        recovery = _load_json("recovery_actions.json")
        if recovery:
            out["recovery_actions"] = _compute_effects(recovery)
            out["source"] = "json"

        disturbances = _load_json("disturbances.json")
        if disturbances:
            out["disturbances"] = _normalize_effects_in_list(disturbances)
            out["source"] = "json"

        eco = _load_json("economy.json")
        if eco:
            out["economy_params"] = eco
            out["source"] = "json"

        dyn = _load_json("dynamics.json")
        if dyn:
            out["dynamics_params"] = dyn
            out["source"] = "json"

        meal_tiers = _load_json("meal_tiers.json")
        if meal_tiers:
            out["meal_tiers"] = _normalize_effects_in_list(meal_tiers)
            out["source"] = "json"

        sleep_tiers = _load_json("sleep_tiers.json")
        if sleep_tiers:
            out["sleep_tiers"] = _normalize_effects_in_list(sleep_tiers)
            out["source"] = "json"

        custom_activities = _load_json("custom_activities.json")
        if custom_activities:
            out["custom_activities"] = _normalize_effects_in_list(custom_activities)
            out["source"] = "json"

        professions = _load_json("professions.json")
        if professions:
            out["professions"] = professions
            out["source"] = "json"

        template_events = _load_json("template_events.json")
        if template_events:
            out["template_events"] = _normalize_template_events(template_events)
            out["source"] = "json"

        weather = _load_json("weather.json")
        if weather:
            out["weather"] = _normalize_weather(weather)
            out["source"] = "json"

    except Exception:
        out["source"] = "default(error)"

    _cache = out
    return out


def reload() -> dict:
    return load_overrides(force=True)


def get_config_dir() -> Path:
    return CONFIG_DIR


def list_config_files() -> list[str]:
    """列出所有配置文件名（不含路径）。"""
    return [f.name for f in sorted(CONFIG_DIR.glob("*.json"))] if CONFIG_DIR.exists() else []


def save_config_file(filename: str, data: any) -> None:
    """保存配置文件并使缓存失效。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    path = CONFIG_DIR / filename
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    reload()


def reset_config_file(filename: str) -> bool:
    """从代码默认值重置指定配置文件；返回是否成功。"""
    from usersim.world import catalog, anthro

    defaults: dict[str, any] = {
        "recovery_actions.json": catalog.RECOVERY_ACTIONS,
        "meal_tiers.json": catalog.MEAL_TIERS,
        "sleep_tiers.json": catalog.SLEEP_TIERS,
        "custom_activities.json": catalog.CUSTOM_ACTIVITIES,
        "professions.json": catalog.PROFESSIONS,
        "disturbances.json": catalog.DISTURBANCES,
        "template_events.json": catalog.TEMPLATE_EVENTS,
        "economy.json": {
            "initial_money": catalog.ECONOMY["initial_money"],
            "overtime_income": catalog.ECONOMY["overtime_income"],
            "debt_stress_per_slot": catalog.ECONOMY["debt_stress_per_slot"],
        },
        "habituation.json": {
            name: {"w_min": w, "tau": t, "curve": c}
            for name, (w, t, c) in anthro.HABITUATION_DEFAULTS.items()
        },
    }

    if filename not in defaults:
        return False

    save_config_file(filename, defaults[filename])
    return True
