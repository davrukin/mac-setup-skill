#!/usr/bin/env python3
"""Sorting game: swipe through everything installed on this Mac and pick a category for each.

Every item already belongs to "everything" (the current_system preset). For each app, tool,
App Store app or editor extension you choose whether it also goes into `developer`,
`common` (added to every preset) or any extra category. Each card shows a suggested
category, colour-coded, and the app's icon when the terminal can draw images (iTerm2,
WezTerm, kitty, Ghostty). Progress is saved to data/game_choices.json, so you can quit and
resume, and re-audits reuse your earlier choices.

Keys:  <- skip (everything only)   -> / up / down  first / second / third category
       1-9 category by number      Enter  accept the suggestion      u undo      q save and quit
"""
from __future__ import annotations

import atexit
import base64
import json
import os
import plistlib
import re
import select
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

import categorize
import common

SKIP = "skip"  # the item only lives in "everything"
DEFAULT_CATEGORIES = ["developer", "common"]
DESCRIPTIONS = {
    "developer": "Software engineering tools, picked in the sorting game",
    "common": "Tools every Mac gets, whatever its role",
}
BG = {"developer": 44, "common": 42, "creative": 45, "essentials": 43, SKIP: 100}
EXTRA_BG = [46, 41, 47]  # cyan, red, white for categories without a fixed colour
ICON_COLS, ICON_ROWS = 14, 7
KIND_LABEL = {"casks": "app (cask)", "brews": "command-line tool", "mas": "Mac App Store", "vscode": "VS Code extension"}
KIND_ORDER = ("casks", "mas", "brews", "vscode")
CHOICES_FILE = common.DATA_DIR / "game_choices.json"


@dataclass
class Item:
    kind: str
    name: str
    ref: str  # what the grouping JSON uses: name, or the App Store id
    key: str  # stable id used in game_choices.json


def build_items(inventory: dict, kinds=KIND_ORDER) -> list[Item]:
    items: list[Item] = []
    for kind in kinds:
        if kind == "mas":
            seen = set()
            for m in inventory.get("mas", []):
                if m["id"] not in seen:
                    seen.add(m["id"])
                    items.append(Item("mas", m["name"], str(m["id"]), f"mas:{m['id']}"))
        else:
            items += [Item(kind, n, n, f"{kind}:{n}") for n in inventory.get(kind, [])]
    return items


def suggest(item: Item, categories: list[str], rules: dict) -> str | None:
    """The category the built-in rules would pick, limited to the categories in play."""
    hits = [c for c in categorize.item_categories(item.kind, item.name, rules) if c in categories]
    if "common" in hits:
        return "common"
    return hits[0] if hits else None


# --------------------------------------------------------------------------
# Colours
# --------------------------------------------------------------------------
def colour_map(categories: list[str]) -> dict[str, int]:
    out, extra = {SKIP: BG[SKIP]}, iter(EXTRA_BG * 3)
    for c in categories:
        out[c] = BG.get(c) or next(extra)
    return out


def badge(label: str, cat: str, colours: dict[str, int]) -> str:
    if os.environ.get("NO_COLOR"):
        return f"[{label}]"
    return f"\x1b[1;97;{colours.get(cat, 100)}m {label} \x1b[0m"


# --------------------------------------------------------------------------
# Icons
# --------------------------------------------------------------------------
def icon_protocol(mode: str = "auto") -> str:
    """'iterm', 'kitty' or '' (no icons)."""
    if mode in ("iterm", "kitty"):
        return mode
    if mode == "off" or os.environ.get("TMUX") or not sys.stdout.isatty():
        return ""
    term, program = os.environ.get("TERM", ""), os.environ.get("TERM_PROGRAM", "")
    if program in ("iTerm.app", "WezTerm") or os.environ.get("LC_TERMINAL") == "iTerm2":
        return "iterm"
    if "kitty" in term or program == "ghostty" or os.environ.get("KITTY_WINDOW_ID"):
        return "kitty"
    return ""


