#!/usr/bin/env bash
# Glimi Community — standalone launcher. Bootstraps the shared monorepo venv
# (editable-installs glimi-core + this app) and starts the Community platform.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; VENV="$ROOT/.venv"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q -e "$ROOT/glimi-core[dashboard]"
"$VENV/bin/pip" install -q -e "$ROOT/glimi-community"
export PYTHONPATH="$ROOT/glimi-core:$ROOT/glimi-community:$ROOT/glimi-workspace${PYTHONPATH:+:$PYTHONPATH}"
exec "$VENV/bin/python" -m community.platform "$@"
