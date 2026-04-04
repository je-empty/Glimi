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

                    Meanwhile, [Agent A ↔ Agent B] in a secret channel...
                        A: "yo owner just DM'd me lol"
                        B: "what now"
                        A: "was talking about you"
                        B: "...what did they say?"

[Owner ↔ Agent B] DM...
    Owner: "What's up?"
    B: "oh nothing much~" (recalls what A said but won't tell the owner directly)
```

- DM context naturally leaks into agent-to-agent conversations
- Agent conversations indirectly influence owner DM responses
- Owner can observe secret conversations (read-only via `internal-dm-*`)
- Agents treat these as "private" — they won't relay content to the owner

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
graph TB
    Owner["👤 Owner"]

    subgraph Discord["Discord Server"]
        direction TB
        subgraph chaos_mgr["chaos-mgr"]
            Dashboard["mgr-dashboard"]
            MgrCreator["mgr-creator"]
            SysLog["mgr-system-log"]
        end
        subgraph chaos_dm["chaos-dm"]
            DM_A["dm-A"]
            DM_B["dm-B"]
        end
        subgraph chaos_internal["chaos-internal-dm"]
            INT_AB["internal-dm-A-B<br/>🔒 Read-only"]
        end
    end

    subgraph System["Chaos System"]
        direction TB
        Bot["Discord Bot<br/>(Webhook Manager)"]
        Runtime["Agent Runtime<br/>(Claude CLI)"]
        Memory["Memory Manager<br/>(Raw→L1→L2)"]
        DB[("SQLite DB")]
        ConvEngine["Conversation Engine"]
        DevRunner["Dev Runner<br/>(Opus · Self-Healing)"]
    end

    subgraph TUI["Terminal UI"]
        Wizard["Wizard"]
        Dash["Dashboard"]
    end

    Owner -->|"DM"| DM_A & DM_B
    Owner -.->|"spy"| INT_AB
    DM_A & DM_B & INT_AB & Dashboard & MgrCreator --> Bot
    Bot --> Runtime --> Memory --> DB
    ConvEngine -->|"autonomous chat"| INT_AB
    DevRunner -->|"fix code → restart"| Bot
    Wizard & Dash --> Bot

    style INT_AB fill:#2d2d2d,stroke:#f5c542,color:#fff
    style DevRunner fill:#2d2d2d,stroke:#f55142,color:#fff
    style ConvEngine fill:#2d2d2d,stroke:#4af5a3,color:#fff
```

---

## Agent Structure

```mermaid
graph TB
    subgraph Mgr["Manager System"]
        Manager["🔵 Manager<br/>──────────<br/>Server Admin<br/>DM/Multi-DM approval<br/>Conversation facilitation<br/>Infinite loop prevention<br/>Emotion/relationship mgmt<br/>Periodic status reports<br/>Error → dev request"]
        Creator["🟡 Creator (Opus)<br/>──────────<br/>New agent creation<br/>Profile JSON design<br/>Avatar prompt generation<br/>Personality/speech setup"]
        Manager <-->|"mgr-creator<br/>1:1 comms"| Creator
    end

    subgraph Personas["Persona Agents"]
        A["Agent A<br/>Personality · MBTI<br/>Speech · Emotion · Memory"]
        B["Agent B<br/>Personality · MBTI<br/>Speech · Emotion · Memory"]
        C["Agent ...<br/>Dynamic creation"]
    end

    Owner["👤 Owner"]

    Owner <-->|"DM"| A
    Owner <-->|"DM"| B
    Owner -.->|"read-only"| AB_Chat

    A -->|"[ACTION] DM request"| Manager
    B -->|"[ACTION] Multi-DM request"| Manager
    Manager -->|"approve → create channel"| AB_Chat

    A <-->|"autonomous chat"| AB_Chat["🔒 A ↔ B<br/>Secret Channel"]
    B <-->|"autonomous chat"| AB_Chat
    A <-->|"relationship evolution<br/>intimacy · nicknames"| B

    Manager -->|"facilitate · monitor<br/>emotion adjust · turn limit"| A & B
    Manager -.->|"periodic reports"| Owner
    Creator -->|"create profile"| C

    style AB_Chat fill:#2d2d2d,stroke:#f5c542,color:#fff
    style Manager fill:#1a3a5c,stroke:#4a9eff,color:#fff
    style Creator fill:#3a3a1a,stroke:#f5c542,color:#fff
```

**Manager**: Approves/rejects DM requests, facilitates conversations, prevents infinite loops (turn limits), manages emotions/relationships, monitors activity, reports to owner, triggers dev bot on errors.

**Creator** (Opus model): Creates new agents with full JSON profiles, designs avatar prompts, works with Manager via mgr-creator channel.

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
