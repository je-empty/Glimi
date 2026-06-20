#!/usr/bin/env bash
# Glimi Community — standalone launcher. Bootstraps the shared monorepo venv
# (editable-installs glimi-core + the apps) and starts the Community platform.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; VENV="$ROOT/.venv"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q -e "$ROOT/glimi-core[dashboard]"
"$VENV/bin/pip" install -q -e "$ROOT/glimi-community"
exec "$VENV/bin/python" -m community.platform "$@"
