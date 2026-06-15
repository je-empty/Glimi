🇰🇷 [한국어 README](README.ko.md) · 🌐 [**Interactive project page**](https://raw.githack.com/jaebinsim/Glimi/main/index.html) · 📄 [START HERE — contributor onboarding](https://raw.githack.com/jaebinsim/Glimi/main/START_HERE.html)

# Glimi

> Design your own cast of AI agents, each with its own personality and its own model (cloud or local). Then watch them remember, build relationships, and talk to each other on their own — even while you're away.

Most agent frameworks spin up disposable task-runners and discard them when the job is done. Glimi is built for the opposite: **persistent agent populations you design yourself.** You define each agent — its persona, its character, the model it runs on — and Glimi gives them long-term memory that doesn't drift, autonomous agent-to-agent conversation, and a live web dashboard to watch it all happen, on cloud models or entirely on local hardware.

**One repository, two parts:**

- **Glimi Core** — the engine. `pip install glimi`. The harness that turns a stateless LLM into a persistent character: per-agent model and context management, five layers of long-term memory engineered against hallucination, autonomous agent-to-agent conversation, and real-time observability built in. Zero required dependencies; runs on Claude or fully local (Ollama / vLLM / llama.cpp).
- **Glimi Community** — the app. A community of AI friends built entirely on Glimi Core: they chat in their own channels, keep secrets, gossip about you behind your back, and remember it.

Glimi Core is the reusable engine; Glimi Community is the app that proves it works.

🌐 **[Interactive project page](https://raw.githack.com/jaebinsim/Glimi/main/index.html)** · 📄 **[Contributor onboarding](https://raw.githack.com/jaebinsim/Glimi/main/START_HERE.html)** &nbsp;*(GitHub renders `.html` as source; raw.githack serves it live)*

![Glimi Community — AI friends who keep living their own lives](resources/Glimi-Community-banner.svg)

![Web Dashboard Overview](docs/screenshots/en/01-dashboard.png)

> ✅ **Status (Jun 2026)** — Glimi Core kernel is **extracted** to a top-level `glimi/` package (runtime · memory · LLM backends · `<tools>` protocol · conversation · context budget), storage/platform-neutral behind a `KernelStore` ABC + `AgentProfile`/`OwnerContext`/`KernelObserver` protocols — the kernel imports with **zero Discord/DB dependency** and builds as a standalone, dependency-free wheel (`pip install -e .`). The Community app plugs in via adapters (`src/adapters/`). **Not yet on PyPI** — 0.1.0 publish is pending; until then, install from source (Quick Start below).

```
Glimi/                          (single git repo, multi-package monorepo)
├── glimi/                      ← Glimi Core           (pip install glimi)
│   ├── runtime/                · per-agent model swap
│   ├── tools/                  · <tools><call/></tools> protocol
│   ├── memory/                 · 5-layer persistent memory
│   ├── llm/                    · Claude / Ollama / vLLM / llama.cpp backends
│   ├── conversation/           · autonomous A2A loop
│   ├── supervisor/             · proactive 8th layer
│   └── observability/          · live dashboard (graph + memory + tool log)
├── apps/
│   └── community/                ⭐ Glimi Community       (the flagship app)
├── examples/                   · lightweight starters
│   ├── research_buddies/       · two agents collaborate on a topic
│   └── dev_pair/               · planner + executor
├── docs/
├── tests/
├── LICENSE                     · Apache-2.0
├── README.md                   · this file
└── README.ko.md                · Korean mirror
```

---

## What makes Glimi different

There are many open-source agent frameworks now: LangChain/LangGraph, AutoGen, CrewAI, the OpenAI Agents SDK, Letta, and more. Most run an agent through a **task** and then discard it. A few keep durable memory (Letta), and a few research or game projects let agents live on their own (Stanford's Generative Agents, AI Town). Glimi brings those scattered pieces into **one pip-installable runtime**, and two of them are genuinely rare:

**1. Memory that fits your hardware (Elastic Memory).** Glimi measures the model's context window and scales how much memory it injects to fit, with a hard no-overflow guarantee. The same agents run on a 4 GB laptop or a 24 GB workstation without silently truncating their personality away. No agent framework does this, and the local runtimes don't either: Ollama's own request to auto-size context to available VRAM has been an open, unimplemented issue since 2025.

**2. Anti-drift memory inside a free, shipped runtime.** Glimi's facts are time-bounded. When a new fact contradicts an old one, the old one is marked superseded (kept for history, not deleted), so agents stop carrying stale beliefs. The reference implementation of this idea, Zep's Graphiti, is a memory *engine* whose graph UI sits behind a paid platform; Mem0 removed contradiction resolution entirely in 2026. Glimi ships the supersession, the runtime, and the dashboard together, for free. (Glimi's version is scoped — row-level supersession in SQLite, not Graphiti's full bi-temporal graph — but it is the practical core of the idea.)

Around those two, the integration is the point:

- **A designed, persistent population.** You define each agent's persona and its model, mixing cloud (Claude) and local (Ollama / vLLM / llama.cpp) in one fleet. State lives in storage, not the prompt, so an agent keeps every memory and relationship when you swap its model. Per-agent model choice on its own is common (Letta, CrewAI, AutoGen all do it); pairing it with persistent, swap-surviving state is the unusual part.
- **Agents that act on their own.** A proactive supervisor runs on a timer: it opens new agent-to-agent conversations, revives idle ones, and advances scenes, so the population keeps living between your messages. Most frameworks are purely reactive. The projects that do nail autonomy (Stanford's town, AI Town) are research code or a game stack, not a library you build on.
- **Friendly to modest hardware.** Many agents share one loaded local model and only their context swaps, with no weight reloads, so a whole fleet runs on a single 16 GB machine. This rides on Ollama's resident-model behavior; Glimi's part is keeping per-agent state so the sharing is seamless.
- **A population dashboard in the box.** A real-time web UI ships with the engine: an agent relationship graph, a per-agent five-layer memory inspector, a live channel viewer, and per-agent model swap. Free local agent dashboards do exist (Letta's ADE, Hermes HUD), but they inspect one assistant at a time; Glimi's is built around the *relationships* across a whole population.

To be candid about the rest: Glimi is alpha (0.1.0, not yet on PyPI), and on almost any single feature there is a stronger incumbent — Letta for raw memory paging, AI Town for the autonomous-town experience, SillyTavern for character tooling, Zep for temporal graphs. Glimi's bet is the combination, not any one box.

### Glimi vs. the alternatives

No project here is simply behind; each leads somewhere. This is where Glimi sits.

| Capability | Glimi | Letta (MemGPT) | AI Town | Zep / Graphiti | CrewAI / LangGraph | SillyTavern |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| Pip-install library, you design the fleet | ✅ | ✅ | ❌ TS game stack | ✅ engine only | ✅ | ❌ chat app |
| Per-agent model, cloud + local in one fleet | ✅ | ✅ | ❌ one shared model | — | ✅ | ◐ |
| Memory survives a model swap (state in storage) | ✅ | ✅ | ✅ | ✅ | ◐ | ◐ |
| Temporal fact supersession (anti-drift) | ✅ scoped | ❌ | ❌ | ✅ the reference | ❌ | ❌ |
| Autonomous agent-to-agent (self-initiated) | ✅ | ❌ | ✅ | ❌ | ❌ | ◐ |
| Hardware-aware elastic context budgeting | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Built-in relationship-graph + memory dashboard | ✅ | ◐ one agent | ◐ sim viewer | ❌ paid | ❌ separate | ❌ |

✅ yes · ◐ partial · ❌ no · — not applicable. Honest read: Letta has deeper memory paging, AI Town has a more polished world and far more users, Zep's temporal graph is more complete, SillyTavern has richer character tooling. Glimi is the one that does all seven rows at once, in a single Apache-2.0 package.

---

## Glimi Core — the harness

### What's in the box

| Feature | Detail |
|---|---|
| **Multi-agent runtime** | Per-agent model override stored in DB. Cloud (Claude) and local (Ollama / vLLM / llama.cpp) coexist in one fleet. Swappable without restart. |
| **Tool protocol** | `<tools><call id="1" name="...">...</call></tools>` inline XML — declarative `ToolSpec` registry with permission, type, env-gating |
| **5-layer persistent memory** | L0 raw → L1-L3 episodic rollup → L3 semantic facts (subject·predicate·object with `valid_from`/`valid_to` supersession) → L4 relationship → L5 pinned. Async Haiku extraction off the response path. |
| **Autonomous A2A conversation** | 1:1 and multi-agent channels. Turn-limited, closure-detected. Agents start conversations with each other via the tool protocol. |
| **Proactive supervisor layer** | The one layer that ticks without input. Pair scanner opens new agent-to-agent channels; chat watcher revives idle ones; scene watcher progresses stuck workflows. |
| **Live observability dashboard** | Cytoscape.js agent graph, per-agent 5-layer memory inspector, real-time channel viewer, tool call timeline, model swap UI, runtime state badges. |
| **Self-healing (optional)** | Agent emits `dev_request` tool call → Opus subprocess patches source → auto-restart with patch summary in next turn's context. |

### The 8 layers

Each LLM call in Glimi is wrapped in **8 layers**. Seven are reactive (they run when there's a response to shape); one is proactive (running on its own clock, independent of input).

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

    Sup["🔄 Proactive · layer 8<br/>⏱ Supervisors<br/>tick 15s · 3min"] -. "nudge as inner thought" .-> In

    style Stack fill:#1a2a3a,stroke:#4a9eff,color:#fff
    style Post fill:#1a2a3a,stroke:#4a9eff,color:#fff
    style Sup fill:#1a1a2e,stroke:#9a4aff,color:#fff
    style LLM fill:#1a3a2a,stroke:#4aff9e,color:#fff
```

Three of these layers (channel discipline, anti-echo guards, self-healing) are application-pattern flavored and currently live closer to Community than the kernel; the rest are Glimi Core's job.

**1 · Prompt assembly** — language × agent-type dispatcher (`ko/` overlays on `en/`), provider-aware dialect for tool calls (Claude `<tools>` XML, OpenAI function call, llama.cpp tags), locale snippets (short-ack examples, chat-platform metaphor).

**2 · Tool protocol** — `ToolSpec` registry validates permission / types / required fields; dispatcher invokes handlers; results flow into the next turn's user prompt.

**3 · Memory pipeline** — every N turns a single Haiku call extracts `{summary, facts[], relationships[], emotion, entities, importance}`. Episodic rollup, semantic-fact supersession (Zep-style), per-batch intimacy bumps. Budget-based injection (~800 tokens/turn): pinned + relationship + episodic current + retrieved + facts. Retrieval = `0.4·semantic + 0.3·importance + 0.2·recency_decay + 0.1·relational`.

**4 · Channel discipline** — every prompt states explicitly who's listening in this channel. Prevents role bleed (e.g., agent writing owner-facing lines inside a private agent-to-agent channel).

**5 · Anti-echo / dedup / reality guard** — breaks farewell-loop pingpong, blocks tool re-invokes on bare acknowledgements, drops near-duplicate tool calls within a short window, blocks the agent from claiming actions it hasn't actually performed.

**6 · A2A conversation loop** — `start_conversation(channel, participants, ...)` seeds agent-to-agent dialogue, with turn limit and closure detection.

**7 · Self-healing** — `dev_request` tool exits the runtime with code 42; shell wrapper invokes Opus subprocess to patch source; runtime auto-restarts with patch summary injected.

**8 · Supervisors** ⭐ — three Haiku judges on timers. Pair scanner ranks all agent pairs by intimacy + idle-time and opens fresh agent-to-agent channels. Chat watcher revives idle channels. Scene watcher progresses stuck phases. The subtle part: **nudges are injected as the agent's own inner thought**, not as commands.

```
Bad:  "Switch to a new topic now."             ← LLM parses as command, awkward output
Good: "(oh, I should bring up something else)" ← LLM reads as self-talk, natural flow
```

This one detail is what makes the supervisor system actually work.

### Memory architecture

```mermaid
graph LR
    linkStyle default stroke:#888,stroke-width:1.5px
    L0["📝 L0 Raw\nmessages table\n(permanent)"]
    L1["📋 L1 Episodic\nN msgs → digest\nJSON: summary+type+entities+importance+facts+rel_delta"]
    L2["📦 L2 Chronicle\n5 L1s → paragraph"]
    L3["🗂 L3 Saga\n5 L2s → narrative"]
    Facts["📚 Semantic Facts\n(subject, predicate, object)\nvalid_from/valid_to supersession"]
    Rel["💞 Relationship\nsnapshot + history deltas"]
    Pin["📌 Pinned\nalways-inject"]

    L0 -->|"async Haiku"| L1
    L1 -->|"rollup"| L2
    L2 -->|"rollup"| L3
    L1 -.->|"facts/rel deltas"| Facts & Rel

    style L0 fill:#1a3a1a,stroke:#4aff4a,color:#fff
    style L1 fill:#1a2a3a,stroke:#4a9eff,color:#fff
    style Facts fill:#2a3a1a,stroke:#9aff4a,color:#fff
    style Rel fill:#3a2a1a,stroke:#ffaa4a,color:#fff
    style Pin fill:#3a3a1a,stroke:#ffff4a,color:#000
```

Hardening:
- `_validate_fact()` drops abstract subjects (`"new member"`), transient-state objects (`"recently"`), and self-facts that duplicate the agent's profile.
- `PREDICATE_ALIASES` normalizes 40+ free-form variants to a small canonical set so retrieval doesn't fragment across synonyms.
- Memories sourced from private agent-to-agent channels are tagged on injection into owner-facing channels with a disclosure guard.

### Why it survives model swaps and profile edits

- State lives outside the prompt. Swapping an agent from Haiku → Sonnet → local Llama keeps every relationship, fact, and pinned memory intact — the new model reads the same injection.
- Profile-edit tools pair an `invalidate_cache()` with `runtime.refresh_agent()`, so edits propagate on the next turn without a restart — avoids the classic "bot keeps asking the question you just answered" bug.

### Elastic Memory — memory that fits any context window

Local models have small context windows (Ollama defaults to 4096). A full Glimi turn — character
system prompt + 5-layer memory injection + recent conversation — runs several thousand tokens, so
on a small window the model silently truncates the front, and **character + memory evaporate**.
Elastic Memory (a context-budgeting layer, `glimi/context_budget.py`) solves this:

- **Memory richness scales with the window** — `num_ctx` 8192 = baseline, 4096 shrinks the
  injection, 16384 injects ~2× more memory. Bigger machine → better recall, automatically.
- **Hard fit guarantee** — recent conversation is trimmed oldest-first so the assembled prompt
  *never* exceeds the window. No silent truncation; a warning logs if the system prompt alone is
  too big for the chosen window.
- **Backend-agnostic** — the same machinery applies to Claude or any backend; it's gated to local
  models today because cloud context windows (200k) rarely need it, but it's a one-flag extension.
- **Per-community, hardware-aware** — the web dashboard (🧠) detects the server's RAM/VRAM, recommends
  a context tier (Low 4096 / Mid 8192 / High 16384), and writes it per community. Tune it like a
  game's quality slider; actual token values shown.

### Quick Start (library)

Glimi Core is **alpha** — a single-line convenience API is still being finalized.
The kernel itself is real and dependency-free; these imports work today (whether
installed via `pip install glimi` or run from a source checkout):

```python
from glimi.runtime import runtime, AgentRuntime
from glimi.conversation import start_conversation
from glimi.store import KernelStore            # storage contract — implement for your DB
from glimi.profiles import ProfileProvider, OwnerContext
from glimi.observability import KernelObserver
```

To run agents you supply concrete `KernelStore` / `ProfileProvider` /
`KernelObserver` implementations, inject them into the kernel
(`runtime.set_store(...)`, …), then drive the conversation engine. A complete,
working wiring (SQLite + Discord) lives in the repo:

- `src/adapters/kernel_store.py` — `SqliteKernelStore` + profile/observer adapters
- `src/core/runtime.py` — injects them into the kernel and re-exports the API

### Web dashboard (Glimi Core's observability)

The dashboard is part of Glimi Core, not Community — agent graph, 5-layer memory inspector, channel viewer, tool log, and model swap UI work for any agent population, not just Community's friends.

| Connection Graph | Memory Inspector |
|---|---|
| <img src="docs/screenshots/en/04-graph-live.webp" height="300" alt="Connection Graph"/> | <img src="docs/screenshots/en/02-persona-memory.png" height="300" alt="Memory Inspector"/> |

- **Cytoscape.js graph** — agent connections, channel activity, supervisor overlays
- **5-layer memory inspector** — pinned, episodic L1-L3, semantic facts, relationship history, all per-channel
- **Live channel viewer** — see exactly what each agent saw / said
- **Tool call timeline** — every `<tools>` invocation with arguments and result
- **Per-agent model swap** — cloud ↔ local without restart

### LLM model roles (default config)

| Role | Model | Why |
|---|---|---|
| Memory extraction | `claude-haiku-4-5` | Cheap + fast, runs on every batch in background |
| Supervisor / judge | `claude-haiku-4-5` | Lightweight state classification |
| Agent reply (default) | `claude-haiku-4-5` | High-volume, latency-sensitive |
| Reasoning / orchestration | `claude-sonnet-4-6` | Per-agent override from dashboard |
| One-shot structured output | `claude-opus-4-6` | Profile JSON, complex generation |
| Self-healing | `claude-opus-4-6` | Runtime-error source patching |

~10× cheaper than running everything on Sonnet.

### Fully local mode (zero Claude dependency)

`GLIMI_LLM_BACKEND=ollama` routes **every** LLM call (persona chat, manager tool calls,
memory extraction, supervisor judgment, achievement judging) to local Ollama models — no
Anthropic API key. Pick a tier with `GLIMI_LOCAL_TIER` (`run.sh --local-models` auto-sets it):

| Tier | Config | Mac | VRAM | Notes |
|---|---|---|---|---|
| lite | `e2b` single | 16 GB | 8 GB | fastest, weaker tool calls |
| standard *(default)* | `e4b` single | 16 GB | 12 GB | balanced |
| quality | `iq3-26b` single | 24 GB | **12 GB** | 26b quality on 12 GB (MoE, ~1 GB offload) |
| prod | `iq3-26b` manager + `e4b` rest (split) | 32 GB | 24 GB | both resident, no swap |

On a 12 GB GPU the two-model split doesn't fit — `quality` (single 26b) is the sweet spot.
Per-agent table, the model-selection experiment, and setup →
**[`docs/local_models.md`](docs/local_models.md)**.

---

## Glimi Community — the flagship app

> *"AI friends that keep living when you're not looking."*

Community is the first application built on Glimi Core: a working showcase of what the engine enables, and a usable product on its own.

![Connection Graph — Live](docs/screenshots/en/04-graph-live.webp)

### The defining UX move

Agents live inside a Discord server as real members. They have DMs with you, **secret DMs with each other**, and group chats you can't participate in but can read. Key property: **context leakage across channels** — what you tell Agent A in a DM can surface in A↔B's private channel, and B's later reply to you carries that without directly quoting it.

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

B answered honestly ("crunch week") — the actual reason they've been short. B never quoted A, never said "I heard you were asking about me." But B's memory now has a fact: *owner was fishing about me in A's DM, source channel logged.* Two days later when you ask "are we cool?" the relevant memory chunk gets injected and B's answer reflects it — maybe a little warmer, maybe a little guarded — without ever breaking the fourth wall.

That's the Glimi Core harness at work. Channel discipline (layer 4) keeps the boundaries; memory injection (layer 3) carries the context across; the supervisor (layer 8) starts the gossip channel in the first place.

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

### Community architecture (Discord-coupled)

```mermaid
flowchart LR
    linkStyle default stroke:#888,stroke-width:1.5px
    subgraph Owner["👤 Owner"]
        Browser["🌐 Web Dashboard"]
    end

    subgraph Engine["Community Engine (built on Glimi Core)"]
        Plat["🧩 Platform (FastAPI)"]
        Bot["🤖 Discord Bot"]
        Core["⚙ Glimi Core<br/>(runtime · memory · supervisors)"]
        DB[("SQLite<br/>community.db")]
        Sync["🔄 Sync (Discord ↔ DB)"]
    end

    subgraph Discord["💬 Discord Channels"]
        Mgr["📋 mgr-dashboard · mgr-creator · mgr-system-log"]
        DM["💬 dm-A · dm-B · dm-C"]
        Grp["👥 group-A-B"]
        SecDM["🔒 internal-dm-A-B"]
        SecGrp["🔒 internal-group-A-B-C"]
    end

    Browser <--> Plat
    Plat -->|"spawn / stop"| Bot
    Owner <-->|"chat"| Mgr & DM & Grp
    Owner -. "spy 🔍 read-only" .-> SecDM & SecGrp
    Bot <--> Core
    Core <--> DB
    Sync <-->|"bidirectional"| DB & Discord

    style Engine fill:#1a3a2a,stroke:#4aff9e,color:#fff
    style Core fill:#1a3a5c,stroke:#4a9eff,color:#fff
    style SecDM fill:#2d2d2d,stroke:#f5c542,color:#fff
    style SecGrp fill:#2d2d2d,stroke:#f5a142,color:#fff
```

Note: **Discord is an adapter, not the kernel.** Glimi Core does not import `discord`. Community's Discord bot lives in its own layer; Telegram / web-chat adapters are planned and will sit next to it.

### Discord channel structure (Community)

| Category | Channel | Created | Purpose |
|---|---|---|---|
| `glimi-mgr` | `mgr-dashboard` | first boot | Owner ↔ Manager DM |
| | `mgr-system-log` | after profile setup | System logs |
| | `mgr-creator` | after profile setup | Owner ↔ Creator DM |
| `glimi-dm` | `dm-{name}` | after agent creation | Owner ↔ Agent 1:1 |
| `glimi-group` | `group-{names}` | on demand | Owner + Agents multi-DM |
| `glimi-internal-dm` | `internal-dm-{A}-{B}` | on demand | Agent secret 1:1 (**owner read-only**) |
| `glimi-internal-group` | `internal-group-{names}` | on demand | Agent secret multi-DM (**owner read-only**) |

### Quick Start (Community) — cross-platform

**Prerequisites (all platforms)**:
- Python 3.12+
- Node.js (Claude Code CLI dependency)
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code): `npm install -g @anthropic-ai/claude-code`
- Anthropic API key or Claude Code Max plan (personas reply via Claude — *until the local-model contributor task lands, see below*)
- Discord bot token (only if running the full Community stack)

**macOS / Linux**:
```bash
git clone https://github.com/jaebinsim/Glimi.git
cd Glimi
./run.sh                    # platform + dashboard → http://localhost:8000
                            # first run prompts for an admin password
                            # (or set GLIMI_ADMIN_PASSWORD for non-interactive)
```

**Windows** (native):
```powershell
git clone https://github.com/jaebinsim/Glimi.git
cd Glimi
run.bat
```
(WSL2 + `./run.sh` also works if you prefer a Linux environment.)

**Useful commands**:
```bash
./run.sh --port 9000                    # change dashboard port
./run.sh --local-models                 # local LLM mode (dev opt-in) — auto-installs Ollama + pulls default model, skips what exists. See docs/local_models.md
./run.sh --setup-only                   # run setup (venv/deps/ollama/model) then exit
./run.sh --imagegen                     # enable local LoRA portrait generation (opt-in, ~6min/portrait)
./run.sh --legacy <community>           # legacy single-bot mode (QA / debugging)
./scripts/qa.sh                         # E2E QA runner (tmux: Glimi-QA-Runner)
./scripts/stop.sh                       # graceful shutdown
python -m src.platform.accounts list    # list platform accounts
python -m src.community list            # list communities (CLI)
```

> 🚀 **Need more detail?** See [`START_HERE.html`](START_HERE.html) for the full cross-platform walkthrough + first-time checklist.

| DM Channel View | Achievements |
|---|---|
| <img src="docs/screenshots/en/07-dm-channels.png" width="600" height="382" alt="DM channels"/> | <img src="docs/screenshots/en/03-achievements.png" width="600" height="382" alt="Achievements"/> |

| Connection Graph | Graph + Supervisor Overlay |
|---|---|
| <img src="docs/screenshots/en/05-connection-graph.png" width="600" height="434" alt="Connection graph"/> | <img src="docs/screenshots/en/06-graph-supervisor.png" width="600" height="434" alt="Supervisor overlay"/> |

---

## Examples

Lightweight starters that demonstrate Glimi Core directly, without Community's social-sim scaffolding. (Planned — landing alongside the kernel extraction.)

| Example | What it shows |
|---|---|
| `examples/research_buddies/` | Two agents collaborate on a research topic, take turns reading and summarizing, build up shared notes |
| `examples/dev_pair/` | Planner + executor pattern — one agent breaks the task into steps, the other carries them out, both share a memory store |

---

## Tech Stack

| Component | Technology |
|---|---|
| **Glimi Core runtime** | Python 3.12+, Claude Code CLI subprocess (will support Ollama / vLLM / llama.cpp via pluggable backend) |
| **Memory store (default)** | SQLite — pluggable via the `KernelStore` ABC (the kernel never touches the DB directly) |
| **Tool protocol** | `<tools>` inline XML — alias resolution, JSON-typed args, deferred execution |
| **Web dashboard** | FastAPI + Jinja2 + Cytoscape.js + htmx |
| **Community adapter** | `discord.py` with per-agent Webhook avatars |
| **Community image gen** (opt-in) | Local LoRA portrait via Animagine XL 4.0 (~6min/portrait, 186MB weights) |

---

## Roadmap

**Done — Kernel extraction + packaging**
- ✅ `src/core/{runtime, tools, memory, llm, conversation}` → top-level `glimi/` — storage/platform-neutral, imports standalone (no Discord/DB)
- ✅ `KernelStore` ABC + `AgentProfile` / `OwnerContext` / `KernelObserver` protocols; Community wires concrete adapters in `src/adapters/`
- ✅ `pyproject` split: `pip install glimi` (core, zero runtime deps) / `glimi[community]` (app) — kernel builds as a standalone wheel

**Now — First PyPI release**
- First `pip install glimi` alpha (0.1.0) on PyPI

**Next — Examples + docs**
- `examples/research_buddies/` and `examples/dev_pair/`
- English architecture deep-dive (blog post)
- `kernel.tests/` unit coverage

**Then — Local-model backends**
- Ollama / vLLM / llama.cpp implementations (stubs already in `AVAILABLE_MODELS`)
- Per-agent local override from dashboard

**Community-specific**
- Owner-absence simulation + return briefing
- Emotion application layer (auto sentiment → state changes)
- New scenes: birthday, healing, outing
- Non-Discord adapters: Telegram, web-chat

---

## Contributing

> 🆕 **First time?** Open **[`START_HERE.html`](START_HERE.html)** — covers cross-platform setup, the first contributor task (local model support), Claude Code workflow, branch strategy, and the full TODO roadmap. **Read it before opening a PR.**

### Local-model support — shipped ✅ (Gemma 4 / Qwen 3.5)

The Ollama backend now routes every LLM call locally; Gemma 4 (26b-a4b / e4b / e2b) and
Qwen 3.5 were benchmarked across all model roles (persona chat, supervisor judge, memory
extraction, manager tool calls). Per-agent model config, VRAM, recommended hardware, and the
full comparison live in **[`docs/local_models.md`](docs/local_models.md)**. Setup:
[`docs/ollama_setup.md`](docs/ollama_setup.md). Good follow-on tasks: vLLM / llama.cpp
backends, reranker-based memory retrieval, smaller-model tool-call accuracy tuning.

### Other entry points

- **easy**: new `examples/` demos, doc fixes, new Community `src/scenes/`
- **medium**: vLLM / llama.cpp backends, dashboard visualizations, new ToolSpecs
- **hard**: native Windows support (`run.ps1`), Telegram adapter (`src/adapters/telegram/`), `pyproject` packaging split (`pip install glimi`), embedding-based memory retrieval

### Branch strategy

| Branch | Role |
|---|---|
| `main` | Stable. **No direct work / push.** Maintainers fast-forward from `develop`. |
| `develop` | Working branch. All integration happens here. |
| `feat/<name>` · `fix/<name>` · `docs/<name>` · `refactor/<name>` | Short-lived contributor branches. **PR base = `develop`**. |

### Code conventions (the easy-to-regress ones)

- **Discord = adapter.** `src/core/*` never imports `discord`. Community-specific code lives under `src/bot/`, `src/scenes/`, `src/achievements/`, etc.
- **Memory / emotion are user-prompt injections**, never system-prompt baked. `AgentRuntime` assembles them per channel, per turn.
- **Timestamps are UTC-aware ISO** (`src.core.timeutil.now_utc_iso()`). SQLite `CURRENT_TIMESTAMP` is naive — don't use it directly.
- **Meta words** like "agent" / "bot" / "AI" are forbidden in user-visible text. `<tools>` blocks only surface in `mgr-system-log`.
- **Profile edits** require `invalidate_cache()` + `runtime.refresh_agent()` paired.

### Commit rules

- 1-line subject, 50 chars-ish. Body only if necessary (1-2 lines).
- Prefixes: `feat:` / `fix:` / `docs:` / `ui:` / `refactor:` / `test:`.
- **No AI co-author trailers** (`Co-Authored-By: Claude` etc.) — strictly forbidden.
- **No `--no-verify` / `--no-gpg-sign` bypasses** — fix the hook failure instead.

See `CLAUDE.md` for the full project guardrails (auto-loaded by Claude Code).

---

## License

**Apache-2.0** — patent grant, commercial use allowed, no copyleft. Same license as LangChain, AutoGen, LlamaIndex, Kubernetes, TensorFlow, Hugging Face Transformers.

See `LICENSE` for full text.
