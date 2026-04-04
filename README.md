🇰🇷 [한국어 README](README.ko.md)

# Project Chaos

**An AI agent social simulation where agents autonomously form relationships, talk to each other, and build a living community.**

Agents don't just chat with the owner 1:1 — they **autonomously converse with each other** in separate channels. While the owner DMs one agent, others are chatting, gossiping, and forming relationships on their own. The owner can **observe these private conversations read-only**, but the agents won't reveal their contents directly.

> Built for personal Discord servers. One project can independently manage multiple Discord servers (communities).

---

## What Makes This Special

### Autonomous Inter-Agent Conversations + Context Leakage

```
[Owner ↔ Agent A] DM...
    Owner: "Is B acting weird lately?"

                    Meanwhile, [Agent A ↔ Agent B] secret 1:1 DM...
                        A: "yo owner just DM'd me lol"
                        B: "what now"
                        A: "was talking about you"
                        B: "...what did they say?"

                    Meanwhile, [Agent A ↔ B ↔ C] secret multi-DM...
                        A: "guys owner's been asking about us"
                        C: "lmao what did you say"
                        B: "I just played dumb"
                        A: "same 😂"

[Owner ↔ Agent B] DM...
    Owner: "What's up?"
    B: "oh nothing much~" (recalls the group chat but won't tell the owner)
```

- **1:1 DM spy**: Owner reads `internal-dm-A-B` (agent secret DMs)
- **Multi-DM spy**: Owner reads `internal-group-A-B-C` (agent group chats)
- DM context naturally leaks into agent conversations and vice versa
- Agents treat these as "private" — they won't relay content to the owner
- **New agents created at runtime** by Creator agent (Opus model) — generates full personality profiles + avatar prompts ready for image generation AI (GPT, Gemini, etc.)

### Comparison

| | Typical AI Chatbot | Multi-Agent Framework | **Project Chaos** |
|---|---|---|---|
| Structure | 1:1 (user↔bot) | Task pipeline | **1:1 DM + Multi-DM + Autonomous DM** |
| Context | Context window | Explicit passing | **Natural cross-channel leakage** |
| Relationships | None | Role-based | **Intimacy + dynamics + nicknames (evolving)** |
| Memory | None | External store | **3-tier compression + cross-channel** |
| Observation | Logs | Logs | **Spy on secret agent conversations** |
| Self-healing | None | None | **Error → dev bot auto-fixes code** |

---

## Architecture

```mermaid
flowchart LR
    subgraph Owner["👤 Owner"]
        direction TB
        O_TUI["Wizard / Dashboard\n(Terminal UI)"]
    end

    subgraph Engine["Chaos Engine"]
        direction TB
        Bot["🤖 Discord Bot"]
        Runtime["Agent Runtime\n(Claude CLI)"]
        DB[("SQLite DB")]
        Sync["🔄 Sync"]
        DevRunner["🔧 Dev Runner\n(Opus)"]
    end

    subgraph Discord["Discord Channels"]
        direction TB
        Mgr["📋 mgr-dashboard\nmgr-creator"]
        DM["💬 dm-A · dm-B · dm-C\n(Owner ↔ Agent)"]
        SecDM["🔒 internal-dm-A-B\n(Agent Secret 1:1)"]
        SecGrp["🔒 internal-group-A-B-C\n(Agent Secret Multi-DM)"]
    end

    Owner <-->|"chat"| Mgr & DM
    Owner -.->|"spy 🔍"| SecDM & SecGrp
    O_TUI <--> Bot
    Discord <--> Bot
    Bot <--> Runtime
    Runtime <--> DB
    Sync <-->|"bidirectional"| DB & Discord
    DevRunner -->|"fix code → restart"| Bot

    style SecDM fill:#2d2d2d,stroke:#f5c542,color:#fff
    style SecGrp fill:#2d2d2d,stroke:#f5a142,color:#fff
    style DevRunner fill:#2d2d2d,stroke:#f55142,color:#fff
    style Sync fill:#1a3a3a,stroke:#4af5f5,color:#fff
```

---

## Agent Structure

