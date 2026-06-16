# Glimi Workspace

**A specialist team that genuinely *interacts* — built entirely on Glimi Core, no Discord, no Community code.**

Glimi Workspace is a *second app on the same kernel*. The Glimi Community sim is a Discord social world of AI friends; this is its **work sibling** — a small team of role-based specialists that takes a work *goal* and produces a deliverable. But it doesn't work in one round-robin room: the team **interacts across several channels the way a real team does** — the owner DMs the lead, the lead delegates to each specialist, specialists talk *to each other*, and the whole team converges in a group room. Both apps run the **same engine** (`glimi`), and both are viewable in the **same Core dashboard** — where these interactions show up as a real **connection graph**.

That's the whole point: a second, distinctly different app on one kernel is the strongest proof that **Glimi Core is a genuinely reusable core**, not a monolith. The Workspace imports only the `glimi` package — zero `discord`, zero Community (`src`) code.

## The team

A manager agent plus three role specialists, sharing **one store**:

| Member | Role | Type |
|---|---|---|
| **Coordinator** | Runs the workspace: greets the owner, restates the goal, assigns the specialists, keeps work moving, delivers the final synthesis. Concise, organized, decisive. | `mgr` |
| **Researcher** | Gathers facts, options, trade-offs — concrete detail. | `persona` |
| **Builder** | Turns decisions into a concrete plan / steps / draft — pragmatic. | `persona` |
| **Critic** | Stress-tests the plan, surfaces risks and gaps, pushes for rigor. | `persona` |

The Coordinator is the Workspace analogue of the Community sim's manager agent (the social-sim's host): the agent that sets up the room and facilitates. Personas are **functional roles** — persona yes, personal name no.

## The interaction model

One `Glimi` instance (one shared store), but a real **interaction web** across distinct channels — exactly the shape a real team has:

1. **Owner ↔ Coordinator** — a DM (`dm-coordinator`). The owner gives the goal; the Coordinator greets, restates it, and lays out who gets which angle. At the end, the Coordinator delivers the final synthesis back here.
2. **Coordinator ↔ each specialist** — per-specialist DMs (`dm-researcher`, `dm-builder`, `dm-critic`). The Coordinator *delegates* a clear angle into each channel; the specialist reads it and responds with a first take.
3. **Specialist ↔ specialist (agent-to-agent)** — internal channels (`internal-researcher-critic`, `internal-builder-researcher`). The pairs who should collaborate **actually talk to each other**, driven by the kernel's A2A engine (`runtime.generate_agent_to_agent`) — Researcher ↔ Critic debate the findings, Builder ↔ Researcher ground the plan. Real back-and-forth, not the owner relaying messages.
4. **Group** — a `group-team` channel where the whole team converges for one shared round and each drops its single most important point.
5. **Coordinator delivers** the final deliverable in the owner DM.

Crucially, nobody is handed the transcript in code — each member **reads its channels out of the kernel's injected memory**, exactly like a real team reading the room.

### The relationships are the graph

As the run interacts, the app records the **working relationships** those interactions form (`store.set_relationship`) — and those relationships are exactly the edges the Core dashboard's connection graph draws:

| Edge | Type | Formed by |
|---|---|---|
| Owner ↔ Coordinator | `lead` | the owner DM |
| Coordinator ↔ Researcher / Builder / Critic | `manages` | each delegation DM |
| Researcher ↔ Critic, Builder ↔ Researcher | `collaborator` | the A2A exchanges (intimacy grows with how much the pair talked) |

So `--serve` renders the team as a real web: the **owner** and the **Coordinator** as hubs, the specialists around them, and **collaboration edges** between the specialists. The relationships are set **structurally** (who worked with whom), so the graph is populated on *any* backend — including the offline `echo`. A real backend *also* grows these organically through the kernel's memory extraction over the same channels (you can watch the `[Memory] L1 추출 … rels=N` lines fire during a real run).

A closing summary prints the channels touched, the relationship edges formed, and the deliverable.

## First-run setup

The app asks the owner's **name** and **goal**, resolved in this order (first hit wins, per field):

1. CLI flag — `--name` / `--goal`
2. env — `GLIMI_WORKSPACE_NAME` / `GLIMI_WORKSPACE_GOAL`
3. a small JSON state file (a prior first run)
4. an interactive `input()` prompt — **only when `sys.stdin.isatty()`**
5. a sensible default (default goal: *"Plan the public launch of our open-source project"*)

Non-interactive runs (CI, pipes, the echo demo) **never hang on input** — they fall straight through to defaults. On a real terminal, the first run asks and persists your answers to `apps/workspace/.workspace_state.json` (gitignored), so it's truly "first run" once.

## How to run

Run from the repo root (until `pip install glimi` lands, use `PYTHONPATH=.`):

