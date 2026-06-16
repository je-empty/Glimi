#!/usr/bin/env bash
# bootstrap.sh — one-command setup for a *fresh* macOS machine.
#
# Installs any missing prerequisites (Xcode CLT, Homebrew, Python 3.12, Node,
# the Claude CLI) and then hands off to ./run.sh, which creates the venv, installs
# the Python deps, starts the platform, and opens your browser to the setup wizard.
#
# Already-installed tools are detected and skipped (idempotent — safe to re-run).
#
#   git clone https://github.com/jaebinsim/Glimi.git && cd Glimi && ./bootstrap.sh
#
# Linux: this script is macOS-focused; install python3.12 + node yourself, then
# run ./run.sh directly.
set -euo pipefail
cd "$(dirname "$0")"

CYAN='\033[36m'; GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; NC='\033[0m'
info() { echo -e "${CYAN}[bootstrap]${NC} $*"; }
ok()   { echo -e "${GREEN}[bootstrap]${NC} $*"; }
warn() { echo -e "${YELLOW}[bootstrap]${NC} $*"; }

if [ "$(uname)" != "Darwin" ]; then
  warn "Not macOS. Install python3.12 + node, then run ./run.sh directly."
  exec ./run.sh "$@"
fi

info "Glimi setup — will install ONLY what's missing, then launch + open your browser."
info "May install: Xcode Command Line Tools, Homebrew, Python 3.12, Node, the Claude CLI."
echo

# 1) Xcode Command Line Tools (git + compilers Homebrew needs).
if ! xcode-select -p >/dev/null 2>&1; then
  info "Installing Xcode Command Line Tools (a macOS dialog may pop up)…"
  xcode-select --install >/dev/null 2>&1 || true
  warn "If a dialog appeared, finish that install, then re-run ./bootstrap.sh."
  warn "(Waiting on the CLT install; re-run this script once it's done if it exits here.)"
  # Can't reliably block on the GUI installer; bail gracefully if not yet present.
  xcode-select -p >/dev/null 2>&1 || exit 0
fi

# 2) Homebrew.
if ! command -v brew >/dev/null 2>&1; then
  info "Installing Homebrew (it will ask for confirmation + your password)…"
  NONINTERACTIVE=1 /bin/bash -c \
    "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
# Make brew available in THIS shell (Apple Silicon → /opt/homebrew, Intel → /usr/local).
for _b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
  [ -x "$_b" ] && eval "$("$_b" shellenv)" && break
done
command -v brew >/dev/null 2>&1 || { echo -e "${RED}[bootstrap] Homebrew not on PATH after install. Open a new terminal and re-run ./bootstrap.sh${NC}"; exit 1; }

# 3) Python 3.12 (run.sh needs 3.11+; we standardize on 3.12).
if ! command -v python3.12 >/dev/null 2>&1; then
  info "Installing Python 3.12…"
  brew install python@3.12
fi

# 4) Node + the Claude CLI (cloud agent replies). Optional but recommended —
#    Glimi also runs fully local via Ollama, and examples run with no model at all.
if ! command -v node >/dev/null 2>&1; then
  info "Installing Node…"
  brew install node
fi
if ! command -v claude >/dev/null 2>&1; then
  info "Installing the Claude CLI (npm i -g @anthropic-ai/claude-code)…"
  npm install -g @anthropic-ai/claude-code \
    || warn "Claude CLI install failed — set ANTHROPIC_API_KEY in .env instead, or use --local-models."
fi

ok "Prerequisites ready."
info "Launching Glimi → your browser will open to the setup wizard."
echo
exec ./run.sh "$@"
