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
    """Catch naming mismatches like iTerm.app vs the cask `iterm2`."""
    n = common.alnum(app_name)
    if len(n) < 4:
        return False
    for token in managed_casks:
        t = common.alnum(token)
        if t == n or t.startswith(n) or (len(t) >= 5 and n.startswith(t)):
            return True
    return False


def scan_apps(managed_casks: set[str], known_casks: set[str] | None) -> dict:
    adopted, unmatched, mas_apps, apple = [], [], [], 0
    seen = set()
    for root in app_dirs():
        for app in iter_apps(root):
            name = app.stem
            if name in seen:
                continue
            seen.add(name)
            if bundle_id(app).startswith("com.apple."):
                apple += 1
                continue
            if (app / "Contents" / "_MASReceipt").exists():
                mas_apps.append(name)  # covered by the `mas` list
                continue
            candidates = common.cask_candidates(name)
            if any(c in managed_casks for c in candidates) or looks_managed(name, managed_casks):
                continue
            match = next((c for c in candidates if known_casks and c in known_casks), None)
            if match:
                adopted.append(match)
            else:
                unmatched.append(name)
    return {
        "adopted_casks": sorted(set(adopted)),
        "unmatched_apps": sorted(set(unmatched), key=str.lower),
        "mas_apps_seen": sorted(set(mas_apps), key=str.lower),
        "apple_apps_skipped": apple,
    }


def build_inventory() -> dict:
    inv = collect_homebrew()
    known = common.available_casks()
    if known is None:
        print("⚠️  Cannot list Homebrew casks here, so manually installed apps cannot be matched to casks.")
    scan = scan_apps(set(inv["casks"]), known)
    inv["casks"] = sorted(set(inv["casks"]) | set(scan["adopted_casks"]))
    inventory = {
        "generated": date.today().isoformat(),
        "taps": sorted(inv["taps"]),
        "brews": sorted(inv["brews"]),
        "casks": inv["casks"],
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

Use ONLY items from the lists above, exactly as written; an item may appear in several groups.
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
    for w in warnings:
        print(f"⚠️  {w}")
    return groups


# --------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ai", action="store_true", help="group tools with an LLM (needs LLM_MODEL; sends tool names to the provider)")
    ap.add_argument("--categorization", metavar="FILE", help="JSON grouping produced by an assistant, instead of rules/LLM")
    ap.add_argument("--inventory-only", action="store_true", help="write data/inventory.json and stop")
    ap.add_argument("--output", default=str(common.PRESETS_FILE), help="presets file to write (default: data/presets.yaml)")
    args = ap.parse_args()

    common.DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("🔍 Auditing this Mac...")
    inventory = build_inventory()
    common.INVENTORY_FILE.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(
        f"✅ {len(inventory['casks'])} apps (casks), {len(inventory['brews'])} CLI tools, "
        f"{len(inventory['mas'])} App Store apps, {len(inventory['vscode'])} VS Code extensions."
    )
    if args.inventory_only:
        print(f"📝 Inventory written to {common.INVENTORY_FILE}")
        return

    everything = common.empty_preset("Everything installed on the audited Mac.", "audit")
    for key in (*common.LIST_KEYS, "mas"):
        everything[key] = list(inventory[key])
    new_presets = {"current_system": everything, **choose_groups(inventory, args)}

    # Refresh audit-generated presets, keep presets that were imported or hand-made.
    out_path = Path(args.output)
    existing = common.load_presets(out_path)["presets"]
    kept = {n: p for n, p in existing.items() if not str(p.get("source", "")).startswith("audit") and n not in new_presets}
    merged = {**new_presets, **kept}
    common.save_presets({"presets": {n: common.normalize_preset(p) for n, p in merged.items()}}, out_path)

    print(f"\n🎉 Presets written to {out_path}:")
    for name, preset in merged.items():
        print(f"   • {name}: {common.preset_size(preset)} items - {preset.get('description', '')}")
    if inventory["unmatched_apps"]:
        print("\nℹ️  Apps with no matching Homebrew cask (install these by hand or from the vendor):")
        for name in inventory["unmatched_apps"]:
            print(f"   - {name}")
    print("\n⚠️  presets.yaml lists everything you have installed. Review it before pushing to a public repo.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
