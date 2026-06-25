# What makes Glimi different

[← README](../README.md)

Glimi Core runs agents that persist across sessions. Standard frameworks launch short-lived agents, compress context, and rebuild later. In Glimi, each agent keeps its context — work, decisions, preferences, and links — stored across sessions and model swaps. The same core drives **Glimi Workspace** (shared workbench) and **Glimi Community** (friend memory).

Other projects (LangChain/LangGraph, AutoGen, CrewAI, OpenAI Agents SDK, Letta, etc.) focus on single **tasks** and discard the agent after. Some (Letta) persist memory or run open worlds (Stanford Generative Agents, AI Town). Glimi merges these ideas into a **single pip-installable runtime** with two traits:

**1. Memory sized to context (Elastic Memory).** Glimi fits memory to the set context window (`num_ctx`). It trims by token budget so prompts stay within limit. The same agent runs at 4096 or 16384 without personality loss. Others trim history (CrewAI, Letta, OpenAI Agents SDK, AutoGen, LangGraph) but not by target size. Ollama's request to auto-match VRAM is still open.

**2. Anti-drift memory.** Facts expire on time or are marked superseded when replaced. Agents forget stale data but keep the record. Zep's Graphiti is closed; Mem0 dropped contradiction handling in 2026. Glimi ships supersession logic, runtime, and dashboard free. It uses row-level SQLite instead of a full graph.

## Integration overview

- **Persistent population.** Each agent has a persona and model (Claude or Ollama). State is stored, not reprised, surviving model swaps.
- **Autonomous activity.** A timed supervisor spawns threads, revives idle agents, and advances scenes offline.
- **Light load.** All agents share one resident model, swapping only context. Fits a fleet on 16 GB. Uses Ollama's resident model while Glimi tracks state.
- **Dashboard.** Web UI shows relationships, memory (L0–L5), live channel, and model inspector. Others show single agents; Glimi spans many.

Status: alpha (0.1.0, not on PyPI). Letta leads in memory depth, AI Town in autonomy, SillyTavern in characters, Zep in graphs. Glimi combines them.

## Glimi vs. the alternatives

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
