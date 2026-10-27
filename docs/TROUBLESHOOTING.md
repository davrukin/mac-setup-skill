# Troubleshooting installs

`setup.sh deploy --preset NAME --run` installs one item at a time. It prints each item before it starts, streams that item's output, and ends with a list of what failed and why. The full output goes to `data/logs/<preset>-<time>.log`, and the failures to `data/logs/<preset>-<time>.failed.txt`. Run the same command again to retry: finished items are skipped.

## The ArtCraft apps are in /Applications, not /Applications/ArtCraft

The Craft casks (artcraft, cadcraft, deckcraft, designcraft, effectcraft, filmcraft, gridcraft, lightcraft, pdfcraft, photocraft, soundcraft, vectorcraft, wordcraft) put themselves in `/Applications/ArtCraft/` through the install path in their current Homebrew definition. If they landed loose in `/Applications`, the Homebrew on that Mac was most likely holding older cask definitions that had no such path. `deploy --run` now runs `brew update` first to prevent that.

The script does this for you, and shows its plan first:

```bash
scripts/setup.sh relocate            # plan only; nothing changes
scripts/setup.sh relocate --apply    # do it (quit the apps first)
```

For a Craft app Homebrew installed, it runs `brew reinstall --cask --force NAME`: Homebrew removes the app from where it recorded it and installs it at the current path, so its records stay right. For one Homebrew did not install, it moves the app into the folder and runs `brew install --cask --adopt NAME`, so Homebrew takes it over without a new download (and puts the app back if that fails). Your settings and data are not touched; only `brew uninstall --zap` removes those. Do not drag the apps yourself: Homebrew then looks for them in the old place.

## Apps from Setapp

Setapp licenses its apps through its own app, so installing the same app with Homebrew leaves Setapp unaware of it. The audit records apps that live in a Setapp folder (`setapp_apps` and `setapp_casks` in `inventory.json`), and `deploy` leaves those casks out and says so. They are listed in `data/manual-installs.md`: install Setapp (`brew install --cask setapp`), sign in, and add them from inside it.

For an inventory made before this existed, run `scripts/setup.sh setapp` once.

`scripts/setup.sh relocate` also lists Setapp apps that are installed only outside Setapp, and those with a second copy outside the Setapp folder. It does not move them: Setapp records a license when it installs an app itself, and putting an app in its folder does not register anything. Add `--apply --uninstall-homebrew-copies` to remove the Homebrew casks of those apps (data kept) before you add them from Setapp.

If you installed some through Homebrew already, remove them with `brew uninstall --cask NAME` (this keeps your data) and add them from Setapp.

## "No downloads initiated for ADAM ID ..."

That is `mas`, the Mac App Store command-line tool, saying the App Store refused to start the download. The runner now explains it next to the app and gives an `macappstore://` link to open it by hand. Usual causes:

- Your Apple ID has never "bought" the app. Open the link and press Get once, then run the command again.
- It is an iPhone or iPad app. `mas` cannot install those.
- It is not offered for this macOS version or this Mac.
- You are not signed in to the App Store.

App Store apps now install last, with a short pause between them, and a failed one does not stop the rest.

## Password and Touch ID prompts

Some apps install from a `.pkg` installer, which needs administrator rights. Before it starts, the runner lists those apps and asks once (macOS shows its own password or Touch ID dialog), then keeps the permission alive for the rest of the run. Each of those apps is also marked next to its name as it installs. Prompts that appear without that marking are not from this tool; the log shows which item was running when it appeared.

## "500 Internal Server Error" dialogs

I have not seen these, so this is a guess, not a fix. System dialogs with a server error during an install most likely come from the App Store or an app's own installer contacting its server while many installs are going on. The runner now spaces App Store installs out and prints what was installing, so check `data/logs/` for the item running when the dialog appeared, and note its exact text. A later run retries only the failures.

## What is still missing after an install

`scripts/setup.sh missing --preset NAME` lists every item in the preset (after your exclusions) that is not installed, and separately the apps that are on disk but were not installed by Homebrew. Add `--install` to be asked, then try the missing ones with the same item-by-item installer.

## Output arrives in a lump

`brew bundle` collects output until it finishes. `--run` no longer uses it: each item prints a `[n/total]` line before it starts, and its output streams live. If output still looks delayed, the log file in `data/logs/` has the exact order and timing of the commands.
