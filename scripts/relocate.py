#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Daniel Avrukin
"""Put apps where their casks say they belong, and list the apps that must come from Setapp.

1. Casks that install into a folder, such as the Craft apps in /Applications/ArtCraft. If the app sits
   loose in /Applications instead:
     - installed by Homebrew: move the app, remove Homebrew's old record (the app is no longer at the path it
       names, so only the record goes), then `brew install --cask --adopt NAME` links it at the new path.
     - not installed by Homebrew: move the app, then `brew install --cask --adopt NAME`.
     Neither downloads anything. They need Homebrew's current definition of the cask to name the folder, so
     it runs `brew update` first; apps whose definition still names none are listed as "cannot be linked yet".
2. Setapp apps. They are never moved or installed: Setapp records a license only for an app it installs
   itself. The script lists every Setapp app in your category (from inventory.json) with its state on this Mac,
   writes data/setapp-to-install.md for you to work through, and with --apply removes the Homebrew-installed
   copies (`brew uninstall --cask`, never --zap, so your data stays). --keep-homebrew-setapp skips the removal.

It only prints what it would do, unless you add --apply.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import audit
import yaml

import common


def folder_rules() -> dict[str, str]:
    """{cask: folder} from references/folders.yaml, for when Homebrew's definition does not name the folder."""
    try:
        path = Path(os.environ.get("MAC_SETUP_FOLDERS_FILE") or common.REFERENCES_DIR / "folders.yaml")  # env: tests
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return {str(c): str(f["folder"]) for f in data.get("folders", []) for c in f.get("casks", [])}


def cask_targets(casks: list[str]) -> dict[str, list[tuple[str, str, str]]]:
    """{cask: [(app bundle name, absolute install path, source)]}. The path comes from the cask's own
    definition ("metadata") or, when that has none, from references/folders.yaml ("rule")."""
    out = common.run(["brew", "info", "--cask", "--json=v2", *casks], timeout=300) if casks else None
    result: dict[str, list[tuple[str, str, str]]] = {}
    if not out:
        return result
    try:
        data = json.loads(out)
    except ValueError:
        return result
    rules = folder_rules()
    roots = {Path(r) for r in audit.app_dirs()}
    for cask in data.get("casks", []):
        token = cask["token"]
        for art in cask.get("artifacts", []):
            if not (isinstance(art, dict) and art.get("app")):
                continue
            name = str(art["app"][0])
            reported = str(art["target"]) if str(art.get("target", "")).startswith("/") else ""
            if token in rules:
                # Homebrew reports a target for every cask (an old definition says /Applications/X.app), so the
                # rule decides where the app belongs; it counts as "metadata" only when the definition agrees.
                wanted = f"{rules[token]}/{name}"
                result.setdefault(token, []).append((name, wanted, "metadata" if Path(reported) == Path(wanted) else "rule"))
            elif reported and Path(reported).parent not in roots:
                result.setdefault(token, []).append((name, reported, "metadata"))  # the cask itself names a subfolder
    return result


def is_running(app: Path) -> bool:
    probe = subprocess.run(["pgrep", "-f", f"{app}/Contents/MacOS"], capture_output=True)
    return probe.returncode == 0


def plan_casks(candidates: list[str], managed: set[str]) -> tuple[list[dict], dict[str, list[str]]]:
    """(moves to make, every folder-bound cask by state: in_place / to_move / not_found)."""
    steps = []
    status: dict[str, list[str]] = {"in_place": [], "to_move": [], "not_found": []}
    for token, entries in sorted(cask_targets(candidates).items()):
        for bundle_name, target, source in entries:
            if Path(target).exists():
                status["in_place"].append(token)
                continue
            # Only a subfolder of an app folder counts (ArtCraft inside /Applications); a plain
            # /Applications target such as Meta.app is where the user chose to keep it.
            home = Path(target).parent.parent
            loose = next((root / bundle_name for root in audit.app_dirs() if root == home and (root / bundle_name).exists()), None)
            if not loose:
                status["not_found"].append(token)
                continue
            # "relink": Homebrew installed it, so move the app and replace its record. "adopt": Homebrew did not.
            # Both need a definition that names the folder; without one, Homebrew would look for the app in /Applications.
            kind = "stale" if source == "rule" else ("relink" if token in managed else "adopt")
            status["to_move"].append(token)
            steps.append({"cask": token, "kind": kind, "from": str(loose), "to": target})
    return steps, status