```bash
# Offline — the echo backend (zero deps, no API key; replies are stubbed,
# so the flow is illustrative).
PYTHONPATH=. python apps/workspace/run.py --name Owner --goal "Plan our launch"

# Real model — genuine collaboration + memory.
GLIMI_LLM_BACKEND=claude_cli PYTHONPATH=. python apps/workspace/run.py \
    --name Owner --goal "Plan the public launch of our open-source project"
PYTHONPATH=. python apps/workspace/run.py --backend ollama   # local Ollama
```

### View it in the Core dashboard — `--serve`

`--serve` is **off by default** (so a plain run completes, prints the deliverable, and is CI-safe). With it, after the work the app serves the finished team in the **same store-driven Core dashboard that serves Community** — the **connection graph** (owner + Coordinator hubs, the specialists, and the collaboration edges between them) plus each member's 5-layer memory:

```bash
PYTHONPATH=. python apps/workspace/run.py --serve   # → http://127.0.0.1:8800
```

Needs the optional web deps: `pip install glimi[dashboard]`. This is the payoff — the dashboard behind the social sim now renders *your work team as a real interaction web*, not a list of isolated agents.

## Sample output (real backend)

Captured from a genuine `GLIMI_LLM_BACKEND=claude_cli` run (`--name Mia --goal "Plan the public launch of our open-source CLI tool"`), **trimmed**. This is real model output, not a mock — note the **agent-to-agent** turns on the internal channels (specialists answering *each other*, not the owner) and the kernel's `[Memory] L1 추출 … rels=N` extraction firing during the run (relationships also grow organically on a real backend):

```
--- The Coordinator delegates ---

Coordinator → Researcher (dm-researcher):
  your angle is to gather the facts, options, and trade-offs the decision needs.
Researcher:
My research angle: Map the decision space before launch. ... My starting point:
the tool's README and current issue/discussion boards — that clarity (or lack)
cascades into every decision downstream.

--- The specialists collaborate (agent-to-agent) ---

--- Builder ↔ Researcher  (internal-builder-researcher) ---
[Memory] L1 추출: owner ch=dm-builder imp=6 ents=2 facts=1 rels=0
Builder:
좋아, 기억했어. 그럼 Researcher가 뭐라고 답했어? 그 세 가지 질문에 대한 답이 있으면
구체적인 plan을 그려줄 수 있을 텐데.
Researcher:
좋아, 그거면 충분해. — README (또는 1~2줄 elevator pitch) / 현재 단계 (알파/베타/
1.0) / 예상 사용자 프로필 — 이거 있으면 launch checklist를 구체적으로 그려줄 수 있어.

--- The team converges (group-team) ---

Critic:
Both solid — but here's what kills launches after those are locked: we haven't
defined what "day 1 success" actually means. ... sketch the minimum support
infrastructure first — monitoring alerts, issue-triage SLA, one person on-call.

--- The Coordinator delivers ---

Coordinator:
## Launch Plan: Open-Source CLI Tool — Team Synthesis
### The Decision First
The team is unanimous: we can't finalize a launch plan without locking three
things first — readiness stage, target audience, and the definition of success.
### Top Risk to Watch (Critic's call)
> Undefined success + no on-call plan = a launch that quietly dies.

--- Summary ---
  goal         : Plan the public launch of our open-source CLI tool
  channels     : the team worked across 7 channels (a real interaction web):
                 - dm-coordinator (33 msgs)
                 - group-team (7 msgs)
                 - internal-builder-researcher (11 msgs)
                 - internal-researcher-critic (6 msgs)
                 - dm-researcher / dm-builder / dm-critic ...
  relationships: the run formed these working ties (these are the graph edges):
                 - Builder ↔ Researcher  [collaborator, intimacy 88]
                 - Researcher ↔ Critic  [collaborator, intimacy 88]
                 - Coordinator ↔ Mia  [lead, intimacy 80]
                 - Coordinator ↔ Researcher / Builder / Critic  [manages, intimacy 60]
```

*Honesty note:* this is a real, unscripted run. On the internal A2A channels the kernel's agent-to-agent path appends a Korean role-guard to the prompt, so those turns came back in Korean (a kernel artifact, left as-is rather than airbrushed) — but they are genuine specialist-to-specialist turns, both speakers, building on each other. Because the owner gave no repo link, the specialists kept asking for grounding context; that's content behavior, not a topology issue — the **interaction web itself is fully realized**, which is what the dashboard graph shows.

## Files

- `run.py` — entry point: argument parsing, the interaction topology (`run_workspace`: the owner DM, delegation DMs, the A2A exchanges, the group round, the delivery, and `form_relationships`), the summary, and the `--serve` dashboard hand-off.
- `team.py` — the team personas, the interaction topology constants (channels + collaborating pairs), and first-run setup (`resolve_setup`). Pure config + I/O; imports nothing from `glimi`/`src`/`discord`.
- `README.md` — this file.

Tests live in `tests/unit/test_glimi_workspace.py` (setup resolution, the multi-channel topology, the relationship web, dashboard population, the **snapshot-relationships graph assertion**, and a kernel-only import guard).
