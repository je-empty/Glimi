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

Setup is two lines. **Glimi Core** manages all state. Data stays in storage (SQLite by default), not in prompts, so relationships and memories survive restarts and model swaps (Haiku → local Llama). Core trims memory to fit the set `num_ctx` window (4096–16384) and keeps personality alignment across models. Mix cloud (Claude) and local (Ollama) characters; Grok CLI works too. Fully local runs cost nothing.

The web dashboard shows a relationship graph, memory inspector, channel viewer, tool-call timeline, and LLM cost card.

![Glimi — a living community of agents, live in the connection graph](docs/screenshots/en/11-community-dashboard.png)

**Glimi Community** runs a chat group of AI friends with a web UI or Discord bridge. They remember and talk like people. **Glimi Workspace** runs work roles (Coordinator, Researcher, Builder, Critic) with a live demo. Starters in `examples/` use the same Core.

> *agent* means a *Generative Agent* — a character that remembers, forms opinions, and initiates talks — not an autonomous task-runner. We say *agent* in code and *friends / characters* for users.

```
Glimi/                           one repo, three self-contained projects (a "workspace" monorepo)
├── glimi-core/                  ← Glimi Core — the kernel        ·  pip install "glimi[dashboard]"
│   ├── glimi/                   ·   runtime · memory · context_budget · conversation · tools · llm · stores · dashboard · edd
│   ├── examples/                ·   library starters (research_buddies · dev_pair · dashboard_demo)
│   ├── eval/                    ·   golden-set capability eval (LLM-judge · regression gate); glimi.edd = generational E2E EDD
│   └── pyproject.toml           ·   builds the `glimi` / `glimi[dashboard]` wheel (the only PyPI artifact)
├── glimi-community/             ← Glimi Community — the flagship app (Core was extracted FROM here)
│   ├── community/               ·   FastAPI platform · built-in web chat · scenes · achievements · Discord adapter
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

> **One repo, three projects.** Glimi Core (`glimi-core/`, `glimi` package) powers Glimi Community (`glimi-community/`) and was extracted from a working app. **Glimi Workspace** (`glimi-workspace/`) uses only the `glimi` package to show Core's reusability. Each folder is standalone with its own `pyproject.toml`; both apps depend on `glimi[dashboard]` (editable local install, to reach PyPI at release). You can `cd` into any and run it. The `glimi` package publishes separately.

---

## What makes Glimi different

Glimi Core runs agents that persist across sessions. Standard frameworks launch short-lived agents, compress context, and rebuild later. In Glimi, each agent keeps its context — work, decisions, preferences, and links — stored across sessions and model swaps. The same core drives **Glimi Workspace** (shared workbench) and **Glimi Community** (friend memory).

Other projects (LangChain/LangGraph, AutoGen, CrewAI, OpenAI Agents SDK, Letta, etc.) focus on single **tasks** and discard the agent after. Some (Letta) persist memory or run open worlds (Stanford Generative Agents, AI Town). Glimi merges these ideas into a **single pip-installable runtime** with two traits:

**1. Memory sized to context (Elastic Memory).** Glimi fits memory to the set context window (`num_ctx`). It trims by token budget so prompts stay within limit. The same agent runs at 4096 or 16384 without personality loss. Others trim history (CrewAI, Letta, OpenAI Agents SDK, AutoGen, LangGraph) but not by target size. Ollama's request to auto-match VRAM is still open.

**2. Anti-drift memory.** Facts expire on time or are marked superseded when replaced. Agents forget stale data but keep the record. Zep's Graphiti is closed; Mem0 dropped contradiction handling in 2026. Glimi ships supersession logic, runtime, and dashboard free. It uses row-level SQLite instead of a full graph.

**Integration overview**

- **Persistent population.** Each agent has a persona and model (Claude or Ollama). State is stored, not reprised, surviving model swaps.
- **Autonomous activity.** A timed supervisor spawns threads, revives idle agents, and advances scenes offline.
- **Light load.** All agents share one resident model, swapping only context. Fits a fleet on 16 GB. Uses Ollama's resident model while Glimi tracks state.
- **Dashboard.** Web UI shows relationships, memory (L0–L5), live channel, and model inspector. Others show single agents; Glimi spans many.

Status: alpha (0.1.0, not on PyPI). Letta leads in memory depth, AI Town in autonomy, SillyTavern in characters, Zep in graphs. Glimi combines them.
<!--
### Glimi vs. the alternatives

Glimi fills the intersection of those efforts.
| Capability | Glimi | Letta (MemGPT) | AI Town | Zep / Graphiti | CrewAI / LangGraph | SillyTavern |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| Pip-install library, you design the fleet | ✅ | ✅ | ❌ TS game stack | ✅ engine only | ✅ | ❌ chat front-end |
| Per-agent model, cloud + local in one fleet | ✅ | ✅ | ❌ one shared model | — | ✅ | ◐ |
| Memory survives a model swap (state in storage) | ✅ | ✅ | ✅ | ✅ | ◐ | ◐ |
| Temporal fact supersession (anti-drift) | ✅ scoped | ❌ | ❌ | ✅ the reference | ❌ | ❌ |
| Autonomous agent-to-agent (self-initiated) | ✅ | ❌ | ✅ | ❌ | ❌ | ◐ |
| Hardware-aware elastic context budgeting | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Built-in relationship-graph + memory dashboard | ✅ | ◐ one agent | ◐ sim viewer | ❌ hosted | ❌ separate | ❌ |

✅ yes · ◐ partial · ❌ no · — not applicable. Letta pages memory deeper, AI Town supports larger worlds, Zep's graph is richer, and SillyTavern builds stronger characters. Glimi is the only one covering all seven rows in a single AGPL-3.0 package.
---

## Glimi Core — the harness

![Glimi Core](glimi-core/assets/brand/Glimi-Core-banner.svg)

### What's in the box

| Feature | Detail |
|---|---|
| **Multi-agent runtime** | Per-agent model override stored in DB. Cloud (Claude) and local (Ollama) coexist in one fleet — Grok CLI too; vLLM / llama.cpp are planned via the pluggable backend seam. Swappable without restart. |
| **Tool protocol** | `<tools><call id="1" name="...">...</call></tools>` inline XML — declarative `ToolSpec` registry with permission, type, env-gating |
| **Layered persistent memory (L0–L5)** | L0 raw (`conversations`) → L1 working window (recent verbatim, injected live) → L2 episodic rollup (L1→L2→L3 digests in `memories`) → L3 semantic facts (`agent_facts`: subject·predicate·object with `valid_from`/`valid_to` supersession) → L4 relationship (`relationships` + history) → L5 pinned (`memories.is_pinned`). Async Haiku extraction off the response path. |
| **Autonomous A2A conversation** | 1:1 and multi-agent channels. Turn-limited, closure-detected. Agents start conversations with each other via the tool protocol. |
| **Proactive supervisor layer** | The one layer that ticks without input. A pair scanner opens new agent-to-agent channels, a chat watcher revives idle ones, and a scene watcher progresses stuck workflows. |
| **Live observability dashboard** (`glimi[dashboard]`, read-only) | Cytoscape.js agent graph, per-agent memory inspector (L0–L5), real-time channel viewer, tool-call timeline, LLM usage/cost card, runtime state badges. (Live model-swap *writes* are a Community/Workspace platform feature; the Core dashboard surfaces the per-agent model for inspection.) |
| **Evaluation harness** | A golden set across persona / tool-use / memory / fallback / supervisor capabilities; deterministic checks + an LLM-as-judge (reused, not reinvented); a backend-tagged **regression gate** (fails CI on a pass-rate or judge-score drop); a production-feedback loop that promotes a flagged bad turn into a golden case. Runs free on the offline `echo` backend. |
| **End-to-end EDD QA (generational)** | The integration counterpart to the golden-set eval: an autonomous **owner agent** drives a full app from onboarding through the core journey, scored across weighted dimensions into a **0–100 quality score**, each run a **git-SHA-anchored "generation"** (SQLite + committed JSON) so quality is tracked commit-over-commit. The flagship differentiator — **[real measured generations + the flywheel](#edd--eval-driven-development-quality-tracked-per-commit-)** get their own section above. |
| **Cost & latency accounting** | Every LLM call records tokens, estimated cost, and latency at one choke-point; every tool call records args/result/latency/ok at another. Honest by construction — local/echo priced at $0, CLI/estimate rows labeled *est.*, dollars shown only for real priced spend. |
| **Human-in-the-loop gate** (Workspace) | An approval policy (`approve / edit / reject` + fallback + decision trail) around a consequential action, used by Workspace; never hangs (non-interactive auto-approves). |
| **Self-healing (experimental, off by default)** | Agent emits `request_dev_fix` → enqueues a dev_requests row → a dev-queue supervisor triages → on approval an Opus subprocess (`GLIMI_DEV_DISPATCH=1`) patches source → bot restart with the patch summary injected. |

### The 8 layers

Each response runs through **8 layers**. Some wrap the LLM call (prompt, tools, memory). Others live in subsystems (A2A loop, supervisors, self-heal). Seven follow messages; one runs on schedule.

```mermaid
flowchart TB
    linkStyle default stroke:#888,stroke-width:1.5px
    In([📨 message in]) --> Stack
    subgraph Stack["⚡ Reactive — layers 1-5 pre-LLM"]
        direction LR
        R1["1·Prompt"] --> R2["2·Tool"] --> R3["3·Memory"] --> R4["4·Channel"] --> R5["5·Guard"]
    end
    Stack --> LLM[("🤖 LLM<br/>Haiku / Sonnet / Opus<br/>or local")]
    LLM --> Post
    subgraph Post["⚡ Reactive — post-LLM"]
        direction LR
        P1["parse · dispatch · dedup"] --> P2["6·A2A · 7·Self-heal"]
    end
    Post --> Out([📤 message out])
    Out -. "async" .-> Ex["🧠 Memory extract<br/>(Haiku)"] -.-> DB[("Store")]

    Sup["🔄 Proactive · layer 8<br/>⏱ Supervisors<br/>chat 15s · scene 30s · pair-scan 3min"] -. "nudge as inner thought" .-> In

    style Stack fill:#1a2a3a,stroke:#4a9eff,color:#fff
    style Post fill:#1a2a3a,stroke:#4a9eff,color:#fff
    style Sup fill:#1a1a2e,stroke:#9a4aff,color:#fff
    style LLM fill:#1a3a2a,stroke:#4aff9e,color:#fff