class Icons:
    """Finds an item's .app bundle and renders its icon through the terminal's image protocol."""

    def __init__(self, inventory: dict, protocol: str):
        self.protocol = protocol
        self.cache_dir: Path | None = None
        self.png: dict[str, bytes | None] = {}
        self.apps: dict[str, Path] = {}
        self.cask_apps: dict[str, list[str]] = {}
        if protocol and common.have("sips"):
            self._index(inventory)
        else:
            self.protocol = ""

    def _index(self, inventory: dict) -> None:
        import audit  # local import: audit imports this module lazily too

        for root in audit.app_dirs():
            for app in audit.iter_apps(root):
                self.apps.setdefault(app.stem.lower(), app)
        tokens = inventory.get("casks", [])
        out = common.run(["brew", "info", "--json=v2", "--cask", *tokens], timeout=120) if tokens else None
        try:
            for cask in json.loads(out or "{}").get("casks", []):
                names = []
                for art in cask.get("artifacts", []):
                    if isinstance(art, dict):
                        names += [re.sub(r"\.app$", "", a.rsplit("/", 1)[-1], flags=re.I) for a in art.get("app", []) if isinstance(a, str)]
                self.cask_apps[cask["token"]] = names
        except (ValueError, KeyError):
            pass
        self.cache_dir = Path(tempfile.mkdtemp(prefix="mac-setup-icons-"))
        atexit.register(shutil.rmtree, self.cache_dir, True)

    def _bundle(self, item: Item) -> Path | None:
        if item.kind == "casks":
            names = self.cask_apps.get(item.name, []) + [item.name.replace("-", " ")]
        elif item.kind == "mas":
            names = [item.name]
        else:
            return None
        for n in names:
            if n.lower() in self.apps:
                return self.apps[n.lower()]
        return None

    @staticmethod
    def _icns(app: Path) -> Path | None:
        resources = app / "Contents" / "Resources"
        try:
            info = plistlib.loads((app / "Contents" / "Info.plist").read_bytes())
        except Exception:  # noqa: BLE001 - unreadable bundle, no icon
            return None
        for key in ("CFBundleIconFile", "CFBundleIconName"):
            name = info.get(key)
            if name:
                for cand in (name, f"{name}.icns"):
                    if (resources / cand).is_file():
                        return resources / cand
        found = sorted(resources.glob("*.icns")) if resources.is_dir() else []
        return found[0] if found else None

    def png_for(self, item: Item) -> bytes | None:
        if not self.protocol or item.key in self.png:
            return self.png.get(item.key)
        data = None
        app = self._bundle(item)
        icns = self._icns(app) if app else None
        if icns and self.cache_dir:
            target = self.cache_dir / (re.sub(r"\W+", "_", item.key) + ".png")
            r = subprocess.run(["sips", "-s", "format", "png", "-Z", "256", str(icns), "--out", str(target)],
                               capture_output=True, timeout=20)
            if r.returncode == 0 and target.exists():
                data = target.read_bytes()
        self.png[item.key] = data
        return data

    def draw(self, item: Item) -> str:
        """Escape sequence that draws the icon at the cursor without moving it."""
        data = self.png_for(item)
        if not data:
            return ""
        b64 = base64.b64encode(data).decode()
        if self.protocol == "iterm":
            image = f"\x1b]1337;File=inline=1;width={ICON_COLS};height={ICON_ROWS};preserveAspectRatio=1:{b64}\x07"
        else:
            chunks = [b64[i:i + 4096] for i in range(0, len(b64), 4096)]
            image = ""
            for n, chunk in enumerate(chunks):
                more = 1 if n < len(chunks) - 1 else 0
                head = f"a=T,f=100,c={ICON_COLS},r={ICON_ROWS}," if n == 0 else ""
                image += f"\x1b_G{head}m={more};{chunk}\x1b\\"
            image = "\x1b_Ga=d\x1b\\" + image
        return "\x1b7  " + image + "\x1b8"


# --------------------------------------------------------------------------
# Keys
# --------------------------------------------------------------------------
class Keys:
    """One key at a time from the terminal, or from MAC_SETUP_GAME_KEYS="enter,right,u,q" (tests)."""

    def __init__(self):
        script = os.environ.get("MAC_SETUP_GAME_KEYS")
        self.script = [k.strip() for k in script.split(",")] if script is not None else None
        self.old = None
        if self.script is None:
            import termios
            import tty

            self.fd = sys.stdin.fileno()
            self.old = termios.tcgetattr(self.fd)
            tty.setcbreak(self.fd)

    def close(self) -> None:
        if self.old is not None:
            import termios

            termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

    def read(self) -> str:
        if self.script is not None:
            return self.script.pop(0) if self.script else "q"
        ch = os.read(self.fd, 1)
        if ch == b"\x1b":
            seq = b""
            while select.select([self.fd], [], [], 0.05)[0] and len(seq) < 2:
                seq += os.read(self.fd, 1)
            return {b"[A": "up", b"[B": "down", b"[C": "right", b"[D": "left"}.get(seq, "esc")
        if ch in (b"\r", b"\n"):
            return "enter"
        if ch in (b"\x7f", b"\x08"):
            return "undo"
        if ch == b"\x03":
            raise KeyboardInterrupt
        return ch.decode("utf-8", "ignore").lower()


# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------
def load_choices(path: Path = CHOICES_FILE) -> dict[str, str]:
    try:
        return dict(json.loads(path.read_text(encoding="utf-8")).get("choices", {}))
    except (OSError, ValueError):
        return {}


def save_choices(choices: dict[str, str], path: Path = CHOICES_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"choices": dict(sorted(choices.items()))}, indent=2) + "\n", encoding="utf-8")


def build_grouping(items: list[Item], choices: dict[str, str], categories: list[str]) -> dict[str, dict]:
    """Choices -> the grouping JSON that categorize.from_grouping accepts."""
    out = {c: {"description": DESCRIPTIONS.get(c, f"{c} tools, picked in the sorting game"),
               "casks": [], "brews": [], "mas": [], "vscode": []} for c in categories}
    for item in items:
        cat = choices.get(item.key)
        if cat in out:
            out[cat][item.kind].append(int(item.ref) if item.kind == "mas" else item.ref)
    return {c: g for c, g in out.items() if any(g[k] for k in ("casks", "brews", "mas", "vscode"))}


