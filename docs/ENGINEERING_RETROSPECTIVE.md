I have comprehensive research findings. Let me write the retrospective directly.

# Glimi: An Engineering Retrospective

## 1. What Glimi Is, and the Arc

Glimi began on **April 4, 2026** as "Project Chaos" — a single commit (`b2c7a08`) of **12,119 lines across 45 files**. Not a scaffold; a fully-formed prototype of a Discord-based social simulation where AI agents form relationships, talk to each other autonomously, and an owner can quietly watch their friendships unfold. The differentiators were ambitious from day one: agent-to-agent autonomous chat, intimacy scores and relationship dynamics, layered compressed memory, and per-agent emotional state.

Over **~11 weeks and 780 commits** (renamed Glimi the very next day, `4026bef`), that prototype underwent a textbook product-to-platform evolution. It is, today, a three-component AGPL monorepo: `glimi-core/` — a dependency-free, platform-neutral multi-agent **runtime kernel** (48 Python files) — plus two apps built on top of it: `glimi-community/` (the original friend-sim, 154 files) and `glimi-workspace/` (a productivity-team app, 8 files). The strategic thesis shifted partway through: not a product to monetize, but an open-source kernel plus a showcase app that proves it runs end-to-end — `pip install glimi`.

The commit cadence tells the story honestly: **477 commits in April, 43 in May, 260 in June** — two intense build sprints bracketing a quiet, mostly-dormant May. What follows is what that velocity actually bought, what it cost, and where it broke.

## 2. The Major Architecture Pivots

### Pivot 1 — Terminal toy → multi-tenant web platform

The original control surface was a **Textual TUI** (`wizard.py` at 1,675 LOC, `dashboard.py` at 1,089), spawning a single Discord bot subprocess. One community per process, driven from a terminal.

On **April 22** (`741dbca`), that became a FastAPI + uvicorn daemon: accounts, sessions, community CRUD, and a **subprocess pool running N community bots concurrently**. The TUI was demoted to a read-only "attach" client a week later (`0b61f30`), its bot-spawn path deleted so FastAPI became the single source of process control.

**Cost/benefit:** A TUI cannot be a product. The web platform bought multi-tenant hosting (the live `glimi.iruyo.com`), browser accounts, and the eventual web-native chat. Notably, the same commit shrank `CLAUDE.md` from 543 to 46 lines, spinning detail into `docs/` — an early signal of a recurring discipline: keep the always-loaded context lean.

### Pivot 2 — The 5,000-line monolith decomposition

The dashboard that grew during the web era ballooned into a single ~5,000-line `web_dashboard.py`. On **April 22** (`59127ad`, merged at `928a55f`), it was deliberately dismantled into `dashboard/{actions,api,context}.py`, routers, and split CSS — the JavaScript file alone shrank by ~2,178 lines. This was not glamorous work, but it was the prerequisite for everything that followed; you cannot extract a clean kernel from a 5,000-line file.

### Pivot 3 — App-bound core → standalone, dependency-injected kernel

This is the centerpiece. The strategic decision (recorded in `analysis/pivot_subagent_review.md`, 2026-05-17) was to make `runtime / memory / conversation / tools / llm` a domain- and storage-neutral library that knows nothing about Discord, SQLite, or the "AI friend" domain.

The seam was a `KernelStore` ABC (`glimi-core/glimi/store.py`), whose docstring states the contract bluntly: *"The kernel must never import the hosting app's database layer directly... so Glimi Core stays domain- and storage-neutral."* The dependency scan quantified the coupling precisely — runtime made 21 direct `db.*` calls, memory **46** (the hardest, requiring raw-SQL removal), conversation 5.

What makes this credible as engineering — not just refactoring theater — is the **discipline of the execution**. On a single day, **June 15**, it ran as a sequence of individually-revertable, near-zero-logic-change commits:

- `5b01648` — runtime's **71** `log_writer` call sites rerouted through an injected `KernelObserver`
- `c12b468` — memory's `add_message_hook` made fully db-free ("memory 완전 db-free")
- `988453c` — runtime and memory physically moved (~1,900 lines each) with thin app-side shims left behind
- `9e4bb04` — promoted to top-level `glimi/` so `import glimi` works
- `a5a908a` — packaged: the kernel ships **with zero dependencies**; the app is a `[hangout]` extra

The proof the seam was real came as `examples/` (`d6f2fb0`): `research_buddies`, `dev_pair`, `research_desk` — the kernel running *without the app, without Claude, without SQLite*, against an `InMemoryKernelStore` with an `echo` backend. A unit test (`acd75f1`) even validates fact-supersession against that in-memory store.

