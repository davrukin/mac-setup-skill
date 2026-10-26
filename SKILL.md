---
name: mac-setup
description: audit a mac's installed apps, homebrew packages, app store apps and vs code extensions, sort them into role presets (developer, creative or photographer, essentials), recommend missing tools in three tiers, and generate a brewfile plus the brew bundle command to install a preset on a new mac. use whenever the user wants to set up a new mac, clone or migrate their mac setup, build a brewfile, make a work mac match their personal one, import someone else's brewfile, or asks what apps and cli tools they should install, even if they never say homebrew or preset.
---

# Mac setup

Turns one Mac's installed software into reusable **presets**, then installs a chosen preset on another Mac with Homebrew.

The scripts in `scripts/` do the deterministic work (scanning, matching names to real Homebrew casks, writing Brewfiles). Your job is the judgment part: grouping tools sensibly, researching current recommendations, and deciding with the user what should not be copied to a new machine.

## First: where does this run?

The scripts must run **on the Mac** being audited or set up. A cloud sandbox cannot see the user's apps.

- You have a shell on the Mac (Claude Code, Codex CLI, a desktop bridge): run the commands yourself.
- You do not: give the user the exact command, ask them to run it in Terminal, and ask them to paste back or upload the output file (`data/inventory.json` or `data/presets.yaml`). Continue from that file.

Use `scripts/setup.sh` as the entry point. It bootstraps Homebrew (asking first) and a Python venv, then routes to the Python scripts. If the user has no Homebrew yet and only wants to read the output, the scripts still run; they just cannot verify cask names.

## Workflows

### 1. Audit the old Mac and build presets

```bash
scripts/setup.sh audit                       # built-in rules, no network, no AI
scripts/setup.sh audit --inventory-only      # just data/inventory.json, so you can do the grouping
scripts/setup.sh audit --categorization group.json   # your grouping (shape: references/schemas.md)
scripts/setup.sh audit --ai                  # LLM grouping; needs LLM_MODEL, sends tool names to that provider
scripts/setup.sh game                        # sort everything yourself in an interactive, swipe-style terminal game
```

What it collects: Homebrew formulae, casks and taps (via `brew bundle dump`), Mac App Store apps, VS Code extensions, and apps in `/Applications` and `~/Applications`. A manually installed app is only added when a real cask exists for it. Everything else lands in `unmatched_apps` in `data/inventory.json` because guessing a cask name from an app name produces Brewfile lines that fail on the new Mac.

Output: `data/presets.yaml` with `current_system` (everything) plus role presets such as `developer`, `creative`, `essentials`.

**Fresh runs.** `setup.sh --new-run game` (or any command) keeps everything in its own folder, `data/runs/YYYY-MM-DD_HHMMSS`, with no saved game choices or earlier presets reused. `--data-dir PATH` picks the folder yourself; pass the same folder to later `deploy`, `presets` and `recommend` calls. Without either flag, files go in `data/`. If Homebrew's cask list is empty (its cached name file went missing), the audit says so and asks before running `brew update`, then re-checks the cask count and continues. `--yes` pre-approves it; without a terminal or approval it stops with instructions. `--allow-incomplete` continues with partial data instead.

**Sorting game (`setup.sh game`, same as `audit --game`).** The user steps through every installed app, tool and App Store app. Everything is always in `current_system` ("everything"); each card suggests a colour-coded category from the built-in rules and the user picks `developer`, `common` (merged into every preset) or `everything only` with arrow keys, number keys or Enter to accept the suggestion. App icons are drawn in iTerm2, WezTerm, kitty and Ghostty (`--icons off` disables them). Each category also has a letter hotkey (developer `d`, common `c`). Press `n` during the game to create a category and hotkey on the spot (the current item goes into it); on the command line use `--categories developer,common,creative:r` to name a hotkey. Created categories are saved and come back on the next run. Under each name the card shows Homebrew's one-line description and, for command-line tools, whether you installed it yourself and which installed software depends on it (a yellow `!` line), so nobody rejects a library that other tools use. Skipping an item never removes it: it stays in `current_system`, and Homebrew installs required dependencies automatically when a preset is deployed. Tools that Homebrew installed only as dependencies are hidden unless `--include-dependencies` is given. Progress is saved to `data/game_choices.json`, so the game can be stopped and resumed (`--redo` starts over). It needs a real terminal, so give the user the command rather than running it yourself.

