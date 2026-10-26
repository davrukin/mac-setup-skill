"""Shared helpers for the mac-setup scripts. Standard library + PyYAML only."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - setup.sh installs it into the venv
    sys.exit("PyYAML is required. Run scripts/setup.sh bootstrap, or: pip install pyyaml")

SKILL_ROOT = Path(__file__).resolve().parent.parent
REFERENCES_DIR = SKILL_ROOT / "references"
DATA_DIR = Path(os.environ.get("MAC_SETUP_DATA", SKILL_ROOT / "data"))
PRESETS_FILE = DATA_DIR / "presets.yaml"
INVENTORY_FILE = DATA_DIR / "inventory.json"
WEB_RECS_FILE = DATA_DIR / "web_recommendations.json"
BREWFILE_DIR = DATA_DIR / "brewfiles"
RECS_DIR = DATA_DIR / "recommendations"

LIST_KEYS = ("taps", "brews", "casks", "vscode")


# --------------------------------------------------------------------------
# Presets
# --------------------------------------------------------------------------
def empty_preset(description: str = "", source: str = "") -> dict:
    return {
        "description": description,
        "source": source,
        "taps": [],
        "brews": [],
        "casks": [],
        "mas": [],
        "vscode": [],
    }


def normalize_preset(preset: dict) -> dict:
    """Fill missing keys, dedupe and sort so diffs in Git stay small."""
    out = empty_preset(preset.get("description", ""), preset.get("source", ""))
    for key in LIST_KEYS:
        out[key] = sorted({str(x) for x in (preset.get(key) or [])}, key=str.lower)
    seen, mas = set(), []
    for entry in preset.get("mas") or []:
        if not isinstance(entry, dict) or "id" not in entry:
            continue
        if entry["id"] in seen:
            continue
        seen.add(entry["id"])
        mas.append({"name": str(entry.get("name", entry["id"])), "id": int(entry["id"])})
    out["mas"] = sorted(mas, key=lambda e: e["name"].lower())
    return out


def load_presets(path: Path = PRESETS_FILE) -> dict:
    if not path.exists():
        return {"presets": {}}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    presets = data.get("presets") or {}
    return {"presets": {name: normalize_preset(p or {}) for name, p in presets.items()}}


def save_presets(data: dict, path: Path = PRESETS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)


def preset_size(preset: dict) -> int:
    return sum(len(preset.get(k) or []) for k in (*LIST_KEYS, "mas"))


# --------------------------------------------------------------------------
# Brewfile parsing / writing
# --------------------------------------------------------------------------
_BREWFILE_LINE = re.compile(r"""^\s*(tap|brew|cask|mas|vscode)\s+(["'])(.+?)\2\s*(?:,\s*(.*))?$""")
_MAS_ID = re.compile(r"id:\s*(\d+)")


def parse_brewfile(text: str) -> tuple[dict, int]:
    """Parse the simple `kind "name"` lines of a Brewfile.

    Returns (preset, ignored_line_count). Lines using Ruby logic, `go`/`cargo`
    entries and the like are counted as ignored instead of being executed.
    """
    preset = empty_preset()
    ignored = 0
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        m = _BREWFILE_LINE.match(line)
        if not m:
            ignored += 1
            continue
        kind, _, name, rest = m.groups()
        if kind == "mas":
            id_match = _MAS_ID.search(rest or "")
            if id_match:
                preset["mas"].append({"name": name, "id": int(id_match.group(1))})
            else:
                ignored += 1
        elif kind == "tap":
            preset["taps"].append(name)
        elif kind == "brew":
            preset["brews"].append(name)
        elif kind == "cask":
            preset["casks"].append(name)
        elif kind == "vscode":
            preset["vscode"].append(name)
    return preset, ignored


def _q(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def render_brewfile(preset: dict, header: str = "") -> str:
    p = normalize_preset(preset)
    lines = []
    if header:
        lines += [f"# {h}" if h else "#" for h in header.splitlines()]
        lines.append("")
    lines += [f"tap {_q(t)}" for t in p["taps"]]
    lines += [f"brew {_q(b)}" for b in p["brews"]]
    lines += [f"cask {_q(c)}" for c in p["casks"]]
    lines += [f"mas {_q(m['name'])}, id: {m['id']}" for m in p["mas"]]
    lines += [f"vscode {_q(v)}" for v in p["vscode"]]
    return "\n".join(lines) + "\n"


def taps_needed(preset: dict) -> list[str]:
    """Derive taps from tap-qualified formulae/casks (`owner/tap/name`)."""
    taps = set(preset.get("taps") or [])
    for name in [*(preset.get("brews") or []), *(preset.get("casks") or [])]:
        parts = name.split("/")
        if len(parts) == 3:
            taps.add("/".join(parts[:2]))
    return sorted(taps)


# --------------------------------------------------------------------------
# Shelling out
# --------------------------------------------------------------------------
def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run(cmd: list[str], timeout: int = 180) -> str | None:
    """Run a command and return stdout, or None if missing / failing / timing out."""
    if not have(cmd[0]):
        return None
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError):
        return None
    return result.stdout if result.returncode == 0 else None


_TOKEN_CACHE: dict[str, set[str] | None] = {}


def _token_set(subcommand: str) -> set[str] | None:
    if subcommand not in _TOKEN_CACHE:
        out = run(["brew", subcommand])
        _TOKEN_CACHE[subcommand] = None if out is None else {l.strip() for l in out.splitlines() if l.strip()}
    return _TOKEN_CACHE[subcommand]


def available_casks() -> set[str] | None:
    """Every cask token Homebrew knows about, or None when brew is unavailable."""
    return _token_set("casks")


def available_formulae() -> set[str] | None:
    return _token_set("formulae")


# --------------------------------------------------------------------------
# Name matching
# --------------------------------------------------------------------------
def slug(name: str) -> str:
    name = re.sub(r"\.app$", "", name.strip(), flags=re.I).lower()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    return name.strip("-")


def cask_candidates(app_name: str) -> list[str]:
    """Plausible cask tokens for an app bundle name, most likely first."""
    base = slug(app_name)
    options = [base]
    options.append(re.sub(r"-v?\d+(\.\d+)*$", "", base))  # "app-7" -> "app"
    options.append(re.sub(r"-app$", "", base))
    options.append(base + "-app")
    seen, out = set(), []
    for o in options:
        if o and o not in seen:
            seen.add(o)
            out.append(o)
    return out


def alnum(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def short_name(token: str) -> str:
    """`owner/tap/name` -> `name`."""
    return token.rsplit("/", 1)[-1]
