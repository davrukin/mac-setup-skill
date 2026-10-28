#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Daniel Avrukin
"""Install a preset one item at a time, saying what is happening as it happens.

`brew bundle` installs everything in one go and its output is easy to lose. This runs the same
installs item by item: it prints what it is about to do, streams that item's output live, keeps a
log file, warns before anything that will ask for your password or Touch ID, and ends with a
list of what failed and why. Items that are already installed are skipped, so re-running is safe.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import common

MAS_NOT_STARTED = "No downloads initiated"
PAUSE_BETWEEN_APP_STORE_INSTALLS = 2  # seconds; the App Store throttles rapid requests


class Step:
    def __init__(self, kind: str, name: str, cmd: list[str], ref: str = ""):
        self.kind, self.name, self.cmd, self.ref = kind, name, cmd, ref or name
        self.note = ""  # shown before the step runs, e.g. that it will ask for a password


def build_steps(preset: dict, skip_mas: bool = False) -> list[Step]:
    p = common.normalize_preset(preset)
    steps = [Step("tap", t, ["brew", "tap", t]) for t in p["taps"]]
    steps += [Step("brew", b, ["brew", "install", b]) for b in p["brews"]]
    steps += [Step("cask", c, ["brew", "install", "--cask", c]) for c in p["casks"]]
    steps += [Step("vscode", v, ["code", "--install-extension", v]) for v in p["vscode"]]
    if not skip_mas:  # last: the App Store is the most failure-prone and the most interactive part
        steps += [Step("mas", m["name"], ["mas", "install", str(m["id"])], str(m["id"])) for m in p["mas"]]
    return steps


def installed_now() -> dict[str, set[str]]:
    def lines(cmd: list[str]) -> set[str]:
        return {ln.strip() for ln in (common.run(cmd) or "").splitlines() if ln.strip()}

    mas_ids = {ln.split()[0] for ln in lines(["mas", "list"])}
    return {
        "tap": lines(["brew", "tap"]),
        "brew": lines(["brew", "list", "--formula", "-1"]),
        "cask": lines(["brew", "list", "--cask", "-1"]),
        "vscode": {ln.lower() for ln in lines(["code", "--list-extensions"])},
        "mas": mas_ids,
    }


def cask_facts(casks: list[str]) -> tuple[set[str], dict[str, list[str]]]:
    """(casks that use an installer package and so need admin rights, explicit install paths by cask)."""
    out = common.run(["brew", "info", "--cask", "--json=v2", *casks]) if casks else None
    admin: set[str] = set()
    targets: dict[str, list[str]] = {}
    if not out:
        return admin, targets
    try:
        data = json.loads(out)
    except ValueError:
        return admin, targets
    for cask in data.get("casks", []):
        for art in cask.get("artifacts", []):
            if not isinstance(art, dict):
                continue
            if "pkg" in art:
                admin.add(cask["token"])
            if "app" in art and str(art.get("target", "")).startswith("/"):
                targets.setdefault(cask["token"], []).append(art["target"])
    return admin, targets


def stream(cmd: list[str], log, env: dict[str, str]) -> tuple[int, str]:
    """Run cmd, showing each output line as it arrives and copying it to the log."""
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env)
    except FileNotFoundError:
        msg = f"{cmd[0]} is not installed"
        print(f"      {msg}", flush=True)
        log.write(msg + "\n")
        return 127, msg
    collected: list[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip()
        log.write(line + "\n")
        log.flush()
        collected.append(line)
        if line.strip():
            print(f"      {line}", flush=True)
    return proc.wait(), "\n".join(collected)


def explain_failure(step: Step, output: str) -> str:
    if step.kind == "mas":
        if MAS_NOT_STARTED in output:
            return ("the App Store did not start the download. Usual causes: this Apple ID has not got the app yet "
                    "(open the link and press Get), it is an iPhone/iPad-only app mas cannot install, or it is not "
                    f"offered for this macOS. Link: macappstore://apps.apple.com/app/id{step.ref}")
        return f"mas failed; open macappstore://apps.apple.com/app/id{step.ref} to install it by hand"
    last = [ln.strip() for ln in output.splitlines() if ln.strip()]
    return last[-1] if last else "no output; see the log"


def keep_sudo_alive(stop: threading.Event) -> None:
    while not stop.wait(50):
        subprocess.run(["sudo", "-n", "-v"], capture_output=True)


def run(preset: dict, name: str, skip_update: bool = False, skip_mas: bool = False) -> int:
    common.require_brew("installing")
    steps = build_steps(preset, skip_mas)
    if not steps:
        print("Nothing to install.")
        return 0
    LOG_DIR = common.DATA_DIR / "logs"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = LOG_DIR / f"{name}-{stamp}.log"
    env = {**os.environ, "HOMEBREW_NO_ENV_HINTS": "1", "HOMEBREW_NO_AUTO_UPDATE": "1", "HOMEBREW_NO_AUTOREMOVE": "1"}
    counts = {k: sum(1 for s in steps if s.kind == k) for k in ("tap", "brew", "cask", "vscode", "mas")}
    print(f"📦 Installing '{name}': {counts['brew']} command-line tools, {counts['cask']} apps, "
          f"{counts['mas']} App Store apps, {counts['vscode']} editor extensions.")
    print(f"📝 Full log: {log_path}\n")

    with open(log_path, "w", encoding="utf-8") as log:
        if not skip_update:
            print("🔄 Updating Homebrew first, so app definitions (including where each app is installed) are current...", flush=True)
            code, _ = stream(["brew", "update"], log, {**env, "HOMEBREW_NO_AUTO_UPDATE": ""})
            print("   done." if code == 0 else "   brew update failed; continuing with the definitions already here.", flush=True)

        done = installed_now()
        casks = [s.name for s in steps if s.kind == "cask" and s.name not in done["cask"]]
        admin, targets = cask_facts(casks)
        for s in steps:
            if s.kind == "cask" and s.name in admin:
                s.note = "uses an installer package, so it will ask for your password or Touch ID"
            elif s.kind == "mas":
                s.note = "App Store download; you must be signed in to the App Store"

        folders = common.folder_rules()  # casks that live in their own folder (the ArtCraft apps)
        stop = threading.Event()
        needs = sorted(admin, key=str.lower)
        if needs and sys.stdin.isatty() and not os.environ.get("MAC_SETUP_NO_SUDO") and common.have("sudo"):
            print(f"🔐 {len(needs)} apps use an installer package that needs administrator rights: {', '.join(needs)}.")
            print("   macOS will ask for your password or Touch ID now, once, so the installers do not each ask later.\n", flush=True)
            if subprocess.run(["sudo", "-v"]).returncode == 0:
                threading.Thread(target=keep_sudo_alive, args=(stop,), daemon=True).start()
            else:
                print("   No administrator rights; those installers may fail or ask again.\n")
        elif needs:
            print(f"🔐 These apps use an installer package and may ask for your password or Touch ID: {', '.join(needs)}\n")

        results: dict[str, list] = {"ok": [], "skipped": [], "failed": []}
        total, started = len(steps), time.time()
        label = {"tap": "tap", "brew": "tool", "cask": "app", "vscode": "extension", "mas": "App Store"}
        try:
            for i, step in enumerate(steps, 1):
                head = f"[{i}/{total}] {label[step.kind]}: {step.name}"
                have = step.name.split("/")[-1] if step.kind in ("brew", "cask") else step.ref  # tap-qualified names list without the tap
                if have in done[step.kind] or (step.kind == "vscode" and step.name.lower() in done["vscode"]):
                    print(f"{head}  ⏭️  already installed", flush=True)
                    results["skipped"].append(step.name)
                    continue
                print(f"{head}" + (f"  ({step.note})" if step.note else "") + "  ...", flush=True)
                folder = folders.get(step.name) if step.kind == "cask" else None
                if folder and not Path(folder).is_dir():
                    try:
                        Path(folder).mkdir(parents=True, exist_ok=True)
                        print(f"      📁 created {folder}", flush=True)
                    except OSError as exc:
                        print(f"      ⚠️  could not create {folder}: {exc}", flush=True)
                log.write(f"\n=== {head}: {' '.join(step.cmd)}\n")
                t0 = time.time()
                code, output = stream(step.cmd, log, env)
                took = f"{time.time() - t0:.0f}s"
                if code == 0:
                    problem = [t for t in targets.get(step.name, []) if not os.path.exists(t)]
                    if problem:
                        print(f"      ⚠️  installed, but not found at {problem[0]}; check where it went (see the docs)")
                    print(f"      ✅ done ({took})", flush=True)
                    results["ok"].append(step.name)
                else:
                    why = explain_failure(step, output)
                    print(f"      ❌ failed ({took}): {why}", flush=True)
                    results["failed"].append((step.kind, step.name, why))
                if step.kind == "mas":
                    time.sleep(PAUSE_BETWEEN_APP_STORE_INSTALLS)
        except KeyboardInterrupt:
            print("\n⛔ Stopped. Run the same command again to carry on; finished items are skipped.")
        finally:
            stop.set()

    mins = (time.time() - started) / 60
    print(f"\n{'=' * 50}\n✅ {len(results['ok'])} installed   ⏭️  {len(results['skipped'])} already there   "
          f"❌ {len(results['failed'])} failed   ({mins:.1f} min)")
    if results["failed"]:
        failed_path = log_path.with_suffix(".failed.txt")
        failed_path.write_text("\n".join(f"{k}\t{n}\t{why}" for k, n, why in results["failed"]) + "\n", encoding="utf-8")
        print("\nFailed:")
        for kind, item, why in results["failed"]:
            print(f"  • {item} ({label[kind]}): {why}")
        print(f"\nList saved to {failed_path}. Run the same command again to retry only these; finished items are skipped.")
    print(f"Full log: {log_path}")
    return 1 if results["failed"] else 0
