#!/usr/bin/env python3
"""Manage presets: list, show, import a Brewfile or presets file from someone else, export, delete."""
from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

import common


def read_source(src: str) -> str:
    """Read a local path or an http(s) URL. GitHub 'blob' links are converted to raw links."""
    if re.match(r"^https?://", src):
        m = re.match(r"^https://github\.com/([^/]+)/([^/]+)/blob/(.+)$", src)
        if m:
            src = f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"
        req = urllib.request.Request(src, headers={"User-Agent": "mac-setup-skill"})
        with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - user-supplied URL by design
            return resp.read(2_000_000).decode("utf-8", errors="replace")
    return Path(src).expanduser().read_text(encoding="utf-8")


def cmd_list(args) -> None:
    presets = common.load_presets()["presets"]
    if not presets:
        print("No presets yet. Run: setup.sh audit   (or: presets.py import <Brewfile>)")
        return
    for i, (name, p) in enumerate(presets.items(), 1):
        print(f"[{i}] {name} - {p.get('description') or 'no description'} ({common.preset_size(p)} items, source: {p.get('source') or 'manual'})")


def cmd_show(args) -> None:
    presets = common.load_presets()["presets"]
    if args.name not in presets:
        sys.exit(f"No preset named '{args.name}'. Try: presets.py list")
    print(common.render_brewfile(presets[args.name], header=f"preset: {args.name}"))


def cmd_import(args) -> None:
    text = read_source(args.source)
    looks_yaml = args.source.lower().endswith((".yaml", ".yml"))
    if looks_yaml:
        loaded = common.yaml.safe_load(text) or {}
        incoming = {n: common.normalize_preset(p or {}) for n, p in (loaded.get("presets") or {}).items()}
        if args.name and len(incoming) == 1:
            incoming = {args.name: next(iter(incoming.values()))}
        ignored = 0
    else:
        preset, ignored = common.parse_brewfile(text)
        name = args.name or re.sub(r"\W+", "-", Path(args.source).stem.strip(".")).strip("-").lower() or "imported"
        incoming = {name: preset}
    if not incoming:
        sys.exit("Nothing to import: no presets or Brewfile entries found.")

    store = common.load_presets()
    for name, preset in incoming.items():
        preset["source"] = f"import:{args.source}"
        if args.description:
            preset["description"] = args.description
        elif not preset.get("description"):
            preset["description"] = f"Imported from {args.source}"
        if name in store["presets"] and not args.force:
            sys.exit(f"Preset '{name}' already exists. Use --name to pick another or --force to overwrite.")
        store["presets"][name] = common.normalize_preset(preset)
        print(f"✅ Imported '{name}' with {common.preset_size(preset)} items.")
    if ignored:
        print(f"ℹ️  Ignored {ignored} Brewfile line(s) this tool does not handle (Ruby logic, go/cargo entries, etc.).")
    common.save_presets(store)
    print("⚠️  Review imported lists before installing: a Brewfile can install anything.")


def cmd_export(args) -> None:
    presets = common.load_presets()["presets"]
    if args.name not in presets:
        sys.exit(f"No preset named '{args.name}'.")
    text = common.render_brewfile(presets[args.name], header=f"preset: {args.name}")
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"✅ Wrote {args.out}")
    else:
        print(text, end="")


def cmd_delete(args) -> None:
    store = common.load_presets()
    if args.name not in store["presets"]:
        sys.exit(f"No preset named '{args.name}'.")
    del store["presets"][args.name]
    common.save_presets(store)
    print(f"🗑️  Deleted '{args.name}'.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(fn=cmd_list)
    p = sub.add_parser("show"); p.add_argument("name"); p.set_defaults(fn=cmd_show)
    p = sub.add_parser("import", help="import a Brewfile (path or URL) or a presets .yaml")
    p.add_argument("source"); p.add_argument("--name"); p.add_argument("--description"); p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_import)
    p = sub.add_parser("export"); p.add_argument("name"); p.add_argument("--out"); p.set_defaults(fn=cmd_export)
    p = sub.add_parser("delete"); p.add_argument("name"); p.set_defaults(fn=cmd_delete)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