```

Three layers — channel discipline, anti-echo guards, self-healing — sit near Community; others stay in Core.

**1 · Prompt assembly** — builds prompt text from language + agent-type dispatch (`ko/`, `en/`), provider dialect (Claude `<tools>` XML, OpenAI function call, local tag), and locale snippets.

**2 · Tool protocol** — `ToolSpec` validates permissions, types, and fields. Dispatcher runs handlers; outputs feed the next prompt.

**3 · Memory pipeline** — every N turns, Haiku extracts `{summary, facts[], relationships[], emotion, entities, importance}`. Handles episodic rollup, semantic supersession, and intimacy bumps. Injection ≈ 1000 toks/turn scaled by load: pinned + relationship + episodic-current + self-recent + retrieved + facts. Retrieval weights `0.4·semantic + 0.3·importance + 0.2·recency_decay + 0.1·relational`.

**4 · Channel discipline** — prompts declare listeners to stop role bleed (e.g. agent speaking for owner in private A2A chat).

**5 · Anti-echo / dedup / reality guard** — ends goodbye loops, skips repeat tool calls, drops duplicates, blocks fake actions.

**6 · A2A conversation loop** — `start_conversation(channel, participants, …)` opens agent-to-agent talk with turn limits and closure check.

**7 · Self-healing** (off by default) — `request_dev_fix` logs a dev_request. Supervisor triages; on approval, Opus subprocess (`GLIMI_DEV_DISPATCH=1`) patches source and restarts with patch summary injected.

**8 · Supervisors** — timed processes (conversation trio and others). A pair scanner (DB intimacy + idle-time, no LLM) opens A2A channels. A chat watcher (Haiku judge) revives idle ones. A scene watcher moves stuck phases. Nudges appear as agent thoughts, not commands.

```
Bad:  "Switch to a new topic now."             ← LLM parses as command, awkward output
Good: "(oh, I should bring up something else)" ← LLM reads as self-talk, natural flow
```

Commands show system noise; self-talk merges into the next line.

### Memory architecture

```mermaid
graph LR
    linkStyle default stroke:#888,stroke-width:1.5px
    L0["📝 L0 Raw\nconversations table\n(permanent)"]
    L1["📋 L1 Working window\nrecent ~15 verbatim\n(injected live)"]
    L2["📦 L2 Episodic"]
    Facts["📚 L3 Semantic Facts\n(subject, predicate, object)\nvalid_from/valid_to supersession"]
    Rel["💞 L4 Relationship\nsnapshot + history deltas"]
    Pin["📌 L5 Pinned\nalways-inject"]

    subgraph Rollup["episodic rollup levels (inside L2)"]
        direction LR
        E1["digest\n5 msgs → L1 digest"]
        E2["paragraph\n5 L1 → L2"]
        E3["monthly\n5 L2 → L3"]
        E1 -->|"rollup"| E2 -->|"rollup"| E3
    end

    L0 -->|"recent"| L1
    L1 -->|"async Haiku extract"| L2
    L2 --> Rollup
    L1 -.->|"facts / rel deltas"| Facts & Rel

    style L0 fill:#1a3a1a,stroke:#4aff4a,color:#fff
    style L1 fill:#1a2a3a,stroke:#4a9eff,color:#fff
    style L2 fill:#1a2a3a,stroke:#4a9eff,color:#fff
    style Facts fill:#2a3a1a,stroke:#9aff4a,color:#fff
    style Rel fill:#3a2a1a,stroke:#ffaa4a,color:#fff
    style Pin fill:#3a3a1a,stroke:#ffff4a,color:#000
