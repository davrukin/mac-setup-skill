#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Daniel Avrukin
"""Find the apps this Mac runs through Setapp and record them in data/inventory.json.

Setapp licenses its apps through its own app, and they live in a Setapp folder inside
/Applications. If Homebrew installs the same app, Setapp does not know about it and the
subscription is not used. A fresh audit does this automatically; run this to add the
information to an inventory made before Setapp was understood.
"""
from __future__ import annotations

import json

import audit
import common


def scan() -> tuple[list[str], list[str], dict[str, str]]:
    index = common.cask_index()
    known = common.available_casks()
    apps: list[str] = []
    casks: list[str] = []
    mapping: dict[str, str] = {}
    seen = set()
    for root in audit.app_dirs():
        for app in audit.iter_apps(root):
            if not audit.is_setapp(app) or app.stem in seen:
                continue
            seen.add(app.stem)
            apps.append(app.stem)
            tokens = audit.resolve_casks(app.stem, audit.bundle_id(app), index, known)
            usable = [t for t in tokens if not index or t not in index["unusable"]]
            mapping[app.stem] = usable[0] if usable else ""
            if usable:
                casks.append(usable[0])
    return sorted(apps, key=str.lower), sorted(set(casks)), dict(sorted(mapping.items(), key=lambda kv: kv[0].lower()))


def main() -> None:
    inventory = json.loads(common.INVENTORY_FILE.read_text(encoding="utf-8"))
    apps, casks, mapping = scan()
    inventory["setapp_apps"], inventory["setapp_casks"], inventory["setapp_map"] = apps, casks, mapping
    common.INVENTORY_FILE.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    print(f"Setapp apps found: {len(apps)}; Homebrew casks they would collide with: {len(casks)}")
    for a in apps:
        print(f"  • {a}")
    print(f"Recorded in {common.INVENTORY_FILE}. deploy now leaves those casks to Setapp.")


if __name__ == "__main__":
    main()
