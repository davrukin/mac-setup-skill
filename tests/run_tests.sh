#!/usr/bin/env bash
# End-to-end tests against a fake `brew` and fake .app bundles. Safe to run anywhere.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
SCRIPTS="$ROOT/scripts"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

export PATH="$HERE/fakebin:$PATH"
export MAC_SETUP_DATA="$TMP/data"
export MAC_SETUP_APP_DIRS="$TMP/Apps"
export MAC_SETUP_SKIP_VENV=1
export MAC_SETUP_ALLOW_NON_MAC=1
unset LLM_MODEL LLM_API_KEY

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); echo "  ✓ $1"; }
bad()  { FAIL=$((FAIL+1)); echo "  ✗ $1"; }
check() { local desc="$1"; shift; if "$@" >/dev/null 2>&1; then ok "$desc"; else bad "$desc"; fi; }
py() { python3 -c "$@"; }

# ---- fake app bundles -------------------------------------------------------
python3 - "$TMP/Apps" <<'PY'
import plistlib, sys
from pathlib import Path
root = Path(sys.argv[1])
def app(rel, bundle_id, mas=False):
    p = root / rel
    (p / "Contents").mkdir(parents=True)
    (p / "Contents" / "Info.plist").write_bytes(plistlib.dumps({"CFBundleIdentifier": bundle_id}))
    if mas: (p / "Contents" / "_MASReceipt").mkdir()
app("Google Chrome.app", "com.google.Chrome")          # not brew-managed, but a cask exists -> adopted
app("Visual Studio Code.app", "com.microsoft.VSCode")  # already managed by brew cask
app("iTerm.app", "com.googlecode.iterm2")              # managed under a different token (iterm2)
app("Weird Tool.app", "com.example.weird")             # no cask -> unmatched
app("Adobe Thing/Adobe Thing.app", "com.example.adobe")  # nested folder, no cask -> unmatched
app("Claude.app", "com.anthropic.claudefordesktop")    # `claude` cask; must not be swallowed by installed claude-code
app("IntelliJ IDEA Community Edition.app", "com.jetbrains.intellij.ce")  # replaced by jetbrains-toolbox
app("darktable.app", "org.darktable")                   # cask is disabled -> unmatched, never adopted
app("zoom.us.app", "us.zoom.xos")                       # .pkg cask, matched via its uninstall stanza
app("Microsoft Word.app", "com.microsoft.Word")             # belongs to the installed microsoft-office suite
app("Safari.app", "com.apple.Safari")                  # Apple first-party -> skipped
app("Xcode.app", "com.apple.dt.Xcode", mas=True)
PY