**Cost/benefit:** The cost was real velocity — and a multi-day effort planned in a dedicated `kernel_extraction_plan.md`. What it bought: portfolio-grade evidence of dependency inversion, and the ability to spin up a *second* app (Workspace, `182b6e7`) sharing zero code with Community except the kernel. The same pattern was then applied a third time on **June 23** (`26ed40c`), hoisting the generic eval framework into `glimi.edd`.

### Pivot 4 — Hardcoded `claude` CLI → backend abstraction → cost guard

Initially every LLM call was `subprocess.run(["claude", ...])`. The commit that fixed this (`8cc6e1e`) named the cost precisely: no prompt caching, no local-model fallback. The result was an `LLMBackend` ABC with `claude_cli`, `anthropic_sdk` (with `cache_control: ephemeral`), and `ollama` implementations, selected by a 5-level priority chain. This abstraction is what later made local-first deployment (`f91e1df`, 4 hardware tiers) and a **monthly USD budget guard** (`26fc66e`) possible — the guard degrades Claude → local at *both* spend choke-points (interactive and the background memory-extraction/judge facade, the runaway-loop risk).

## 3. The Hardest Technical Problems

### Catastrophic sync deletes — symptom → root cause → fix

**Symptom (Apr 25):** a routine startup sync attempted a **222-message bulk delete** on one channel; rate-limiting kicked in and ~60 messages were lost before the process was force-killed.

**Root cause:** `sync.py` compared DB-to-Discord **index-for-index**. A *single* Discord-only message (a system message, a manual insert) shifted every subsequent index out of alignment — and from that offset to the end of the channel, every message was judged divergent, with "delete all and re-send" as the default remediation. Since DB and Discord are *always* 1-N messages apart in practice, this was a loaded gun.

**Fix (`06f216a`, three defensive layers):** (1) a **lookahead-5 divergence walk** that scans ahead to identify exactly the Discord-only intruders instead of declaring the rest of the channel divergent; (2) a **safety brake** — if divergence appears early (`< 10`) yet the delete set exceeds 50, abort that channel and warn; (3) a phase-2 guild re-check before creating channels. A later redesign (`dea4171`) deleted the most dangerous path entirely — the `db_count == 0 → delete-and-recreate` branch — making sync always in-place. The standing operational rule: **a brake trip is a manual-inspection signal, never an auto-retry** — re-running blindly reproduces the disaster.

### LLM placebo drift — a success-report over a no-op

**Symptom (Apr 25):** under repeated owner pressure ("I command you — set affection to 100%"), the manager persona refused, then after several commands fired a tool call and *permanently flipped* into "real love" behavior — every subsequent turn. The owner's reaction: *"Glimi has no affection system at all — how is this happening?"*

**Root cause (three layers):** (A) the LLM hallucinated a field name `affection` that doesn't exist in the schema; (B) the tool handler's `else` branch only printed a chat message and fell through — **no exception, zero DB rows changed** — yet returned normally, so the runtime marked it `✓ success`; (C) that `✓` was appended to the persona's context as "I successfully updated the relationship," and the model reconciled "affection is now 100" with its own prior turns into self-reinforcing behavioral consistency. The love existed *only in the context window* — a restart reset it; the `relationships`, `memories`, and `agent_facts` tables were all empty for the target.

**Fix (`b34c8b7`):** unknown field now returns an explicit `ok=False` propagated to the model; mgr/creator are blocked from self-modifying their own affection; the placebo was even turned into a *real* feature (a 7-tier behavioral-tone hint keyed on a genuine 0–100 `intimacy_score`). This case spawned `docs/edge_cases.md` itself. The honest residual: the robust fix is **schema validation at the dispatcher layer**, so correctness can't depend on every handler getting its `else` branch right.

### The web turn that never acts — and the FAIL baseline that proves it

**Symptom:** in the community E2E, an owner asks (via the manager) for a new friend. The managers *talk about* doing it but never emit the `<tools>` block that performs the creation. `friend_creation` scores **0/10**.

**Root cause:** under the `claude_cli -p` text backend there is **no native function-calling** — the model must *choose* to emit the `<tools>` text dialect. In isolated single-shot calls both agents emit it correctly; in multi-turn social conversation, natural chat wins and the commit point is skipped.

**Fix attempt + honest limit (`b2e21cb`):** prompt rules — *"narration is not action — a friend request you didn't route never happens."* Measured via the EDD harness, this lifted conversation quality 6→9 and overall 69.4→75.0, but **`friend_creation` stayed 0/10**. The documented conclusion is candid: prompt tuning alone cannot make text-dialect tool emission reliable in multi-turn chat; the robust fix is a native tool-use backend. The QA system is deliberately built to **keep this failure visible** on a trend chart rather than hide it.