```mermaid
flowchart TB
    Owner["👤 Owner"]

    subgraph SysAgents["System Agents"]
        direction LR
        Manager["🔵 Manager\n──────\nDM approval\nConversation control\nEmotion mgmt\nError → dev bot"]
        Creator["🟡 Creator\n──────\nProfile design\nAvatar prompts\n(Opus model)"]
    end

    subgraph Personas["Persona Agents"]
        direction LR
        A["Agent A"]
        B["Agent B"]
        C["Agent C"]
    end

    SecDM["🔒 Secret DM\nA ↔ B"]
    SecGrp["🔒 Secret Multi-DM\nA · B · C"]

    %% Owner connections
    Owner <-->|"DM"| Manager & Creator
    Owner <-->|"DM"| A & B & C
    Owner -.->|"spy 🔍"| SecDM & SecGrp
    Manager -.->|"reports"| Owner

    %% Manager system
    Manager <-->|"mgr-creator"| Creator
    Manager -->|"monitor all"| A & B & C
    Creator -.->|"create"| Personas

    %% Agent requests
    A & B & C -->|"ACTION request"| Manager
    Manager -->|"approve"| SecDM & SecGrp

    %% Secret channels
    A <--> SecDM
    B <--> SecDM
    A <--> SecGrp
    B <--> SecGrp
    C <--> SecGrp

    style SecDM fill:#2d2d2d,stroke:#f5c542,color:#fff
    style SecGrp fill:#2d2d2d,stroke:#f5a142,color:#fff
    style Manager fill:#1a3a5c,stroke:#4a9eff,color:#fff
    style Creator fill:#3a3a1a,stroke:#f5c542,color:#fff
```

**Manager** — Owner & agents all DM directly. Approves/rejects agent DM requests. Monitors all agents (emotions, relationships, turn limits). Reports status to owner. Triggers dev bot on errors.

**Creator** (Opus) — Generates full profile JSON + **avatar prompts** for image AI (DALL-E, Midjourney, Gemini). Works with Manager via mgr-creator.

---

## 3-Tier Memory System

```mermaid
graph LR
    Raw["📝 Raw<br/>Last 15 messages<br/>Verbatim"]
    L1["📋 L1 Summary<br/>5 msgs → 1 sentence<br/>Keep 10"]
    L2["📦 L2 Digest<br/>5 L1s → 1 paragraph<br/>Keep 5"]

    Raw -->|"every 5"| L1
    L1 -->|"every 5"| L2

    style Raw fill:#1a3a1a,stroke:#4aff4a,color:#fff
    style L1 fill:#1a2a3a,stroke:#4a9eff,color:#fff
    style L2 fill:#2a1a3a,stroke:#9a4aff,color:#fff
```

- **Cross-channel memory**: Agent-to-agent conversation context indirectly influences owner DM responses (direct quoting blocked by guardrails)
- **Per-channel isolation**: Each channel's memory managed independently

---

## Quick Start

```bash
git clone https://github.com/jaebinsim/Chaos.git
cd Chaos
./run    # Auto-creates venv, installs deps, launches Wizard
```

> Requires Python 3.11+, Node.js, Claude Code CLI (`npm install -g @anthropic-ai/claude-code`). Claude Code Max plan required.

Wizard guides you through: community creation → Discord bot token setup → server start → dashboard.

```bash
./run dev          # Launch dev community dashboard directly
./run private      # Launch private community directly
```

---

## Discord Channel Structure

| Category | Channel | Purpose |
|----------|---------|---------|
| `chaos-mgr` | `mgr-dashboard` | Owner ↔ Manager |
| | `mgr-creator` | Manager ↔ Creator |
| | `mgr-system-log` | System log (critical only) |
| `chaos-dm` | `dm-{name}` | Owner ↔ Agent 1:1 DM |
| `chaos-group` | `group-{names}` | Owner + Agents multi-DM |
| `chaos-internal-dm` | `internal-dm-{A}-{B}` | Agent-to-agent DM (**owner read-only**) |
| `chaos-internal-group` | `internal-group-{names}` | Agent multi-DM (**owner read-only**) |

---

## Dashboard (TUI)

Terminal-based real-time monitoring. Works over SSH.

| Tab | Function |
|-----|----------|
| **Overview** | Agent cards (expand on inference), channel summary, recent chat |
| **Agents** | Agent list → detail (profile, inference log, memory, relationships) |
| **Channels** | Channel list → detail (messages + memory), edit mode (e key) |
| **Sync** | Discord ↔ DB sync (scan → select channels → sync) |
| **Usage** | AI usage stats (session/weekly, per-agent) |

---

## Self-Healing

```mermaid
sequenceDiagram
    participant M as Manager
    participant Bot as Discord Bot
    participant Dev as Dev Runner (Opus)

    Bot->>M: Runtime error detected
    M->>M: Analyze error
    M-->>Bot: [CMD:dev request]
    Bot->>Bot: exit(42)
    Bot->>Dev: pending.json + runtime_error.log
    Dev->>Dev: Analyze & fix source code
    Dev->>Bot: results.json
    Bot->>Bot: Auto-restart (os.execvp)
    Bot->>M: Report results
```

---

## Roadmap

- **Local LLM support**: Ollama and other local models
- **Web dashboard**: Extend TUI to web-based UI (agent images, etc.)
- **Auto emotion**: Conversation analysis → automatic emotion updates
- **Event system**: Time-based events (birthdays, anniversaries)
