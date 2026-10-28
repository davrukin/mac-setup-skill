# Troubleshooting installs

`setup.sh deploy --preset NAME --run` installs one item at a time. It prints each item before it starts, streams that item's output, and ends with a list of what failed and why. The full output goes to `data/logs/<preset>-<time>.log`, and the failures to `data/logs/<preset>-<time>.failed.txt`. Run the same command again to retry: finished items are skipped.

## The ArtCraft apps are in /Applications, not /Applications/ArtCraft

The Craft casks (artcraft, cadcraft, deckcraft, designcraft, effectcraft, filmcraft, gridcraft, lightcraft, pdfcraft, photocraft, soundcraft, vectorcraft, wordcraft) put themselves in `/Applications/ArtCraft/` through the install path in their current Homebrew definition. If they landed loose in `/Applications`, the Homebrew on that Mac was most likely holding older cask definitions that had no such path. `deploy --run` now runs `brew update` first to prevent that.

The script does this for you, and shows its plan first. It works on one category (preset) at a time: anything in `not_needed`, or that you excluded for that preset, is ignored and not listed. It also creates the folder (`/Applications/ArtCraft`) if it does not exist, and the installer creates it before installing a Craft cask into it.

```bash
scripts/setup.sh relocate --preset developer            # plan only; nothing changes
scripts/setup.sh relocate --preset developer --apply    # do it (quit the apps first)
```

`relocate` runs `brew update` first (and shows its error if that fails), then works in two steps:

1. **Move.** Every Craft app in `/Applications` goes into `/Applications/ArtCraft/`. An app that is running is skipped and named.
2. **Link.** Each moved app is linked to Homebrew with `brew install --cask --adopt`. If Homebrew had installed it, its old record (which still points at the old path) is removed first. When the cask's own definition does not name the folder, the command adds `--appdir=/Applications/ArtCraft`, so Homebrew looks in the right place; I checked that a cask adopted this way is later found by a plain `brew uninstall`.

Nothing is downloaded and your settings and data are not touched; only `brew uninstall --zap` removes those. If step 2 fails for an app, it stays safely in the new folder and the exact command to finish is printed. `references/folders.yaml` lists which casks belong in which folder; add your own. Every `brew` command the script runs has Homebrew's automatic removal of unused dependencies turned off, so it does not clean up unrelated packages.

Do not drag the apps yourself: Homebrew then looks for them in the old place.

## Apps from Setapp

Setapp licenses its apps through its own app, so installing the same app with Homebrew leaves Setapp unaware of it. The audit records apps that live in a Setapp folder (`setapp_apps` and `setapp_casks` in `inventory.json`), and `deploy` leaves those casks out and says so. They are listed in `data/manual-installs.md`: install Setapp (`brew install --cask setapp`), sign in, and add them from inside it.

For an inventory made before this existed, run `scripts/setup.sh setapp` once.

`scripts/setup.sh relocate --preset NAME` lists the **Setapp apps in that category**, one per line, (from the Setapp apps recorded in `inventory.json` on the Mac you audited, filtered to the apps that belong to the category), with its state on this Mac: installed by Homebrew, installed some other way, already in the Setapp folder, or not installed. It writes `data/setapp-to-install.md`, a checklist of the ones to add yourself. It never moves or installs Setapp apps, because Setapp records a license only for an app it installs itself.

With `--apply` it removes the Homebrew-installed copies (`brew uninstall --cask`, never `--zap`, so your data stays) and asks first. Add `--keep-homebrew-setapp` to leave them. Then open Setapp, sign in, and install and license the apps on the checklist.

If you did this by hand: `brew uninstall --cask NAME` keeps your data, and then you add the app from Setapp.

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
