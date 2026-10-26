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
import json,yaml;i=json.load(open('$MAC_SETUP_DATA/inventory.json'));assert set(i['unmatched_apps'])=={'Weird Tool','Adobe Thing'},i['unmatched_apps']
c=yaml.safe_load(open('$PRESETS'))['presets']['current_system']['casks'];assert 'weird-tool' not in c and 'safari' not in c"
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
import yaml;p=yaml.safe_load(open('$PRESETS'))['presets']['photo'];assert p['casks']==['figma'] and p['mas'][0]['id']==1289583905"
check "hallucinated items dropped with a warning" grep -q "hallucinated-app" "$TMP/group.out"

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

echo "== launcher =="
check "setup.sh --help works" bash "$SCRIPTS/setup.sh" --help
check "setup.sh presets list routes to python" bash -c "bash '$SCRIPTS/setup.sh' presets list | grep -q current_system"
check "setup.sh refuses unknown command" bash -c "! bash '$SCRIPTS/setup.sh' nonsense"
check "setup.sh recommend with no extra args (empty-array handling)" bash "$SCRIPTS/setup.sh" recommend --preset developer --json

echo
echo "passed: $PASS  failed: $FAIL"
[ "$FAIL" -eq 0 ]