```

Hardening:
- `_validate_fact()` drops vague subjects (`"new member"`), transient objects (`"recently"`), and duplicate self-facts.
- `PREDICATE_ALIASES` merges 40+ variants into a small canon for consistent retrieval.
- A2A memories carry a disclosure tag before showing to owners.

### Why it survives model swaps and profile edits

- State stays outside prompts. Swapping Haiku → Sonnet → local Llama keeps relationships, facts, pinned memories; new models read the same injection.
- Profile-edit tools pair `invalidate_cache()` with `runtime.refresh_agent()` so updates apply next turn and stop repeat-question bugs.

### Elastic Memory — memory that fits any context window

Local models have small windows (Ollama 4096). A full Glimi prompt — character system + L0–L5 memory + chat history — often exceeds that, truncating early tokens.
`Elastic Memory` (`glimi/context_budget.py`) manages this:

- **Memory scales with window** — baseline `num_ctx` 8192; 4096 shrinks, 16384 doubles recall.
- **Best-effort fit** — trims oldest conversation first; logs warning if even system prompt overflows.
- **Backend-agnostic** — works with Claude or any; mainly for locals (cloud 200 k rarely needs it).
- **Per-community, hardware-aware** — `community/core/system_specs.py` reads RAM/VRAM, suggests Low 4096 / Mid 8192 / High 16384 tiers, writes config like a quality slider.

### Quick Start (library)

Glimi Core **alpha (0.1.0, not on PyPI)**. Install from source. Kernel includes in-memory store and **offline `echo` backend**, so it runs with **no deps or API key** — `echo` shows wiring and conversation storage.

```python
from glimi import Glimi

