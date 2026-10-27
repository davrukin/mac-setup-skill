#!/usr/bin/env bash
# mac-setup launcher: bootstraps Homebrew + a Python venv, then routes to the Python scripts.
#
#   setup.sh                    interactive menu
#   setup.sh bootstrap          install Homebrew (asks first) and the Python environment
#   setup.sh audit [args]       scan this Mac, write presets      (run on the OLD Mac)
#   setup.sh game [args]        sort apps into categories, swipe-style  (= audit --game)
#   setup.sh deploy [args]      preset -> Brewfile -> install     (run on the NEW Mac)
#   setup.sh recommend [args]   tiered suggestions for a preset
#   setup.sh presets <cmd>      list | show | import | export | delete
#   setup.sh verify [args]      check presets for conflicts, deprecated packages, duplicates; fix library placement
#   setup.sh manual [args]      write data/manual-installs.md: where to get apps Homebrew cannot install
#
# Flags: -y/--yes  skip confirmation prompts.   --with-ai  install litellm for LLM features.
#        --new-run  keep this run in its own folder, data/runs/YYYY-MM-DD_HHMMSS (fresh start, nothing reused).
#        --data-dir PATH  use PATH instead of data/ (reuse the same PATH later for deploy, presets, recommend).
# Env:   MAC_SETUP_SKIP_VENV=1  use the system python3 instead of creating .venv (tests, CI).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
VENV="$ROOT/.venv"
YES=0
WITH_AI=0

info() { printf '%s\n' "$*"; }
warn() { printf '⚠️  %s\n' "$*" >&2; }
die()  { printf '❌ %s\n' "$*" >&2; exit 1; }
trap 'printf "\n❌ Something failed (line %s). Nothing was left half-configured by this script.\n" "$LINENO" >&2' ERR

confirm() {
  [ "$YES" = 1 ] && return 0
  [ -t 0 ] || die "Needs confirmation but stdin is not a terminal. Re-run with --yes."
  read -r -p "$1 [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]]
}

require_mac() {
  [ "${MAC_SETUP_ALLOW_NON_MAC:-0}" = 1 ] && return 0
  [ "$(uname -s)" = "Darwin" ] || die "This tool inspects and configures macOS. Run it on a Mac."
}

load_brew_env() {
  for candidate in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    if [ -x "$candidate" ]; then eval "$("$candidate" shellenv)"; return 0; fi
  done
  return 1
}

ensure_brew() {
  if command -v brew >/dev/null 2>&1; then info "✅ Homebrew is ready."; return 0; fi
  if load_brew_env; then info "✅ Homebrew found and added to PATH for this run."; return 0; fi
  info "🍺 Homebrew is not installed."
  confirm "Download and run the official Homebrew installer from raw.githubusercontent.com/Homebrew/install?" || die "Homebrew is required for this step."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  load_brew_env || die "Homebrew installed but brew was not found in the usual locations."
  local line; line="eval \"\$($(command -v brew) shellenv)\""
  if ! grep -qsF "$line" "$HOME/.zprofile"; then
    printf '%s\n' "$line" >> "$HOME/.zprofile"
    info "📝 Added Homebrew to ~/.zprofile."
  fi
}

ensure_python() {
  if [ "${MAC_SETUP_SKIP_VENV:-0}" = 1 ]; then PY="python3"; return 0; fi
  command -v python3 >/dev/null 2>&1 || die "python3 not found. On a fresh Mac run: xcode-select --install"
  if [ ! -d "$VENV" ]; then info "🐍 Creating virtual environment at $VENV"; python3 -m venv "$VENV"; fi
  PY="$VENV/bin/python"
  "$PY" -m pip install --quiet pyyaml || die "Could not install pyyaml."
  if [ "$WITH_AI" = 1 ] || [ -n "${LLM_MODEL:-}" ]; then
    "$PY" -m pip install --quiet litellm || warn "Could not install litellm; AI features will be skipped."
  fi
}