PRESETS="$MAC_SETUP_DATA/presets.yaml"
echo "== audit =="
python3 "$SCRIPTS/audit.py" > "$TMP/audit.out"
check "presets.yaml written" test -f "$PRESETS"
check "inventory.json written" test -f "$MAC_SETUP_DATA/inventory.json"
check "current_system has adopted google-chrome" py "
import yaml;p=yaml.safe_load(open('$PRESETS'))['presets']['current_system'];assert 'google-chrome' in p['casks']"
check "no duplicate cask for managed apps (iterm, vscode)" py "
import yaml;c=yaml.safe_load(open('$PRESETS'))['presets']['current_system']['casks'];assert sorted(c)==sorted(set(c));assert 'iterm' not in c and 'visual-studio-code' in c and c.count('iterm2')==1"
check "unmatched apps reported, not guessed into casks" py "
import json,yaml;i=json.load(open('$MAC_SETUP_DATA/inventory.json'));assert set(i['unmatched_apps'])=={'Weird Tool','Adobe Thing','darktable'},i['unmatched_apps']
c=yaml.safe_load(open('$PRESETS'))['presets']['current_system']['casks'];assert 'weird-tool' not in c and 'safari' not in c"
check "apps are matched through Homebrew metadata, not name guessing" py "
import json;i=json.load(open('$MAC_SETUP_DATA/inventory.json'));c=i['casks'];assert 'claude' in c and 'claude-code' in c and 'zoom' in c,c;assert 'darktable' not in c"
check "JetBrains apps are replaced by jetbrains-toolbox" py "
import json;i=json.load(open('$MAC_SETUP_DATA/inventory.json'));assert 'jetbrains-toolbox' in i['casks'] and 'intellij-idea-ce' not in i['casks'];assert i['consolidated']=={'jetbrains-toolbox':['IntelliJ IDEA Community Edition']},i['consolidated']"
check "shared common preset (claude, figma) is merged into every role preset" py "
import yaml;P=yaml.safe_load(open('$PRESETS'))['presets']
for n in ('developer','creative','common'): assert {'claude','figma'}<=set(P[n]['casks']),n"
check "an app of an installed conflicting suite is not adopted as its own cask" py "
import json;i=json.load(open('$MAC_SETUP_DATA/inventory.json'));assert 'microsoft-office' in i['casks'] and 'microsoft-word' not in i['casks'],i['casks'];assert 'Microsoft Word' not in i['unmatched_apps']"
check "Apple apps skipped, MAS app comes from mas list" py "
import json;i=json.load(open('$MAC_SETUP_DATA/inventory.json'));assert i['apple_apps_skipped']>=1;assert {m['id'] for m in i['mas']}=={497799835,1289583905}"
check "developer preset has editor, terminal, extension, tap" py "
import yaml;d=yaml.safe_load(open('$PRESETS'))['presets']['developer'];assert {'visual-studio-code','iterm2'}<=set(d['casks']);assert 'ms-python.python' in d['vscode'];assert 'git' in d['brews']"
check "creative preset has figma and exiftool" py "
import yaml;d=yaml.safe_load(open('$PRESETS'))['presets']['creative'];assert 'figma' in d['casks'] and 'exiftool' in d['brews']"
check "tap derived for tap-qualified formula" py "
import yaml;p=yaml.safe_load(open('$PRESETS'))['presets']['current_system'];assert 'someone/tools' in p['taps']"

echo "== assistant-supplied grouping =="
cat > "$TMP/group.json" <<'JSON'
{"photo": {"description": "Photo workflow", "casks": ["figma", "hallucinated-app"], "brews": ["exiftool"], "mas": ["Pixelmator Pro", 999]}}
JSON
python3 "$SCRIPTS/audit.py" --categorization "$TMP/group.json" > "$TMP/group.out"
check "custom group created" py "
import yaml;p=yaml.safe_load(open('$PRESETS'))['presets']['photo'];assert 'figma' in p['casks'] and 'hallucinated-app' not in p['casks'] and p['mas'][0]['id']==1289583905"
check "shared common set is added to assistant-made groups too" py "
import yaml;P=yaml.safe_load(open('$PRESETS'))['presets'];assert {'claude','figma'}<=set(P['photo']['casks']);assert 'common' in P"
check "hallucinated items dropped with a warning" grep -q "hallucinated-app" "$TMP/group.out"

echo "== sorting game =="
export MAC_SETUP_GAME_KEYS="enter,enter,enter,enter,enter,right,enter,left,u,2,q"
python3 "$SCRIPTS/audit.py" --game > "$TMP/game.out"
unset MAC_SETUP_GAME_KEYS
check "game saves choices to game_choices.json" py "
import json;c=json.load(open('$MAC_SETUP_DATA/game_choices.json'))['choices'];assert c['casks:google-chrome']=='skip' and c['casks:iterm2']=='developer' and c['casks:visual-studio-code']=='common',c"
check "game picks become presets; undo replaced the skip" py "
import yaml;P=yaml.safe_load(open('$PRESETS'))['presets']
assert {'iterm2','jetbrains-toolbox'}<=set(P['developer']['casks']) and 'google-chrome' not in P['developer']['casks']
assert {'claude','figma','visual-studio-code'}<=set(P['common']['casks']),P['common']
assert 'creative' not in P and 'google-chrome' in P['current_system']['casks']"
check "common picks are merged into the developer preset" py "
import yaml;P=yaml.safe_load(open('$PRESETS'))['presets'];assert {'claude','visual-studio-code'}<=set(P['developer']['casks'])"
MAC_SETUP_GAME_KEYS="q" python3 "$SCRIPTS/audit.py" --game > "$TMP/game2.out"
check "second run resumes from saved choices" bash -c "grep -q 'Resuming' '$TMP/game2.out' && python3 -c \"import yaml;P=yaml.safe_load(open('$PRESETS'))['presets'];assert 'iterm2' in P['developer']['casks']\""
check "game refuses to run without a terminal" bash -c "! python3 '$SCRIPTS/audit.py' --game < /dev/null >/dev/null 2>&1"

