# Apps to install by hand

These 91 apps have no usable Homebrew cask, so `brew bundle` will not install them. Each is grouped by the category it was assigned to and says where to get it.

_Classified by assistant (mac-setup skill) on 2026-10-26; the categories are proposals, so edit `manual_apps.json` to change them. Links marked "not verified" are the vendor's usual address and were not confirmed by a search._

## Developer

| App | Where to get it | Notes |
| --- | --- | --- |
| Arduino | `brew install --cask arduino-ide`<br>[link (not verified)](https://www.arduino.cc/en/software/OldSoftwareReleases/) | You have the legacy 1.8.19 IDE. The `arduino-ide` cask installs the current 2.x IDE, which is a different app; use the legacy download only if you need 1.8. |
| IDLE, Python Launcher | Vendor download<br>[link (not verified)](https://www.python.org/downloads/macos/) | Come from the python.org installer for 3.12, which is separate from Homebrew's python@3.12. |
| Zenmap | Vendor download<br>[link (not verified)](https://nmap.org/download.html#macosx) | Bundled with the Nmap macOS installer. Homebrew's cask is disabled (fails its Gatekeeper check). |
| WaveSpeed Desktop | Vendor download<br>[link](https://wavespeed.ai/desktop) | Free AI generation app; builds for Mac are also on the project's GitHub releases. |
| Flinto | Setapp | Prototyping tool installed through Setapp. |

## Common

| App | Where to get it | Notes |
| --- | --- | --- |
| AlDente Pro, Receipts, Taskheat, Tripsy, MonsterWriter, Merlin Project Express, JoyTap, iBoysoft NTFS for Mac | Setapp | Installed through Setapp (cask `setapp`, already in common). Homebrew's `aldente`, `receipts` and `merlin-project` casks are different editions, not these. |
| MacDown | `brew install --cask macdown-3000` | Homebrew's `macdown` cask is disabled; `macdown-3000` is the maintained fork with the same editor. |
| MakeMKV | Vendor download<br>[link (not verified)](https://www.makemkv.com/download/) | Homebrew's cask is disabled (fails its Gatekeeper check). |
| Microsoft Teams classic | `brew install --cask microsoft-teams` | Teams classic is retired; the cask installs the current Teams. |
| net.downloadhelper.coapp | Vendor download<br>[link (not verified)](https://www.downloadhelper.net/) | Companion app for the Video DownloadHelper browser extension. Homebrew's cask is discontinued. |
| Superfocus | App Store<br>[link](https://apps.apple.com/us/app/-/id6738845613) | Focus app; needs an active subscription. |
| eBay | App Store<br>[link](https://apps.apple.com/us/app/ebay-online-shopping-selling/id282614216) | iPhone/iPad app running on your Mac. |
| TripIt | App Store<br>[link](https://apps.apple.com/us/app/tripit-travel-planner/id311035142) | iPhone/iPad app running on your Mac. |
| Daily Budget | App Store<br>[link (not verified)](https://apps.apple.com/us/app/daily-budget-original/id651896614) | iPhone/iPad app. Matched by name to 'Daily Budget Original'; the App Store has other apps called Daily Budget, so check the developer. |
| Today's Budget | App Store<br>[link](https://apps.apple.com/us/app/todays-budget-saving-is-fun/id1593868439) | iPhone/iPad app running on your Mac. |
| Pack, Repeat | App Store<br>[link](https://apps.apple.com/us/app/packing-list-pack-repeat/id6473901846) | iPhone/iPad app running on your Mac. |

## Photography

| App | Where to get it | Notes |
| --- | --- | --- |
| Adobe Lightroom, Adobe Lightroom Classic, Adobe Photoshop 2026 | `brew install --cask adobe-creative-cloud`<br>[link (not verified)](https://creativecloud.adobe.com/apps/download/creative-cloud) | Install the Creative Cloud app with the cask, sign in with your Adobe ID, then install these three from it. |
| Affinity Photo 2 | Already covered | Replaced by the unified Affinity app; the `affinity` cask is already in your photography category. |
| Capture One | Vendor download<br>[link (not verified)](https://www.captureone.com/) | Download from the vendor; needs your Capture One licence or subscription. |
| Corel AfterShot Pro 3 (64-bit), Painter Essentials 7 | Vendor download<br>[link (not verified)](https://www.corel.com/) | Legacy Corel Mac Essentials kit. Sold as licence-key downloads, so use your Corel account or original purchase email. |
| DXOPhotoLab9, DxO FilmPack 8 | Vendor download<br>[link (not verified)](https://www.dxo.com/dxo-photolab/) | FilmPack 8 is built into PhotoLab 9; install PhotoLab, then enter the FilmPack licence key in its menu. |
| RAW FILE CONVERTER EX 3.0 powered by SILKYPIX | Vendor download<br>[link (not verified)](https://fujifilm-x.com/global/support/download/software/) | Fujifilm's edition of SILKYPIX. Different from the `fujifilm-x-raw-studio` cask you already have. |
| ON1 Photo RAW 2025, ON1 Photo RAW 2026 | Vendor download<br>[link (not verified)](https://www.on1.com/) | Two yearly versions are installed; the 2026 one is enough on a new Mac. |
| Imaging Edge Desktop, Edit, Remote, Viewer | `brew install --cask imaging-edge` | Sony's Imaging Edge suite; Edit, Remote and Viewer are its three parts. Homebrew has a working cask. |
| OM Workspace | Vendor download<br>[link](https://download.omsystem.com/pages/owdownload/) | The download page asks for your OM System camera's serial number. |
| Blackmagic RAW Player, Blackmagic RAW Speed Test | Vendor download<br>[link (not verified)](https://www.blackmagicdesign.com/support/) | Search 'Blackmagic RAW' under Support > Latest Downloads. |
| DaVinci Resolve, DaVinci Control Panels Setup, Fairlight Studio Utility, Blackmagic Remote Monitor, Blackmagic Proxy Generator Lite, Uninstall Resolve | Vendor download<br>[link (not verified)](https://www.blackmagicdesign.com/products/davinciresolve) | One installer provides all of these utilities. You also have DaVinci Resolve from the App Store (listed in your photography category), so install only one of the two. |
| CameraBag Pro, Luminar, Luminar Neo, TouchRetouch, Filmage Editor | Setapp | Installed through Setapp; install Setapp (cask `setapp`, already in common) and sign in. |
| darktable | Vendor download<br>[link (not verified)](https://www.darktable.org/install/) | Homebrew's cask is disabled (fails its Gatekeeper check), so use the vendor download. |
| digikam, showfoto | Vendor download<br>[link (not verified)](https://www.digikam.org/download/) | digiKam and showfoto ship together. Homebrew's cask is disabled (fails its Gatekeeper check). |

## Gaming

| App | Where to get it | Notes |
| --- | --- | --- |
| armsx2 | Vendor download<br>[link](https://github.com/ARMSX2/ARMSX2/releases) | PS2 emulator for Apple silicon; download the macOS build from GitHub releases. |
| OpenEmu | Vendor download<br>[link (not verified)](https://openemu.org/) | Homebrew's cask is disabled (fails its Gatekeeper check). |
| Old School RuneScape | Vendor download<br>[link (not verified)](https://oldschool.runescape.com/) | Homebrew's cask is discontinued. You already have the `runescape` cask in gaming. |
| RemotePlay | `brew install --cask sony-ps-remote-play` | PlayStation Remote Play; Homebrew has a working cask. |
| Cities Skylines, DiRT 4, Fly Dangerous, Graphwar, SimplePlanes, College Bound | Steam<br>[link (not verified)](https://store.steampowered.com/) | Launcher stubs in ~/Applications. Install the `steam` cask (already in gaming), sign in, and re-download from your library. College Bound is assumed to be a Steam game (unverified). |
| Bitburner | Steam<br>[link (not verified)](https://store.steampowered.com/search/?term=Bitburner) | Programming idle game; also playable free in the browser. |
| Theme Hospital, Theme Park | GOG<br>[link (not verified)](https://www.gog.com/) | Bought on GOG. Install the `gog-galaxy` cask (already in gaming) and re-download. |

## Not Needed

_Not needed on a new Mac (discontinued, covered elsewhere, or only needed occasionally)._

| App | Where to get it | Notes |
| --- | --- | --- |
| Toast Express | Vendor download<br>[link (not verified)](https://www.corel.com/) | Part of the same Corel kit; disc burning is already covered by the `burn` cask. |
| AetherSX2 | Discontinued | Upstream development stopped; this Mac build is unofficial. ARMSX2 (listed under gaming) is its successor. |
| Counter-Strike Global Offensive | Discontinued | CS:GO was replaced by Counter-Strike 2, which does not run on macOS. |
| Google Docs, Google Sheets, Google Slides | Comes with another app | Google Drive shortcuts to documents, not apps. Drive for desktop (cask `google-drive`, in common) recreates the ones that exist. |
| YouTube | Chrome web app | Chrome web app. In Chrome open youtube.com and use Install if you want it again. |
| Chromebook Recovery Utility | Chrome web app<br>[link (not verified)](https://chromewebstore.google.com/detail/jndclpdbaamdhonoechobihbbiimdgai) | Chrome app, only needed when recovering a Chromebook. |
| Messenger | Discontinued | The desktop app was discontinued (Homebrew's cask is disabled). Use messenger.com. |
| Claude Code URL Handler | Comes with another app | Created by Claude Code itself (cask `claude-code`); it comes back automatically. |
| Xamarin Profiler, Visual Studio (Preview) | Discontinued | Visual Studio for Mac and Xamarin were retired by Microsoft in 2024. Use VS Code or JetBrains Rider instead. |
| Navigation Updater, Uninstall Navigation Updater | Vendor download<br>[link](https://update.hyundai.com/US/F1/navigationUpdate) | Hyundai car map updater; download it only when you update the car. |
| SamsungPortableSSD_1.0 | Vendor download<br>[link](https://www.samsung.com/semiconductor/minisite/ssd/download/tools/) | Samsung Portable SSD software. Samsung's notes say it does not work on Apple silicon Macs. |
| uniFLOW SmartClient | Ask your IT | Print client for an organisation's print system; it comes from that organisation's IT, not a public download. |
| AnyTrans, MobileTrans | Vendor download<br>[link (not verified)](https://www.imobie.com/anytrans/) | Paid phone-transfer tools (AnyTrans by iMobie; MobileTrans by Wondershare at wondershare.com). Download when needed. |

## Unsure

_Could not be identified or sourced; decide yourself._

| App | Where to get it | Notes |
| --- | --- | --- |
| TeslaTunes | Source unknown | No official download found by search. If you still use it, find the installer from where you originally got it. |
| Whiteboard, Task Manager TMOG | Source unknown | Could not identify these from their bundle ids (dev.fast.review, com.tmog.taskmanager); no download source found. |

## Setapp apps

These 32 apps are installed through Setapp on the audited Mac. Install Setapp (`brew install --cask setapp`), sign in, and add them from inside it. Installing them any other way (for example Homebrew) leaves Setapp unaware of the license.

- AlDente Pro
- Bartender
- BetterTouchTool
- Boom 3D
- CameraBag Pro
- Chronicle
- CleanMyMac
- DevUtils
- Disk Drill
- Filmage Editor
- Flinto
- Godspeed
- iBoysoft NTFS for Mac
- JoyTap
- Luminar
- Luminar Neo
- Marked
- Merlin Project Express
- MetaImage
- MonsterWriter
- NetSpot
- PhotosRevive
- Prizmo
- Proxyman
- Receipts
- Soulver
- Swift Publisher
- Taphouse
- Taskheat
- TouchRetouch
- Tripsy
- WiFi Explorer

## Casks Homebrew does have

Some entries above have a working cask under a different name. To install them with your presets, add:

```ruby
cask "adobe-creative-cloud"
cask "arduino-ide"
cask "imaging-edge"
cask "macdown-3000"
cask "microsoft-teams"
cask "sony-ps-remote-play"
```