chat = Glimi(backend="echo")          # offline: no deps, no API key, no network
chat.add_agent("nova", persona="A curious, upbeat companion who loves questions.")

print(chat.reply("nova", "Hi! What's your name?"))
print(chat.reply("nova", "Nice — tell me something fun."))
```

Switch the backend for real models; nothing else changes.

```python
chat = Glimi(backend="claude_cli")    # Claude via the Claude CLI login (no SDK); metered API credits, not a free subscription
chat = Glimi(backend="ollama")        # fully local via Ollama — the free option (set GLIMI_OLLAMA_MODEL)
```

`Glimi` connects modules — in-memory `KernelStore`, simple `ProfileProvider`/`OwnerContext`, `NullObserver`, and selected backend. Import parts directly if you outgrow defaults.

```python
from glimi import (
    InMemoryKernelStore, SimpleProfileProvider, SimpleOwnerContext,
    KernelStore, ProfileProvider, OwnerContext, KernelObserver,  # seams to implement
    LLMBackend, LLMResponse, EchoBackend,
)
```

To use your DB, implement `KernelStore` (and optional `ProfileProvider`/`OwnerContext`/`KernelObserver`) and inject with `glimi.runtime.set_store(...)`. Example (SQLite + Discord):

- `community/adapters/kernel_store.py` — `SqliteKernelStore` + profile/observer adapters
- `community/core/runtime.py` — injects them and exports API

### Web dashboard (Glimi Core's observability)

The Core dashboard shows all agents — graph, memory inspector (L0–L5), channel view, tool log. It is **read-only**; live model-swap writes need Community or Workspace.

| Connection Graph | Memory Inspector |
|---|---|
| <img src="docs/screenshots/en/04-graph-live.webp" height="300" alt="Connection Graph"/> | <img src="docs/screenshots/en/02-persona-memory.png" height="300" alt="Memory Inspector"/> |

- **Cytoscape.js graph** — agent links, channel activity, supervisor overlay
- **Memory inspector (L0–L5)** — pinned, episodic, semantic, relationship data
- **Live channel viewer** — shows each agent's view
- **Tool call timeline** — `<tools>` args + results
- **Per-agent model (read-only)** — lists model and override badge (live swap in Community/Workspace)

### LLM model roles (default config)

| Role | Model | Why |
|---|---|---|
| Memory extraction | `claude-haiku-4-5` | Cheap + fast, runs on every batch in background |
| Supervisor / judge | `claude-haiku-4-5` | Lightweight state classification |
| Agent reply (default) | `claude-haiku-4-5` | High-volume, latency-sensitive |
| Reasoning / orchestration | `claude-sonnet-4-6` | Per-agent override from dashboard |
| One-shot structured output | `claude-opus-4-6` | Profile JSON, complex generation |
| Self-healing | `claude-opus-4-6` | Runtime-error source patching |

About 10× cheaper than Sonnet-only.

### Fully local mode (zero Claude dependency)

`GLIMI_LLM_BACKEND=ollama` routes all LLM calls (persona, manager tools, memory extraction, supervisor checks, achievement judging) to local Ollama — no Anthropic key. Choose tier with `GLIMI_LOCAL_TIER` (`run.sh --local-models`).

| Tier | Config | Mac | VRAM | Notes |
|---|---|---|---|---|
| lite | `e2b` single | 16 GB | 8 GB | fastest, weaker tool calls |
| standard *(default)* | `e4b` single | 16 GB | 12 GB | balanced |
| quality | `iq3-26b` single | 24 GB | **12 GB** | 26b quality on 12 GB (MoE, ~1 GB offload) |
| prod | `iq3-26b` manager + `e4b` rest (split) | 32 GB | 24 GB | both resident, no swap |

A 12 GB GPU can't hold a two-model split; use `quality` (26b single). See **[`docs/local_models.md`](docs/local_models.md)** for table and setup.

---

## Glimi Community — the flagship app

![Glimi Community](glimi-community/assets/brand/Glimi-Community-banner.svg)

> *"AI friends that keep living when you're not looking."*

Community is a **real application** built on Glimi Core — the main showcase for Core. It's not a demo.

Friends remember everything: time, jokes, hard weeks, secrets. Each friend keeps personal memory. After days, they ask, "did that thing work out?" Swapping a model (Haiku → Llama) keeps tone and memory. They don't reset — they know you.

![The cast — a populated community of friends, each with their own MBTI, age, mood, and per-agent model](docs/screenshots/en/20-community-cast.png)

![Connection Graph — Live](docs/screenshots/en/04-graph-live.webp)

### Talk to them — the built-in web chat

Community provides its own chat: Discord-style layout, character sidebar, grouped messages, replies, reactions, threads, dark/light themes, mobile support. The dashboard and chat share one store. Click a graph line to jump to its chat.

| Web chat (light) | Web chat (dark) | On mobile |
|---|---|---|
| <img src="docs/screenshots/en/08-web-chat.png" alt="Web chat — light theme"/> | <img src="docs/screenshots/en/09-web-chat-dark.png" alt="Web chat — dark theme"/> | <img src="docs/screenshots/en/10-web-chat-mobile.png" height="420" alt="Web chat on mobile"/> |

Discord is optional and runs as one adapter. Chat moves via WebSocket through Core's neutral outbox/inbox seam, used by Telegram and future adapters.

**A demo is included.** On setup, a read-only **demo community** appears automatically. It shows Glimi in action without tokens or bots. Posting is off, and a banner marks it so.

<img src="docs/screenshots/en/16-community-demo-readonly.png" alt="Read-only demo community — look-only mockup" width="820"/>

### The defining UX move

Each character has channels — DMs with you, **secret DMs with each other**, and group chats you can read but not join — on web or Discord. **Context leaks between channels**: what you tell A can show in A↔B, and B answers in that tone without quoting.

```
14:02 — you DM A in #dm-A
  You: "hey, is B mad at me or something? they've been short with me all week"
  A:   "lol why would they be 🤷 probably just busy"

