#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Daniel Avrukin
"""Recommend tools missing from a preset, split into three tiers.

Candidates come from (any combination):
  * references/recommended_seed.yaml   - small curated fallback list
  * data/web_recommendations.json      - research an assistant did on current online lists
  * --source URL|FILE                  - a Brewfile / README / blog post; `brew "x"`, `cask "x"`
                                         and `brew install ...` lines are extracted
  * --ai                               - an LLM suggestion (needs LLM_MODEL)

Every candidate is dropped if the preset already has it, and (when Homebrew is
available) checked against the real formula/cask catalogue so invented names never
reach a Brewfile. Tier 1 = very useful, 2 = nice to have, 3 = could be useful.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import categorize
import common
from ai_skill import ai_configured, call_ai
from presets import read_source

TIERS = [
    ("tier_1_very_useful", "Tier 1: Very useful"),
    ("tier_2_nice_to_have", "Tier 2: Nice to have"),
    ("tier_3_could_be_useful", "Tier 3: Could be useful"),
]
MIN_HITS_FOR_RELEVANCE = 2  # a role counts as "yours" once this many of your tools belong to it


@dataclass
class Candidate:
    name: str
    type: str  # "brew" | "cask" | "unknown"
    reason: str = ""
    tier: int | None = None
    categories: set = field(default_factory=set)
    sources: set = field(default_factory=set)
    verified: bool | None = None  # True/False once checked against Homebrew, None if unknowable


# --------------------------------------------------------------------------
# Candidate sources
# --------------------------------------------------------------------------
def from_seed(roles: set[str]) -> list[Candidate]:
    path = common.REFERENCES_DIR / "recommended_seed.yaml"
    with open(path, "r", encoding="utf-8") as f:
        entries = common.yaml.safe_load(f) or []
    out = []
    for e in entries:
        cats = set(e.get("categories") or [])
        if roles and not (cats & roles):
            continue
        out.append(Candidate(e["name"], e["type"], e.get("reason", ""), e.get("tier"), cats, {"seed"}))
    return out


def from_web_file(path) -> list[Candidate]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for e in data.get("items", []):
        srcs = set(e.get("sources") or []) or {"web-research"}
        out.append(Candidate(e["name"], e.get("type", "unknown"), e.get("reason", ""), e.get("tier"), set(e.get("categories") or []), srcs))
    return out


_BREWFILE_RE = re.compile(r"""^\s*(brew|cask)\s+["']([^"']+)["']""", re.M)
_INSTALL_RE = re.compile(r"brew\s+install\s+([^\n`|;&<>#]+)")
_NAME_OK = re.compile(r"^[A-Za-z0-9@._+/-]+$")


def extract_names(text: str) -> list[tuple[str, str]]:
    """Return (type, name) pairs found in Brewfile lines and `brew install` commands."""
    found = [(kind, name) for kind, name in _BREWFILE_RE.findall(text)]
    for m in _INSTALL_RE.finditer(text):
        tokens = m.group(1).split()
        kind = "cask" if "--cask" in tokens or "--casks" in tokens else "unknown"
        for tok in tokens:
            tok = tok.strip("\"'\\")
            if tok.startswith("-") or not _NAME_OK.match(tok):
                continue
            found.append((kind, tok))
    return found


def from_source(src: str) -> list[Candidate]:
    try:
        text = read_source(src)
    except Exception as exc:  # noqa: BLE001
        print(f"⚠️  Could not read {src}: {exc}")
        return []
    return [Candidate(name, kind, "", None, set(), {src}) for kind, name in extract_names(text)]


def from_ai(preset: dict, preset_name: str) -> list[Candidate]:
    print(f"🧠 Asking {os.environ.get('LLM_MODEL')} for suggestions (sends the preset's tool names).")
    prompt = f"""
I am setting up a macOS machine with the '{preset_name}' preset.
Installed casks: {preset.get('casks')}
Installed brews: {preset.get('brews')}
Suggest Homebrew casks/formulae I am MISSING that would be useful. Only suggest real, currently available Homebrew names. Do NOT repeat anything installed.
Respond ONLY with JSON:
{{"tier_1_very_useful": [{{"name": "", "type": "cask or brew", "reason": "short reason"}}],
  "tier_2_nice_to_have": [...], "tier_3_could_be_useful": [...]}}
