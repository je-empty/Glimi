#!/usr/bin/env bash
# Glimi Workspace — standalone launcher. Bootstraps the shared monorepo venv
# (editable-installs glimi-core + the apps) and starts the Workspace server.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"; VENV="$ROOT/.venv"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q -e "$ROOT/glimi-core[dashboard]"
"$VENV/bin/pip" install -q -e "$ROOT/glimi-workspace"
exec "$VENV/bin/python" -m workspace.run --server "$@"
