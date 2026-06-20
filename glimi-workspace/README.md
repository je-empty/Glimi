# Glimi Workspace

A role-based work team built on [**Glimi Core**](../glimi-core): give it a goal and a **Coordinator** delegates to a **Researcher**, **Builder**, and **Critic** who talk to each other and report back — with a live dashboard (connection graph, each member's memory, channels, usage) and a human-in-the-loop approval gate.

This app imports **only** the `glimi` package — zero Community code — which is the proof that Glimi Core is genuinely reusable: one kernel, two very different apps.

## Run

```bash
./run.sh                 # bootstraps the shared venv, then starts the server
# from the repo root:   ./run.sh workspace
```

One server hosts N workspaces; a read-only **Demo** is always live so the dashboard updates with zero setup, offline, $0.

## What's in here

- **`workspace/server.py`** — the multi-workspace server (parallel to Community's one-process → N-communities).
- **`workspace/run.py · team.py · demo.py · approval.py`** — the role team, the seeded demo, and the HITL approval gate.

## Depends on

[`glimi[dashboard]`](../glimi-core) only — no Community imports (enforced by `tests/unit/test_split_boundaries.py`).

---
AGPL-3.0-or-later · © 2026 Jaebin Sim
