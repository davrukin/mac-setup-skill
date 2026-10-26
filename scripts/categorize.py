"""Sort inventory items into role presets (developer, creative, essentials, ...).

Heuristic rules live in references/categories.yaml so they can be edited without
touching code. An assistant (or an LLM) can supply its own grouping instead; that
grouping is validated against the real inventory so invented items never get in.
"""
from __future__ import annotations

import re
from collections import Counter

import common


def load_rules() -> dict:
    path = common.REFERENCES_DIR / "categories.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return (common.yaml.safe_load(f) or {}).get("presets", {})


def _matches(rule: dict, kind: str, name: str) -> bool:
    short = common.short_name(name)
    if short in (rule.get(kind) or []) or name in (rule.get(kind) or []):
        return True
    return any(re.search(p, short) for p in rule.get("patterns") or [])


def item_categories(kind: str, name: str, rules: dict | None = None) -> list[str]:
    """Which role presets an item belongs to. kind is 'brews' | 'casks' | 'mas'."""
    rules = rules or load_rules()
    hits = []
    for preset_name, rule in rules.items():
        if kind == "mas":
            if any(re.search(p, name) for p in rule.get("mas_patterns") or []):
                hits.append(preset_name)
        elif _matches(rule, kind, name):
            hits.append(preset_name)
    return hits


def category_hits(preset: dict, rules: dict | None = None) -> Counter:
    """How many of a preset's items fall into each role (used to pick relevant recommendations)."""
    rules = rules or load_rules()
    counts: Counter = Counter()
    for kind in ("brews", "casks"):
        for name in preset.get(kind) or []:
            counts.update(item_categories(kind, name, rules))
    for entry in preset.get("mas") or []:
        counts.update(item_categories("mas", entry["name"], rules))
    if preset.get("vscode"):
        for preset_name, rule in rules.items():
            if rule.get("vscode") == "all":
                counts[preset_name] += len(preset["vscode"])
    return counts


def heuristic(inventory: dict) -> dict[str, dict]:
    """Group the inventory with the rules file. Returns {preset_name: preset_dict}."""
    rules = load_rules()
    groups: dict[str, dict] = {}
    for preset_name, rule in rules.items():
        group = common.empty_preset(rule.get("description", ""), "audit:heuristic")
        for kind in ("brews", "casks"):
            group[kind] = [n for n in inventory.get(kind, []) if preset_name in item_categories(kind, n, rules)]
        group["mas"] = [m for m in inventory.get("mas", []) if preset_name in item_categories("mas", m["name"], rules)]
        if rule.get("vscode") == "all":
            group["vscode"] = list(inventory.get("vscode", []))
        group["taps"] = common.taps_needed(group)
        if common.preset_size(group):
            groups[preset_name] = group
    return groups


def apply_shared(groups: dict[str, dict], inventory: dict) -> None:
    """Make every `shared: true` preset from the rules file part of ALL presets.

    Runs after any grouping (built-in rules, an assistant's JSON, or an LLM) so the shared
    the common set is never left to the grouper. Only items that are really in the inventory are added.
    """
    rules = load_rules()
    shared = {n: r for n, r in rules.items() if r.get("shared")}
    for name, rule in shared.items():
        base = groups.setdefault(name, common.empty_preset(rule.get("description", ""), "audit:shared"))
        for kind in ("brews", "casks"):
            found = [n for n in inventory.get(kind, []) if _matches(rule, kind, n)]
            base[kind] = sorted(set(base.get(kind) or []) | set(found))
        have = {m["id"] for m in base.get("mas") or []}
        base["mas"] = (base.get("mas") or []) + [
            m for m in inventory.get("mas", [])
            if m["id"] not in have and any(re.search(p, m["name"]) for p in rule.get("mas_patterns") or [])
        ]
        base["taps"] = common.taps_needed(base)
    for name, group in list(groups.items()):
        if name in shared or name == "current_system":
            continue
        for src in shared:
            for kind in ("brews", "casks"):
                group[kind] = sorted(set(group.get(kind) or []) | set(groups[src].get(kind) or []))
            known = {m["id"] for m in group.get("mas") or []}
            group["mas"] = (group.get("mas") or []) + [m for m in groups[src].get("mas") or [] if m["id"] not in known]
        group["taps"] = common.taps_needed(group)
    for name in [n for n in shared if not common.preset_size(groups[n])]:
        del groups[name]  # nothing from the shared list is installed here


def from_grouping(grouping: dict, inventory: dict, source: str) -> tuple[dict[str, dict], list[str]]:
    """Turn an assistant/LLM grouping into presets, dropping anything not in the inventory.

    Accepted shape: {"<name>": {"description"?, "casks": [], "brews": [], "mas": [names or ids], "vscode": []}}
    Returns (presets, warnings).
    """
    warnings: list[str] = []
    have_brews, have_casks = set(inventory.get("brews", [])), set(inventory.get("casks", []))
    have_vscode = set(inventory.get("vscode", []))
    mas_by_id = {m["id"]: m for m in inventory.get("mas", [])}
    mas_by_name = {m["name"].lower(): m for m in inventory.get("mas", [])}

    presets: dict[str, dict] = {}
    for name, spec in (grouping or {}).items():
        if not isinstance(spec, dict):
            continue
        group = common.empty_preset(spec.get("description") or f"{name} tools", source)
        for kind, pool in (("brews", have_brews), ("casks", have_casks), ("vscode", have_vscode)):
            for item in spec.get(kind) or []:
                if item in pool:
                    group[kind].append(item)
                else:
                    warnings.append(f"{name}: dropped unknown {kind[:-1]} '{item}'")
        for item in spec.get("mas") or []:
            entry = None
            if isinstance(item, dict):
                entry = mas_by_id.get(item.get("id"))
            elif isinstance(item, int) or str(item).isdigit():
                entry = mas_by_id.get(int(item))
            else:
                entry = mas_by_name.get(str(item).lower())
            if entry:
                group["mas"].append(entry)
            else:
                warnings.append(f"{name}: dropped unknown Mac App Store app '{item}'")
        group["taps"] = common.taps_needed(group)
        if common.preset_size(group):
            presets[name] = group
    return presets, warnings
