# Agent instructions

This repository is a skill. The full instructions are in [SKILL.md](SKILL.md); read it first and follow it. Reference material is in `references/`.

Quick facts for agents that read only this file:

- The scripts in `scripts/` must run on the Mac being audited or set up. If you only have a cloud sandbox, give the user the command and ask for the output file.
- Entry point: `scripts/setup.sh` (`audit`, `recommend`, `deploy`, `presets`, `bootstrap`). Add `--yes` to skip confirmation prompts, and `MAC_SETUP_SKIP_VENV=1` to use the system `python3` with PyYAML.
- `scripts/setup.sh game` is an interactive sorting game for the user; it needs a real terminal, so give the user the command instead of running it. Tests drive it with `MAC_SETUP_GAME_KEYS`.
- Never run `deploy --run` without showing the user the dry-run output and getting a go-ahead.
- After editing any script, run `bash tests/run_tests.sh`. It uses a fake `brew` and installs nothing.
- Commit frequently, as the user requires: make a small commit after each logical change (one concern per commit, with a descriptive message explaining what and why), on the current branch. Do not batch unrelated edits into one commit, and do not leave finished work uncommitted.