echo "== game: descriptions and dependencies =="
check "descriptions and dependents come from Homebrew" py "
import sys,json;sys.path.insert(0,'$SCRIPTS');import game
inv={'casks':['iterm2'],'brews':['git','jq','wget'],'mas':[],'vscode':[]}
meta,_=game.load_meta(inv)
assert meta['casks:iterm2']['desc'].startswith('Terminal emulator')
assert meta['brews:jq']['needed_by']==['git'] and meta['brews:git']['desc'].startswith('Distributed')
items={i.name:i for i in game.build_items(inv)}
assert game.dependency_only(items['jq'],meta) and not game.dependency_only(items['git'],meta) and not game.dependency_only(items['wget'],meta)
text=game.describe(items['jq'],meta['brews:jq']); assert 'git' in text and 'dependency' in text"
check "dependency-only tools are hidden unless asked for" bash -c "grep -q 'hidden because Homebrew only installed them as dependencies' '$TMP/game.out'"

echo "== game: new category and hotkey =="
MAC_SETUP_DATA="$TMP/game2" MAC_SETUP_GAME_KEYS="n,creative,r,d,r,n,odd,c,q" python3 "$SCRIPTS/audit.py" --game > "$TMP/game3.out"
check "new category gets a hotkey, takes the current item, hotkeys d and r sort items" py "
import json;s=json.load(open('$TMP/game2/game_choices.json'));c=s['choices']
assert c['casks:claude']=='creative' and c['casks:claude-code']=='developer' and c['casks:figma']=='creative',c"
check "clashing hotkey is refused but the category is still created" py "
import json;s=json.load(open('$TMP/game2/game_choices.json'));assert s['categories']['creative']=='r' and s['categories']['odd']=='' and s['categories']['common']=='c',s['categories'];assert s['choices']['casks:google-chrome']=='odd'"
check "new category becomes a preset" py "
import yaml;P=yaml.safe_load(open('$TMP/game2/presets.yaml'))['presets'];assert {'claude','figma'}<=set(P['creative']['casks']) and 'odd' in P"
MAC_SETUP_DATA="$TMP/game2" MAC_SETUP_GAME_KEYS="q" python3 "$SCRIPTS/audit.py" --game > "$TMP/game4.out"
check "categories made in-game are remembered on the next run" py "
import json;s=json.load(open('$TMP/game2/game_choices.json'));assert s['categories']['creative']=='r'"

echo "== manual installs document =="
cat > "$TMP/manual.json" <<'JSON'
{"generated": "2026-10-26", "classified_by": "test", "entries": [
 {"apps": ["Weird Tool"], "category": "developer", "source": "vendor", "url": "https://example.com/weird", "verified": true, "note": "n"},
 {"apps": ["Ghost App"], "category": "not_needed", "source": "discontinued"}]}
JSON
python3 "$SCRIPTS/manual_apps.py" --input "$TMP/manual.json" --output "$TMP/manual.md" > "$TMP/manual.out"
check "document lists classified apps with links" bash -c "grep -q 'Weird Tool' '$TMP/manual.md' && grep -q '(https://example.com/weird)' '$TMP/manual.md'"
check "unclassified inventory apps are flagged" bash -c "grep -q 'Not classified yet' '$TMP/manual.md' && grep -q 'Adobe Thing' '$TMP/manual.md' && grep -q 'not classified yet' '$TMP/manual.out'"
check "stale entries are reported" grep -q "Ghost App" "$TMP/manual.out"