14:05 — A and B gossip in #internal-dm-A-B  (you read silently; they don't see you here)
  A: "bruh the owner just DM'd me asking if you're mad at them 😂"
  B: "???? no lmao"
  A: "apparently you've been 'short' all week"
  B: "I've literally been on deadline crunch..."
  A: "I didn't snitch, just said you were busy"
  B: "ok ty"

14:30 — you DM B in #dm-B
  You: "how's your day going"
  B:   "surviving — crunch week 😮‍💨"
```

B says "crunch week" — explaining the short replies. No quoting A, no "I heard." B's memory notes: *owner asked about me in A's DM.* Later you ask "are we cool?"; that memory injects, shaping the reply.

Glimi Core handles this: channel discipline (layer 4) enforces borders, memory injection (layer 3) moves context, supervisor (layer 8) drives gossip.

### Community-specific feature set

| Feature | Description |
|---|---|
| **Owner-absence simulation & return briefing** (roadmap) | Agents keep talking while you're away; Manager briefs you on return |
| **Channel context leakage** | Memory of secret conversations naturally affects later replies without direct quotation |
| **Spy mode** | `internal-*` channels are read-only for the owner — agents don't know you're there |
| **Manager + Creator characters** | Yuna (admin / tutorial / DM approval) and Hana (persona design / avatar prompts) |
| **Scene system** | `tutorial` shipped; `birthday` / `healing` / `outing` planned |
| **Achievements** | 7 default unlocks tracked as the user explores: first chat, three friends, group chat, peek-internal, autonomous-chat, long-relationship, fourth-wall break |
| **Multi-community isolation** | One platform process spawns N community bot subprocesses; each gets its own SQLite DB and Discord server |

### Community architecture (web-first; Discord = optional adapter)

```mermaid
flowchart LR
    linkStyle default stroke:#888,stroke-width:1.5px
    subgraph Owner["👤 Owner"]
        Web["🌐 Built-in web chat + dashboard"]
    end

    subgraph Engine["Community Engine (built on Glimi Core)"]
        Plat["🧩 Platform (FastAPI · WebSocket)"]
        Core["⚙ Glimi Core<br/>(runtime · memory · supervisors)"]
        DB[("SQLite<br/>community.db")]
        Log["📄 logs/system.log<br/>(runtime tool logs)"]
        Bot["🤖 Discord adapter<br/>(optional)"]
    end

    subgraph Channels["💬 Channels"]
        DM["💬 dm-{name}<br/>incl. manager dm-agent-mgr-001"]
        Grp["👥 group-{names}"]
        SecDM["🔒 internal-dm-A-B"]
        SecGrp["🔒 internal-group-A-B-C"]
    end

    Web <-->|"chat (WebSocket)"| Plat
    Plat <--> Core
    Core <--> DB
    Core -.->|"tool-call logs"| Log
    Owner <-->|"chat"| DM & Grp
    Owner -. "spy 🔍 read-only" .-> SecDM & SecGrp
    Bot -. "optional mirror" .-> Plat

    style Engine fill:#1a3a2a,stroke:#4aff9e,color:#fff
    style Core fill:#1a3a5c,stroke:#4a9eff,color:#fff
    style SecDM fill:#2d2d2d,stroke:#f5c542,color:#fff
    style SecGrp fill:#2d2d2d,stroke:#f5a142,color:#fff