run_py() { local script="$1"; shift; "$PY" "$SCRIPT_DIR/$script" "$@"; }

menu() {
  info "=== mac-setup ==="
  if [ -t 0 ] && [ -z "${LLM_MODEL:-}" ]; then
    info "Optional AI help (press Enter to skip). Use any LiteLLM model string, e.g. openai/<model>, gemini/<model>, ollama/<model>."
    read -r -p "Model string: " model || true
    if [ -n "${model:-}" ]; then
      export LLM_MODEL="$model"
      if [[ "$model" != ollama/* ]]; then read -r -s -p "API key (kept in memory for this run only): " key || true; echo; [ -n "${key:-}" ] && export LLM_API_KEY="$key"; fi
      ensure_python
    fi
  fi
  info ""
  info "1) Audit this Mac and generate presets   (run on the OLD Mac)"
  info "2) Pick a preset and deploy              (run on the NEW Mac)"
  info "3) Recommend more tools for a preset"
  info "4) List presets"
  read -r -p "Choose 1-4: " choice
  # macOS ships bash 3.2, where expanding an empty array under `set -u` is an error, so use ${arr[@]+...}.
  local ai_flag=(); [ -n "${LLM_MODEL:-}" ] && ai_flag=(--ai)
  case "$choice" in
    1) require_mac; run_py audit.py ${ai_flag[@]+"${ai_flag[@]}"} ;;
    2) require_mac; ensure_brew; run_py deploy.py ${ai_flag[@]+"${ai_flag[@]}"} ;;
    3) read -r -p "Preset name [current_system]: " p; run_py recommend.py --preset "${p:-current_system}" ${ai_flag[@]+"${ai_flag[@]}"} ;;
    4) run_py presets.py list ;;
    *) die "Invalid choice." ;;
  esac
}

# ---- argument handling -----------------------------------------------------
ARGS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    -y|--yes) YES=1; export MAC_SETUP_YES=1 ;;
    --with-ai) WITH_AI=1 ;;
    --new-run) export MAC_SETUP_DATA="${MAC_SETUP_DATA:-$ROOT/data}/runs/$(date +%Y-%m-%d_%H%M%S)" ;;
    --data-dir) [ "$#" -ge 2 ] || die "--data-dir needs a path."; export MAC_SETUP_DATA="$2"; shift ;;
    *) ARGS+=("$1") ;;
  esac
  shift
done
if [ -n "${MAC_SETUP_DATA:-}" ]; then
  mkdir -p "$MAC_SETUP_DATA"
  info "📁 Using data folder: $MAC_SETUP_DATA"
fi
CMD="${ARGS[0]:-menu}"
REST=(); [ "${#ARGS[@]}" -gt 1 ] && REST=("${ARGS[@]:1}")

case "$CMD" in
  bootstrap) require_mac; ensure_brew; ensure_python; info "✅ Ready. Next: setup.sh audit (old Mac) or setup.sh deploy (new Mac)." ;;
  audit)     require_mac; ensure_python; run_py audit.py ${REST[@]+"${REST[@]}"} ;;
  game)      require_mac; ensure_python; run_py audit.py --game ${REST[@]+"${REST[@]}"} ;;
  deploy)    require_mac; ensure_brew; ensure_python; run_py deploy.py ${REST[@]+"${REST[@]}"} ;;
  recommend) ensure_python; run_py recommend.py ${REST[@]+"${REST[@]}"} ;;
  verify)    ensure_python; run_py verify.py ${REST[@]+"${REST[@]}"} ;;
  manual)    ensure_python; run_py manual_apps.py ${REST[@]+"${REST[@]}"} ;;
  presets)   ensure_python; run_py presets.py ${REST[@]+"${REST[@]}"} ;;
  menu)      ensure_python; menu ;;
  -h|--help|help) sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' ;;
  *) die "Unknown command '$CMD'. Try: setup.sh --help" ;;
esac
