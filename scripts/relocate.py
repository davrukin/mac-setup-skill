#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Daniel Avrukin
"""Put the apps of one category (preset) where their casks say they belong, and list its Setapp apps.

Only the category you pick is considered: anything in the not_needed list, or that you excluded for that
preset, is ignored.

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
import common
import deploy


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
    rules = common.folder_rules()
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


def find_loose(home: Path, bundle_name: str, token: str) -> Path | None:
    """The app sitting directly in `home`: by its exact bundle name, else by a name that matches the cask
    ignoring case, spaces and dashes (so "Art Craft.app" still counts as the artcraft cask)."""
    if not any(Path(r) == home for r in audit.app_dirs()) or not home.is_dir():
        return None
    exact = home / bundle_name
    if exact.exists():
        return exact
    want = common.alnum(token)
    return next((a for a in sorted(home.iterdir()) if a.suffix == ".app" and common.alnum(a.stem) == want), None)


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
            loose = find_loose(home, bundle_name, token)
            if not loose:
                status["not_found"].append(token)
                continue
            # Two steps per app: move it, then link it to Homebrew. When the cask's own definition does not name the
            # folder (source "rule"), the link step passes --appdir so Homebrew looks in the right place.
            status["to_move"].append(token)
            steps.append({"cask": token, "managed": token in managed, "appdir": str(Path(target).parent) if source == "rule" else "",
                          "from": str(loose), "to": target})
    return steps, status


def category_setapp_apps(name: str, store: dict, inventory: dict) -> list[str]:
    """The Setapp apps that belong to preset `name`: those whose cask is in it, and those with no cask that were
    filed under this category (or under common) in manual_apps.json. not_needed and your excludes are left out."""
    left_out = common.exclusion_names(store) | set(common.load_preset_excludes().get(name, []))
    casks = {c for c in store[name].get("casks", []) if c not in left_out}
    try:
        manual = json.loads((common.DATA_DIR / "manual_apps.json").read_text(encoding="utf-8"))
        filed = {a: e.get("category") for e in manual.get("entries", []) for a in e.get("apps", [])}
    except (OSError, ValueError):
        filed = {}
    mapping = inventory.get("setapp_map", {})
    keep = []
    for app in inventory.get("setapp_apps", []):
        if app in left_out:
            continue
        cask = mapping.get(app)
        if name == "current_system":
            keep.append(app)
        elif cask:
            if cask in casks:
                keep.append(app)
        elif filed.get(app) in (name, "common"):
            keep.append(app)
    return keep


def plan_setapp(managed: set[str], name: str, store: dict) -> list[dict]:
    """The Setapp apps of this category, with their state on THIS Mac:
    homebrew (a cask installed it: to be removed), outside (present, but not through Setapp),
    setapp (already in the Setapp folder), absent (not installed). Each entry also says which cask it is."""
    try:
        inventory = json.loads(common.INVENTORY_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    mapping = inventory.get("setapp_map", {})
    known = set(inventory.get("setapp_casks", []))
    out = []
    for app in category_setapp_apps(name, store, inventory):
        # The cask recorded on the audited Mac, else any installed cask named like the app (Bartender -> bartender).
        cask = mapping.get(app) or next((c for c in common.cask_candidates(app) if c in managed or c in known), "")
        loose = any((root / f"{app}.app").exists() for root in audit.app_dirs())
        in_setapp = any((root / "Setapp" / f"{app}.app").exists() for root in audit.app_dirs())
        if cask and cask in managed:
            state = "homebrew"
        elif in_setapp:
            state = "setapp"
        elif loose:
            state = "outside"
        else:
            state = "absent"
        out.append({"app": app, "cask": cask, "state": state, "also_in_setapp": in_setapp})
    return out


def write_setapp_list(apps: list[dict], category: str) -> Path:
    todo = [a for a in apps if a["state"] != "setapp"]
    lines = [f"# Setapp apps to install and license yourself ({category})", "",
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
    # Homebrew otherwise runs `brew autoremove` after an uninstall, which removes unrelated leftover dependencies.
    return subprocess.run(cmd, env={**os.environ, "HOMEBREW_NO_AUTOREMOVE": "1"}).returncode == 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", help="the category (preset) to work on; anything outside it is ignored (default: ask)")
    ap.add_argument("--apply", action="store_true", help="do it (default: only show the plan)")
    ap.add_argument("--skip-update", action="store_true", help="do not run `brew update` first")
    ap.add_argument("--keep-homebrew-setapp", action="store_true",
                    help="with --apply: leave the Homebrew copies of Setapp apps installed (by default they are removed)")
    args = ap.parse_args()
    common.require_brew("finding apps in the wrong folder")

    managed = {ln.strip() for ln in (common.run(["brew", "list", "--cask", "-1"]) or "").splitlines() if ln.strip()}
    store = common.load_presets()["presets"]
    if not store:
        sys.exit(f"❌ No presets found at {common.PRESETS_FILE}.")
    name = deploy.pick_preset(store, args.preset)
    preset, _ = deploy.effective_preset(name, store, verbose=False)
    print(f"\n📂 Category '{name}': {common.preset_size(preset)} items after leaving out everything not needed or excluded.")
    wanted = list(preset.get("casks") or [])  # this category's casks, without not_needed, your excludes or Setapp's
    if not args.skip_update:
        print("\n🔄 Updating Homebrew so cask definitions (which say where each app belongs) are current...", flush=True)
        update = subprocess.run(["brew", "update"], capture_output=True, text=True)
        if update.returncode != 0:
            tail = (update.stderr or update.stdout).strip().splitlines()[-3:]
            print("   ⚠️  brew update failed, so cask definitions may be out of date:\n      " + "\n      ".join(tail))
    print(f"\n🔍 Looking at the '{name}' category for apps in the wrong folder...", flush=True)
    steps, status = plan_casks(sorted(wanted), managed)
    setapp = plan_setapp(managed, name, store)
    brew_copies = [a["cask"] for a in setapp if a["state"] == "homebrew"]
    rules = common.folder_rules()
    folders = sorted({rules[c] for c in wanted if c in rules})

    def bullets(items: list[str], indent: str = "      ") -> None:
        for item in items:
            print(f"{indent}• {item}")

    print("\n📁 Folders for this category's apps:")
    for folder in folders:
        print(f"  {folder}  ({'exists' if Path(folder).is_dir() else 'will be created'})")
    if not folders:
        print("  none")
    found = sum(len(v) for v in status.values())
    print(f"\n📁 Apps with a home folder: {found} checked")
    if status["in_place"]:
        print(f"  ✅ already in their folder ({len(status['in_place'])}):")
        bullets(status["in_place"])
    if not found:
        print("  Homebrew reported no cask with a home folder here. Run `brew update`, or check references/folders.yaml.")
    print(f"  ➡️  to move: {len(steps)}")
    for s in steps:
        print(f"      • {s['cask']}: {s['from']} → {s['to']}")
    if steps:
        print("      Step 1 moves them; Step 2 links each to Homebrew (" + ("drops the old record, then " if any(x["managed"] for x in steps) else "")
              + "brew install --cask --adopt).")

    def names(state: str) -> list[str]:
        return [a["app"] for a in setapp if a["state"] == state]

    print(f"\n🧩 Setapp apps in the '{name}' category: {len(setapp)}")
    for state, label in (("homebrew", "🍺 installed by Homebrew, to be removed"),
                         ("outside", "⚠️  installed some other way (left alone)"),
                         ("setapp", "✅ already in the Setapp folder")):
        if names(state):
            print(f"  {label} ({len(names(state))}):")
            bullets(names(state))
    todo = [a["app"] for a in setapp if a["state"] != "setapp"]
    todo_path = write_setapp_list(setapp, name)
    print(f"\n  📝 {len(todo)} to install from Setapp yourself: the checklist is in {todo_path}")
    if not setapp:
        print("  (No Setapp apps in this category. Run `scripts/setup.sh setapp` on the Mac where Setapp is installed.)")

    if not args.apply:
        print("\nNothing changed. Quit the apps listed, then run again with --apply.")
        return
    for folder in folders:
        if not Path(folder).is_dir():
            try:
                Path(folder).mkdir(parents=True, exist_ok=True)
                print(f"\n📁 Created {folder}")
            except OSError as exc:
                print(f"\n⚠️  Could not create {folder}: {exc}")
    if not steps and not (brew_copies and not args.keep_homebrew_setapp):
        sys.exit(0)

    failed = 0
    moved: list[dict] = []
    skipped: list[str] = []
    if steps and not common.confirm(f"\nMove {len(steps)} app(s) now, then link them to Homebrew? Quit them first."):
        print("   Nothing was moved, because the answer was not yes (use --yes to skip this question).")
    elif steps:
        print("\n━━ Step 1 of 2: moving the apps ━━")
        for s in steps:
            if is_running(Path(s["from"])):
                print(f"→ {s['cask']}: skipped, the app is running; quit it and run again")
                skipped.append(f"{s['cask']} (running)")
                failed += 1
                continue
            Path(s["to"]).parent.mkdir(parents=True, exist_ok=True)
            shutil.move(s["from"], s["to"])
            print(f"→ {s['cask']}: moved to {s['to']}", flush=True)
            moved.append(s)
        print(f"   Moved {len(moved)}" + (f", skipped {len(skipped)}: {', '.join(skipped)}" if skipped else "") + ".")

        print("\n━━ Step 2 of 2: linking them to Homebrew ━━")
        for s in moved:
            print(f"→ {s['cask']}", flush=True)
            ok = True
            if s["managed"]:
                # The old record points at the old path; the app is gone from there, so this only removes the record.
                ok = run_step("uninstall", ["brew", "uninstall", "--cask", s["cask"]])
            adopt = ["brew", "install", "--cask", "--adopt"] + ([f"--appdir={s['appdir']}"] if s["appdir"] else []) + [s["cask"]]
            ok = ok and run_step("adopt", adopt)
            if not ok:
                print(f"   ❌ could not link it; the app is safe at {s['to']}. Finish with: {' '.join(adopt)}")
                failed += 1
            else:
                print("   ✅ linked")
    if brew_copies and not args.keep_homebrew_setapp and common.confirm(
            f"\nRemove the {len(brew_copies)} Homebrew copies of Setapp apps so you can install them from Setapp? (Your data is kept.)"):
        for token in brew_copies:
            print(f"\n→ {token}", flush=True)
            if not run_step("uninstall", ["brew", "uninstall", "--cask", token]):
                failed += 1
    if todo:
        print(f"\nNext: open Setapp, sign in, and install and license the apps on the checklist ({todo_path}).")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