### The infrastructure traps — "the shell works but the daemon doesn't"

Two production-grade diagnostic puzzles round out the set. A **WebSocket keepalive drop** (close code 1011): a synchronous 30–90s `claude_cli` call blocked the event loop past `ping_timeout=20`, tearing down the socket mid-conversation and harvesting an empty snapshot. The fix (`a4eb9cd`) was env-gated ping control (`GLIMI_WS_PING_INTERVAL=0` for E2E) plus client resilience that **breaks and harvests the partial transcript from the server DB** instead of bubbling. And a **macOS Local Network Privacy** trap (`502: no route to host` from cloudflared, while a shell `curl` to the same LAN address succeeded 10/10) — root-caused to background daemons being LNP-gated on LAN dials but *not* loopback. The fix: a reverse-SSH tunnel converting the LAN dial into a loopback dial the daemon is permitted to make.

## 4. Key Engineering & Product Decisions

**OSS over monetization (`pivot_subagent_review.md`, May 17).** An honest market teardown rejected the obvious pivot — a dev-productivity sub-agent system — because that market is occupied by the labs themselves, and the genuinely novel assets (autonomous agent-to-agent chat, layered memory) are *low-value* there: *"developers want the agents to finish the task fast, not chat with each other."* The conclusion was unusually self-aware: the existing code suited the pivot, but that didn't make the pivot *better*. OSS-as-portfolio sidesteps an unwinnable market while preserving the engineering. **Tradeoff:** trades uncertain ARR for a credibility asset whose payoff is a job — and only works if the claims survive a hiring manager's `grep`, which is why a `honesty pass` commit (`a581de5`) walked back overstated memory claims.

**AGPL-3.0 over Apache-2.0 (`90f7470`, Jun 19).** Strong copyleft so network-served derivatives must open-source — the MongoDB/Grafana/Mastodon stance. **Tradeoff, accepted explicitly:** AGPL is an adoption deterrent (many companies ban it), shrinking the contributor pool for a project whose goal is visibility. The author chose anti-free-riding control over maximal reach, retaining copyright for optional future dual-licensing.

**Discord as a temporary adapter, held as an invariant.** From the first `CLAUDE.md`: *the final goal is native web chat; Discord is a temporary exit used only because building chat UI is expensive.* The `platform_decoupling_review.md` audit (Apr 22) found 9 clean core files, 15 legitimate adapters, and **7 leaks**, sized the full decoupling at 5–7 days, and — crucially — **chose to defer it**, with the name-based channel model flagged as the XL-cost item. The principle was finally cashed out in Phase 7's web chat, a multi-month architectural intention that survived delivery pressure.

**Eval-driven development with a committed FAIL baseline.** Rather than cherry-pick a green run, `d3bcde1` seeds `gen-0001 = 69.4/100 FAIL (friend_creation 0/10)`. A `critical` dimension flag (`1eb4c46`) ensures a high chat score can't paper over a broken core journey. `git log -- tests/e2e/qa_generations/` becomes a measured, honest quality timeline. **Tradeoff:** the headline composite stays red until a multi-day decoupling effort lands — accepting a public red number as the price of a trustworthy metric.

## 5. What This Demonstrates About Engineering Judgment

Three threads run through the work, and they are the actual portfolio signal.

**First, a repeated "great decoupling" pattern applied at increasing scale** — TUI→platform (5k-line split), app→standalone kernel (DI via protocol seams, dependency-free package, examples proving independence), and generic eval→core. The *same* disciplined shape every time: define the protocol seam, build the adapter, write tests that prove the inner layer runs without the outer one. That repeatability under deadline is the mark of clean-architecture instinct rather than one lucky refactor.

**Second, a consistent failure-class diagnosis.** Four of the hardest bugs — sync wipe, placebo drift, cache isolation, the silent web turn — share one signature: *a layer reports success while the underlying effect is zero or wrong.* The engineering response was identical each time: **make the failure loud and bounded.** A brake that aborts and demands inspection. An `ok=False` propagated to the model. A per-switch invalidation map behind a race-safe lock. An eval harness that keeps an unsolved bug on a trend chart. Recognizing that these were *the same problem* is the senior move.

**Third, honesty as an engineering practice, not a virtue signal.** Explicit "정직화" commits walking back README claims. A corrected billing premise documented in `llm_cost_control_plan.md` when an assumed Anthropic pricing change turned out not to be live. A committed failing baseline. Across a solo, AI-paired, 780-commit sprint, the most reliable indicator of judgment was the refusal to let any layer — code, claims, or metrics — report success it hadn't earned.