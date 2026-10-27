#!/usr/bin/env python3
"""Audit this Mac and write role presets to data/presets.yaml.

Sources scanned: Homebrew (formulae, casks, taps), Mac App Store apps, VS Code
extensions, and apps in /Applications and ~/Applications that Homebrew does not
manage. Manually installed apps are only adopted when a real cask exists for
them; everything else is listed in data/inventory.json as "unmatched" instead of
being guessed into a Brewfile that would fail on the new Mac.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import categorize
import common
from ai_skill import ai_configured, call_ai


# --------------------------------------------------------------------------
# Collection
# --------------------------------------------------------------------------
def collect_homebrew() -> dict:
    """Use `brew bundle dump` (it already folds in taps, casks, mas and vscode)."""
    inv = common.empty_preset()
    if not common.have("brew"):
        print("⚠️  Homebrew not found: skipping formulae, casks and taps.")
        return inv
    print("📦 Dumping Homebrew state...")
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "Brewfile"
        common.run(["brew", "bundle", "dump", "--file", str(target), "--force"], timeout=600)
        if not target.exists():
            print("⚠️  `brew bundle dump` failed; Homebrew data skipped.")
            return inv
        inv, _ = common.parse_brewfile(target.read_text(encoding="utf-8"))

    # `brew bundle dump` only includes these when the helper CLIs are installed. Fall back
    # to the helper CLIs directly.
    if not inv["mas"]:
        out = common.run(["mas", "list"])
        for line in (out or "").splitlines():
            m = re.match(r"^\s*(\d+)\s+(.+?)\s+\(", line)
            if m:
                inv["mas"].append({"name": m.group(2).strip(), "id": int(m.group(1))})
    if not inv["vscode"]:
        out = common.run(["code", "--list-extensions"])
        inv["vscode"] = [l.strip() for l in (out or "").splitlines() if l.strip()]
    return inv


def app_dirs() -> list[Path]:
    override = os.environ.get("MAC_SETUP_APP_DIRS")  # used by the test suite
    if override:
        return [Path(p) for p in override.split(os.pathsep) if p]
    return [Path("/Applications"), Path.home() / "Applications"]


def iter_apps(root: Path):
    """Yield .app bundles in root and one folder level below (e.g. Adobe's per-app folders)."""
    if not root.is_dir():
        return
    for entry in sorted(root.iterdir()):
        if entry.suffix == ".app":
            yield entry
        elif entry.is_dir() and not entry.is_symlink():
            for sub in sorted(entry.iterdir()):
                if sub.suffix == ".app":
                    yield sub


def bundle_id(app: Path) -> str:
    try:
        with open(app / "Contents" / "Info.plist", "rb") as f:
            return str(plistlib.load(f).get("CFBundleIdentifier", ""))
    except Exception:  # noqa: BLE001 - unreadable bundles are simply treated as unknown
        return ""


def looks_managed(app_name: str, managed_casks: set[str]) -> bool:
    """Name-based fallback (iTerm.app vs the cask `iterm2`), used only when Homebrew's cask
    metadata is unavailable. Homebrew's own app/bundle-id data is preferred because fuzzy
    names also swallow unrelated apps (the `claude` app vs the `claude-code` cask)."""
    n = common.alnum(app_name)
    if len(n) < 4:
        return False
    for token in managed_casks:
        t = common.alnum(token)
        if t == n or t.startswith(n) or (len(t) >= 5 and n.startswith(t)):
            return True
    return False


def load_consolidation() -> dict[str, dict]:
    """Rules that replace a family of apps with one installer/launcher cask."""
    path = common.REFERENCES_DIR / "categories.yaml"
    with open(path, "r", encoding="utf-8") as f:
        return (common.yaml.safe_load(f) or {}).get("consolidate", {}) or {}


def consolidation_target(token: str, bundle: str, rules: dict[str, dict]) -> str | None:
    for target, rule in rules.items():
        if token == target:
            return None
        if token and any(re.search(p, token) for p in rule.get("cask_patterns", [])):
            return target
        if bundle and any(bundle.startswith(p) for p in rule.get("bundle_prefixes", [])):
            return target
    return None


def resolve_casks(name: str, bundle: str, index: dict | None, known: set[str] | None) -> list[str]:
    """Cask tokens that install this app, best first. Uses Homebrew's artifact metadata
    (app bundle name, then bundle id) and falls back to guessing from the name."""
    if index is None:
        return [c for c in common.cask_candidates(name) if known and c in known]
    found: list[str] = []
    for token in index["apps"].get(name.lower(), []) + index["bundles"].get(bundle, []):
        if token not in found:
            found.append(token)
    slugs = common.cask_candidates(name)
    # Casks installed from a .pkg (Zoom, Office) or with versioned app names list no matching
    # .app artifact, so a cask named like the app is still a good answer.
    found += [c for c in slugs if known and c in known and c not in found]
    found.sort(key=lambda t: (t in index["unusable"], t not in slugs))
    return found


def scan_apps(managed_casks: set[str], known_casks: set[str] | None,
              index: dict | None = None, rules: dict[str, dict] | None = None) -> dict:
    rules = rules or {}
    unusable = index["unusable"] if index else set()
    adopted, unmatched, mas_apps, apple = [], [], [], 0
    consolidated: dict[str, list[str]] = {}
    seen = set()
    for root in app_dirs():
        for app in iter_apps(root):
            name = app.stem
            if name in seen:
                continue
            seen.add(name)
            bundle = bundle_id(app)
            if bundle.startswith("com.apple."):
                apple += 1
                continue
            if (app / "Contents" / "_MASReceipt").exists():
                mas_apps.append(name)  # covered by the `mas` list
                continue
            tokens = resolve_casks(name, bundle, index, known_casks)
            target = consolidation_target(tokens[0] if tokens else "", bundle, rules)
            if target:
                consolidated.setdefault(target, []).append(name)
                continue
            if any(t in managed_casks for t in tokens):
                continue
            if index is None and looks_managed(name, managed_casks):
                continue
            usable = [t for t in tokens if t not in unusable]
            if usable and index and any(
                m in index["conflicts"].get(usable[0], ()) or usable[0] in index["conflicts"].get(m, ())
                for m in managed_casks
            ):
                continue  # e.g. Word.app belongs to the installed microsoft-office suite, not to the microsoft-word cask
            if usable:
                adopted.append(usable[0])
            else:
                unmatched.append(name)
    return {
        "adopted_casks": sorted(set(adopted)),
        "unmatched_apps": sorted(set(unmatched), key=str.lower),
        "mas_apps_seen": sorted(set(mas_apps), key=str.lower),
        "apple_apps_skipped": apple,
        "consolidated": {t: sorted(set(v), key=str.lower) for t, v in consolidated.items()},
    }


def repair_cask_list() -> set[str]:
    """Homebrew's cask list is empty (its cached name file is missing). Offer `brew update`, which
    rebuilds it, and re-check the count. Exits with instructions if the user declines or it stays empty."""
    print("\n⚠️  Homebrew's cask list is empty (`brew casks` printed nothing). Without it, installed apps cannot be\n"
          "   matched to casks and the inventory would be incomplete. `brew update` rebuilds the list.")
    if not common.confirm("Run `brew update` now? (it refreshes Homebrew's own package data; nothing is installed)"):
        sys.exit("Not updating. Run `brew update` yourself, check that `brew casks | wc -l` is in the thousands, then re-run.\n"
                 "To continue anyway with partial data, add --allow-incomplete.")
    if subprocess.run(["brew", "update"]).returncode != 0:
        sys.exit("❌ `brew update` failed (see its output above). Fix that, then re-run.")
    common.reset_token_cache()
    known = common.available_casks()
    print(f"🔎 `brew casks` now lists {len(known or ())} casks.")
    if not known:
        sys.exit("❌ The cask list is still empty after `brew update`. Try `brew doctor`, then re-run.")
    return known


def build_inventory(allow_incomplete: bool = False) -> dict:
    inv = collect_homebrew()
    known = common.available_casks()
    if known is None and common.have("brew") and not allow_incomplete:
        known = repair_cask_list()
    if known is None:
        print("⚠️  Cannot list Homebrew casks here, so manually installed apps cannot be matched to casks.")
    index = common.cask_index() if known else None
    if known and index is None:
        print("⚠️  Homebrew cask metadata unavailable; falling back to matching by app name.")
    rules = load_consolidation()
    scan = scan_apps(set(inv["casks"]), known, index, rules)

    # Casks brew already installs can belong to a consolidated family too (e.g. intellij-idea-ce).
    consolidated = scan["consolidated"]
    kept = []
    for token in set(inv["casks"]) | set(scan["adopted_casks"]):
        target = consolidation_target(token, "", rules)
        if target:
            consolidated.setdefault(target, []).append(token)
        else:
            kept.append(token)
    for target in consolidated:
        if target in (known or set()):
            kept.append(target)
    scan["consolidated"] = {t: sorted(set(v), key=str.lower) for t, v in consolidated.items()}
    inventory = {
        "generated": date.today().isoformat(),
        "taps": sorted(inv["taps"]),
        "brews": sorted(inv["brews"]),
        "casks": sorted(set(kept)),
        "mas": sorted(inv["mas"], key=lambda m: m["name"].lower()),
        "vscode": sorted(inv["vscode"]),
        **scan,
    }
    return inventory


# --------------------------------------------------------------------------
# Categorization
# --------------------------------------------------------------------------
def ai_grouping(inventory: dict) -> dict | None:
    print(f"🧠 Asking {os.environ.get('LLM_MODEL')} to group your tools.")
    print("   (This sends the NAMES of your installed tools to that provider. Ctrl-C now to cancel.)")
    mas_names = [m["name"] for m in inventory["mas"]]
    prompt = f"""
Group these macOS tools into role-based presets.
Casks: {inventory['casks']}
Brews: {inventory['brews']}
Mac App Store apps: {mas_names}
VS Code extensions: {inventory['vscode']}

Use ONLY items from the lists above, exactly as written (the shared "common" tools are added to every group automatically); an item may appear in several groups.
Groups: "developer" (software engineering), "creative" (design, photo, video, audio), "essentials" (productivity and system utilities).
Respond ONLY with a JSON object of this shape:
{{"developer": {{"casks": [], "brews": [], "mas": [], "vscode": []}}, "creative": {{...}}, "essentials": {{...}}}}
"""
    return call_ai(prompt)


def choose_groups(inventory: dict, args) -> dict[str, dict]:
    groups, warnings = None, []
    if args.categorization:
        data = json.loads(Path(args.categorization).read_text(encoding="utf-8"))
        groups, warnings = categorize.from_grouping(data, inventory, "audit:assistant")
    elif args.game:
        import game  # imported lazily: game needs audit's helpers too

        cats = [c.strip() for c in args.categories.split(",") if c.strip()]
        data = game.play(inventory, cats, redo=args.redo, icon_mode=args.icons,
                         include_deps=args.include_dependencies)
        groups, warnings = categorize.from_grouping(data, inventory, "audit:game")
        categorize.apply_shared(groups, inventory, use_rules=False)
        return groups
    elif args.ai:
        if not ai_configured():
            print("⚠️  --ai needs LLM_MODEL set and litellm installed. Using built-in rules instead.")
        else:
            data = ai_grouping(inventory)
            if data:
                groups, warnings = categorize.from_grouping(data, inventory, "audit:ai")
                print("✅ AI grouping applied (unknown items dropped).")
    if not groups:
        groups = categorize.heuristic(inventory)
    categorize.apply_shared(groups, inventory)  # the shared `common` preset goes into every preset, however they were grouped
    for w in warnings:
        print(f"⚠️  {w}")
    return groups


# --------------------------------------------------------------------------
def save_presets(inventory: dict, groups: dict[str, dict], out_path: Path, write: bool = True) -> dict[str, dict]:
    """Write current_system plus `groups` to out_path, keeping presets that were imported or hand-made."""
    everything = common.empty_preset("Everything installed on the audited Mac.", "audit")
    for key in (*common.LIST_KEYS, "mas"):
        everything[key] = list(inventory[key])
    new_presets = {"current_system": everything, **groups}
    existing = common.load_presets(out_path)["presets"]
    kept = {n: p for n, p in existing.items() if not str(p.get("source", "")).startswith("audit") and n not in new_presets}
    merged = {**new_presets, **kept}
    merged = {n: common.normalize_preset(p) for n, p in merged.items()}
    if write:
        common.save_presets({"presets": merged}, out_path)
    return merged


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ai", action="store_true", help="group tools with an LLM (needs LLM_MODEL; sends tool names to the provider)")
    ap.add_argument("--categorization", metavar="FILE", help="JSON grouping produced by an assistant, instead of rules/LLM")
    ap.add_argument("--game", action="store_true", help="sort every installed item into categories in an interactive, swipe-style terminal game")
    ap.add_argument("--categories", default="developer,common,not_needed", help="game categories, comma-separated, optionally name:hotkey (default: developer,common,not_needed)")
    ap.add_argument("--redo", action="store_true", help="game: ignore saved choices and start over")
    ap.add_argument("--include-dependencies", action="store_true", help="game: also ask about tools that are only installed as dependencies")
    ap.add_argument("--icons", choices=["auto", "iterm", "kitty", "off"], default="auto", help="game: how to draw app icons")
    ap.add_argument("--allow-incomplete", action="store_true", help="continue even if Homebrew's cask list is unavailable (apps will not be matched to casks)")
    ap.add_argument("--inventory-only", action="store_true", help="write data/inventory.json and stop")
    ap.add_argument("--output", default=str(common.PRESETS_FILE), help="presets file to write (default: data/presets.yaml)")
    args = ap.parse_args()

    common.DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("🔍 Auditing this Mac...")
    inventory = build_inventory(args.allow_incomplete)
    common.INVENTORY_FILE.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(
        f"✅ {len(inventory['casks'])} apps (casks), {len(inventory['brews'])} CLI tools, "
        f"{len(inventory['mas'])} App Store apps, {len(inventory['vscode'])} VS Code extensions."
    )
    if args.inventory_only:
        print(f"📝 Inventory written to {common.INVENTORY_FILE}")
        return

    out_path = Path(args.output)
    merged = save_presets(inventory, choose_groups(inventory, args), out_path)

    print(f"\n🎉 Presets written to {out_path}:")
    for name, preset in merged.items():
        print(f"   • {name}: {common.preset_size(preset)} items - {preset.get('description', '')}")
    if inventory["unmatched_apps"]:
        print("\nℹ️  Apps with no matching Homebrew cask (install these by hand or from the vendor):")
        for name in inventory["unmatched_apps"]:
            print(f"   - {name}")
    try:
        import verify  # lazy: verify imports audit

        findings = verify.verify_presets(merged)
        if findings:
            print(f"\n🔎 Verification: {verify.summary(findings)}. Details and fixes: setup.sh verify")
    except Exception as exc:  # noqa: BLE001 - the check is advisory and must never fail an audit
        print(f"\nℹ️  Skipped the verification step ({exc}). Run setup.sh verify to retry.")
    print("\n⚠️  presets.yaml lists everything you have installed. Review it before pushing to a public repo.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