echo "== missing Homebrew cask list =="
check "audit stops with a fix when brew's cask list is empty" bash -c "FAKE_BREW_NO_CASKS=1 MAC_SETUP_DATA='$TMP/nocasks' python3 '$SCRIPTS/audit.py' 2>&1 | grep -q 'brew update'; [ \${PIPESTATUS[0]} -ne 0 ]"
mkdir -p "$TMP/state" && touch "$TMP/state/needs_update"
check "without confirmation the audit does not run brew update" bash -c "FAKE_BREW_STATE='$TMP/state' MAC_SETUP_DATA='$TMP/repair' python3 '$SCRIPTS/audit.py' < /dev/null >/dev/null 2>&1; [ \$? -ne 0 ] && [ -e '$TMP/state/needs_update' ]"
check "with --yes the audit runs brew update, rechecks and continues" bash -c "FAKE_BREW_STATE='$TMP/state' MAC_SETUP_YES=1 MAC_SETUP_DATA='$TMP/repair' python3 '$SCRIPTS/audit.py' | grep -q 'now lists' && [ ! -e '$TMP/state/needs_update' ] && test -f '$TMP/repair/presets.yaml'"
check "--allow-incomplete continues anyway" bash -c "FAKE_BREW_NO_CASKS=1 MAC_SETUP_DATA='$TMP/nocasks' python3 '$SCRIPTS/audit.py' --allow-incomplete >/dev/null"

echo "== presets import / list / export =="
cat > "$TMP/community.Brewfile" <<'BF'
# someone else's Brewfile
tap "homebrew/bundle"
brew "bat"
cask "raycast"
mas "Things 3", id: 904280696
if OS.mac? then brew "ruby-logic" end
BF
python3 "$SCRIPTS/presets.py" import "$TMP/community.Brewfile" --name community > "$TMP/import.out"
check "imported preset listed" bash -c "python3 '$SCRIPTS/presets.py' list | grep -q community"
check "Ruby logic line ignored, not executed" grep -q "Ignored 1" "$TMP/import.out"
check "re-import without --force refuses" bash -c "! python3 '$SCRIPTS/presets.py' import '$TMP/community.Brewfile' --name community"
check "audit keeps imported presets" bash -c "python3 '$SCRIPTS/audit.py' >/dev/null && python3 '$SCRIPTS/presets.py' list | grep -q community"
check "export renders Brewfile syntax" bash -c "python3 '$SCRIPTS/presets.py' export community | grep -q 'mas \"Things 3\", id: 904280696'"

echo "== recommend =="
cat > "$TMP/list.md" <<'MD'
Install these: `brew install ripgrep fd` and `brew install --cask raycast rectangle`
cask "totally-fake-app"
brew "eza"
MD
python3 "$SCRIPTS/recommend.py" --preset developer --source "$TMP/list.md" --json > "$TMP/recs.json"
check "already-installed tools are not recommended" py "
import json;r=json.load(open('$TMP/recs.json'));names={t['name'] for k in r if k.startswith('tier') for t in r[k]};assert 'git' not in names and 'jq' not in names"
check "names Homebrew does not list are dropped" py "
import json;r=json.load(open('$TMP/recs.json'));names={t['name'] for k in r if k.startswith('tier') for t in r[k]};assert 'totally-fake-app' not in names;assert any('totally-fake-app' in d for d in r['_dropped_unverified'])"
check "source-found tools appear with correct types" py "
import json;r=json.load(open('$TMP/recs.json'));allr=[t for k in r if k.startswith('tier') for t in r[k]];d={t['name']:t['type'] for t in allr};assert d['ripgrep']=='brew' and d['rectangle']=='cask' and d['eza']=='brew'"
check "three tier buckets present" py "
import json;r=json.load(open('$TMP/recs.json'));assert all(k in r for k in ('tier_1_very_useful','tier_2_nice_to_have','tier_3_could_be_useful'))"
cat > "$MAC_SETUP_DATA/web_recommendations.json" <<'JSON'
{"generated": "2026-10-26", "items": [{"name": "bat", "type": "brew", "tier": 1, "reason": "from research", "sources": ["https://a.example", "https://b.example", "https://c.example"]}]}
JSON
python3 "$SCRIPTS/recommend.py" --preset developer --no-seed --json > "$TMP/recs2.json"
check "assistant web research file is used and tiered" py "
import json;r=json.load(open('$TMP/recs2.json'));assert [t['name'] for t in r['tier_1_very_useful']]==['bat']"
rm "$MAC_SETUP_DATA/web_recommendations.json"

