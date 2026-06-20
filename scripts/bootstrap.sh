#!/usr/bin/env bash
# bootstrap.sh — thin alias. Prerequisite auto-install (Homebrew, Python, Node,
# Claude CLI on macOS) is now FOLDED INTO run.sh, so the canonical one-command
# setup needs no separate bootstrap step:
#
#     ./run.sh community      # Glimi Community  → http://localhost:8000
#     ./run.sh workspace --serve   # Glimi Workspace → http://127.0.0.1:8800
#
# This script just forwards to run.sh for back-compat (e.g. ./bootstrap.sh workspace).
cd "$(dirname "$0")"
exec ./run.sh "$@"
