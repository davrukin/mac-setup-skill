# Using these categories as a template

The categories in this repo are meant to be a starting point. You can take them, keep what fits and change the rest. Nothing here is private to one machine: the choices are names of public Homebrew packages and App Store apps.

## What a template contains

| Piece | File | Use it for |
|---|---|---|
| Categories and hotkeys, plus one decision per item | `data/game_choices.json` | Pre-answering the sorting game |
| Ready-made presets | `data/presets.yaml` | Deploying as they are, or importing |
| Rules for sorting without the game | `references/categories.yaml` | Default grouping on any Mac |
| Overlapping tools | `references/overlaps.yaml` | Warnings from `verify` |
| Per-preset excludes | `data/preset_excludes.yaml` | Keeping some common apps off one preset |

## Option 1: pre-answer the game with these choices

Best when you want your own presets with these as the starting answers.

```bash
git clone https://github.com/davrukin/mac-setup-skill mac-setup && cd mac-setup
mkdir -p ~/my-mac-setup
cp data/game_choices.json ~/my-mac-setup/
scripts/setup.sh game --data-dir ~/my-mac-setup
```

The game scans your Mac and skips every item the template already decided (it prints "Resuming: N items already sorted"). Only items the template has not seen are asked about, and each card still shows a suggested category. Template items that you do not have are ignored. `--redo` ignores the saved choices and asks about everything, so do not use it if you want the template's answers.

Use `--data-dir` and keep the same folder for `deploy`, `verify` and `presets`. Do not use `--new-run` for this: it starts clean and reuses nothing.

## Option 2: change the categories first

The template's categories are `developer`, `common`, `photography`, `gaming` and `not_needed`. Edit `categories` in your copy of `game_choices.json`, or press `n` in the game to add a category and hotkey. Rename or remove categories before you play, then check the result with `setup.sh presets show NAME`.

```json
"categories": { "developer": "d", "common": "c", "music": "m", "not_needed": "x" }
```

Keep `not_needed` if you want an exclusion list. `common` is merged into every other preset, so use it for things you want everywhere.

## Option 3: deploy a preset without sorting

If the template's `developer` preset is close enough, skip the game:

```bash
scripts/setup.sh verify
scripts/setup.sh deploy --preset developer --dry-run
scripts/setup.sh deploy --preset developer --exclude slack --dry-run
```

Or import another repo's presets into yours:

```bash
scripts/setup.sh presets import https://raw.githubusercontent.com/davrukin/mac-setup-skill/main/data/presets.yaml
```

## Things to check before you adopt a template

- **Read the choices, they are opinions.** The `not_needed` list is one person's call (for example, it drops Parallels, CrossOver and NordVPN). `data/preset_excludes.yaml` leaves 27 apps off `developer`. Look through both.
- **Run `verify` and a dry run first.** Nothing here has been installed with a real `brew bundle install` yet; tests use a fake `brew`.
- **Your own audit overwrites the inventory.** `data/inventory.json` and `data/presets.yaml` in this repo describe one Mac. If you run a plain `audit` in the clone, they are replaced; use `--data-dir` to keep them.
- **License.** The files are AGPL-3.0-or-later. A derivative you distribute, or run as a service, must be offered under the same license (see `LICENSE`).

## Sharing your own template

Commit your `game_choices.json`, `presets.yaml` and `preset_excludes.yaml` to a repo, check them for anything private, and give people the clone and `--data-dir` steps above. Because the format is plain JSON and YAML, others can adapt it the same way.
