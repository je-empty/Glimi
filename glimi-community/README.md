# Glimi Community

A cast of AI friends — each with its own persona, persistent memory, and relationships — who keep talking to you and to each other even when you're away. The flagship app on [**Glimi Core**](../glimi-core).

A built-in **web chat** (light/dark, replies, reactions, threads, mobile) is the live transport (`GLIMI_TRANSPORT=web`, no token). It plugs into a transport-neutral seam (`Outbox`/`ChannelAdapter`), so new transports (Telegram, etc.) drop into the same slot. Everything you watch — the relationship graph, each friend's 5-layer memory, the channels — is the Core dashboard, rendered for this app.

## Run

```bash
./run.sh                 # bootstraps the shared venv, then starts the platform
# from the repo root:   ./run.sh community
```

First run opens a setup wizard (pick a model backend: Claude / Ollama / local). Run it fully local and it costs nothing.

## What's in here

- **`community/platform/`** — the FastAPI platform, the built-in web chat, and the dashboard host.
- **`community/`** — scenes, achievements, the live web adapter (`adapters/web/channels.py`), the memory glue, and `adapters/kernel_store.py` (a `SqliteKernelStore(KernelStore)` that injects this app into the neutral kernel via DI).
- **`assets/`, `i18n/`** — profile images and localization.

## Depends on

[`glimi[dashboard]`](../glimi-core) — the kernel plus its dashboard web layer. In this monorepo that resolves to the local editable install; after launch, the published PyPI release.

---
AGPL-3.0-or-later · © 2026 Jaebin Sim
