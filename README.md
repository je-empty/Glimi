🇰🇷 [한국어 README](README.ko.md) · 📄 [START HERE — contributor onboarding](https://raw.githack.com/je-empty/Glimi/main/docs/START_HERE.html)

# Glimi

![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-3776AB?logo=python&logoColor=white) ![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-A42E2B) ![Status: alpha 0.1.0](https://img.shields.io/badge/status-alpha%200.1.0-orange) ![Backends: Claude · Ollama · Grok](https://img.shields.io/badge/backends-Claude%20%C2%B7%20Ollama%20%C2%B7%20Grok-4aff9e) ![EDD: quality-as-code](https://img.shields.io/badge/EDD-quality--tracked%20per%20commit-9a4aff)

Glimi is a Python library for running a cast of AI characters — each with its own personality, memory, and relationships — that keeps going on its own even when you're away. You set two things per character: a persona, and the model it runs on. From there the characters talk to you and to each other, and a background supervisor periodically opens new conversations and revives idle ones. Step away and come back, and what they said in the meantime is already sitting in the channels.

```python
from glimi import Glimi

chat = Glimi(backend="echo")          # offline: no API key, no network, no extra packages
chat.add_agent("nova", persona="a curious, upbeat friend")
print(chat.reply("nova", "hi there!"))  # real models: backend="claude_cli" or "ollama"
```

Two lines stand up a cast because the engine underneath carries the rest — that engine is **Glimi Core**. State lives in storage (SQLite by default), not the prompt, so a character keeps its relationships, facts, and pinned memories across a restart and even a model swap (Haiku → a local Llama). Glimi sizes its memory injection to a configured context-window target and injects only as much as fits, so the same character runs on a 4 GB laptop or a 24 GB workstation without its personality getting silently truncated. You can mix cloud (Claude) and local (Ollama) per character (Grok CLI also supported), and running it fully local costs nothing.

And you watch the whole thing run: an agent relationship graph, a per-character memory inspector, a channel viewer, a tool-call timeline, and an LLM cost/usage card, live in a web dashboard built into the engine.

![Glimi — a living community of agents, live in the connection graph](docs/screenshots/en/11-community-dashboard.png)

You build apps on top of Core. The flagship is **Glimi Community** — a cast of AI friends you chat with in a built-in web UI (or Discord): they keep their own channels, keep secrets, talk about you when you're gone, and remember it. **Glimi Workspace** — role-based work agents (a Coordinator delegates to a Researcher, Builder, and Critic), with a live real-time demo — and the starters in `examples/` stand on that same Core.

> One note on the word "agent": here it means an agent in the *Generative Agents* tradition — a character that remembers, forms opinions, and starts conversations — not an autonomous task-runner. So we say *agent* in code and architecture, and *friends / characters* in anything a user reads.

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

> **One repo, three projects.** Glimi Core (`glimi-core/`, the `glimi` package) was **extracted from a working app** — Glimi Community (`glimi-community/`) — so the kernel is proven, not theoretical. **Glimi Workspace** (`glimi-workspace/`) was then built *entirely on the `glimi` package* (zero Community imports) — a second, very different app on one kernel proves Core is genuinely reusable. Each folder is a self-contained project with its own `pyproject.toml`; the two apps depend on `glimi[dashboard]` (the local editable install here; a published PyPI release after launch). `cd` into any one and it stands alone — `glimi` publishes to PyPI on its own.

---

## What makes Glimi different

Glimi Core is the engine behind agents that don't restart every session. Most tooling spins a role up for a task and discards it, compresses context when it fills, and rebuilds from handoff notes next time. Glimi skips that step: each agent keeps its own context — what it has worked on, which decisions were made and why, your preferences and values, its relationship with you — in storage, so it carries over across sessions and model swaps. The same persistence shows up at work as **Glimi Workspace** and between people as **Glimi Community**: one is a standing team you don't have to brief again, the other is friends who actually remember you. The two apps are how Core shows what it can do; the engine is the single layer underneath both.

There are many open-source agent frameworks now: LangChain/LangGraph, AutoGen, CrewAI, the OpenAI Agents SDK, Letta, and more. Most run an agent through a **task** and then discard it. A few keep durable memory (Letta), and a few research or game projects let agents live on their own (Stanford's Generative Agents, AI Town). Glimi brings those scattered pieces into **one pip-installable runtime**, and two of them are genuinely rare:

**1. Memory that fits your hardware (Elastic Memory).** Glimi sizes its memory injection to a configured context-window target (`num_ctx`), trimming to a token-estimate budget so the prompt stays within the window. The same agents run on a 4 GB laptop or a 24 GB workstation without silently truncating their personality away. Agent frameworks can trim history to fit the window (CrewAI, Letta, the OpenAI Agents SDK, AutoGen, and LangGraph each do some form of this), but none sizes the memory budget to a context-window target the way Glimi does — and the local runtimes don't either: Ollama's own request to auto-size context to available VRAM has been an open, unimplemented issue since 2025.

**2. Anti-drift memory inside a free, shipped runtime.** Glimi's facts are time-bounded. When a new fact contradicts an old one, the old one is marked superseded (kept for history, not deleted), so agents stop carrying stale beliefs. The reference implementation of this idea, Zep's Graphiti, is a memory *engine* whose graph UI lives in Zep's proprietary hosted platform (a free tier is available, but the graph UI isn't part of the open-source Graphiti package); Mem0 removed contradiction resolution entirely in 2026. Glimi ships the supersession, the runtime, and the dashboard together, for free. (Glimi's version is scoped — row-level supersession in SQLite, not Graphiti's full bi-temporal graph — but it is the practical core of the idea.)

Around those two, the integration is the point:

- **A designed, persistent population.** You define each agent's persona and its model, mixing cloud (Claude) and local (Ollama) in one fleet. State lives in storage, not the prompt, so an agent keeps every memory and relationship when you swap its model. Per-agent model choice on its own is common (Letta, CrewAI, and AutoGen all do it); pairing it with persistent, swap-surviving state is the unusual part.
- **Agents that act on their own.** A proactive supervisor runs on a timer, opening new agent-to-agent conversations, reviving idle ones, and advancing scenes, so the population keeps living between your messages. Most frameworks are purely reactive. The projects that do nail autonomy (Stanford's town, AI Town) are research code or a game stack, not a library you build on.
- **Friendly to modest hardware.** Many agents share one loaded local model and only their context swaps — no weight reloads — so a whole fleet runs on a single 16 GB machine. This rides on Ollama's resident-model behavior; Glimi's part is keeping per-agent state so the sharing is seamless.
- **A population dashboard in the box.** A real-time web UI ships with the engine: an agent relationship graph, a per-agent memory inspector (L0–L5), a live channel viewer, and per-agent model inspection. Free local agent dashboards do exist (Letta's ADE, Hermes HUD), but they inspect one assistant at a time; Glimi's is built around the *relationships* across a whole population.

To be candid about the rest: Glimi is alpha (0.1.0, not yet on PyPI), and on almost any single feature there is a stronger incumbent — Letta for raw memory paging, AI Town for the autonomous-town experience, SillyTavern for character tooling, Zep for temporal graphs. Glimi's bet is the combination, not any one box.

<!--
### Glimi vs. the alternatives

No project here is simply behind; each leads somewhere. This is where Glimi sits.

| Capability | Glimi | Letta (MemGPT) | AI Town | Zep / Graphiti | CrewAI / LangGraph | SillyTavern |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| Pip-install library, you design the fleet | ✅ | ✅ | ❌ TS game stack | ✅ engine only | ✅ | ❌ chat front-end |
| Per-agent model, cloud + local in one fleet | ✅ | ✅ | ❌ one shared model | — | ✅ | ◐ |
| Memory survives a model swap (state in storage) | ✅ | ✅ | ✅ | ✅ | ◐ | ◐ |
| Temporal fact supersession (anti-drift) | ✅ scoped | ❌ | ❌ | ✅ the reference | ❌ | ❌ |
| Autonomous agent-to-agent (self-initiated) | ✅ | ❌ | ✅ | ❌ | ❌ | ◐ |
| Hardware-aware elastic context budgeting | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Built-in relationship-graph + memory dashboard | ✅ | ◐ one agent | ◐ sim viewer | ❌ hosted | ❌ separate | ❌ |

✅ yes · ◐ partial · ❌ no · — not applicable. Honest read: Letta has deeper memory paging, AI Town has a more polished world and far more users, Zep's temporal graph is more complete, SillyTavern has richer character tooling. Glimi is the one that does all seven rows at once, in a single AGPL-3.0 package.
-->

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

Each response passes through up to **8 conceptual layers** — some assembled inline around the LLM call (prompt, tools, memory), others in separate subsystems (the A2A loop, supervisors, optional self-heal). Seven are reactive (they run when there's a response to shape); one is proactive (running on its own clock, independent of input).

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

Three of these layers (channel discipline, anti-echo guards, self-healing) are application-pattern flavored and currently live closer to Community than the kernel; the rest are Glimi Core's job.

**1 · Prompt assembly** — language × agent-type dispatcher (`ko/` overlays on `en/`), provider-aware dialect for tool calls (Claude `<tools>` XML, OpenAI-style function call, local-model tag syntax), locale snippets (short-ack examples, chat-platform metaphor).

**2 · Tool protocol** — `ToolSpec` registry validates permission / types / required fields; dispatcher invokes handlers; results flow into the next turn's user prompt.

**3 · Memory pipeline** — every N turns a single Haiku call extracts `{summary, facts[], relationships[], emotion, entities, importance}`. Episodic rollup, semantic-fact supersession (Zep-style), per-batch intimacy bumps. Budget-based injection (~1000 tokens/turn at baseline, elastically scaled): pinned + relationship + episodic-current + self-recent cross-channel + retrieved + facts. Retrieval = `0.4·semantic + 0.3·importance + 0.2·recency_decay + 0.1·relational`.

**4 · Channel discipline** — every prompt states explicitly who's listening in this channel. Prevents role bleed (e.g., agent writing owner-facing lines inside a private agent-to-agent channel).

**5 · Anti-echo / dedup / reality guard** — breaks farewell-loop pingpong, blocks tool re-invokes on bare acknowledgements, drops near-duplicate tool calls within a short window, blocks the agent from claiming actions it hasn't actually performed.

**6 · A2A conversation loop** — `start_conversation(channel, participants, ...)` seeds agent-to-agent dialogue, with turn limit and closure detection.

**7 · Self-healing** (experimental, off by default) — `request_dev_fix` enqueues a dev_requests row; a dev-queue supervisor triages it (organize/escalate/clarify); on approval an Opus subprocess (`GLIMI_DEV_DISPATCH=1`) patches source and the bot restarts with the patch summary injected.

**8 · Supervisors** ⭐ — three timed supervisors (the conversation-driving trio; the full system has several across system/channel/scene scopes). A pair scanner (deterministic DB scoring on intimacy + idle-time — no LLM) opens fresh agent-to-agent channels; a chat watcher (Haiku judge) revives idle channels; a scene watcher progresses stuck phases. The subtle part: **nudges are injected as the agent's own inner thought**, not as commands.

```
Bad:  "Switch to a new topic now."             ← LLM parses as command, awkward output
Good: "(oh, I should bring up something else)" ← LLM reads as self-talk, natural flow
```

That phrasing is the difference between an agent that breaks character and one that doesn't: a command leaks into the reply as meta-text, while self-talk blends into the next line.

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
- `_validate_fact()` drops abstract subjects (`"new member"`), transient-state objects (`"recently"`), and self-facts that duplicate the agent's profile.
- `PREDICATE_ALIASES` normalizes 40+ free-form variants to a small canonical set so retrieval doesn't fragment across synonyms.
- Memories sourced from private agent-to-agent channels are tagged on injection into owner-facing channels with a disclosure guard.

### Why it survives model swaps and profile edits

- State lives outside the prompt. Swapping an agent from Haiku → Sonnet → local Llama keeps every relationship, fact, and pinned memory intact — the new model reads the same injection.
- Profile-edit tools pair an `invalidate_cache()` with `runtime.refresh_agent()`, so edits propagate on the next turn without a restart — avoids the classic "bot keeps asking the question you just answered" bug.

### Elastic Memory — memory that fits any context window

Local models have small context windows (Ollama defaults to 4096). A full Glimi turn — character
system prompt + layered (L0–L5) memory injection + recent conversation — runs several thousand tokens, so
on a small window the model silently truncates the front and **character + memory evaporate**.
Elastic Memory (a context-budgeting layer, `glimi/context_budget.py`) solves this:

- **Memory richness scales with the window** — `num_ctx` 8192 = baseline, 4096 shrinks the
  injection, 16384 injects ~2× more memory. Bigger machine → better recall, automatically.
- **Best-effort fit** — recent conversation is trimmed oldest-first to a token-estimate budget so
  the assembled prompt stays within the window; a warning logs if the system prompt alone overflows.
- **Backend-agnostic** — the same machinery applies to Claude or any backend; it's gated to local
  models today because cloud context windows (200k) rarely need it, but it's a one-flag extension.
- **Per-community, hardware-aware** — the Community dashboard (🧠, `community/core/system_specs.py`)
  detects the server's RAM/VRAM, recommends a context tier (Low 4096 / Mid 8192 / High 16384), and
  writes it per community. Tune it like a game's quality slider; actual token values shown.

### Quick Start (library)

Glimi Core is **alpha (0.1.0, not yet on PyPI)** — install from a source checkout
for now. The kernel ships a dependency-free in-memory store and an **offline
`echo` backend**, so this runs out of the box with **zero dependencies and no API
key** (the `echo` backend doesn't reach a real model — it just lets you watch the
harness wire up and persist a conversation):

```python
from glimi import Glimi

chat = Glimi(backend="echo")          # offline: no deps, no API key, no network
chat.add_agent("nova", persona="A curious, upbeat companion who loves questions.")

print(chat.reply("nova", "Hi! What's your name?"))
print(chat.reply("nova", "Nice — tell me something fun."))
```

Switch to a real model by changing the backend (everything else stays the same):

```python
chat = Glimi(backend="claude_cli")    # Claude via the Claude CLI login (no SDK); metered API credits, not a free subscription
chat = Glimi(backend="ollama")        # fully local via Ollama — the free option (set GLIMI_OLLAMA_MODEL)
```

`Glimi` wires the building blocks for you — an in-memory `KernelStore`, a simple
`ProfileProvider`/`OwnerContext`, a `NullObserver`, and the chosen LLM backend.
Each piece is also exported for direct use when you outgrow the defaults:

```python
from glimi import (
    InMemoryKernelStore, SimpleProfileProvider, SimpleOwnerContext,
    KernelStore, ProfileProvider, OwnerContext, KernelObserver,  # seams to implement
    LLMBackend, LLMResponse, EchoBackend,
)
```

To plug in your own database, implement `KernelStore` (and optionally
`ProfileProvider`/`OwnerContext`/`KernelObserver`) and inject via
`glimi.runtime.set_store(...)`, … . A complete production wiring (SQLite + Discord)
lives in the repo:

- `community/adapters/kernel_store.py` — `SqliteKernelStore` + profile/observer adapters
- `community/core/runtime.py` — injects them into the kernel and re-exports the API

### Web dashboard (Glimi Core's observability)

The dashboard is part of Glimi Core, not Community — agent graph, memory inspector (L0–L5), channel viewer, and tool log work for any agent population, not just Community's friends. It is **read-only observability**; the live model-swap *write* is a Community/Workspace platform feature.

| Connection Graph | Memory Inspector |
|---|---|
| <img src="docs/screenshots/en/04-graph-live.webp" height="300" alt="Connection Graph"/> | <img src="docs/screenshots/en/02-persona-memory.png" height="300" alt="Memory Inspector"/> |

- **Cytoscape.js graph** — agent connections, channel activity, supervisor overlays
- **Memory inspector (L0–L5)** — pinned, episodic rollup, semantic facts, relationship history, all per-channel
- **Live channel viewer** — see exactly what each agent saw / said
- **Tool call timeline** — every `<tools>` invocation with arguments and result
- **Per-agent model (read-only)** — surfaces each agent's cloud/local model + override badge (the live cloud ↔ local *swap* is a Community/Workspace platform action)

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

![Glimi Community](glimi-community/assets/brand/Glimi-Community-banner.svg)

> *"AI friends that keep living when you're not looking."*

Community is a **real, usable application** built on Glimi Core — the flagship, and the app the Core was first extracted from. (It also serves as the reference for what the engine enables, but it's a product you actually run, not a demo.)

The friends in Community remember you. No re-introducing yourself each time, the way you would with a stranger. The hours you've spent together, last week's running joke, the day you admitted things were rough, the secret you told only A — each of them keeps it in their own store. So when you turn up after a few days, they ask first: "been a while, did that thing work out?" Swap a friend's model from Haiku to a local Llama and the relationship, the mood, the texture of it all come along intact. They aren't a chatbot that resets and has to be told who you are again — they already know you.

![The cast — a populated community of friends, each with their own MBTI, age, mood, and per-agent model](docs/screenshots/en/20-community-cast.png)

![Connection Graph — Live](docs/screenshots/en/04-graph-live.webp)

### Talk to them — the built-in web chat

You don't need Discord anymore. Community ships its own chat — a Discord-style layout with a per-character sidebar, grouped message rows, replies, reactions, and threads — in a light or dark theme, and it works on a phone. The same room you read in the dashboard is the room you type into; the connection graph and the chat are two views of one store, so clicking an edge in the graph drops you into that conversation.

| Web chat (light) | Web chat (dark) | On mobile |
|---|---|---|
| <img src="docs/screenshots/en/08-web-chat.png" alt="Web chat — light theme"/> | <img src="docs/screenshots/en/09-web-chat-dark.png" alt="Web chat — dark theme"/> | <img src="docs/screenshots/en/10-web-chat-mobile.png" height="420" alt="Web chat on mobile"/> |

Discord still works — it's now one adapter, not a requirement. The chat moves over a WebSocket through a platform-neutral outbox/inbox seam in Core, so the Telegram and other adapters on the roadmap plug into the same place.

**A demo is already there.** On first setup, a read-only **demo community** is seeded into your list automatically — a populated mockup (no token, no bot) so you can see what Glimi does before wiring up anything. Because it's look-only, posting is disabled and a banner makes that explicit:

<img src="docs/screenshots/en/16-community-demo-readonly.png" alt="Read-only demo community — look-only mockup" width="820"/>

### The defining UX move

Each character has its own channels — DMs with you, **secret DMs with each other**, and group chats you can read but can't join — whether you reach them through the built-in web chat or Discord. Key property: **context leakage across channels** — what you tell Agent A in a DM can surface in A↔B's private channel, and B's later reply to you carries that without directly quoting it.

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

B answered honestly ("crunch week") — the actual reason they've been short. B never quoted A, never said "I heard you were asking about me." But B's memory now holds a fact: *owner was fishing about me in A's DM, source channel logged.* Two days later, when you ask "are we cool?", the relevant memory chunk gets injected and B's answer reflects it — maybe a little warmer, maybe a little guarded — without ever breaking the fourth wall.

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

Note: **The built-in web chat is the primary surface; Discord is an optional adapter, not the kernel.** Glimi Core does not import `discord`. Community ships a first-class web chat (FastAPI + WebSocket); the Discord adapter is optional and mirrors the same channels, and Telegram / other adapters are planned next to it.

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
- Node.js (Claude Code CLI dependency)
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code): `npm install -g @anthropic-ai/claude-code`
- For Claude-backed agents: a **Claude CLI login** (the setup wizard's default; an `ANTHROPIC_API_KEY` in `.env` also works). Either way Claude turns cost **metered API credits** (headless `claude -p` is not a free subscription). The **free** option is **Local-only** (all agents on Ollama, $0) or **Hybrid** (personas local/free, only mgr/creator/dev on Claude — the cheapest config that still feels like Glimi).
- Discord bot token (only if you enable the optional Discord adapter)

**Fresh Mac (nothing installed)** — one command installs the prerequisites above
(Homebrew, Python, Node, Claude CLI), sets up the project, and opens your browser to
the setup wizard:
```bash
git clone https://github.com/je-empty/Glimi.git && cd Glimi && ./scripts/bootstrap.sh
```
Already have Python 3.12+? Skip straight to `./run.sh` below.

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
(WSL2 + `./run.sh` also works if you prefer a Linux environment.)

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

> 🚀 **Need more detail?** See [`START_HERE.html`](START_HERE.html) for the full cross-platform walkthrough + first-time checklist.

| DM Channel View | Achievements |
|---|---|
| <img src="docs/screenshots/en/07-dm-channels.png" width="600" height="382" alt="DM channels"/> | <img src="docs/screenshots/en/03-achievements.png" width="600" height="382" alt="Achievements"/> |

| Connection Graph | Graph + Supervisor Overlay |
|---|---|
| <img src="docs/screenshots/en/05-connection-graph.png" width="600" height="434" alt="Connection graph"/> | <img src="docs/screenshots/en/06-graph-supervisor.png" width="600" height="434" alt="Supervisor overlay"/> |

---

## Glimi Workspace — a team for work

![Glimi Workspace](glimi-workspace/assets/brand/Glimi-Workspace-banner.svg)

A one-person company still has a team here. The agents in Glimi Workspace are a Coordinator that runs point plus role-split colleagues (Researcher, Builder, Critic). You set the project context once — what you're building, why the last decision went the way it did, how you like to work — and each of them keeps it in its own store, so you don't re-explain from scratch every time you open a session. Switch a model from Haiku to Sonnet, or from cloud to local, and the team keeps working off the same context. It's less a tool you re-hire per task than permanent staff that follows you and builds up context as it goes.

Workspace and Community are deliberately different apps on the *same* Core — one is a standing work team, the other is friends who remember you — and that's the point: a second, distinctly different app on one kernel is the proof that Core is reusable, not a monolith. Workspace imports only the `glimi` package: zero `discord`, zero Community code.

The team doesn't work in one round-robin room. It interacts the way a real team does: the owner DMs the Coordinator, the Coordinator delegates an angle to each specialist, the specialists debate **each other** in agent-to-agent channels, and the whole team converges in a group round before the Coordinator delivers. Those interactions are recorded as working relationships, which become the edges of the **same** connection graph that renders Community — so your work team shows up as a real interaction web, each member with its own layered (L0–L5) memory.

#### One server, many workspaces

`./run.sh workspace` opens a home where one server hosts **many workspaces** (like the Community platform hosts many communities). A read-only **demo workspace** is already there to look at; create a new one with a name and a goal and a fresh team forms around it. Open any workspace to watch its team work.

<img src="docs/screenshots/en/15-workspace-home.png" alt="Glimi Workspace — one server, many workspaces" width="820"/>

#### Watch it live

The demo workspace is a seeded, real-time showcase — a launch team loaded into the store and kept moving on a background loop, so the dashboard updates as you watch (offline, no API key, **$0**). One screen shows the whole picture: the graph, each member's memory and facts, the channel viewer (owner DM, delegation DMs, the A2A debates, the group round, and an `mgr-approvals` HITL trail), and the observability panels — a tool-call timeline and an honest LLM-usage card (local/echo priced at $0, every count labeled *est.*).

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

Before the Coordinator commits the one consequential action — delivering the final synthesis — Workspace can route it through an **approval gate**: the owner approves, edits, or rejects it, with a deterministic fallback on reject and a decision trail written to `mgr-approvals` (visible in the dashboard). Policy is config (`--approve auto|final|off`), and it never hangs — non-interactive runs (CI, pipes, the demo) auto-approve. It's the HITL seam an evaluator looks for: a checkpoint on the action that matters, observable after the fact.

---

## EDD — eval-driven development (quality tracked per commit) ⭐

A multi-agent product is hard to *prove*: "the friends feel more real now" is a vibe, not a number. Glimi's answer is **EDD — eval-driven development**: an autonomous **owner agent** (a persona, not a script) drives a real app end-to-end from onboarding through the core journey, the session is scored across **weighted dimensions** into a single **0–100 composite**, and every run is a **git-SHA-anchored "generation"** committed to the repo. So `git log` becomes a measurable quality timeline, and every commit's effect on product quality is observable. The framework is **`glimi.edd`** — domain-neutral, part of the `glimi` kernel, inherited by **both** Community and Workspace (each supplies its own dimensions and owner agent).

**How a generation is scored** — each dimension is 0–10 with a weight; the composite is the weighted average normalized to 0–100. `critical` dimensions are make-or-break: if one fails, the whole run fails regardless of the composite (a high chat score can't paper over a broken core journey). LLM-judge dimensions are **skipped** — excluded from the composite, never faked — on the offline `echo` backend or when no judge is available, so a free self-test can never inflate the score. Community's six dimensions:

| Dimension | Kind | Weight | Critical | What it checks |
|---|---|:--:|:--:|---|
| `onboarding` | structural | 1.0 | | A fresh owner greets the manager and gets oriented |
| `friend_creation` | structural | 1.5 | ⭐ | An owner request actually creates a new friend, and conversation follows |
| `conversation_quality` | LLM-judge | 2.0 | | Replies are human, coherent, in-character (5 axes: in_character · coherence · naturalness · engagement · no_meta) |
| `no_hallucination` | LLM-judge | 1.5 | | No invented facts, no claiming actions it never took |
| `no_leaks` | structural | 1.0 | | Zero meta / error / tool-block leakage into chat |
| `responsiveness` | structural | 1.0 | | Every driven DM gets a distinct reply, no stalls |

### The flywheel, with real measurements

These are the **actual generations committed to this repo** (`tests/e2e/qa_generations/*.json`) — real `claude_cli` runs, scored by the judge, each stamped with the git SHA it ran against. N is small (the system is new); the point is the **methodology that accumulates data over generations**, not a long history yet. Read honestly, they already tell a story.

| Gen | git SHA | Branch | Composite / 100 | Verdict | `conversation_quality` | `friend_creation` (critical) | Failing |
|:--:|:--:|---|:--:|:--:|:--:|:--:|---|
| **1** | `1eb4c46`* | `feat/community-qa-system` | **69.4** | ❌ FAIL | 6.0 | **0.0** | friend_creation, conversation_quality |
| **2** | `b3eaf74`* | `feat/community-qa-system` | **75.0** | ❌ FAIL | **9.0** ▲ | **0.0** | friend_creation |
| **3** | `f1eb58a`* | `develop` | **72.5** | ❌ FAIL | 8.0 | **0.0** | friend_creation |
| **4** | `f1eb58a`* | `develop` | **56.9** | ❌ FAIL | 4.0 ▼ | **0.0** | friend_creation, conversation_quality, no_hallucination |
| ⋯ | gens 5–10 | the web-native onboarding build | 56.9 → 85.0 | building | — | 0.0 → **10.0** | — |
| **11** | `a8d874d`* | `feat/web-native-onboarding` | **85.0** | ✅ **PASS** | 7.0 | **10.0** ▲▲ | — *(first PASS)* |

`*` = working tree was dirty at run time. Composite/dimension scores are read verbatim from the committed JSON. **Gen 11 is the milestone**: the build that made onboarding web-native (gens 5–10 iterated toward it) flipped the critical `friend_creation` from **0 → 10**, turning the first ✅ PASS (85/100) — exactly the `0 → 10` jump the harness predicted while it sat red.

What the numbers actually say — and why we publish the failures, not just the PASS:

- **`conversation_quality` swung 6.0 → 9.0 → 8.0 → 4.0 … → 7.0** across generations. That volatility is the honest signal of a non-deterministic LLM product, and it's exactly what a *trend* (not a single screenshot) is for. Gen-1→2 caught a real improvement (the manager stopped re-asking a question the owner had already answered twice); gen-4 caught a regression of the same failure mode; by gen-11 it had settled back to 7.0. Without the harness, all of it would have been invisible.
- **`friend_creation` is `critical`, and for gens 1–10 it sat at 0.0 — so every early run FAILed by design.** That was the harness working, not the system broken: it honestly pinned a known architectural gap. The autonomous onboarding supervisor only ran inside the Discord-bot subprocess, so a pure web E2E couldn't progress it (the "Discord = adapter" decoupling — see [`docs/qa_system.md`](docs/qa_system.md) and `analysis/platform_decoupling_review.md`). Then the web-native onboarding build closed the gap, and **gen-11 reads `friend_creation` = 10.0 → the first ✅ PASS (85/100)**. The number moved **0 → 10 exactly as the harness predicted while it sat red** — the flywheel demonstrated, not asserted. (`conversation_quality` 7.0 and `no_hallucination` 6.0 are the remaining soft spots; the harness keeps them visible rather than hiding them behind the green.)

That is the pitch in one line: **product quality is a first-class, git-tracked metric — every commit's impact is measured and visible**, including the regressions and the unfinished work. The dashboard and PDF below are how a reviewer reads that timeline at a glance.

### See it: the `/admin/qa` dashboard + PDF reports

The platform serves a **QA dashboard** at `/admin/qa` (admin login → "QA" menu): the latest score as a hero, a **quality-over-generations trend chart**, and a per-generation table with every dimension. Any generation exports to a **self-contained PDF** (`glimi.edd.report` renders a print-optimized HTML one-pager through Playwright headless Chromium; the trend line is server-rendered SVG, so it prints identically with no JS).

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

**Reusable for adopters.** `glimi.edd` is domain-neutral and ships in the `glimi` wheel — bring your own dimensions and owner-agent driver and you get the composite scoring, the git-anchored generation store (SQLite + committed JSON), and the HTML/PDF report for free:

```python
from glimi.edd import Dimension, DimResult, build_assessment, GenerationStore

DIMS = [Dimension("onboarding", "Onboarding", 1.0, "structural", "fresh user gets oriented"),
        Dimension("core_journey", "Core journey", 1.5, "structural", "...", critical=True)]
results = [DimResult.for_dim(d, score=..., passed=..., detail="...") for d in DIMS]  # you evaluate
assessment = build_assessment(results, min_overall=70)                              # core scores → 0–100
store = GenerationStore(db_path="qa.db", generations_dir="qa_generations/")          # core persists
store.record(assessment.as_dict(), run_id="run-1")                                   # → SQLite + git-SHA JSON
```

Community implements its six dimensions on top of this; Glimi Workspace adopts the same `glimi.edd` core with deliverable / delegation / A2A dimensions — one EDD framework, two apps. Full design: [`docs/qa_system.md`](docs/qa_system.md).

---

## Examples

Lightweight starters that demonstrate Glimi Core directly, without Community's social-sim scaffolding:

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

**Done — Kernel extraction + packaging**
- ✅ `community/core/{runtime, tools, memory, llm, conversation}` → top-level `glimi/` — storage/platform-neutral, imports standalone (no Discord/DB)
- ✅ `KernelStore` ABC + `AgentProfile` / `OwnerContext` / `KernelObserver` protocols; Community wires concrete adapters in `community/adapters/`
- ✅ `pyproject`: `pip install glimi` (core, **zero runtime deps**) + extras `glimi[sdk]` (anthropic SDK) and `glimi[dashboard]` (FastAPI web UI) — the kernel builds as a standalone wheel straight from this monorepo; the apps depend on it

**Now — First PyPI release**
- First `pip install glimi` alpha (0.1.0) on PyPI

**Next — Examples + docs**
- `glimi-core/examples/research_buddies/` and `glimi-core/examples/dev_pair/`
- English architecture deep-dive (blog post)
- `kernel.tests/` unit coverage

**Then — Local-model backends**
- vLLM / llama.cpp implementations (Ollama + Grok already shipped; stubs already in `AVAILABLE_MODELS`)
- Per-agent local override from dashboard

**Then — Per-agent RAG memory (memory at scale)** ⭐
- The layered (L0–L5) memory works *in context*, but an agent that has lived a long time eventually outgrows any window. Plan: give **each agent its own RAG corpus** on top of a proven retrieval core — the agent's accumulated history + knowledge is embedded and indexed, and the agent pulls only what's relevant per turn instead of carrying it all in the prompt. Memory stops being a budget you spend and becomes a store you query.
- **Expected effect**: recall that doesn't degrade as history grows (retrieval is `O(top-k)`, not `O(history)`); a distinct, inspectable per-agent knowledge base; precise, *sourced* recall instead of summary drift.
- **Latency as character, not friction**: retrieval adds a delay the in-context memory doesn't. The agent invokes the RAG lookup as a **skill/tool while it's on-load** and masks the wait *in character* — *"잠시만…", "그거 뭐였더라, 기억 더듬는 중…"* — so the retrieval pause reads as a person recalling, not a spinner. The same latency that would feel like lag becomes a believable human beat.

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
full comparison live in **[`docs/local_models.md`](docs/local_models.md)**; setup is in
[`docs/ollama_setup.md`](docs/ollama_setup.md). Good follow-on tasks: vLLM / llama.cpp
backends, reranker-based memory retrieval, and smaller-model tool-call accuracy tuning.

### Other entry points

- **easy**: new `examples/` demos, doc fixes, new Community `community/scenes/`
- **medium**: vLLM / llama.cpp backends, dashboard visualizations, new ToolSpecs
- **hard**: native Windows support (`run.ps1`), Telegram adapter (`community/adapters/telegram/`), `pyproject` packaging split (`pip install glimi`), embedding-based memory retrieval

### Branch strategy

| Branch | Role |
|---|---|
| `main` | Stable. **No direct work / push.** Maintainers fast-forward from `develop`. |
| `develop` | Working branch. All integration happens here. |
| `feat/<name>` · `fix/<name>` · `docs/<name>` · `refactor/<name>` | Short-lived contributor branches. **PR base = `develop`**. |

### Code conventions (the easy-to-regress ones)

- **Discord = adapter.** `community/core/*` never imports `discord`. Community-specific code lives under `community/bot/`, `community/scenes/`, `community/achievements/`, etc.
- **Memory / emotion are user-prompt injections**, never system-prompt baked. `AgentRuntime` assembles them per channel, per turn.
- **Timestamps are UTC-aware ISO** (`community.core.timeutil.now_utc_iso()`). SQLite `CURRENT_TIMESTAMP` is naive — don't use it directly.
- **Meta words** like "agent" / "bot" / "AI" are forbidden in user-visible text. `<tools>` blocks never surface in conversation channels — runtime tool-call logs go to the `logs/system.log` file.
- **Profile edits** require `invalidate_cache()` + `runtime.refresh_agent()` paired.

### Commit rules

- 1-line subject, 50 chars-ish. Body only if necessary (1-2 lines).
- Prefixes: `feat:` / `fix:` / `docs:` / `ui:` / `refactor:` / `test:`.
- **No AI co-author trailers** (`Co-Authored-By: Claude` etc.) — strictly forbidden.
- **No `--no-verify` / `--no-gpg-sign` bypasses** — fix the hook failure instead.

See `CLAUDE.md` for the full project guardrails (auto-loaded by Claude Code).

---

## License

**AGPL-3.0-or-later** — strong copyleft. You're free to use, study, modify, and share Glimi; in return, **any distributed or network-served derivative must also be open-sourced under the AGPL and keep this project's attribution** — so it can't be taken closed or shipped as a proprietary product. Contributions are welcome under the same license; the author retains copyright and may grant separate commercial licenses. Same "stay open, grow with contributors, prevent proprietary free-riding" stance as MongoDB, Grafana, and Mastodon.

See `LICENSE` for the full text and `NOTICE` for attribution/trademark.