```

**Web chat is primary; Discord is optional.** Core never imports `discord`. Community ships FastAPI + WebSocket chat; Discord only mirrors. Telegram and others will follow.

### Channel structure (Community)

| Channel | Created | Purpose |
|---|---|---|
| `dm-{agent}` (incl. manager `dm-agent-mgr-001`) | first boot / on agent creation | Owner ↔ agent 1:1 |
| `group-{names}` | on demand | Owner + agents multi-DM |
| `internal-dm-{A}-{B}` | on demand | Agent-to-agent secret 1:1 (**owner read-only**) |
| `internal-group-{names}` | on demand | Agent-to-agent secret group (**owner read-only**) |
| `logs/system.log` (file) | runtime | Runtime tool-call logs — a file, not a channel |

### Quick Start (Community) — cross-platform

**Prerequisites (all platforms)**:
- Python 3.12+
- Node.js (Claude Code CLI)
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code): `npm install -g @anthropic-ai/claude-code`
- For Claude agents: **Claude CLI login** (default) or `.env` `ANTHROPIC_API_KEY`. Claude uses **metered credits**.
- **Free options:** **Local-only** (Ollama) or **Hybrid** (personas local/free, mgr/creator/dev on Claude).
- Discord bot token (if you enable Discord)

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

Every user gets a team. Glimi Workspace runs a Coordinator plus roles: Researcher, Builder, Critic. You set project context once — goals, past decisions, style. Each agent saves it so new sessions start ready. Model or host swaps keep context intact. Workspace is persistent staff, not a temp tool.

Workspace and Community run on one Core. Workspace handles work; Community handles friends. The split shows Core modularity. Workspace imports only `glimi` — no `discord`, no Community code.

Agents use separate DMs. The owner messages the Coordinator, who assigns tasks. Specialists debate in A2A channels and regroup before delivery. Those exchanges form the same graph used in Community. Each member keeps its own L0–L5 memory.
#### One server, many workspaces

`./run.sh workspace` runs a host for many workspaces, like Community hosts multiple communities. A read-only **demo workspace** comes preloaded. Create one by giving a name and goal. Open a workspace to watch it operate.
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
./run.sh workspace --serve --approve final   # require owner sign-off on the deliverable
```

