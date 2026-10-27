#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Daniel Avrukin
"""Turn a preset into a Brewfile and the command that installs it.

Interactive when run in a terminal with no flags. For assistants and scripts, pass
--preset (and optionally --exclude / --include-recs / --run) to run without prompts.
"""
from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

import common
import install
import verify
import recommend as rec


def pick_preset(presets: dict, wanted: str | None) -> str:
    names = list(presets)
    if wanted:
        if wanted not in presets:
            sys.exit(f"No preset named '{wanted}'. Available: {', '.join(names)}")
        return wanted
    if not sys.stdin.isatty():
        sys.exit("Pass --preset NAME (non-interactive). Available: " + ", ".join(names))
    print("\nAvailable presets:")
    for i, name in enumerate(names, 1):
        p = presets[name]
        print(f" [{i}] {name} - {p.get('description') or 'no description'} ({common.preset_size(p)} items)")
    choice = input("\nSelect a preset number: ").strip()
    try:
        return names[int(choice) - 1]
    except (ValueError, IndexError):
        sys.exit("Invalid choice.")


def apply_excludes(preset: dict, excludes: set[str]) -> tuple[dict, list[str]]:
    """Remove items by name (matches formulae, casks, App Store names/ids and extensions)."""
    removed = []
    out = common.normalize_preset(preset)
    for key in ("brews", "casks", "vscode", "taps"):
        keep = []
        for item in out[key]:
            (removed if item in excludes or common.short_name(item) in excludes else keep).append(item)
        out[key] = keep
    keep_mas = []
    for m in out["mas"]:
        if m["name"] in excludes or str(m["id"]) in excludes:
            removed.append(m["name"])
        else:
            keep_mas.append(m)
    out["mas"] = keep_mas
    return out, removed


def add_recs(preset: dict, recs: dict, up_to_tier: int) -> tuple[dict, list[str]]:
    out = common.normalize_preset(preset)
    added = []
    for i, (key, _) in enumerate(rec.TIERS, 1):
        if i > up_to_tier:
            break
        for t in recs.get(key, []):
            if t.get("verified") is False:
                continue
            bucket = "casks" if t["type"] == "cask" else "brews"
            if t["name"] not in out[bucket]:
                out[bucket].append(t["name"])
                added.append(f"{t['name']} ({t['type']})")
    out["taps"] = common.taps_needed(out)
    return common.normalize_preset(out), added


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset")
    ap.add_argument("--exclude", default="", help="comma-separated names to leave out (e.g. personal apps that do not belong on a work Mac)")
    ap.add_argument("--no-recs", action="store_true", help="skip recommendations")
    ap.add_argument("--include-recs", type=int, choices=(1, 2, 3), help="also install recommendations up to this tier")
    ap.add_argument("--source", action="append", default=[], help="extra list to mine for recommendations (repeatable)")
    ap.add_argument("--ai", action="store_true", help="include LLM recommendations (needs LLM_MODEL)")
    ap.add_argument("--output", help="where to write the Brewfile (default: data/brewfiles/<preset>.Brewfile)")
    ap.add_argument("--dry-run", action="store_true", help="print the Brewfile and command, change nothing")
    ap.add_argument("--ignore-problems", action="store_true", help="install even if verification found conflicts or disabled packages")
    ap.add_argument("--run", action="store_true", help="install the preset after writing the Brewfile, item by item with progress and a log")
    ap.add_argument("--skip-update", action="store_true", help="with --run: do not run `brew update` first")
    ap.add_argument("--skip-mas", action="store_true", help="with --run: leave the Mac App Store apps for later")
    args = ap.parse_args()

    store = common.load_presets()["presets"]
    if not store:
        sys.exit(f"❌ No presets found at {common.PRESETS_FILE}. Run audit first, or import one: presets.py import <Brewfile>")
    name = pick_preset(store, args.preset)
    preset = store[name]

    excludes = {e.strip() for e in args.exclude.split(",") if e.strip()}
    if name != common.EXCLUDE_PRESET:
        marked = common.exclusion_names(store)
        if marked:
            print(f"🚫 Leaving out everything in the '{common.EXCLUDE_PRESET}' preset ({len(marked)} names).")
        excludes |= marked
    own = set(common.load_preset_excludes().get(name, []))
    if own:
        print(f"🚫 Leaving out {len(own)} item(s) you excluded for '{name}': {', '.join(sorted(own, key=str.lower))}")
        excludes |= own
    setapp = common.setapp_casks() & set(preset.get("casks") or [])
    if setapp:
        print(f"🧩 {len(setapp)} app(s) belong to Setapp, so Homebrew will not install them: {', '.join(sorted(setapp))}.\n"
              "   Install Setapp, sign in, and add them from inside it so your subscription covers them (see data/manual-installs.md).")
        excludes |= setapp
    if excludes:
        preset, removed = apply_excludes(preset, excludes)
        print(f"➖ Excluded {len(removed)} item(s) from this preset: {', '.join(removed) or 'none matched'}")

    findings = verify.verify_presets({name: preset})
    if findings:
        print(f"\n🔎 Checked '{name}' against Homebrew: {verify.summary(findings)}.")
        verify.print_findings(findings)
    blocking = [f for f in findings if f["severity"] == "error"]
    if blocking and args.run and not args.ignore_problems:
        sys.exit("❌ Not installing: fix the problems above (setup.sh verify can help), or add --ignore-problems.")

    interactive = sys.stdin.isatty() and not args.preset
    if not args.no_recs:
        recs = rec.recommend(name, preset, sources=args.source, use_ai=args.ai, exclude=excludes)
        rec.print_recs(recs)
        tier = args.include_recs
        if tier is None and interactive:
            answer = input("\nAdd recommendations to the install? [1/2/3 = up to that tier, n = none]: ").strip()
            tier = int(answer) if answer in ("1", "2", "3") else None
        if tier:
            preset, added = add_recs(preset, recs, tier)
            print(f"➕ Added {len(added)} recommended item(s).")

    header = f"Generated by mac-setup from preset '{name}'\nInstall with: brew bundle install --file=<this file>"
    brewfile = common.render_brewfile(preset, header)
    if args.dry_run:
        print("\n" + "=" * 50 + "\n" + brewfile)
    path = Path(args.output) if args.output else common.BREWFILE_DIR / f"{name}.Brewfile"
    if not args.dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(brewfile, encoding="utf-8")
        print(f"\n✅ Wrote {path}")

    command = ["brew", "bundle", "install", f"--file={path}"]
    print("\nInstall command:\n  " + " ".join(shlex.quote(c) for c in command))
    print("  (--run does the same installs one item at a time with live progress, a log file and a list of failures.)")
    if preset["mas"]:
        print("  (Mac App Store apps need you signed in to the App Store on this Mac first.)")
    if args.dry_run:
        return

    run_now = args.run
    if not run_now and interactive:
        run_now = input("\nRun it now? (y/n): ").strip().lower() == "y"
    if run_now:
        if not common.have("brew"):
            sys.exit("❌ Homebrew is not installed. Run scripts/setup.sh bootstrap first.")
        code = install.run(preset, name, skip_update=args.skip_update, skip_mas=args.skip_mas)
        if code == 0:
            print("🎉 Installation complete.")
        sys.exit(code)


if __name__ == "__main__":
    main()
