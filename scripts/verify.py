#!/usr/bin/env python3
"""Check presets before they are installed, and tidy the categories.

Checks (using Homebrew's own metadata, so nothing is guessed):
  * disabled or deprecated casks/formulae   (will fail or warn on a new Mac)
  * casks/formulae that conflict with each other inside one preset (brew bundle would fail)
  * Mac App Store apps listed twice under different ids
  * overlapping tools from references/overlaps.yaml (youtube-dl vs yt-dlp, ...)
  * library placement: a formula must be available wherever the tools that depend on it are

Everything in the `not_needed` preset is treated as excluded, as deploy does.

  verify.py                     report only
  verify.py --apply             move disabled/deprecated items to not_needed and re-home
                                libraries next to their dependents, then rebuild presets.yaml
  verify.py --set CAT KEY...    move items to a category (KEY is `casks:name` or a bare name), then rebuild
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import audit
import categorize
import common
import game

OVERLAPS_FILE = common.REFERENCES_DIR / "overlaps.yaml"


# --------------------------------------------------------------------------
# Homebrew metadata
# --------------------------------------------------------------------------
def fetch_infos(casks: set[str], brews: set[str]) -> tuple[dict[str, dict], dict[str, dict]]:
    cask_info = {c["token"]: c for c in game._brew_json(["--cask", *sorted(casks)])} if casks else {}
    formula_info = {}
    if brews:
        for f in game._brew_json(["--formula", *sorted(brews)]):
            formula_info[f["name"]] = f
            formula_info[f.get("full_name") or f["name"]] = f
    return cask_info, formula_info


def status(info: dict | None) -> tuple[str, str]:
    """('disabled' | 'deprecated' | '', reason)."""
    if not info:
        return "", ""
    if info.get("disabled"):
        return "disabled", info.get("disable_reason") or ""
    if info.get("deprecated"):
        return "deprecated", info.get("deprecation_reason") or ""
    return "", ""


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------
def load_overlaps() -> list[dict]:
    try:
        with open(OVERLAPS_FILE, "r", encoding="utf-8") as f:
            return (common.yaml.safe_load(f) or {}).get("overlaps", [])
    except OSError:
        return []


def check_presets(presets: dict, cask_info: dict, formula_info: dict, overlaps: list[dict] | None = None) -> list[dict]:
    """Findings: {severity: error|warn|info, kind, items, presets, message, fix?}.

    `fix` is {"category": "not_needed", "keys": ["casks:x", ...]} when the problem can be fixed
    automatically.
    """
    overlaps = load_overlaps() if overlaps is None else overlaps
    excluded = common.exclusion_names(presets)
    found: dict[tuple, dict] = {}

    def add(severity, kind, items, preset, message, fix=None):
        key = (kind, tuple(sorted(items)))
        entry = found.setdefault(key, {"severity": severity, "kind": kind, "items": sorted(items), "presets": [],
                                       "message": message, "fix": fix})
        if preset not in entry["presets"]:
            entry["presets"].append(preset)

    for pname, raw in presets.items():
        if pname == common.EXCLUDE_PRESET:
            continue
        preset, _ = _without(raw, excluded)
        casks, brews = set(preset["casks"]), set(preset["brews"])

        for kind, names, infos in (("casks", casks, cask_info), ("brews", brews, formula_info)):
            for name in sorted(names):
                state, reason = status(infos.get(name) or infos.get(common.short_name(name)))
                if state == "disabled":
                    add("error", "disabled", [name], pname, f"{name} is disabled in Homebrew ({reason or 'no reason given'}); brew bundle will fail on it.",
                        {"category": common.EXCLUDE_PRESET, "keys": [f"{kind}:{name}"]})
                elif state == "deprecated":
                    add("warn", "deprecated", [name], pname, f"{name} is deprecated ({reason or 'no reason given'}); it will warn and may be removed.",
                        {"category": common.EXCLUDE_PRESET, "keys": [f"{kind}:{name}"]})

        for token in sorted(casks):
            info = cask_info.get(token) or {}
            clash = set((info.get("conflicts_with") or {}).get("cask") or []) & casks
            for other in sorted(clash):
                add("error", "conflict", [token, other], pname, f"{token} conflicts with {other}; Homebrew cannot install both.")
        for name in sorted(brews):
            info = formula_info.get(name) or formula_info.get(common.short_name(name)) or {}
            for other in sorted(set(info.get("conflicts_with") or []) & {common.short_name(b) for b in brews}):
                add("error", "conflict", [name, other], pname, f"{name} conflicts with {other}; Homebrew cannot install both.")

        by_name: dict[str, set[int]] = {}
        for m in preset["mas"]:
            by_name.setdefault(m["name"].lower(), set()).add(m["id"])
        for name, ids in by_name.items():
            if len(ids) > 1:
                add("warn", "duplicate-app", [f"mas:{i}" for i in sorted(ids)], pname,
                    f"'{name}' appears under {len(ids)} different App Store ids ({', '.join(map(str, sorted(ids)))}); keep one.")

        have = casks | brews | {common.short_name(b) for b in brews}
        for rule in overlaps:
            a, b = rule["items"]
            if a in have and b in have:
                severity = "warn" if rule.get("kind") == "replaced" else "info"
                fix = None
                if rule.get("kind") == "replaced":
                    kind = "casks" if a in casks else "brews"
                    fix = {"category": common.EXCLUDE_PRESET, "keys": [f"{kind}:{a}"]}
                add(severity, "overlap", [a, b], pname, f"{a} and {b} overlap: {rule.get('reason', '')}", fix)
    order = {"error": 0, "warn": 1, "info": 2}
    return sorted(found.values(), key=lambda f: (order[f["severity"]], f["kind"], f["items"]))


def _without(preset: dict, excluded: set[str]) -> tuple[dict, list[str]]:
    import deploy  # local import: deploy imports verify for its pre-install check

    return deploy.apply_excludes(preset, excluded)


# --------------------------------------------------------------------------
# Library placement
# --------------------------------------------------------------------------
def dependents(inventory: dict, formula_info: dict, cask_info: dict) -> dict[str, set[str]]:
    """formula name -> keys (`brews:x` / `casks:y`) of installed items that depend on it directly."""
    inventory_brews = {common.short_name(b): b for b in inventory.get("brews", [])}
    out: dict[str, set[str]] = {}
    seen = set()
    for f in formula_info.values():
        if f["name"] in seen:
            continue
        seen.add(f["name"])
        installed = (f.get("installed") or [{}])[-1]
        for dep in installed.get("runtime_dependencies") or []:
            if dep.get("declared_directly"):
                out.setdefault(common.short_name(dep["full_name"]), set()).add(f"brews:{inventory_brews.get(f['name'], f['name'])}")
    for c in cask_info.values():
        for f in (c.get("depends_on") or {}).get("formula") or []:
            out.setdefault(common.short_name(str(f)), set()).add(f"casks:{c['token']}")
    return out


def plan_library_moves(choices: dict[str, str], inventory: dict, deps: dict[str, set[str]]) -> list[dict]:
    """Where each formula that other installed tools depend on should live.

    A formula should be available wherever its dependents are: with the same category as its
    dependents if they agree, in `common` if they disagree. Formulae already in `common` stay
    there, items are never moved to the exclusion category by this rule, and dependents that
    are excluded or only in "everything" do not count. Repeated until nothing changes, because
    a library can depend on another library.
    """
    current = dict(choices)
    moves: dict[str, dict] = {}
    skip = (game.SKIP, common.EXCLUDE_PRESET, None)
    for _ in range(10):
        changed = False
        for brew in inventory.get("brews", []):
            key = f"brews:{brew}"
            if key not in current or current[key] in (common.EXCLUDE_PRESET,):
                continue
            users = {u: current.get(u) for u in deps.get(common.short_name(brew), ()) if current.get(u) not in skip}
            if not users:
                continue
            cats = set(users.values())
            target = next(iter(cats)) if len(cats) == 1 else "common"
            if current[key] == target or current[key] == "common":
                continue
            moves[key] = {"from": moves.get(key, {}).get("from", current[key]), "to": target,
                          "because": sorted(f"{u.split(':', 1)[1]} ({c})" for u, c in users.items())}
            current[key] = target
            changed = True
        if not changed:
            break
    return [{"key": k, **v} for k, v in moves.items()]


# --------------------------------------------------------------------------
# Applying changes
# --------------------------------------------------------------------------
def resolve_key(token: str, inventory: dict) -> str:
    if ":" in token and token.split(":", 1)[0] in ("casks", "brews", "mas", "vscode"):
        return token
    hits = [it.key for it in game.build_items(inventory) if it.name == token or it.name.lower() == token.lower()]
    if len(hits) != 1:
        sys.exit(f"'{token}' matches {len(hits)} items ({', '.join(hits) or 'none'}); write it as kind:name, e.g. casks:{token}")
    return hits[0]


def rebuild(inventory: dict, write: bool = True) -> dict[str, dict]:
    """Presets as the saved game choices define them (written to presets.yaml unless write=False),
    without auditing again."""
    choices, hotkeys = game.load_choices(), game.load_categories()
    items = game.build_items(inventory)
    data = game.build_grouping(items, choices, list(hotkeys))
    groups, warnings = categorize.from_grouping(data, inventory, "audit:game")
    categorize.apply_shared(groups, inventory, use_rules=False)
    for w in warnings:
        print(f"⚠️  {w}")
    return audit.save_presets(inventory, groups, common.PRESETS_FILE, write=write)


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------
ICON = {"error": "❌", "warn": "⚠️ ", "info": "ℹ️ "}


def print_findings(findings: list[dict]) -> None:
    for f in findings:
        where = ", ".join(f["presets"][:4]) + (f" +{len(f['presets']) - 4} more" if len(f["presets"]) > 4 else "")
        print(f"{ICON[f['severity']]} {f['message']}  [{where}]")


def summary(findings: list[dict]) -> str:
    n = {s: sum(1 for f in findings if f["severity"] == s) for s in ("error", "warn", "info")}
    return f"{n['error']} problem(s) that would break an install, {n['warn']} warning(s), {n['info']} note(s)"


def verify_presets(presets: dict, names: list[str] | None = None) -> list[dict]:
    chosen = {n: p for n, p in presets.items() if not names or n in names or n == common.EXCLUDE_PRESET}
    casks = {c for p in chosen.values() for c in common.normalize_preset(p)["casks"]}
    brews = {b for p in chosen.values() for b in common.normalize_preset(p)["brews"]}
    cask_info, formula_info = fetch_infos(casks, brews)
    return check_presets(chosen, cask_info, formula_info)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", action="append", help="check only these presets (default: all)")
    ap.add_argument("--apply", action="store_true", help="apply the automatic fixes and library moves, then rebuild presets.yaml")
    ap.add_argument("--set", nargs="+", action="append", metavar=("CATEGORY", "KEY"),
                    help="move items to CATEGORY (e.g. --set not_needed casks:vivaldi opera), then rebuild")
    args = ap.parse_args()

    presets = common.load_presets()["presets"]
    if not presets:
        sys.exit(f"No presets found at {common.PRESETS_FILE}. Run audit (or the game) first.")
    inventory = json.loads(common.INVENTORY_FILE.read_text(encoding="utf-8"))
    choices = game.load_choices()
    hotkeys = game.load_categories()
    if choices:  # check what the saved choices produce, not a possibly stale presets.yaml
        presets = rebuild(inventory, write=False)

    print("🔎 Reading Homebrew's package data...")
    brews = {b for b in inventory.get("brews", [])}
    casks = {c for c in inventory.get("casks", [])}
    cask_info, formula_info = fetch_infos(casks, brews)
    findings = check_presets({n: p for n, p in presets.items() if not args.preset or n in args.preset or n == common.EXCLUDE_PRESET},
                             cask_info, formula_info)
    deps = dependents(inventory, formula_info, cask_info)
    moves = plan_library_moves(choices, inventory, deps) if choices else []

    changes: dict[str, str] = {}
    for group in args.set or []:
        category, keys = group[0], group[1:]
        if category not in hotkeys and category != game.SKIP:
            sys.exit(f"Unknown category '{category}'. Known: {', '.join(hotkeys)}")
        for k in keys:
            changes[resolve_key(k, inventory)] = category
    if args.apply:
        for f in findings:
            if f["fix"]:
                changes.update({k: f["fix"]["category"] for k in f["fix"]["keys"]})
        changes.update({m["key"]: m["to"] for m in moves})

    print("\nBefore any changes:" if changes else "")
    print_findings(findings)
    if moves:
        print("\n📚 Library placement (a tool should be available wherever the tools that need it are):")
        for m in moves:
            print(f"   {m['key'].split(':', 1)[1]}: {m['from']} -> {m['to']}, needed by {', '.join(m['because'])}")
    print(f"\n{summary(findings)}.")

    if changes:
        choices.update(changes)
        game.save_choices(choices, hotkeys)
        merged = rebuild(inventory)
        print(f"\n✅ Applied {len(changes)} change(s) to game_choices.json and rebuilt {common.PRESETS_FILE}:")
        for key, category in sorted(changes.items()):
            print(f"   {key} -> {category}")
        after = verify_presets(merged)
        print(f"\nAfter the changes: {summary(after)}.")
        print_findings(after)
    elif (findings and any(f["fix"] for f in findings)) or moves:
        print("Run again with --apply to fix what can be fixed automatically, or --set CATEGORY KEY... for the rest.")
    sys.exit(1 if any(f["severity"] == "error" for f in findings) and not changes else 0)


if __name__ == "__main__":
    main()
