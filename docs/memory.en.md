# Glimi — Memory & Runtime Internals

[← README](../README.md)

How a single response flows through the runtime, the layered persistent memory stack (L0–L5), and why state survives model swaps and profile edits. State lives outside prompts, so relationships and memories persist across restarts and model changes (Haiku → local Llama).

---

## The 8 layers

Each response runs through **8 layers** — five pre-LLM (prompt, tool, memory, channel, guard), two post-LLM (A2A loop, self-heal), and a scheduled supervisor tier. Some wrap the LLM call (prompt, tools, memory). Others live in subsystems (A2A loop, supervisors, self-heal). Seven follow messages; one runs on schedule.

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

**1 · Prompt assembly** — builds prompt text from language + agent-type dispatch (`ko/`, `en/`), provider dialect (Claude `<tools>` XML, OpenAI function call, local tag), and locale snippets.

**2 · Tool protocol** — `ToolSpec` validates permissions, types, and fields. Dispatcher runs handlers; outputs feed the next prompt.

**3 · Memory pipeline** — every N turns, Haiku extracts `{summary, facts[], relationships[], emotion, entities, importance}`. Handles episodic rollup, semantic supersession, and intimacy bumps. Injection ≈ 1000 toks/turn scaled by load: pinned + relationship + episodic-current + self-recent + retrieved + facts. Retrieval weights `0.4·semantic + 0.3·importance + 0.2·recency_decay + 0.1·relational`.

**4 · Channel discipline** — prompts declare listeners to stop role bleed (e.g. agent speaking for owner in private A2A chat).

**5 · Anti-echo / dedup / reality guard** — ends goodbye loops, skips repeat tool calls, drops duplicates, blocks fake actions.

**6 · A2A conversation loop** — `start_conversation(channel, participants, …)` opens agent-to-agent talk with turn limits and closure check.

**7 · Self-healing** (off by default) — `request_dev_fix` logs a dev_request. Supervisor triages; on approval, Opus subprocess (`GLIMI_DEV_DISPATCH=1`) patches source and restarts with patch summary injected.

**8 · Supervisors** — timed processes (conversation trio and others). A pair scanner (DB intimacy + idle-time, no LLM) opens A2A channels. A chat watcher (Haiku judge) revives idle ones. A scene watcher moves stuck phases. Nudges appear as agent thoughts, not commands.

```
Bad:  "Switch to a new topic now."             ← LLM parses as command, awkward output
Good: "(oh, I should bring up something else)" ← LLM reads as self-talk, natural flow
```

Commands show system noise; self-talk merges into the next line.

## Memory architecture

Layered persistent memory (L0–L5): L0 raw (`conversations`) → L1 working window (recent verbatim, injected live) → L2 episodic rollup (L1→L2→L3 digests in `memories`) → L3 semantic facts (`agent_facts`: subject·predicate·object with `valid_from`/`valid_to` supersession) → L4 relationship (`relationships` + history) → L5 pinned (`memories.is_pinned`). Async Haiku extraction runs off the response path.

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

## Why it survives model swaps and profile edits

- State stays outside prompts. Swapping Haiku → Sonnet → local Llama keeps relationships, facts, pinned memories; new models read the same injection.
- Profile-edit tools pair `invalidate_cache()` with `runtime.refresh_agent()` so updates apply next turn and stop repeat-question bugs.