"""
    data = call_ai(prompt) or {}
    out = []
    for i, (key, _) in enumerate(TIERS, 1):
        for e in data.get(key) or []:
            if isinstance(e, dict) and e.get("name"):
                out.append(Candidate(e["name"], e.get("type", "unknown"), e.get("reason", ""), i, set(), {"ai"}))
    return out


# --------------------------------------------------------------------------
# Merge, verify, tier
# --------------------------------------------------------------------------
def resolve_type(c: Candidate, formulae, casks) -> str:
    if c.type in ("brew", "cask"):
        return c.type
    base = common.short_name(c.name)
    if casks and base in casks and not (formulae and base in formulae):
        return "cask"
    return "brew"


def verified(c: Candidate, formulae, casks):
    """True / False when Homebrew can tell us, None when it cannot."""
    pool = formulae if c.type == "brew" else casks
    if pool is None or c.name.count("/") == 2:  # tap-qualified names are not in the core lists
        return None
    return common.short_name(c.name) in pool


def recommend(preset_name: str, preset: dict, *, sources=(), use_ai=False, use_seed=True,
              web_file=common.WEB_RECS_FILE, validate=True, max_per_tier=15, roles=None, exclude=()) -> dict:
    formulae = common.available_formulae() if validate else None
    casks = common.available_casks() if validate else None

    if roles is None:
        hits = categorize.category_hits(preset)
        roles = {r for r, n in hits.items() if n >= MIN_HITS_FOR_RELEVANCE} | {"essentials"}
    pool: list[Candidate] = []
    if use_seed:
        pool += from_seed(roles)
    pool += from_web_file(web_file)
    for src in sources:
        pool += from_source(src)
    if use_ai and ai_configured():
        pool += from_ai(preset, preset_name)

    # Anything already in the preset, or deliberately excluded by the user, must not be suggested.
    installed = {common.short_name(x) for x in (*preset.get("brews", []), *preset.get("casks", []), *exclude)}
    merged: dict[tuple, Candidate] = {}
    dropped: list[str] = []
    for c in pool:
        c.type = resolve_type(c, formulae, casks)
        if common.short_name(c.name) in installed:
            continue
        ok = verified(c, formulae, casks)
        if ok is False:
            dropped.append(f"{c.name} ({c.type})")
            continue
        key = (c.type, c.name)
        if key in merged:
            m = merged[key]
            m.sources |= c.sources
            m.categories |= c.categories
            m.reason = m.reason or c.reason
            m.tier = min(t for t in (m.tier, c.tier) if t) if (m.tier or c.tier) else None
        else:
            c.verified = ok
            merged[key] = c

    buckets: dict[str, list] = {k: [] for k, _ in TIERS}
    for c in merged.values():
        independent = len({s for s in c.sources if s != "seed"})
        tier = c.tier or (1 if independent >= 3 else 2 if independent == 2 else 3)
        if independent >= 3:
            tier = 1
        key = TIERS[tier - 1][0]
        buckets[key].append({
            "name": c.name, "type": c.type, "reason": c.reason,
            "sources": sorted(c.sources), "verified": c.verified,
        })
    for key in buckets:
        buckets[key].sort(key=lambda e: (-len(e["sources"]), e["name"]))
        buckets[key] = buckets[key][:max_per_tier]
    buckets["_dropped_unverified"] = sorted(set(dropped))
    buckets["_roles"] = sorted(roles)
    return buckets


def print_recs(recs: dict) -> None:
    print("\n" + "=" * 50 + "\n💡 RECOMMENDATIONS\n" + "=" * 50)
    if recs.get("_roles"):
        print(f"(matched to roles: {', '.join(recs['_roles'])})")
    for key, title in TIERS:
        if recs.get(key):
            print(f"\n--- {title} ---")
            for t in recs[key]:
                flag = "" if t["verified"] is not False else " [unverified]"
                note = f": {t['reason']}" if t["reason"] else ""
                print(f" • {t['name']} ({t['type']}){note}{flag}")
    if recs.get("_dropped_unverified"):
        print(f"\nℹ️  Dropped {len(recs['_dropped_unverified'])} suggestion(s) Homebrew does not list: {', '.join(recs['_dropped_unverified'][:8])}")
    if all(not recs.get(k) for k, _ in TIERS):
        print("Nothing to recommend: your preset already covers the candidates found.")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", default="current_system")
    ap.add_argument("--source", action="append", default=[], metavar="URL_OR_FILE", help="Brewfile / README / article to mine for tools (repeatable)")
    ap.add_argument("--web-file", default=str(common.WEB_RECS_FILE))
    ap.add_argument("--role", action="append", help="force recommendation roles (developer, creative, essentials); default: inferred from preset")
    ap.add_argument("--ai", action="store_true")
    ap.add_argument("--no-seed", action="store_true")
    ap.add_argument("--no-validate", action="store_true", help="skip checking names against Homebrew")
    ap.add_argument("--max-per-tier", type=int, default=15)
    ap.add_argument("--json", action="store_true", help="print JSON only")
    args = ap.parse_args()

    store = common.load_presets()["presets"]
    if args.preset not in store:
        sys.exit(f"No preset named '{args.preset}'. Try: presets.py list")
    recs = recommend(args.preset, store[args.preset], sources=args.source, use_ai=args.ai, use_seed=not args.no_seed,
                     web_file=Path(args.web_file), validate=not args.no_validate, max_per_tier=args.max_per_tier,
                     roles=set(args.role) if args.role else None)
    common.RECS_DIR.mkdir(parents=True, exist_ok=True)
    out = common.RECS_DIR / f"{args.preset}.json"
    out.write_text(json.dumps(recs, indent=2) + "\n", encoding="utf-8")
    if args.json:
        print(json.dumps(recs, indent=2))
    else:
        print_recs(recs)
        print(f"\n📝 Saved to {out}")
        if common.available_casks() is None and not args.no_validate:
            print("ℹ️  Homebrew was not available, so names were not verified. Run again on the Mac before installing.")


if __name__ == "__main__":
    main()
