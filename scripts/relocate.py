#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Daniel Avrukin
"""Put apps where their casks say they belong, and list the apps that must come from Setapp.

1. Casks that install into a folder, such as the Craft apps in /Applications/ArtCraft. If the app sits
   loose in /Applications instead:
     - installed by Homebrew: `brew reinstall --cask --force NAME`. Homebrew removes the app from the place it
       recorded and installs it at the current path, so its records stay right.
     - not installed by Homebrew: move the app into the folder, then `brew install --cask --adopt NAME`
       so Homebrew takes it over without downloading it again.
2. Setapp apps. They are NOT moved: Setapp records a license when it installs an app itself, and putting an
   app into its folder does not make Setapp aware of it. The script lists the Setapp apps that are installed
   some other way, so you can add them from Setapp; --uninstall-homebrew-copies removes the Homebrew casks of
   those apps first (your data stays, because it never uses --zap).

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
import common


def cask_targets(casks: list[str]) -> dict[str, list[tuple[str, str]]]:
    """{cask: [(app bundle name, absolute install path)]} for casks that name an explicit install path."""
    out = common.run(["brew", "info", "--cask", "--json=v2", *casks], timeout=300) if casks else None
    result: dict[str, list[tuple[str, str]]] = {}
    if not out:
        return result
    try:
        data = json.loads(out)
    except ValueError:
        return result
    for cask in data.get("casks", []):
        for art in cask.get("artifacts", []):
            if isinstance(art, dict) and art.get("app") and str(art.get("target", "")).startswith("/"):
                result.setdefault(cask["token"], []).append((str(art["app"][0]), str(art["target"])))
    return result


def is_running(app: Path) -> bool:
    probe = subprocess.run(["pgrep", "-f", f"{app}/Contents/MacOS"], capture_output=True)
    return probe.returncode == 0


def plan_casks(candidates: list[str], managed: set[str]) -> list[dict]:
    steps = []
    for token, entries in cask_targets(candidates).items():
        for bundle_name, target in entries:
            if Path(target).exists():
                continue
            # Only a subfolder of an app folder counts (ArtCraft inside /Applications); a plain
            # /Applications target such as Meta.app is where the user chose to keep it.
            home = Path(target).parent.parent
            loose = next((root / bundle_name for root in audit.app_dirs() if root == home and (root / bundle_name).exists()), None)
            if not loose:
                continue
            kind = "reinstall" if token in managed else "adopt"
            steps.append({"cask": token, "kind": kind, "from": str(loose), "to": target})
    return steps


def plan_setapp(managed: set[str]) -> dict:
    """Setapp apps by situation: only outside Setapp, or also outside it (an extra copy), plus Homebrew casks among them."""
    try:
        inventory = json.loads(common.INVENTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"only_outside": [], "extra_copy": [], "brew_copies": []}
    only_outside, extra_copy = [], []
    for name in inventory.get("setapp_apps", []):
        loose = any((root / f"{name}.app").exists() for root in audit.app_dirs())
        in_setapp = any((root / "Setapp" / f"{name}.app").exists() for root in audit.app_dirs())
        if loose and in_setapp:
            extra_copy.append(name)
        elif loose:
            only_outside.append(name)
    brew_copies = sorted(set(inventory.get("setapp_casks", [])) & managed)
    return {"only_outside": only_outside, "extra_copy": extra_copy, "brew_copies": brew_copies}


def run_step(label: str, cmd: list[str]) -> bool:
    print(f"   $ {' '.join(cmd)}", flush=True)
    return subprocess.run(cmd).returncode == 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="do it (default: only show the plan)")
    ap.add_argument("--uninstall-homebrew-copies", action="store_true",
                    help="with --apply: `brew uninstall --cask` the Homebrew copies of Setapp apps, so you can add them from Setapp")
    args = ap.parse_args()

    managed = {ln.strip() for ln in (common.run(["brew", "list", "--cask", "-1"]) or "").splitlines() if ln.strip()}
    store = common.load_presets()["presets"]
    candidates = sorted(managed | {c for p in store.values() for c in p.get("casks", [])})
    print("🔍 Looking for apps in the wrong folder...", flush=True)
    steps = plan_casks(candidates, managed)
    setapp = plan_setapp(managed)
    outside, extra, brew_copies = setapp["only_outside"], setapp["extra_copy"], setapp["brew_copies"]

    print(f"\n📁 Apps that belong in a folder but sit elsewhere: {len(steps)}")
    for s in steps:
        how = "brew reinstall --cask --force" if s["kind"] == "reinstall" else "move, then brew install --cask --adopt"
        print(f"  • {s['cask']}: {s['from']} → {s['to']}   ({how})")
    print(f"\n🧩 Setapp apps installed only outside Setapp: {len(outside)}")
    for name in outside:
        print(f"  • {name}")
    if outside:
        print("   These were not moved: Setapp only knows an app it installed itself. Add them from inside Setapp.")
    if extra:
        print(f"\n🧩 Setapp apps that also have a separate copy outside the Setapp folder: {len(extra)}")
        for name in extra:
            print(f"  • {name}")
    if brew_copies:
        print(f"\n🍺 Homebrew casks of Setapp apps: {', '.join(brew_copies)}")

    if not args.apply:
        print("\nNothing changed. Quit the apps listed, then run again with --apply.")
        return
    if not steps and not (args.uninstall_homebrew_copies and brew_copies):
        return

    failed = 0
    if steps and common.confirm(f"\nMove {len(steps)} app(s) now? Quit them first."):
        for s in steps:
            print(f"\n→ {s['cask']}", flush=True)
            if is_running(Path(s["from"])):
                print("   skipped: the app is running; quit it and run again")
                failed += 1
                continue
            if s["kind"] == "reinstall":
                Path(s["to"]).parent.mkdir(parents=True, exist_ok=True)
                ok = run_step("reinstall", ["brew", "reinstall", "--cask", "--force", s["cask"]])
            else:
                Path(s["to"]).parent.mkdir(parents=True, exist_ok=True)
                shutil.move(s["from"], s["to"])
                print(f"   moved to {s['to']}")
                ok = run_step("adopt", ["brew", "install", "--cask", "--adopt", s["cask"]])
                if not ok:
                    shutil.move(s["to"], s["from"])
                    print("   adopt failed; the app was put back where it was")
            if ok and not Path(s["to"]).exists():
                print(f"   ⚠️  finished, but nothing is at {s['to']}")
                ok = False
            print("   ✅ done" if ok else "   ❌ failed")
            failed += 0 if ok else 1
    if args.uninstall_homebrew_copies and brew_copies and common.confirm(
            f"\nUninstall the {len(brew_copies)} Homebrew copies of Setapp apps (data is kept)?"):
        for token in brew_copies:
            print(f"\n→ {token}", flush=True)
            if not run_step("uninstall", ["brew", "uninstall", "--cask", token]):
                failed += 1
    if outside:
        print("\nNext: open Setapp, sign in, and install these from there:\n  " + ", ".join(outside))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
