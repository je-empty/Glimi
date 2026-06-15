# research_desk — a specialist team that builds shared memory

A persistent "research desk": three specialists — an **Editor** (frames &
synthesizes), a **Researcher** (brings concrete detail), and a **Skeptic**
(stress-tests claims) — work one question over several rounds on a single shared
channel.

It's [Glimi Core](../../README.md) used as a plain **library** — no Discord, no
Community code, ~100 lines. The same engine that powers Glimi Community.

## What it shows

- **A designed population** — three distinct personas. Each could run a different
  model (cloud or local) and still share one store.
- **One shared, persistent memory** — every turn lands in a single channel and any
  agent can read the whole desk back from storage. Nobody is handed the transcript
  by hand: the kernel injects the shared history (and rolled-up memory) into each
  turn.
- **Layered long-term memory** — as the desk grows, raw turns roll up into L1
  summaries that get reused later. In a real-backend run you can watch the Editor's
  final verdict explicitly *drop* a point the Skeptic killed two turns earlier —
  that's the shared memory carrying across, not a coincidence.

## Run it

Offline, zero dependencies, no API key — the `echo` backend stubs replies, so the
reasoning is illustrative (it proves the wiring, not the thinking):

```bash
PYTHONPATH=. python examples/research_desk/run.py
```

Swap in a real model for genuine collaboration and meaningful memory:

```bash
GLIMI_LLM_BACKEND=claude_cli python examples/research_desk/run.py   # Claude CLI
python examples/research_desk/run.py --backend ollama              # local Ollama
```

(Once `pip install glimi` lands, plain `python run.py` works.)

## Sample output (real backend: `claude_cli`, trimmed)

```
--- The desk opens: Should a small team self-host its LLMs, or use a hosted API? ---
Editor: Framing — this is a leverage-vs-control decision. Angles to examine:
  operational reality, economics, technical fit, the "scalability cliff", vendor
  risk. What I'd investigate first: their use case, skill mix, models, constraints.

--- Round 1 ---
Skeptic: The Editor's framing has dangerous oversimplifications. The "scalability
  cliff" assumes break-even is a point, not a fog. The "DevOps person" assumption
  is doing a lot of unspoken work. Vendor risk cuts both ways. Most teams should
  actually be hybrid. What's their actual pain point?

--- Round 2 ---
Researcher: Reading the Skeptic's pushback — let me ground it in numbers. Cost
  crossover: <5M tokens/mo → API wins (~$9/mo); 10–100M → fog zone; 1B+ → self-host
  math works but it's a 24/7 operation. The DevOps elephant is real.
Skeptic: The weak link is "attrition cost is hard to quantify but brutal." That's
  hand-wavy — show me exit-interview data or we stop saying it.

--- The Editor synthesizes the desk's verdict ---
Editor: Verdict — a three-gate decision. Gate 1 (blocker): sustained DevOps
  capacity. Gate 2: token volume. Gate 3: the unnamed constraint (latency/privacy).
  Dropping the "attrition cost" handwave — the Skeptic's right.

--- Memory snapshot (one shared store) ---
  the full discussion (89 messages) lives in ONE shared channel, readable by any agent.
  Rolled up into long-term memory (L1): Editor=5, Researcher=2
```

Notice the Editor's verdict references and **drops** the Skeptic's "attrition cost"
critique from an earlier turn. None of that was passed between agents in code — each
one read the desk out of the shared store.