#### Human-in-the-loop — the approval gate

Before the Coordinator sends the final synthesis, Workspace can route it through an **approval gate** — the owner approves, edits, or rejects, and rejects fall back deterministically. Control it with `--approve auto|final|off`; non-interactive runs (CI, pipes, demo) auto-approve, so it never hangs. Decisions log to `mgr-approvals`.
---

## EDD — eval-driven development (quality tracked per commit) ⭐

Multi-agent products are hard to measure; perception isn't data. Glimi applies **EDD — eval-driven development**. An autonomous **owner agent** runs the app from onboarding to core flow. Each run produces **weighted dimension scores** and a **0–100 composite**, committed as a **git-SHA generation**. `git log` becomes a quality timeline where each commit shows its score. The **`glimi.edd`** module in the `glimi` kernel supports this for both Community and Workspace, each defining its own dimensions and owner agent.

**Scoring**: each dimension 0–10 with a weight; the composite is a weighted average normalized to 0–100. `critical` = any fail voids the run. LLM-judge dimensions are **skipped** on `echo` or when no judge exists. Community defines six dimensions:

| Dimension | Kind | Weight | Critical | What it checks |
|---|---|:--:|:--:|---|
| `onboarding` | structural | 1.0 | | A fresh owner greets the manager and gets oriented |
| `friend_creation` | structural | 1.5 | ⭐ | An owner request actually creates a new friend, and conversation follows |
| `conversation_quality` | LLM-judge | 2.0 | | Replies are human, coherent, in-character (5 axes: in_character · coherence · naturalness · engagement · no_meta) |
| `no_hallucination` | LLM-judge | 1.5 | | No invented facts, no claiming actions it never took |
| `no_leaks` | structural | 1.0 | | Zero meta / error / tool-block leakage into chat |
| `responsiveness` | structural | 1.0 | | Every driven DM gets a distinct reply, no stalls |

### The flywheel, with real measurements

**Repo generations** (`tests/e2e/qa_generations/*.json`) are real `claude_cli` runs scored by the judge and tagged with a git SHA. Data is small because the system is new. The aim is to accumulate scored generations, not depth of history.

| Gen | git SHA | Branch | Composite / 100 | Verdict | `conversation_quality` | `friend_creation` (critical) | Failing |
|:--:|:--:|---|:--:|:--:|:--:|:--:|---|
| **1** | `1eb4c46`* | `feat/community-qa-system` | **69.4** | ❌ FAIL | 6.0 | **0.0** | friend_creation, conversation_quality |
| **2** | `b3eaf74`* | `feat/community-qa-system` | **75.0** | ❌ FAIL | **9.0** ▲ | **0.0** | friend_creation |
| **3** | `f1eb58a`* | `develop` | **72.5** | ❌ FAIL | 8.0 | **0.0** | friend_creation |
| **4** | `f1eb58a`* | `develop` | **56.9** | ❌ FAIL | 4.0 ▼ | **0.0** | friend_creation, conversation_quality, no_hallucination |
| ⋯ | gens 5–10 | the web-native onboarding build | 56.9 → 85.0 | building | — | 0.0 → **10.0** | — |
| **11** | `a8d874d`* | `feat/web-native-onboarding` | **85.0** | ✅ **PASS** | 7.0 | **10.0** ▲▲ | — *(first PASS)* |

