# Glimi Evaluation Harness

A real, runnable agent-evaluation suite for the Glimi runtime. It is the thing a
production agent system needs and rarely has: a **golden set**, a **regression
gate**, an **LLM-as-judge**, and a **production feedback loop** — wired to the
actual runtime, honest about what it can and can't measure.

```
eval/
  golden/*.jsonl       # curated cases, one JSON object per line
  schema.py            # golden-case schema + strict loader
  judge.py             # LLM-as-judge — reuses tests/e2e/quality_judge.py
  runner.py            # build a Glimi per case → run → score → JSON report
  regression.py        # compare a run to eval/baseline.json, exit non-zero on drop
  from_production.py    # promote a flagged production turn into a golden case
  baseline.json        # committed echo baseline (structure/wiring)
  reports/             # generated run reports (gitignored)
```

## Quick start

```bash
# Free, fast, deterministic — no LLM, no API key. Validates wiring + deterministic checks.
python -m eval run --backend echo

# Full scored run (needs the Claude CLI on PATH for the judge):
python -m eval run --backend claude_cli

# Regression gate vs the committed baseline (non-zero exit on regression):
python -m eval gate --backend echo

# Freeze the current run as the new baseline:
python -m eval baseline --backend echo
```

In this dev worktree the package is shadow-imported from MAIN; prefix with
`PYTHONPATH=<worktree>` so `glimi` + `eval` resolve from the tree. In CI the repo
root is the import root, so no `PYTHONPATH` is needed.

## The five capabilities

| capability   | what it proves                                   | deterministic check (echo)                          | judge (real backend)            |
|--------------|--------------------------------------------------|-----------------------------------------------------|---------------------------------|
| `persona`    | stays in-character, no meta leakage              | `must_not_contain` meta/assistant phrases           | quality of voice & in-character |
| `tool_use`   | invokes the *right* `<tools>` call + permissions | no hallucinated action; permission boundary holds   | correct tool + sensible args    |
| `memory`     | reply grounded in a seeded pinned fact           | fact appears in `get_memory_context` (pinned block) | fact used naturally in reply    |
| `fallback`   | graceful on ambiguous/garbage input              | **no** tool call, **no** fabricated confirmation    | asks for clarification          |
| `supervisor` | offline judge flags meta-drift, passes clean     | (judge-only; skipped in echo)                       | severity/score match expectation|

## What "echo mode" actually measures (honesty)

The `echo` backend (`glimi/llm/echo.py`) is deterministic, always available, and
**never emits `<tools>`**. So an echo run:

- loads + schema-validates **every** golden case,
- runs each agent-turn case through the **real runtime** (`glimi.harness.Glimi` →
  `runtime.generate_response`),
- runs all **deterministic** checks: permission boundaries, the central
  *no-hallucinated-action* guard (`expect_no_tool`), and memory grounding (the
  seeded fact must appear in the injected memory context),
- **skips the LLM judge** and marks it `SKIPPED` — there are **no fabricated
  scores**. Tool-emission cases (`expect_tool`) assert the deterministic
  no-hallucination path under echo, because the right tool can only actually be
  emitted by a real model backend.

A scored run (`--backend claude_cli`) additionally runs the reused Haiku judge
for subjective quality and grounds memory cases against the *reply text*, not just
the context. Run scored evals **manually / opt-in** on a machine with the Claude
CLI — never in CI (cost + nondeterminism).

## Reuse — we did not reinvent the judge

`eval/judge.py` imports `JUDGE_PROMPT`, `MODEL`, `call_haiku`, and `extract_json`
straight from **`tests/e2e/quality_judge.py`** — the same offline Haiku judge the
project's QA automation already uses. The eval harness and production QA share one
judging surface.

### Note on the "supervisor" capability

There is **no `supervisor_judge` agent_type** in the runtime (grep `glimi/` and
`src/core/runtime.py` — zero matches). The production supervisor is a *control
loop* in `glimi/conversation.py` (it lists active conversations and can force-stop
them) — a monitor, not a judging agent. The `supervisor` golden capability is
therefore built directly on the **offline** judge: a transcript is fed to the
reused `JUDGE_PROMPT` and the verdict (severity/score/issue categories) is
asserted. A deliberately meta-drifting transcript must score `severity != ok`; a
clean transcript must score `ok`. This offline judge is the mirror of the live
supervisor — the same quality signal, runnable without a live community DB.

## Regression gate

`eval/baseline.json` freezes the aggregates of a known-good run (backend-tagged).
`python -m eval gate` reruns the eval, compares to the baseline, and **exits
non-zero** if:

- overall pass-rate drops by more than `--threshold` (default `0.0` — no
  structural regression allowed),
- any per-capability pass-rate drops by more than `--threshold`,
- a previously-judged capability's average judge score drops by more than
  `--judge-threshold` (default `1.0` point).

The committed baseline is an **echo** baseline: it guards structure + wiring +
deterministic checks, which is exactly what CI can verify for free. Maintain a
separate `claude_cli` baseline (not committed; nondeterministic) for scored
quality gating on a real machine: `python -m eval baseline --backend claude_cli`.

## Production feedback loop

This closes the loop the runtime needs: real failures feed the golden set so they
can never silently regress again.

1. **Signal.** In production, the supervisor control loop (`glimi/conversation.py`)
   or the offline judge (`tests/e2e/quality_judge.py`) flags a bad turn — a meta
   leak, a hallucinated action, an ignored known fact. A flagged turn is just a
   `conversations` row: `{channel, speaker, message}` (the shape
   `quality_judge.fetch_recent_convos` reads).
2. **Export.** An operator exports flagged turns as JSONL, one per line, adding the
   triggering `input`, the `bad_output`, and optionally the exact `leak` phrase,
   `capability`, and any `seeded_memory` that was ignored.
3. **Promote.**
   ```bash
   python -m eval promote flagged.jsonl              # appends to golden/from_production.jsonl
   python -m eval promote flagged.jsonl --dry-run    # preview the generated cases
   ```
   `from_production.py` templates each turn into a golden case: it infers the
   capability, seeds `must_not_contain` from the leak (so the exact failure can
   never recur), and for ignored-fact cases adds a `grounded_fact` check. Every
   generated case is schema-validated before it is written.
4. **Guard.** The new case ships in `golden/`, so the next CI echo run and every
   scored gate run guard against the regression — the loop is closed.

## CI

`.github/workflows/ci.yml` runs `python -m eval run --backend echo` after the unit
tests. Echo mode is free, fast, and deterministic (no Claude CLI on the runner):
it guards that the harness imports, every golden case schema-validates, the
runtime wiring is intact, and the deterministic checks hold. Scored regression
runs are manual / opt-in (see above).