echo "== deploy =="
python3 "$SCRIPTS/deploy.py" --preset developer --exclude iterm2,git --include-recs 1 --dry-run > "$TMP/dry.out"
check "dry run prints Brewfile without writing one" bash -c "grep -q 'brew \"jq\"' '$TMP/dry.out' && [ ! -e '$MAC_SETUP_DATA/brewfiles/developer.Brewfile' ]"
check "excluded items are left out of the Brewfile and not re-recommended" bash -c "! grep -qE '^(cask|brew) \"(iterm2|git)\"' '$TMP/dry.out' && ! grep -qE '^ • (iterm2|git) ' '$TMP/dry.out'"
check "tier-1 recommendations added" grep -q 'brew "ripgrep"' "$TMP/dry.out"
check "install command is printed" grep -q "brew bundle install --file=" "$TMP/dry.out"
python3 "$SCRIPTS/deploy.py" --preset developer --no-recs --run > "$TMP/run.out"
check "Brewfile written to data/brewfiles" test -f "$MAC_SETUP_DATA/brewfiles/developer.Brewfile"
check "brew bundle install invoked" grep -q "fake brew: bundle install" "$TMP/run.out"
check "non-interactive run without --preset fails clearly" bash -c "! python3 '$SCRIPTS/deploy.py' < /dev/null 2>'$TMP/err.out' && grep -q -- '--preset' '$TMP/err.out'"

echo "== verification =="
check "conflicts, disabled, deprecated, duplicates and overlaps are found" py "
import sys;sys.path.insert(0,'$SCRIPTS');import verify
P={'p':{'casks':['a','b','gone'],'brews':['youtube-dl','yt-dlp','old'],'mas':[{'name':'Pages','id':1},{'name':'Pages','id':2}]}}
cask={'a':{'token':'a','conflicts_with':{'cask':['b']}},'b':{'token':'b'},'gone':{'token':'gone','disabled':True,'disable_reason':'discontinued'}}
form={'old':{'name':'old','deprecated':True,'deprecation_reason':'unsupported'}}
f=verify.check_presets(P,cask,form)
kinds={(x['kind'],tuple(x['items'])) for x in f}
assert ('conflict',('a','b')) in kinds and ('disabled',('gone',)) in kinds and ('deprecated',('old',)) in kinds
assert ('duplicate-app',('mas:1','mas:2')) in kinds and ('overlap',('youtube-dl','yt-dlp')) in kinds,kinds
assert [x['severity'] for x in f][:2]==['error','error']
fix=next(x for x in f if x['kind']=='overlap')['fix']; assert fix['keys']==['brews:youtube-dl']"
check "items in not_needed are not reported" py "
import sys;sys.path.insert(0,'$SCRIPTS');import verify
P={'p':{'casks':['gone']},'not_needed':{'casks':['gone']}}
assert verify.check_presets(P,{'gone':{'token':'gone','disabled':True}},{})==[]"
check "libraries move next to the tools that need them" py "
import sys;sys.path.insert(0,'$SCRIPTS');import verify
inv={'brews':['glib','pango','poppler','lib2']}
deps={'glib':{'brews:pango','brews:poppler'},'pango':{'brews:poppler'},'lib2':{'brews:pango'}}
ch={'brews:glib':'developer','brews:pango':'developer','brews:poppler':'common','brews:lib2':'photography'}
m={x['key']:x['to'] for x in verify.plan_library_moves(ch,inv,deps)}
assert m=={'brews:glib':'common','brews:pango':'common','brews:lib2':'common'},m"
check "library rule ignores excluded dependents and never moves out of common" py "
import sys;sys.path.insert(0,'$SCRIPTS');import verify
inv={'brews':['lib','lib3']};deps={'lib':{'brews:x'},'lib3':{'brews:y'}}
assert verify.plan_library_moves({'brews:lib':'developer','brews:x':'not_needed'},inv,deps)==[]
assert verify.plan_library_moves({'brews:lib3':'common','brews:y':'developer'},inv,deps)==[]"
mkdir -p "$TMP/vfy" && cat > "$TMP/vfy/presets.yaml" <<'YAML'
presets:
  office:
    casks: [microsoft-office, microsoft-word]