The `shared: true` preset in `references/categories.yaml` (`common`: Claude, Claude Code, Figma) is added to every role preset after grouping, whichever way the grouping was made (built-in rules, `--categorization` or `--ai`), so do not worry about including those items in your own grouping. App-to-cask matching uses Homebrew's cask metadata (app names and bundle ids), and families listed under `consolidate:` (JetBrains IDEs and Android Studio) are replaced by their launcher cask (`jetbrains-toolbox`).

**Best result without an API key:** run `--inventory-only`, read `data/inventory.json`, write a grouping that reflects what this person actually does (a staff Android engineer who shoots film needs different presets than a web developer), save it as JSON, and run `--categorization`. Unknown items are dropped automatically, so a slip cannot put a non-existent package in a preset. Tell the user how many items were dropped and why.

### 2. Recommend missing tools (three tiers)

```bash
scripts/setup.sh recommend --preset developer
scripts/setup.sh recommend --preset developer --source <url-or-file> --source <another>
```

Tier 1 very useful, tier 2 nice to have, tier 3 could be useful, relative to what the preset already has. Candidates are pooled from a small offline seed list, from `data/web_recommendations.json`, from any `--source` (Brewfiles, READMEs, articles: it extracts `brew "x"`, `cask "x"` and `brew install` lines), and optionally an LLM. Anything already installed or excluded is removed, and, where Homebrew is available, names that do not exist are dropped.

**Do the online research yourself when you have web access.** The seed list is a fallback that goes stale. Follow `references/web-research.md`: find current lists, cross-check at least two independent sources per tool, paraphrase the reasons (do not copy article text), and write `data/web_recommendations.json`. Then run `recommend`. The script weights tools that several sources agree on.

### 3. Deploy on the new Mac

```bash
scripts/setup.sh deploy                                   # interactive
scripts/setup.sh deploy --preset developer --dry-run      # show the Brewfile and command only
scripts/setup.sh deploy --preset developer --exclude slack,discord --include-recs 1 --run
```

It writes `data/brewfiles/<preset>.Brewfile`, prints `brew bundle install --file=...`, and runs it only with `--run` or a "y" at the prompt.

Before installing, **ask the user what should be left out**. Common cases on a work Mac: personal chat, VPN and password-manager apps, anything the employer already deploys through MDM, and tools that conflict with company policy. Pass those with `--exclude`. Show the dry-run output and get a go-ahead before `--run`, because this installs software on a machine the user may not fully own.

Notes to pass on: Mac App Store entries need the user signed in to the App Store first; an app already present in `/Applications` can make a cask install fail until it is removed or adopted; re-running the same command skips finished items.

### 4. Use someone else's config

```bash
scripts/setup.sh presets import <path-or-url-to-Brewfile> --name team-base
scripts/setup.sh presets import <url-to-presets.yaml>
scripts/setup.sh presets list | show NAME | export NAME --out Brewfile | delete NAME
```

GitHub `blob` URLs are converted to raw URLs. Only simple `tap`/`brew`/`cask`/`mas`/`vscode` lines are read; Ruby logic and other entries are counted and ignored, never executed. An imported Brewfile can still install anything, so skim it with the user first. Imported presets survive later audits.

## Privacy and safety

- `data/presets.yaml` and `data/inventory.json` list everything the user has installed. Both are committed on purpose: the user checks the repo out on the new Mac and the presets and inventory come with it. Generated Brewfiles (`data/brewfiles/`) and recommendation output are regenerated, not committed. Before the repo is shared publicly, scan both files for anything private (credentials, home paths, email addresses, employer or school specific tools) and ask the user about borderline app names.
- LLM features send tool **names** to whichever provider `LLM_MODEL` points at. Say so before using `--ai`. API keys come from the environment only and are never written to disk.
- Homebrew's installer is a remote script. `setup.sh` asks before running it; do not bypass that.

## Reference files

- `references/schemas.md`: file formats (presets, inventory, grouping JSON, web recommendations, recommendation output). Read before writing any of these by hand.
- `references/web-research.md`: how to research and verify recommendations.
- `references/categories.yaml`: the built-in grouping rules; edit to change default presets.
- `references/recommended_seed.yaml`: the offline fallback list.
- `README.md`: install instructions for Claude, ChatGPT and standalone use.

## Checking your work

`bash tests/run_tests.sh` runs everything against a fake `brew` and fake app bundles (no real installs). Run it after editing any script.
