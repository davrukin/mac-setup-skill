#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Daniel Avrukin
"""Write a document listing the apps Homebrew cannot install, with where to get each one.

Input is data/manual_apps.json, written by the assistant (the skill's LLM) from the
`unmatched_apps` list in data/inventory.json: each entry groups related apps, gives them a
category and says how to get them (vendor download, Setapp, Steam, App Store, a Homebrew
cask that was missed, ...). See references/schemas.md for the format.

This script only renders and checks: it flags apps that are in the inventory but in no entry,
and entries that name apps that are no longer installed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import common

SOURCE_LABEL = {
    "vendor": "Vendor download", "setapp": "Setapp", "steam": "Steam", "gog": "GOG", "app-store": "App Store",
    "chrome": "Chrome web app", "cask": "Homebrew cask", "covered": "Already covered", "bundled": "Comes with another app",
    "discontinued": "Discontinued", "it-managed": "Ask your IT", "unknown": "Source unknown",
}
CATEGORY_NOTE = {
    "not_needed": "Not needed on a new Mac (discontinued, covered elsewhere, or only needed occasionally).",
    "unsure": "Could not be identified or sourced; decide yourself.",
}


def get_it(entry: dict) -> str:
    source = entry.get("source", "unknown")
    parts = [SOURCE_LABEL.get(source, source)]
    if entry.get("cask"):
        parts = [f"`brew install --cask {entry['cask']}`"]
    if entry.get("url"):
        label = "link" if entry.get("verified") else "link (not verified)"
        parts.append(f"[{label}]({entry['url']})")
    return "<br>".join(parts)


def render(data: dict, inventory: dict, categories: list[str]) -> tuple[str, list[str], list[str]]:
    entries = data.get("entries", [])
    installed = set(inventory.get("unmatched_apps", []))
    named = {a for e in entries for a in e.get("apps", [])}
    missing = sorted(installed - named, key=str.lower)
    stale = sorted(named - installed, key=str.lower)

    order = [c for c in categories if c not in ("not_needed", "unsure")] + ["not_needed", "unsure"]
    for e in entries:
        if e.get("category") not in order:
            order.insert(-2, e.get("category", "unsure"))
    lines = [
        "# Apps to install by hand",
        "",
        f"These {len(installed)} apps have no usable Homebrew cask, so `brew bundle` will not install them. "
        "Each is grouped by the category it was assigned to and says where to get it.",
        "",
        f"_Classified by {data.get('classified_by', 'unknown')} on {data.get('generated', '?')}; the categories are proposals, so edit "
        "`manual_apps.json` to change them. Links marked \"not verified\" are the vendor's usual address and were not confirmed by a search._",
        "",
    ]
    for cat in dict.fromkeys(order):
        group = [e for e in entries if e.get("category") == cat]
        if not group:
            continue
        lines += [f"## {cat.replace('_', ' ').title()}", ""]
        if cat in CATEGORY_NOTE:
            lines += [f"_{CATEGORY_NOTE[cat]}_", ""]
        lines += ["| App | Where to get it | Notes |", "| --- | --- | --- |"]
        for e in group:
            apps = ", ".join(e.get("apps", []))
            lines.append(f"| {apps} | {get_it(e)} | {e.get('note', '')} |".replace("\n", " "))
        lines.append("")
    casks = sorted({e["cask"] for e in entries if e.get("cask") and e.get("category") != "not_needed"})
    if casks:
        lines += ["## Casks Homebrew does have", "",
                  "Some entries above have a working cask under a different name. To install them with your presets, add:", "",
                  "```ruby", *[f'cask "{c}"' for c in casks], "```", ""]
    if missing:
        lines += ["## Not classified yet", "",
                  "In the inventory but not in `manual_apps.json`; ask the assistant to classify them:", "",
                  *[f"- {a}" for a in missing], ""]
    return "\n".join(lines), missing, stale


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default=str(common.DATA_DIR / "manual_apps.json"))
    ap.add_argument("--inventory", default=str(common.INVENTORY_FILE))
    ap.add_argument("--output", default=str(common.DATA_DIR / "manual-installs.md"))
    args = ap.parse_args()

    try:
        data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    except FileNotFoundError:
        sys.exit(f"{args.input} not found. Ask the assistant to classify the unmatched apps from inventory.json first.")
    inventory = json.loads(Path(args.inventory).read_text(encoding="utf-8"))
    try:
        game = json.loads((Path(args.inventory).parent / "game_choices.json").read_text(encoding="utf-8"))
        categories = list(game.get("categories", {}))
    except (OSError, ValueError):
        categories = ["developer", "common"]
    text, missing, stale = render(data, inventory, categories)
    Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(f"📝 Wrote {args.output}")
    if missing:
        print(f"⚠️  {len(missing)} apps are not classified yet: {', '.join(missing)}")
    if stale:
        print(f"ℹ️  {len(stale)} classified apps are not in this inventory: {', '.join(stale)}")


if __name__ == "__main__":
    main()
