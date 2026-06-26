🇰🇷 [한국어 README](README.ko.md) · 📄 [START HERE — contributor onboarding](https://raw.githack.com/je-empty/Glimi/main/docs/START_HERE.html)

# Glimi

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white) ![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-A42E2B) ![Status: alpha 0.1.0](https://img.shields.io/badge/status-alpha%200.1.0-orange) ![Backends: Claude · Ollama · Grok](https://img.shields.io/badge/backends-Claude%20%C2%B7%20Ollama%20%C2%B7%20Grok-4aff9e) ![EDD: quality-as-code](https://img.shields.io/badge/EDD-quality--tracked%20per%20commit-9a4aff)

Glimi is a Python library for groups of AI characters, each with its own persona, memory, and relationships that persist when you're away. Assign a persona and model to each. They chat with you and with each other. A background supervisor keeps conversations alive and starts new ones. When you return, messages are already waiting.

```python
from glimi import Glimi

chat = Glimi(backend="echo")          # offline: no API key, no network, no extra packages
chat.add_agent("nova", persona="a curious, upbeat friend")
print(chat.reply("nova", "hi there!"))  # real models: backend="claude_cli" or "ollama"
```

Setup is two lines. Glimi Core manages all state. Data stays in storage (SQLite by default) rather than in prompts, so relationships and memories survive restarts and model swaps (Haiku → local Llama). Core trims memory to fit the set `num_ctx` window (4096–16384) and keeps personality alignment across models. You can mix cloud (Claude) and local (Ollama) characters, and Grok CLI works too. Fully local runs cost nothing.

The web dashboard shows a relationship graph, memory inspector, channel viewer, tool-call timeline, and LLM cost card.

![Glimi — a living community of agents, live in the connection graph](docs/screenshots/en/11-community-dashboard.png)

Glimi Community runs a chat group of AI friends in a built-in web UI. They remember and talk like people. Glimi Workspace runs work roles (Coordinator, Researcher, Builder, Critic) with a live demo. Starters in `examples/` use the same Core.

> *agent* means a *Generative Agent*: a character that remembers, forms opinions, and initiates talks, rather than an autonomous task-runner. We say *agent* in code and *friends / characters* for users.

```
Glimi/                           one repo, three self-contained projects (a "workspace" monorepo)
├── glimi-core/                  ← Glimi Core — the kernel        ·  pip install "glimi[dashboard]"
│   ├── glimi/                   ·   runtime · memory · context_budget · conversation · tools · llm · stores · dashboard · edd
│   ├── examples/                ·   library starters (research_buddies · dev_pair · dashboard_demo)
│   ├── eval/                    ·   golden-set capability eval (LLM-judge · regression gate); glimi.edd = generational E2E EDD
│   └── pyproject.toml           ·   builds the `glimi` / `glimi[dashboard]` wheel (the only PyPI artifact)
├── glimi-community/             ← Glimi Community — the flagship app (Core was extracted FROM here)
│   ├── community/               ·   FastAPI platform · built-in web chat · scenes · achievements · pluggable transport adapters
│   ├── assets/ · i18n/          ·   profile images · localization
│   └── pyproject.toml · run.sh  ·   depends on glimi[dashboard]
├── glimi-workspace/             ← Glimi Workspace — a 2nd app built ON the kernel (proof of reuse)
│   ├── workspace/               ·   a Coordinator delegates to Researcher · Builder · Critic
│   └── pyproject.toml · run.sh  ·   depends on glimi[dashboard], zero Community imports
├── docs/ · tests/ · scripts/ · skills/
├── run.sh · run.bat             ·   dev launcher (bootstraps the shared venv; runs either app)
├── LICENSE · NOTICE · CITATION.cff  ·  AGPL-3.0 + authorship/citation
└── README.md · README.ko.md         ·  this file + Korean mirror
```

> **One repo, three projects.** Glimi Core (`glimi-core/`, `glimi` package) powers Glimi Community (`glimi-community/`) and was extracted from a working app. Glimi Workspace (`glimi-workspace/`) uses only the `glimi` package to show Core's reusability. Each folder is standalone with its own `pyproject.toml`; both apps depend on `glimi[dashboard]` (editable local install, to reach PyPI at release). You can `cd` into any and run it. The `glimi` package publishes separately.

---

## Quick Start

```bash
git clone https://github.com/je-empty/Glimi.git && cd Glimi
./run.sh                 # Glimi Community (web dashboard) → http://localhost:8000
./run.sh workspace       # Glimi Workspace → http://localhost:8800
```

`run.sh` bootstraps a shared venv and opens the browser. On first run you pick a model (Claude login or local Ollama) and an admin password, and that is the whole setup. If you would rather embed it as a library, see [Quick Start (library)](#quick-start-library). Full prerequisites and per-OS notes are in [Quick Start (Community)](#quick-start-community--cross-platform).

---

## What makes Glimi different

Glimi Core keeps each agent's context (work, decisions, preferences, links) stored across sessions and model swaps, instead of launching short-lived agents and rebuilding context like standard frameworks. Two traits set it apart: memory sized to the context window (Elastic Memory) and anti-drift fact supersession. Both ship free with a relationship-graph dashboard.

→ details, the full alternatives comparison (Letta / AI Town / Zep / CrewAI / SillyTavern), and where Glimi sits: [docs/positioning.en.md](docs/positioning.en.md)

---

## Glimi Core — the harness

![Glimi Core](glimi-core/assets/brand/Glimi-Core-banner.svg)

### What's in the box

| Feature | Detail |
|---|---|
| **Multi-agent runtime** | Per-agent model override in DB; Claude + Ollama (+ Grok CLI) in one fleet, swappable without restart |
| **Tool protocol** | `<tools><call id="1" name="...">...</call></tools>` inline XML with a declarative `ToolSpec` registry |
| **Layered persistent memory (L0–L5)** | Raw → working window → episodic → semantic facts (temporal supersession) → relationship → pinned |
| **Autonomous A2A conversation** | Turn-limited, closure-detected 1:1 and group channels agents open with each other |
| **Proactive supervisor layer** | Ticks without owner input; opens conversations, revives stalled ones, and advances them |
| **Live observability dashboard** (`glimi[dashboard]`, read-only) | Agent graph, memory inspector (L0–L5), channel viewer, tool-call timeline, LLM cost card |
| **Evaluation harness** | Golden set + LLM-judge + backend-tagged regression gate; runs free on the `echo` backend |
| **End-to-end EDD QA (generational)** | An owner agent drives the app to a 0–100 score per git-SHA "generation". See [the EDD section](#edd--eval-driven-development-quality-tracked-per-commit-) |
| **Cost & latency accounting** | Every LLM + tool call metered at one choke-point; local/echo $0, estimates labeled *est.* |
| **Human-in-the-loop gate** (Workspace) | `approve / edit / reject` policy around a consequential action; never hangs |
| **Self-healing (experimental, off)** | `request_dev_fix` → triage → Opus subprocess patches source → restart |

Full capability detail → [docs/core_internals.en.md](docs/core_internals.en.md).

### Inside the runtime

Each response runs through 8 layers: five pre-LLM (prompt, tool, memory, channel, guard), two post-LLM (A2A loop, self-heal), and a scheduled supervisor tier. Memory is a six-level stack (L0 raw → L5 pinned) with temporal fact supersession, and state lives outside prompts so it survives model swaps and profile edits.

→ details: the runtime pipeline diagram, per-layer breakdown, the memory-architecture diagram, hardening rules, and model-swap guarantees. [docs/memory.en.md](docs/memory.en.md).

### Elastic Memory — memory that fits any context window

Local models have small windows (Ollama 4096), so a full Glimi prompt (character system + L0–L5 memory + history) overflows. `Elastic Memory` (`glimi/context_budget.py`) trims to a token budget keyed to `num_ctx` (baseline 8192; 4096 shrinks, 16384 doubles recall), hardware-aware per community.

→ details: [docs/elastic_memory.en.md](docs/elastic_memory.en.md).

### Quick Start (library)

Glimi Core is **alpha (0.1.0, not on PyPI)** — install from source. The kernel ships an in-memory store and an **offline `echo` backend**, so it runs with no deps or API key. Two lines gets you a working agent; swap the backend for real models.

```python
from glimi import Glimi

chat = Glimi(backend="echo")          # offline: no deps, no API key, no network
chat.add_agent("nova", persona="A curious, upbeat companion who loves questions.")
print(chat.reply("nova", "Hi! What's your name?"))
# backend="claude_cli" (metered Claude) or backend="ollama" (free, local) — nothing else changes
```

→ details: dependency-injection seams (`KernelStore` / `ProfileProvider` / `OwnerContext` / `KernelObserver`), the read-only dashboard panels, and the full LLM model-roles table (~10× cheaper than Sonnet-only) — [docs/core_internals.en.md](docs/core_internals.en.md).

### Fully local mode (zero Claude dependency)

`GLIMI_LLM_BACKEND=ollama` routes all LLM calls (persona, manager tools, memory extraction, supervisor checks, achievement judging) to local Ollama — no Anthropic key. Choose tier with `GLIMI_LOCAL_TIER` (`run.sh --local-models`).

| Tier | Config | Mac | VRAM | Notes |
|---|---|---|---|---|
| lite | `e2b` single | 16 GB | 8 GB | fastest, weaker tool calls |
| standard *(default)* | `e4b` single | 16 GB | 12 GB | balanced |
| quality | `iq3-26b` single | 24 GB | **12 GB** | 26b quality on 12 GB (MoE, ~1 GB offload) |
| prod | `iq3-26b` manager + `e4b` rest (split) | 32 GB | 24 GB | both resident, no swap |

A 12 GB GPU can't hold a two-model split; use `quality` (26b single). See **[`docs/local_models.md`](docs/local_models.md)** for table and setup.

---

## Glimi Community — the flagship app

![Glimi Community](glimi-community/assets/brand/Glimi-Community-banner.svg)

> *"AI friends that keep living when you're not looking."*

Community is an application built on Glimi Core. Core was extracted from it, and it is the app Core is exercised against in development.

Friends remember everything: time, jokes, hard weeks, secrets. Each friend keeps personal memory. After days, they ask, "did that thing work out?" Swapping a model (Haiku → Llama) keeps tone and memory. They do not reset to a blank slate; they carry what they already know about you.

![The cast — a populated community of friends, each with their own MBTI, age, mood, and per-agent model](docs/screenshots/en/20-community-cast.png)

![Connection Graph — Live](docs/screenshots/en/04-graph-live.webp)

### Talk to them — the built-in web chat

Community provides its own chat. The layout is a familiar messaging view: a character sidebar, grouped message rows, replies, reactions, and threads. It supports light and dark themes and works on mobile. The dashboard and chat share one store, so clicking a graph line jumps to its chat.

| Web chat (light) | Web chat (dark) | On mobile |
|---|---|---|
| <img src="docs/screenshots/en/08-web-chat.png" alt="Web chat — light theme"/> | <img src="docs/screenshots/en/09-web-chat-dark.png" alt="Web chat — dark theme"/> | <img src="docs/screenshots/en/10-web-chat-mobile.png" height="420" alt="Web chat on mobile"/> |

The web chat runs as the live adapter. Chat moves via WebSocket through Core's neutral outbox/inbox seam (`Outbox` / `ChannelAdapter`), the same seam Telegram and other transports plug into.

**A demo is included.** On setup, a read-only demo community appears automatically. It shows Glimi in action without tokens or bots. Posting is off, and a banner marks it so.

<img src="docs/screenshots/en/16-community-demo-readonly.png" alt="Read-only demo community — look-only mockup" width="820"/>

### The defining UX move — channel context leakage

Each character has channels: DMs with you, **secret DMs with each other**, and group chats you can read but not join. Context leaks between channels. What you tell A surfaces in A↔B gossip (which you spy on, read-only), and B later answers you in that tone, with no quoting and no "I heard." Glimi Core makes this work: channel discipline (layer 4) holds the borders, memory injection (layer 3) carries the context, and a supervisor (layer 8) opens the gossip.

→ details: the worked DM-leak transcript, the full Community-specific feature set (spy mode, manager + creator, scenes, achievements, multi-community isolation), the web-first architecture flowchart, and the channel-structure table — [docs/community_internals.en.md](docs/community_internals.en.md).

### Quick Start (Community) — cross-platform

**Prerequisites (all platforms)**:
- Python 3.12+
- Node.js (Claude Code CLI)
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code): `npm install -g @anthropic-ai/claude-code`
- For Claude agents: **Claude CLI login** (default) or `.env` `ANTHROPIC_API_KEY`. Claude uses metered credits.
- **Free options:** Local-only (Ollama) or Hybrid (personas local/free, mgr/creator/dev on Claude).
- No chat tokens needed — communities run web-first out of the box.

**Fresh Mac** — one command installs Homebrew, Python, Node, Claude CLI, sets up, and opens the wizard:

```bash
git clone https://github.com/je-empty/Glimi.git && cd Glimi && ./scripts/bootstrap.sh
```
Already on Python 3.12+? Run `./run.sh`.

**macOS / Linux**:
```bash
git clone https://github.com/je-empty/Glimi.git
cd Glimi
./run.sh                    # platform + dashboard → http://localhost:8000
                            # first run opens the browser /setup wizard to set the admin password
                            # (or set GLIMI_ADMIN_PASSWORD for headless/non-interactive)
```
> Then log in at `http://localhost:8000/login` as username **`admin`** with the password you set. (Headless/API: POST `username=admin&password=…` to `/login`.) Your community dashboard lives at `/community/<id>`.

**Windows** (native):
```powershell
git clone https://github.com/je-empty/Glimi.git
cd Glimi
run.bat
```
(WSL2 + `./run.sh` works.)

**Useful commands**:
```bash
./run.sh workspace                      # Glimi Workspace server (home + demo + create) → http://127.0.0.1:8800
./run.sh --port 9000                    # change dashboard port
./run.sh --local-models                 # local LLM mode (dev opt-in) — auto-installs Ollama + pulls default model, skips what exists. See docs/local_models.md
./run.sh --setup-only                   # run setup (venv/deps/ollama/model) then exit
./run.sh --imagegen                     # enable local LoRA portrait generation (opt-in, ~6min/portrait)
./run.sh --legacy <community>           # legacy single-bot mode (QA / debugging)
./scripts/community_e2e.sh --owner-agent --qa   # web E2E EDD QA — owner-agent-driven, scored generation (docs/qa_system.md)
./scripts/stop.sh                       # graceful shutdown
python -m community.platform.accounts list    # list platform accounts
python -m community.community list            # list communities (CLI)
```

> 🚀 See [`START_HERE.html`](docs/START_HERE.html) for setup and checklist.

| DM Channel View | Achievements |
|---|---|
| <img src="docs/screenshots/en/07-dm-channels.png" width="600" height="382" alt="DM channels"/> | <img src="docs/screenshots/en/03-achievements.png" width="600" height="382" alt="Achievements"/> |

| Connection Graph | Graph + Supervisor Overlay |
|---|---|
| <img src="docs/screenshots/en/05-connection-graph.png" width="600" height="434" alt="Connection graph"/> | <img src="docs/screenshots/en/06-graph-supervisor.png" width="600" height="434" alt="Supervisor overlay"/> |

---

## Glimi Workspace — a team for work

![Glimi Workspace](glimi-workspace/assets/brand/Glimi-Workspace-banner.svg)

Every user gets a team. Glimi Workspace runs a Coordinator that proposes a goal-appropriate set of specialist roles for the task (e.g. researcher / builder / critic, or trail-scout / logistics-planner / gear-guide for a trip). The roster is generated per goal, not a fixed three. You set project context once: goals, past decisions, style. Each agent saves it so new sessions start ready, and model or host swaps keep that context intact. Workspace behaves like persistent staff rather than a tool you spin up and discard.

Workspace and Community run on one Core. Workspace handles work; Community handles friends. The split shows Core modularity. Workspace imports only `glimi` — no chat SDK, no Community code.

Agents use separate DMs. The owner messages the Coordinator, who assigns tasks. Specialists debate in A2A channels and regroup before delivery. Those exchanges form the same graph used in Community. Each member keeps its own L0–L5 memory.
#### One server, many workspaces

`./run.sh workspace` runs a host for many workspaces, the way Community hosts multiple communities. A read-only demo workspace comes preloaded. Create one by giving a name and goal, then open a workspace to watch it operate.
<img src="docs/screenshots/en/15-workspace-home.png" alt="Glimi Workspace — one server, many workspaces" width="820"/>

#### Watch it live

The demo runs a stored live team that loops on its data. The dashboard updates in real time (offline, no key, **$0**). One screen shows the graph, member memories and facts, channel viewer (owner DM, delegations, A2A debates, group round, `mgr-approvals` history), plus panels for tool-call timeline and LLM usage (local/echo $0, counts *est.*).
| Live team dashboard | Agent detail — memory, facts, relationships |
|---|---|
| <img src="docs/screenshots/en/13-workspace-full.png" alt="Workspace live demo dashboard"/> | <img src="docs/screenshots/en/14-workspace-agent-detail.png" alt="Workspace agent detail"/> |

```bash
./run.sh workspace                      # the workspace server (home + demo + create) → http://127.0.0.1:8800
./run.sh workspace --demo               # serve just the seeded demo team
./run.sh workspace --serve              # run a real goal once, then serve the result
./run.sh workspace --serve --name "<you>" --goal "<your goal>"   # your own goal (else a default goal runs)
./run.sh workspace --serve --approve final   # require owner sign-off on the deliverable
```
> With a real backend (Claude/local), `--serve` runs the full work round first, which can take several minutes before `:8800` opens. It isn't hung; watch the console. (`--demo` serves instantly.)

#### Human-in-the-loop — the approval gate

Before the Coordinator sends the final synthesis, Workspace can route it through an approval gate: the owner approves, edits, or rejects, and rejects fall back deterministically. Control it with `--approve auto|final|off`; non-interactive runs (CI, pipes, demo) auto-approve, so it never hangs. Decisions log to `mgr-approvals`.

---

## EDD — eval-driven development (quality tracked per commit) ⭐

Glimi measures multi-agent quality with **EDD**: an autonomous owner agent drives the app from onboarding through the core journey, scored across weighted dimensions into a 0–100 composite and committed as a git-SHA generation, so `git log` becomes a quality timeline. Real runs span gen-1 (69.4, FAIL) to gen-11 (85.0, PASS, the highest so far), with a `critical` gate that voids a run when the `friend_creation` journey breaks even if the chat score is high. A `/admin/qa` dashboard and `glimi.edd` PDF reports visualize it.

![EDD — /admin/qa dashboard: gen-11 PASS 85, the dimension breakdown, and the quality-over-generations trend](docs/screenshots/en/19-edd-dashboard.png)

→ details: the six scoring dimensions, the full generation table, the flywheel analysis, the dashboard + PDF commands, and the adopter API (`glimi.edd`) — [docs/edd.en.md](docs/edd.en.md).

---

## 📚 Deep dives

This README is the at-a-glance tour. Each subsystem has a focused doc:

| Topic | Doc |
|---|---|
| **Memory & runtime internals** — the 8-layer pipeline, L0–L5 stack, model-swap survival | [`docs/memory.en.md`](docs/memory.en.md) |
| **Elastic Memory** — context-window-aware memory budgeting | [`docs/elastic_memory.en.md`](docs/elastic_memory.en.md) |
| **Positioning** — what makes Glimi different + the full vs-alternatives table | [`docs/positioning.en.md`](docs/positioning.en.md) |
| **Core capabilities & library embedding** — full capability detail, `KernelStore` DI, model roles | [`docs/core_internals.en.md`](docs/core_internals.en.md) |
| **Community internals** — channels, context-leak, spy mode, architecture | [`docs/community_internals.en.md`](docs/community_internals.en.md) |
| **EDD** — eval-driven development: dimensions, the generation table, the flywheel | [`docs/edd.en.md`](docs/edd.en.md) |
| **Local models** — Ollama tiers + setup | [`docs/local_models.md`](docs/local_models.md) |
| **Contributor onboarding** — setup, first task, workflow | [`docs/START_HERE.html`](docs/START_HERE.html) |

---

## Examples

Lightweight starters that run on Glimi Core only, without the Community social-sim layer:

| Example | What it shows |
|---|---|
| `glimi-core/examples/research_buddies/` | Two agents collaborate on a research topic, take turns reading and summarizing, build up shared notes |
| `glimi-core/examples/dev_pair/` | Planner + executor pattern — one agent breaks the task into steps, the other carries them out, both share a memory store |
| `glimi-core/examples/dashboard_demo/` | Seed a small population on an in-memory store and serve it in the read-only Core dashboard (`glimi[dashboard]`) |

---

## Tech Stack

| Component | Technology |
|---|---|
| **Glimi Core runtime** | Python 3.12+. Claude (Claude CLI subprocess + Anthropic SDK), a fully-local Ollama backend, and a Grok CLI backend; the LLMBackend seam is pluggable (vLLM / llama.cpp planned, not yet shipped) |
| **Memory store (default)** | SQLite — pluggable via the `KernelStore` ABC (the kernel never touches the DB directly) |
| **Tool protocol** | `<tools>` inline XML — alias resolution, JSON-typed args, deferred execution |
| **Web dashboard** | FastAPI + Jinja2 + Cytoscape.js + htmx |
| **Community transport** | Built-in web chat (FastAPI + WebSocket) over Core's pluggable `ChannelAdapter` seam — per-agent avatars, new transports plug into the same seam |
| **Community image gen** (opt-in) | Local LoRA portrait via Animagine XL 4.0 (~6min/portrait, 186MB weights) |

---

## Roadmap

**Kernel extraction and packaging**
- ✅ Moved `community/core/{runtime, tools, memory, llm, conversation}` → `glimi/`; imports standalone, no transport/DB coupling.
- ✅ Added `KernelStore` ABC plus `AgentProfile`, `OwnerContext`, `KernelObserver` protocols; adapters in `community/adapters/`.
- ✅ `pyproject`: `pip install glimi` installs core with **no runtime deps**. Extras: `glimi[sdk]` (Anthropic), `glimi[dashboard]` (FastAPI). Kernel builds as wheel used by apps.

**First PyPI release**
- Alpha 0.1.0 of `pip install glimi` on PyPI.

**Next — Examples and docs**
- `examples/research_buddies/`, `examples/dev_pair/`
- English architecture post
- `kernel.tests/` coverage

**Local-model backends**
- Add vLLM / llama.cpp. (Ollama, Grok live; stubs in `AVAILABLE_MODELS`)
- Dashboard supports per-agent local override.

**Per-agent RAG memory**
- L0–L5 runs in context. For long sessions add **per-agent RAG corpus** with retrieval core. History is embedded and indexed; agent fetches per turn. Memory becomes a query store.
- **Effect**: recall stays stable (`O(top-k)`); each agent gets an inspectable knowledge base with sourced recall.
- **Latency**: retrieval delay handled *in character* — *"잠시만…", "기억 더듬는 중…"* — so pause feels natural.

**Community features**
- Owner-absence simulation and briefing
- Emotion layer (sentiment → state)
- Scenes: birthday, healing, outing
- Telegram and web chat adapters

---

## Contributing

> 🆕 **First time?** Open **[`START_HERE.html`](docs/START_HERE.html)** for setup, first contributor task (local model support), Claude Code workflow, branch policy, and TODO roadmap. **Read before any PR.**

### Local-model support — shipped ✅ (Gemma 4 / Qwen 3.5)

Ollama handles all local LLM calls. Gemma 4 (26b-a4b / e4b / e2b) and Qwen 3.5 were tested on persona chat, supervisor judge, memory extraction, and manager tools. Full configs, VRAM, hardware, and results: **[`docs/local_models.md`](docs/local_models.md)**. Setup: [`docs/ollama_setup.md`](docs/ollama_setup.md). Planned next: vLLM / llama.cpp backends, reranker-based memory retrieval, small-model tool-call tuning.

### Other entry points

- **easy**: new `examples/`, doc fixes, Community `community/scenes/`
- **medium**: vLLM / llama.cpp backends, dashboard visuals, ToolSpecs
- **hard**: Windows native (`run.ps1`), Telegram adapter (`community/adapters/telegram/`), `pyproject` packaging split (`pip install glimi`), embedding-based memory retrieval

### Branch strategy

| Branch | Role |
|---|---|
| `main` | Stable. **No direct work / push.** Maintainers fast-forward from `develop`. |
| `develop` | Working branch. All integration happens here. |
| `feat/<name>` · `fix/<name>` · `docs/<name>` · `refactor/<name>` | Short-lived contributor branches. **PR base = `develop`**. |

### Code conventions (the easy-to-regress ones)

- **Transport = adapter.** `community/core/*` never imports a chat SDK — transports plug into the `ChannelAdapter` seam (`community/adapters/web/`). Community code lives in `community/scenes/`, `community/achievements/`, manager tool handlers in `community/core/mgr_actions.py`, etc.
- **Memory / emotion = user-prompt injections**, not system-prompts. `AgentRuntime` builds per channel and turn.
- **Timestamps = UTC ISO** (`community.core.timeutil.now_utc_iso()`). SQLite `CURRENT_TIMESTAMP` is naive—avoid it.
- **Meta words** like "agent", "bot", "AI" banned in user text. `<tools>` blocks are internal. Tool-call logs → `logs/system.log`.
- **Profile edits** require both `invalidate_cache()` and `runtime.refresh_agent()`.

### Commit rules

- Subject: 1 line, ~50 chars. Optional short body (1–2 lines).
- Prefix: `feat:` / `fix:` / `docs:` / `ui:` / `refactor:` / `test:`.
- **No AI co-author tags** (`Co-Authored-By: Claude` etc.).
- **No bypass flags** (`--no-verify`, `--no-gpg-sign`); fix the hook.

See `CLAUDE.md` for guardrails (auto-loaded by Claude Code).

---

## License

**AGPL-3.0-or-later** — strong copyleft license. You can use, study, modify, and share Glimi. **Distributed or network-served derivatives must remain open under AGPL and keep attribution.** No closed or sold versions. Contributions use the same license; the author keeps copyright and may issue commercial licenses. Similar to MongoDB, Grafana, and Mastodon: open use and shared growth.

See `LICENSE` and `NOTICE` for details.