YAML
MAC_SETUP_DATA="$TMP/vfy" python3 "$SCRIPTS/deploy.py" --preset office --no-recs --dry-run > "$TMP/vfy.out"
check "deploy reports conflicts it finds with Homebrew" grep -q "conflicts with" "$TMP/vfy.out"
check "deploy refuses to install while conflicts remain" bash -c "! MAC_SETUP_DATA='$TMP/vfy' python3 '$SCRIPTS/deploy.py' --preset office --no-recs --run >/dev/null 2>&1"
check "--ignore-problems overrides the refusal" bash -c "MAC_SETUP_DATA='$TMP/vfy' python3 '$SCRIPTS/deploy.py' --preset office --no-recs --run --ignore-problems >/dev/null 2>&1"

echo "== not_needed is an exclusion =="
check "common is not merged into the not_needed preset" py "
import sys;sys.path.insert(0,'$SCRIPTS');import categorize,common
inv={'casks':['claude','foo'],'brews':[],'mas':[],'vscode':[]}
g={'not_needed':{'casks':['foo']},'developer':{'casks':[]}}
categorize.apply_shared(g,inv)
assert g['not_needed']['casks']==['foo'] and 'claude' in g['developer']['casks'] and 'claude' in g['common']['casks'],g"
mkdir -p "$TMP/excl" && cat > "$TMP/excl/presets.yaml" <<'YAML'
presets:
  work:
    brews: [jq, bat]
    casks: [raycast]
    mas: [{name: Things 3, id: 904280696}]
  not_needed:
    brews: [bat]
    mas: [{name: Things 3, id: 904280696}]
YAML
MAC_SETUP_DATA="$TMP/excl" python3 "$SCRIPTS/deploy.py" --preset work --no-recs --dry-run > "$TMP/excl.out"
check "items in not_needed are left out of every other preset" bash -c "grep -q 'brew \"jq\"' '$TMP/excl.out' && ! grep -q 'brew \"bat\"' '$TMP/excl.out' && ! sed -n '/^# Generated/,\$p' '$TMP/excl.out' | grep -q 'Things 3' && grep -q 'cask \"raycast\"' '$TMP/excl.out'"

check "excluding an App Store app removes that id, not its same-named twin" py "
import sys;sys.path.insert(0,'$SCRIPTS');import common,deploy
P={'a':{'mas':[{'name':'Pages','id':1},{'name':'Pages','id':2}]},'not_needed':{'mas':[{'name':'Pages','id':1}]}}
out,_=deploy.apply_excludes(P['a'],common.exclusion_names(P));assert [m['id'] for m in out['mas']]==[2],out"

echo "== launcher =="
check "--new-run audits into its own dated folder" bash -c "bash '$SCRIPTS/setup.sh' --new-run audit >/dev/null && ls -d '$MAC_SETUP_DATA'/runs/????-??-??_?????? | head -1 | xargs -I{} test -f {}/presets.yaml"
check "--data-dir uses the given folder" bash -c "bash '$SCRIPTS/setup.sh' --data-dir '$TMP/custom' audit >/dev/null && test -f '$TMP/custom/inventory.json'"
check "setup.sh --help works" bash "$SCRIPTS/setup.sh" --help
check "setup.sh presets list routes to python" bash -c "bash '$SCRIPTS/setup.sh' presets list | grep -q current_system"
check "setup.sh refuses unknown command" bash -c "! bash '$SCRIPTS/setup.sh' nonsense"
check "setup.sh recommend with no extra args (empty-array handling)" bash "$SCRIPTS/setup.sh" recommend --preset developer --json

echo
echo "passed: $PASS  failed: $FAIL"
[ "$FAIL" -eq 0 ]
