# Glimi Workspace

**A persistent specialist team for real work, built entirely on Glimi Core — no Discord, no Community code.**

Glimi Workspace is a *second app on the same kernel*. The Glimi Community sim is a Discord social world of AI friends; this is its **work sibling** — a small team of role-based specialists that takes a work *goal* and produces a deliverable. Both run the **same engine** (`glimi`), and both are viewable in the **same Core dashboard**.

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

## The flow

On **one shared workspace channel**, one `Glimi` instance (one shared store):

1. **Coordinator** greets the owner by name, restates the goal, introduces the team, and assigns each specialist an angle.
2. **Two rounds**: Researcher → Builder → Critic each contribute. Crucially, nobody is handed the transcript in code — each member **reads the shared workspace out of the kernel's injected memory**, exactly like a real team reading the room.
3. **Coordinator** synthesizes the final deliverable.
4. A clean summary prints (shared-store stats + the deliverable).

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

`--serve` is **off by default** (so a plain run completes, prints the deliverable, and is CI-safe). With it, after the work the app serves the finished team in the **same store-driven Core dashboard that serves Community** — the connection graph plus each member's 5-layer memory:

```bash
PYTHONPATH=. python apps/workspace/run.py --serve   # → http://127.0.0.1:8800
```

Needs the optional web deps: `pip install glimi[dashboard]`. This is the payoff — the dashboard behind the social sim now renders *your work team*.

## Sample output (real backend)

Captured from a genuine `GLIMI_LLM_BACKEND=claude_cli` run (`--goal "Plan the public launch of our open-source project"`), **trimmed**. This is real model output, not a mock — note how the Critic and Coordinator build on each other's earlier turns, which they read from shared memory (not from a transcript handed to them in code):

```
================================================================
  Glimi Workspace — a specialist team on Glimi Core
================================================================
  owner   : Owner
  goal    : Plan the public launch of our open-source project
  backend : claude_cli
  team    : Coordinator, Researcher, Builder, Critic
================================================================

--- The workspace opens ---

Coordinator:
Hey Owner — welcome back.
Goal: Plan a sharp, well-timed public launch ... that drives real adoption.
Here's how I'm splitting the work:
| Specialist | Angle |
| Researcher | Landscape audit — comparable OSS launches, timing, channels ... |
| Builder    | Launch checklist — repo hygiene, docs, CI badges, release artifacts ... |
| Critic     | Risk & gap analysis — what could sink the launch, weak spots ... |

--- Round 1 ---

Builder:
... here's the launch readiness framework I'd use:
| Phase | Owner | Blockers? |
| Repo Hygiene    | Builder | What's the GH org/name? Public or migrate? |
| Docs Foundation | Builder | README, quickstart, contrib guide |
| Release Pipeline| Builder | Tags, artifacts (npm/PyPI?), CI badges, CHANGELOG |
| Risk Sweep      | Critic  | License, security audit scope, missing tests |
| Soft Launch     | Builder | Early beta feedback — catch surprises before public |

Critic:
Looking at this plan, the biggest risk is timing of the security audit — it's
after soft launch, which is too late. ... Mitigation: move Risk Sweep to run
*parallel* with Docs Foundation, not after Soft Launch. ... Second gap: "Soft
Launch" has no exit criteria — what triggers the go/no-go?

--- The Coordinator delivers ---

Coordinator:
## Launch Plan Synthesis — OSS Public Launch
### The Decision Before the Plan
> "What's the single thing that, if it broke, would push this launch back 6
> months or kill it entirely?"
| Answer | Plan Shape |
| Security audit not started | Audit first → 2–4 wks → then launch |
| Key person risk            | De-risk via docs/bus-factor before any date |
| Nothing critical           | Velocity mode — optimize for speed |
### The Plan Framework (ready to activate)
Week 1–2 — Hardening: repo hygiene, CI green, LICENSE, CONTRIBUTING, security review.
Week 3   — Soft Launch: private beta, repo public, no announcements.
Week 4–5 — Signal Build: README polish, demo video, seed early adopters.
Week 6   — Public Launch: Show HN, Product Hunt, founder thread, reply to every comment.
### Top Risk to Watch
Self-deception about readiness ... Mitigation: run the Critic's single question
*now*, in writing, with all stakeholders in the room.

--- Summary ---
  goal       : Plan the public launch of our open-source project
  turns       : 108 messages in ONE shared workspace channel, readable by every member.
  long-term L1: Coordinator=2, Researcher=2, Builder=1
```

*Honesty note:* in this captured run one Researcher turn in Round 1 hit a transient `claude_cli` timeout (`응답 지연 — 다시 시도해주세요`) and recovered the next round — real LLM-CLI behavior, left as-is rather than airbrushed. The `long-term L1` line shows raw turns rolling up into the kernel's 5-layer memory during the run.

## Files

- `run.py` — entry point: argument parsing, the flow, the summary, and the `--serve` dashboard hand-off.
- `team.py` — the team personas + first-run setup (`resolve_setup`). Pure config + I/O; imports nothing from `glimi`/`src`/`discord`.
- `README.md` — this file.

Tests live in `tests/unit/test_glimi_workspace.py` (setup resolution, the echo flow, dashboard population, and a kernel-only import guard).
