#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Daniel Avrukin
"""Show what a preset should have installed on this Mac but does not, and optionally install it.

The preset is taken as deploy would install it (minus not_needed, your per-preset excludes and
Setapp apps). Each item is then checked against this Mac:

  installed   Homebrew, the App Store, or the editor reports it
  elsewhere   a cask whose app is on disk but was not installed by Homebrew (not reinstalled, since
              Homebrew would refuse to overwrite it; `brew install --cask --adopt NAME` hands it to Homebrew)
  missing     not installed at all: these are the ones --install tries

  missing.py --preset developer              list only
  missing.py --preset developer --install    list, ask, then install the missing items
"""
from __future__ import annotations

import argparse
import sys

import audit
import common
import deploy
import install


def app_presence(casks: list[str]) -> set[str]:
    """Casks whose app bundle is present on disk, found through Homebrew's app-name metadata."""
    index = common.cask_index()
    if not index:
        return set()
    stems = {app.stem for root in audit.app_dirs() for app in audit.iter_apps(root)}
    wanted = set(casks)
    found = {t for name, tokens in index["apps"].items() if name in {s.lower() for s in stems} for t in tokens if t in wanted}
    # Casks installed from a .pkg list no .app artifact (Google Drive, Zoom), so also accept a cask named like the app.
    found |= {t for stem in stems for t in common.cask_candidates(stem) if t in wanted}
    return found


def classify(preset: dict) -> dict[str, dict]:
    p = common.normalize_preset(preset)
    have = install.installed_now()
    elsewhere_casks = app_presence([c for c in p["casks"] if c not in have["cask"]])

    def pick(kind: str, name: str, ref: str) -> str:
        key = name.split("/")[-1] if kind in ("brew", "cask") else ref
        if key in have[kind] or (kind == "vscode" and name.lower() in have["vscode"]):
            return "installed"
        if kind == "cask" and name in elsewhere_casks:
            return "elsewhere"
        return "missing"

    out = {"installed": common.empty_preset(), "elsewhere": common.empty_preset(), "missing": common.empty_preset()}
    for state in out.values():
        state["mas"] = []
    for kind, key in (("tap", "taps"), ("brew", "brews"), ("cask", "casks"), ("vscode", "vscode")):
        for item in p[key]:
            out[pick(kind, item, item)][key].append(item)
    for m in p["mas"]:
        out[pick("mas", m["name"], str(m["id"]))]["mas"].append(m)
    return out


def names(preset: dict) -> list[str]:
    return [*preset["taps"], *preset["brews"], *preset["casks"], *preset["vscode"], *[m["name"] for m in preset["mas"]]]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", help="the category/preset to check (default: ask)")
    ap.add_argument("--exclude", default="", help="comma-separated names to ignore")
    ap.add_argument("--install", action="store_true", help="after listing, offer to install the missing items")
    ap.add_argument("--skip-update", action="store_true", help="with --install: do not run `brew update` first")
    ap.add_argument("--skip-mas", action="store_true", help="with --install: leave out App Store apps")
    args = ap.parse_args()

    store = common.load_presets()["presets"]
    if not store:
        sys.exit(f"❌ No presets found at {common.PRESETS_FILE}.")
    name = deploy.pick_preset(store, args.preset)
    preset, _ = deploy.effective_preset(name, store, {e.strip() for e in args.exclude.split(",") if e.strip()})
    print(f"\n🔍 Checking '{name}' against this Mac...", flush=True)
    state = classify(preset)

    total = sum(len(names(s)) for s in state.values())
    miss, there, away = names(state["missing"]), names(state["installed"]), names(state["elsewhere"])
    print(f"\n{total} items in '{name}': ✅ {len(there)} installed   🧩 {len(away)} present but not from Homebrew   ❌ {len(miss)} missing")
    if away:
        print("\nPresent but not installed by Homebrew (left alone; `brew install --cask --adopt NAME` hands one to Homebrew):")
        for item in away:
            print(f"  • {item}")
    if not miss:
        print("\nNothing is missing.")
        return
    labels = (("taps", "tap"), ("brews", "tool"), ("casks", "app"), ("vscode", "extension"))
    print("\nMissing:")
    for key, label in labels:
        for item in state["missing"][key]:
            print(f"  • {item}  ({label})")
    for m in state["missing"]["mas"]:
        print(f"  • {m['name']}  (App Store, id {m['id']})")

    if not args.install:
        print(f"\nTo try installing these: scripts/setup.sh missing --preset {name} --install")
        return
    if not common.confirm(f"\nTry to install these {len(miss)} items now?"):
        print("Nothing installed.")
        return
    sys.exit(install.run(state["missing"], f"{name}-missing", skip_update=args.skip_update, skip_mas=args.skip_mas))


if __name__ == "__main__":
    main()
