# Current configuration

What this repo ships today. Everything here came from sorting one Mac's software with the sorting game, then checking the result with `setup.sh verify`. Counts are as of 2026-10-27.

## Categories

Set in `data/game_choices.json`, which also keeps one decision per item (248 so far).

| Category | Hotkey | Items | What it is for |
|---|---|---|---|
| `developer` | `d` | 72 | Engineering tools: editors, terminals, CLIs, containers, Android and iOS tooling |
| `common` | `c` | 106 | Needed on every Mac whatever its role. Merged into every other preset |
| `photography` | `f` | 19 | Photo and video tools (raw processing, editors, upscalers, encoders) |
| `gaming` | `g` | 16 | Game stores, launchers and games |
| `not_needed` | `x` | 35 | An exclusion list, not a preset. `deploy` leaves these out of every preset |

`current_system` also exists in `data/presets.yaml`. It holds everything found on the audited Mac and is never merged with `common` or `not_needed`.

## Presets

Built from those choices in `data/presets.yaml`. Each preset includes `common`, so it installs on its own.

| Preset | Taps | Formulae | Casks | App Store |
|---|---|---|---|---|
| `current_system` | 2 | 47 | 132 | 69 |
| `developer` | 1 | 40 | 93 | 45 |
| `photography` | 1 | 15 | 74 | 36 |
| `gaming` | 1 | 12 | 70 | 40 |
| `common` | 1 | 12 | 64 | 30 |
| `not_needed` | 0 | 4 | 23 | 8 |

`developer` also has 27 per-preset excludes (see below), so it installs fewer items than the table shows.

## Files that hold the configuration

| File | Role |
|---|---|
| `data/game_choices.json` | Categories, hotkeys and one category per item. The source of truth for the presets |
| `data/presets.yaml` | The presets built from those choices |
| `data/preset_excludes.yaml` | Items kept off one preset only. Today: 27 common apps kept off `developer` (media, finance, shopping and reading apps, WhatsApp, and similar). Change with `setup.sh presets exclude\|include PRESET item...` |
| `data/inventory.json` | Everything found on the audited Mac, with Homebrew metadata |
| `data/manual_apps.json`, `data/manual-installs.md` | Apps with no usable cask, where to get each one, and a category for each |
| `references/categories.yaml` | Rules used when you sort without the game (and the shared `common` set) |
| `references/overlaps.yaml` | Pairs of tools that overlap, reported by `verify` |

## Rules worth knowing

- **`common`** holds Claude, Claude Code, Figma, and the hardware tools you keep on every Mac.
- **Browsers:** only Firefox and Chrome are kept; other browsers are in `not_needed`.
- **JetBrains:** the IDEs and Android Studio are replaced by `jetbrains-toolbox`.
- **Library placement:** `verify` puts a library formula in the same category as the tools that depend on it, so it is never installed without its dependents.
- **Conflicts and deprecated packages:** `verify` flags them, and `deploy --run` refuses to start while any would break `brew bundle` (override with `--ignore-problems`).
- **Pre-installed Apple apps** such as GarageBand and iMovie are in `not_needed`.

## How to change it

- Re-sort everything: `scripts/setup.sh game --redo`. Without `--redo`, items already decided are skipped. With it, saved choices are ignored.
- Add a category and hotkey: press `n` in the game, or pass `--categories developer,common,music:m`.
- Edit by hand: `scripts/setup.sh verify --set CATEGORY KEY...` where a key looks like `casks:figma` or `brews:git`.
- Keep an item off one preset: `scripts/setup.sh presets exclude developer WhatsApp`.

Before installing on a new Mac, run `scripts/setup.sh verify`, then `scripts/setup.sh deploy --preset developer --dry-run`.