def plan_setapp(managed: set[str]) -> list[dict]:
    """Every Setapp app in the category (the audited Mac's Setapp apps), with its state on THIS Mac:
    homebrew (a cask installed it: to be removed), outside (present, but not through Setapp),
    setapp (already in the Setapp folder), absent (not installed). Each entry also says which cask it is."""
    try:
        inventory = json.loads(common.INVENTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    mapping = inventory.get("setapp_map", {})
    known = set(inventory.get("setapp_casks", []))
    out = []
    for name in inventory.get("setapp_apps", []):
        # The cask recorded on the audited Mac, else any installed cask named like the app (Bartender -> bartender).
        cask = mapping.get(name) or next((c for c in common.cask_candidates(name) if c in managed or c in known), "")
        loose = any((root / f"{name}.app").exists() for root in audit.app_dirs())
        in_setapp = any((root / "Setapp" / f"{name}.app").exists() for root in audit.app_dirs())
        if cask and cask in managed:
            state = "homebrew"
        elif in_setapp:
            state = "setapp"
        elif loose:
            state = "outside"
        else:
            state = "absent"
        out.append({"app": name, "cask": cask, "state": state, "also_in_setapp": in_setapp})
    return out


def write_setapp_list(apps: list[dict]) -> Path:
    todo = [a for a in apps if a["state"] != "setapp"]
    lines = ["# Setapp apps to install and license yourself", "",
             "Open Setapp, sign in, and install each of these from inside it. Setapp only records a license for an app it installs "
             "itself, so these are not installed or moved by the scripts.", ""]
    lines += [f"- [ ] {a['app']}" + ("  _(a Homebrew copy was removed)_" if a["state"] == "homebrew" else "") for a in todo]
    if not todo:
        lines.append("Everything is already installed through Setapp.")
    path = common.DATA_DIR / "setapp-to-install.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def run_step(label: str, cmd: list[str]) -> bool:
    print(f"   $ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd).returncode == 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="do it (default: only show the plan)")
    ap.add_argument("--skip-update", action="store_true", help="do not run `brew update` first")
    ap.add_argument("--keep-homebrew-setapp", action="store_true",
                    help="with --apply: leave the Homebrew copies of Setapp apps installed (by default they are removed)")
    args = ap.parse_args()
    common.require_brew("finding apps in the wrong folder")

    managed = {ln.strip() for ln in (common.run(["brew", "list", "--cask", "-1"]) or "").splitlines() if ln.strip()}
    store = common.load_presets()["presets"]
    if not args.skip_update:
        print("🔄 Updating Homebrew so cask definitions (which say where each app belongs) are current...", flush=True)
        subprocess.run(["brew", "update"], capture_output=True)
    candidates = sorted(managed | set(folder_rules()) | {c for p in store.values() for c in p.get("casks", [])})
    print("🔍 Looking for apps in the wrong folder...", flush=True)
    steps, status = plan_casks(candidates, managed)
    setapp = plan_setapp(managed)
    brew_copies = [a["cask"] for a in setapp if a["state"] == "homebrew"]

    found = sum(len(v) for v in status.values())
    print(f"\n📁 Apps with a home folder: {found} checked")
    if status["in_place"]:
        print(f"  ✅ already in their folder ({len(status['in_place'])}): {', '.join(status['in_place'])}")
    if status["not_found"]:
        print(f"  ➖ not installed here, nothing to move ({len(status['not_found'])}): {', '.join(status['not_found'])}")
    if not found:
        print("  Homebrew reported no cask with a home folder. Run `brew update`, or check references/folders.yaml.")
    print(f"  ➡️  to move: {len(steps)}")
    for s in steps:
        how = {"relink": "move, drop the old Homebrew record, brew install --cask --adopt",
               "adopt": "move, then brew install --cask --adopt",
               "stale": "cannot be linked yet: Homebrew's definition has no folder; run brew update and try again"}[s["kind"]]
        print(f"  • {s['cask']}: {s['from']} → {s['to']}   ({how})")
    def names(state: str) -> list[str]:
        return [a["app"] for a in setapp if a["state"] == state]

    print(f"\n🧩 Setapp apps in your category: {len(setapp)}")
    for state, label in (("homebrew", "🍺 installed by Homebrew, to be removed"),
                         ("outside", "⚠️  installed some other way (left alone)"),
                         ("setapp", "✅ already in the Setapp folder"),
                         ("absent", "➖ not installed on this Mac")):
        if names(state):
            print(f"  {label} ({len(names(state))}): {', '.join(names(state))}")
    print(f"  📝 To install from Setapp yourself: {sum(1 for a in setapp if a['state'] != 'setapp')} (list in {write_setapp_list(setapp)})")
    if not setapp:
        print("  (This inventory has no Setapp apps. Run `scripts/setup.sh setapp` on the Mac where Setapp is installed.)")

    if not args.apply:
        print("\nNothing changed. Quit the apps listed, then run again with --apply.")
        return
    if not steps and not (brew_copies and not args.keep_homebrew_setapp):
        return

    failed = 0
    if steps and common.confirm(f"\nMove {len(steps)} app(s) now? Quit them first."):
        for s in steps:
            print(f"\n→ {s['cask']}", flush=True)
            if s["kind"] == "stale":
                print("   skipped: Homebrew's definition does not name the folder yet; run `brew update`, then try again")
                continue
            if is_running(Path(s["from"])):
                print("   skipped: the app is running; quit it and run again")
                failed += 1
                continue
            Path(s["to"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(s["from"], s["to"])
            print(f"   moved to {s['to']}")
            ok = True
            if s["kind"] == "relink":
                # The old record points at the old path; with the app gone from there, this only removes the record.
                ok = run_step("uninstall", ["brew", "uninstall", "--cask", s["cask"]])
            ok = ok and run_step("adopt", ["brew", "install", "--cask", "--adopt", s["cask"]])
            if not ok:
                if s["kind"] == "adopt":
                    shutil.move(s["to"], s["from"])
                    print("   adopt failed; the app was put back where it was")
                else:
                    print(f"   the app is now at {s['to']} but Homebrew is not linked to it; finish with: brew install --cask --adopt {s['cask']}")
            if ok and not Path(s["to"]).exists():
                print(f"   ⚠️  finished, but nothing is at {s['to']}")
                ok = False
            print("   ✅ done" if ok else "   ❌ failed")
            failed += 0 if ok else 1
    if brew_copies and not args.keep_homebrew_setapp and common.confirm(
            f"\nRemove the {len(brew_copies)} Homebrew copies of Setapp apps so you can install them from Setapp? (Your data is kept.)"):
        for token in brew_copies:
            print(f"\n→ {token}", flush=True)
            if not run_step("uninstall", ["brew", "uninstall", "--cask", token]):
                failed += 1
    todo = [a["app"] for a in setapp if a["state"] != "setapp"]
    if todo:
        print("\nNext: open Setapp, sign in, and install and license these yourself:\n  " + ", ".join(todo))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