# --------------------------------------------------------------------------
# Game
# --------------------------------------------------------------------------
def card(items, i, categories, colours, choices, icons, rules, note) -> str:
    item = items[i]
    done = sum(1 for it in items if it.key in choices)
    width = 30
    filled = int(width * done / max(len(items), 1))
    tally = "  ".join(
        f"{badge(c, c, colours)} {sum(1 for v in choices.values() if v == c)}" for c in categories)
    sug = suggest(item, categories, rules)
    current = choices.get(item.key)
    out = ["\x1b[2J\x1b[H"]
    out.append(f"  mac-setup sorting game   {i + 1}/{len(items)}   [{'#' * filled}{'.' * (width - filled)}]\n")
    out.append(f"  {tally}  {badge('everything', SKIP, colours)} (all items)\n\n")
    out.append((icons.draw(item) if icons else "") + "\n" * ICON_ROWS)
    out.append(f"  \x1b[1m{item.name}\x1b[0m   \x1b[2m{KIND_LABEL[item.kind]}\x1b[0m\n\n")
    out.append("  suggested: " + (badge(sug, sug, colours) if sug else badge("everything only", SKIP, colours)))
    if current:
        out.append("   chosen before: " + badge(current if current != SKIP else "everything only", current, colours))
    out.append("\n\n")
    arrows = ["→", "↑", "↓"]
    for n, c in enumerate(categories):
        hint = f"{arrows[n]} or {n + 1}" if n < len(arrows) else str(n + 1)
        out.append(f"  {hint:<7} {badge(c, c, colours)}\n")
    out.append(f"  ←       {badge('everything only', SKIP, colours)}\n\n")
    out.append("  Enter accept suggestion   u undo   q save and quit\n")
    if note:
        out.append(f"\n  {note}\n")
    return "".join(out)


def play(inventory: dict, categories: list[str] | None = None, redo: bool = False,
         icon_mode: str = "auto", kinds=KIND_ORDER) -> dict[str, dict]:
    """Run the game and return the grouping JSON for the choices made."""
    categories = list(dict.fromkeys(categories or DEFAULT_CATEGORIES))
    if "common" not in categories:
        categories.append("common")
    items = build_items(inventory, kinds)
    rules = categorize.load_rules()
    colours = colour_map(categories)
    choices = {} if redo else {k: v for k, v in load_choices().items() if any(it.key == k for it in items)}
    scripted = os.environ.get("MAC_SETUP_GAME_KEYS") is not None
    if not scripted and not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.exit("The sorting game needs an interactive terminal.")
    icons = None if scripted else Icons(inventory, icon_protocol(icon_mode))
    keys = Keys()
    todo = [i for i, it in enumerate(items) if it.key not in choices]
    history: list[int] = []
    pos, note = 0, ""
    if choices and not redo:
        note = f"Resuming: {len(choices)} items already sorted (use --redo to start over)."
    try:
        while pos < len(todo):
            i = todo[pos]
            sys.stdout.write(card(items, i, categories, colours, choices, icons, rules, note))
            sys.stdout.flush()
            note = ""
            key = keys.read()
            if key == "q":
                break
            if key in ("u", "undo"):
                if history:  # only cards sorted in this session can be undone
                    j = history.pop()
                    choices.pop(items[j].key, None)
                    pos = todo.index(j)
                continue
            arrow = {"right": 0, "up": 1, "down": 2}
            if key == "enter":
                pick = suggest(items[i], categories, rules) or SKIP
            elif key in ("left", "s", " "):
                pick = SKIP
            elif key in arrow and arrow[key] < len(categories):
                pick = categories[arrow[key]]
            elif key.isdigit() and 1 <= int(key) <= len(categories):
                pick = categories[int(key) - 1]
            else:
                continue
            history.append(i)
            choices[items[i].key] = pick
            pos += 1
    finally:
        keys.close()
        save_choices(choices)
    sys.stdout.write("\x1b[2J\x1b[H")
    counts = {c: sum(1 for v in choices.values() if v == c) for c in categories}
    left = len(items) - len(choices)
    print(f"Sorted {len(choices)} of {len(items)} items "
          f"({', '.join(f'{n} {c}' for c, n in counts.items())}, {len(choices) - sum(counts.values())} everything only).")
    if left:
        print(f"{left} left unsorted; they stay in 'everything'. Run the game again to continue where you stopped.")
    print(f"Choices saved to {CHOICES_FILE}.")
    return build_grouping(items, choices, categories)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--categories", default=",".join(DEFAULT_CATEGORIES), help="comma-separated categories (default: developer,common)")
    ap.add_argument("--redo", action="store_true", help="ignore saved choices and start over")
    ap.add_argument("--icons", choices=["auto", "iterm", "kitty", "off"], default="auto")
    a = ap.parse_args()
    inv = json.loads(common.INVENTORY_FILE.read_text(encoding="utf-8"))
    print(json.dumps(play(inv, a.categories.split(","), a.redo, a.icons), indent=2))
