# Troubleshooting installs

`setup.sh deploy --preset NAME --run` installs one item at a time. It prints each item before it starts, streams that item's output, and ends with a list of what failed and why. The full output goes to `data/logs/<preset>-<time>.log`, and the failures to `data/logs/<preset>-<time>.failed.txt`. Run the same command again to retry: finished items are skipped.

## The ArtCraft apps are in /Applications, not /Applications/ArtCraft

The Craft casks (artcraft, cadcraft, deckcraft, designcraft, effectcraft, filmcraft, gridcraft, lightcraft, pdfcraft, photocraft, soundcraft, vectorcraft, wordcraft) put themselves in `/Applications/ArtCraft/` through the install path in their current Homebrew definition. If they landed loose in `/Applications`, the Homebrew on that Mac was most likely holding older cask definitions that had no such path. `deploy --run` now runs `brew update` first to prevent that.

To move the ones already installed, and keep Homebrew's records right, let Homebrew do the move. Do not drag the apps yourself, because Homebrew then looks for them in the old place.

```bash
brew update
mkdir -p /Applications/ArtCraft
for c in artcraft cadcraft deckcraft designcraft effectcraft filmcraft gridcraft lightcraft pdfcraft photocraft soundcraft vectorcraft wordcraft; do
  brew list --cask "$c" >/dev/null 2>&1 && brew reinstall --cask "$c"
done
ls /Applications/ArtCraft
```

`reinstall` removes the app from where Homebrew recorded it and installs it again at the path in the updated definition. It does not delete your settings or data, because that only happens with `brew uninstall --zap`. If a reinstall complains that an app already exists, quit that app and use `brew reinstall --cask --force NAME`.

If you already moved some by hand, run the same loop. `--force` is the fallback if Homebrew cannot find where it put the app.

## Apps from Setapp

Setapp licenses its apps through its own app, so installing the same app with Homebrew leaves Setapp unaware of it. The audit records apps that live in a Setapp folder (`setapp_apps` and `setapp_casks` in `inventory.json`), and `deploy` leaves those casks out and says so. They are listed in `data/manual-installs.md`: install Setapp (`brew install --cask setapp`), sign in, and add them from inside it.

For an inventory made before this existed, run `scripts/setup.sh setapp` once.

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

## Output arrives in a lump

`brew bundle` collects output until it finishes. `--run` no longer uses it: each item prints a `[n/total]` line before it starts, and its output streams live. If output still looks delayed, the log file in `data/logs/` has the exact order and timing of the commands.
