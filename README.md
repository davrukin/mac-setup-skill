# mac-setup

Copy one Mac's software onto another. It audits a Mac (Homebrew formulae and casks, taps, Mac App Store apps, VS Code extensions, and manually installed apps), sorts everything into role **presets** (developer, creative, essentials, or your own), suggests tools you are missing in three tiers, and produces a Brewfile plus the `brew bundle install` command for the preset you pick.

It works three ways: as a **Claude skill**, as a **ChatGPT skill**, or as plain scripts you run yourself. The assistant adds judgment (grouping tools sensibly, researching current recommendations); the scripts do the exact work.

## Standalone quick start

On the Mac you want to copy:

```bash
git clone <this repo> mac-setup && cd mac-setup
scripts/setup.sh audit            # writes data/presets.yaml
git add data/presets.yaml && git commit -m "My presets" && git push
```

On the new Mac:

```bash
git clone <this repo> mac-setup && cd mac-setup
scripts/setup.sh deploy --preset developer --dry-run     # review first
scripts/setup.sh deploy --preset developer --exclude slack,discord --run
```

Needs macOS, `python3` (installed with the Xcode command line tools), and Homebrew (`setup.sh` offers to install it and asks before downloading anything).

## Commands

| Command | What it does |
|---|---|
| `setup.sh audit [--ai] [--inventory-only] [--categorization FILE]` | Scan this Mac, write `data/inventory.json` and `data/presets.yaml` |
| `setup.sh recommend --preset NAME [--source URL_OR_FILE]` | Tiered suggestions: very useful, nice to have, could be useful |
| `setup.sh deploy [--preset NAME] [--exclude a,b] [--include-recs 1\|2\|3] [--dry-run] [--run]` | Preset to Brewfile to install command |
| `setup.sh presets list\|show\|import\|export\|delete` | Manage presets, including importing someone else's Brewfile |
| `setup.sh bootstrap` | Install Homebrew (with confirmation) and the Python environment |

## How the pieces decide things

- **Grouping.** By default, rules in `references/categories.yaml` (edit them to change what counts as "developer"). With an assistant, it reads `data/inventory.json` and writes a grouping that fits you; with `--ai`, an LLM through LiteLLM does it. Grouping from an assistant or LLM is checked against the inventory, and unknown items are dropped.
- **Manually installed apps.** Added only when Homebrew has a real cask for them. The rest are listed as `unmatched_apps` rather than guessed into a Brewfile that would fail. Apple's own apps are skipped; App Store apps come from `mas`.
- **Recommendations.** Pooled from a small offline seed list, research an assistant saved to `data/web_recommendations.json`, any `--source` list or Brewfile you point at, and optionally an LLM. Installed or excluded items are removed. With Homebrew present, names that do not exist are dropped. Tools several sources agree on rank higher.
- **Imports.** `presets import <Brewfile or URL>` reads plain `tap`/`brew`/`cask`/`mas`/`vscode` lines only. It never executes Ruby from a Brewfile.

## Use with Claude

- **Claude Code:** `git clone <this repo> ~/.claude/skills/mac-setup` (or put it in a project's `.claude/skills/`). Ask: "set up my new Mac like my old one".
- **Claude.ai / desktop:** zip the folder (the `.skill`/zip from the release works) and upload it under Settings, Capabilities, Skills.

Claude in the cloud cannot see your Mac, so it will hand you commands to run and ask you to upload `data/inventory.json` or `data/presets.yaml`. In Claude Code, or anywhere it has a shell on your Mac, it runs the scripts itself.

## Use with ChatGPT

The repo follows the same `SKILL.md` layout, with an `agents/openai.yaml` for the ChatGPT skill UI.

- **ChatGPT skills:** upload the zip (one skill per archive) where ChatGPT lets you add skills. Then ask the same way. ChatGPT's sandbox cannot see your Mac either, so run the `setup.sh` commands in Terminal and upload `data/inventory.json` for it to group and research against.
- **Codex CLI or other local agents:** clone the repo and point the agent at `AGENTS.md` / `SKILL.md`; it can run the scripts directly.
- **Custom GPT fallback:** paste `SKILL.md` into the GPT's Instructions and upload `references/*` as Knowledge. Run the scripts yourself and paste results back.

ChatGPT's skill packaging has changed more than once. If an upload is rejected, check OpenAI's current skill requirements; the core content (`SKILL.md`, `scripts/`, `references/`) does not depend on either vendor.

## Privacy

`data/presets.yaml` lists everything you have installed and is meant to be committed so a new Mac can fetch it; use a private repo or review it first. `--ai` sends tool names (not file contents) to the provider you configure. API keys are read from the environment and are never written to disk.

## Layout

```
SKILL.md              instructions for the assistant
scripts/              setup.sh + audit.py, categorize.py, recommend.py, deploy.py, presets.py, common.py, ai_skill.py
references/           categories.yaml, recommended_seed.yaml, schemas.md, web-research.md
agents/openai.yaml    ChatGPT skill UI metadata
data/                 presets.yaml and generated files
tests/run_tests.sh    end-to-end tests with a fake brew (installs nothing)
```

## Tests

```bash
bash tests/run_tests.sh
```

Runs the audit, import, recommend and deploy flows against a fake `brew` and fake `.app` bundles. It has not been run against a real Mac or a real Homebrew; try `deploy --dry-run` first on any new machine.

## License

Add one before publishing (MIT is a common choice for a tool like this).