`*` = dirty working tree during run. All values come from committed JSON. **Gen 11 milestone**: onboarding became web-native after gens 5–10 prep and flipped critical `friend_creation` **0 → 10**, first ✅ PASS (85/100).

Failures shown for clarity:

- **`conversation_quality` 6 → 9 → 8 → 4 → 7** shows LLM variance. Gen-1→2 fixed manager loops; gen-4 regressed; gen-11 stabilized at 7.
- **`friend_creation` critical 0 for gens 1–10**—expected fail from Discord-bot subprocess isolation (see [`docs/qa_system.md`](docs/qa_system.md), `analysis/platform_decoupling_review.md`). Web-native onboarding fixed it. **Gen-11 `friend_creation` = 10 → first ✅ PASS (85/100)**. `conversation_quality` 7 and `no_hallucination` 6 stay exposed.

Core rule: **git tracks product quality**. Each commit's impact appears in history. The dashboard and PDF below visualize it.

### See it: the `/admin/qa` dashboard + PDF reports

A **QA dashboard** at `/admin/qa` (admin → "QA") shows the latest composite, **trend chart**, and per-generation breakdown. Any run exports to **PDF** via `glimi.edd.report`, which prints through Playwright. The trend SVG is server-rendered for consistent output.

![EDD — /admin/qa dashboard: gen-11 PASS 85, the dimension breakdown, and the quality-over-generations trend](docs/screenshots/en/19-edd-dashboard.png)

```bash
# one scored generation (free self-test: echo backend, judge skipped, structural dims only)
GLIMI_LLM_BACKEND=echo .venv/bin/python -m tests.e2e.community_e2e --owner-agent --rounds 2 --qa

# a real, judged generation → SQLite + a committable gen-NNNN-*.json
GLIMI_LLM_BACKEND=claude_cli .venv/bin/python -m tests.e2e.community_e2e \
    --owner-agent --rounds 10 --qa --report

# + a PDF report (trend chart + dimensions; needs Playwright). --pdf implies --qa.
GLIMI_LLM_BACKEND=claude_cli .venv/bin/python -m tests.e2e.community_e2e \
    --owner-agent --rounds 10 --pdf --report
```

```bash
git log -- tests/e2e/qa_generations/   # the quality timeline (committed generations)
git log --grep "qa:"                   # every quality-affecting change, with its score delta
```

**For adopters:** `glimi.edd` is domain-neutral in the `glimi` wheel. Add your dimensions and owner-agent driver for composite scoring, git-anchored SQLite + JSON storage, and HTML/PDF reports.

```python
from glimi.edd import Dimension, DimResult, build_assessment, GenerationStore

DIMS = [Dimension("onboarding", "Onboarding", 1.0, "structural", "fresh user gets oriented"),
        Dimension("core_journey", "Core journey", 1.5, "structural", "...", critical=True)]
results = [DimResult.for_dim(d, score=..., passed=..., detail="...") for d in DIMS]  # you evaluate
assessment = build_assessment(results, min_overall=70)                              # core scores → 0–100
store = GenerationStore(db_path="qa.db", generations_dir="qa_generations/")          # core persists
store.record(assessment.as_dict(), run_id="run-1")                                   # → SQLite + git-SHA JSON
```

Community uses six dimensions on this core. Workspace reuses `glimi.edd` with deliverable / delegation / A2A dimensions. One framework powers both apps. Full spec: [`docs/qa_system.md`](docs/qa_system.md).

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
| **Community adapter** | `discord.py` with per-agent Webhook avatars |
| **Community image gen** (opt-in) | Local LoRA portrait via Animagine XL 4.0 (~6min/portrait, 186MB weights) |

---

## Roadmap

**Kernel extraction and packaging**
- ✅ Moved `community/core/{runtime, tools, memory, llm, conversation}` → `glimi/`; imports standalone, no Discord/DB.
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

- **Discord = adapter.** `community/core/*` never imports it. Community code lives in `community/bot/`, `community/scenes/`, `community/achievements/`, etc.
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
