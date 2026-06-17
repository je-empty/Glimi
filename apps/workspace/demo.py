"""apps/workspace/demo.py — a seeded, live, real-time-viewable Workspace demo.

The Workspace analogue of the Community showcase (``scripts/seed_demo_mockup.py``):
a hand-authored, believable team — a **Coordinator** plus a **Researcher**,
**Builder**, and **Critic** — working a real goal (*plan the public launch of our
open-source project*), seeded directly into the kernel's in-memory store so you can
watch it **live** in the Core dashboard with zero setup: no API key, no network, no
Discord.

Two pieces, mirroring the Community demo's "seed + faked liveness":

1. :func:`seed` lays down the finished work — the interaction web across DMs,
   agent-to-agent channels, a group round, the owner-approved deliverable, plus
   relationships, emotions, 5-layer memory, semantic facts, and a few
   observability rows (tool calls + echo-backend usage at $0 — local is free).

2. :func:`activity_loop` keeps the dashboard **genuinely live**: it unfolds a short
   "launch prep" continuation one turn at a time, then drops into a heartbeat that
   keeps emotions and usage ticking — so the auto-refreshing dashboard shows new
   activity without a reload, and without spending a cent.

Built entirely on the ``glimi`` package — kernel only (no ``src``, no Discord), the
same boundary the rest of Glimi Workspace holds.

Run it (needs the dashboard extra: ``pip install "glimi[dashboard]"``)::

    PYTHONPATH=. python apps/workspace/run.py --demo            # → http://127.0.0.1:8800
    PYTHONPATH=. python apps/workspace/run.py --demo --host 0.0.0.0
"""
from __future__ import annotations

import json
import threading
from typing import Optional

from glimi import Glimi

try:  # script / flat-dir on sys.path
    from team import LABELS, SPECIALISTS, TEAM
except ImportError:  # imported as apps.workspace.demo
    from .team import LABELS, SPECIALISTS, TEAM

# ── the demo's fixed setup ───────────────────────────────────────────────────
OWNER_NAME = "Sam"
OWNER_ID = "owner"
GOAL = "Plan the public launch of our open-source project"

# Channels (mirror team.py's topology so the seeded demo and a real run look alike).
DM_COORDINATOR = "dm-coordinator"
DM = {"researcher": "dm-researcher", "builder": "dm-builder", "critic": "dm-critic"}
A2A_RC = "internal-researcher-critic"
A2A_BR = "internal-builder-researcher"
GROUP = "group-team"
APPROVALS = "mgr-approvals"  # mgr-* system log convention (never a chat channel)

# ── the seeded transcript (hand-authored, believable — the finished work) ─────
# (channel, speaker_id, text). speaker "owner" == Sam.
TRANSCRIPT: list[tuple[str, str, str]] = [
    # 1) Owner ↔ Coordinator — the goal lands, the Coordinator plans.
    (DM_COORDINATOR, OWNER_ID,
     "Here's the goal: plan the public launch of our open-source project. I don't "
     "want hype we can't back up — a clean, honest launch. Where do we start?"),
    (DM_COORDINATOR, "coordinator",
     "Got it, Sam — one clear target: a credible launch that doesn't overpromise. "
     "I'll split it three ways. Researcher digs into how comparable projects "
     "actually converted; Builder turns the call into an ordered checklist with a "
     "date and owners; Critic stress-tests it for the ways launch day bites. I'll "
     "bring you the synthesis."),

    # 2) Coordinator ↔ each specialist — real delegation + first take.
    (DM["researcher"], "coordinator",
     "Researcher — your angle: how did comparable open-source projects launch, and "
     "what actually moved the needle (not vanity metrics)? Bring specifics."),
    (DM["researcher"], "researcher",
     "On it. First read: the launches that converted weren't the loudest — they led "
     "with a 60-second 'here's the thing working' demo and a brutally clear 'what "
     "it is / what it isn't.' Show HN plus one well-timed thread beat a scattered "
     "multi-channel push in three of the four cases I pulled. Digging into the "
     "conversion data now."),

    (DM["builder"], "coordinator",
     "Builder — turn the direction into a concrete, ordered launch checklist: "
     "steps, owners, a realistic date. Smallest thing that ships."),
    (DM["builder"], "builder",
     "Drafting. Skeleton: (1) freeze scope + write the honest README, (2) record "
     "the 60s demo, (3) stage the Show HN post + first-comment FAQ, (4) line up "
     "people to answer issues on launch day, (5) ship Tuesday 9am PT. I'd cut "
     "everything that isn't those five. Sequencing the dependencies now."),

    (DM["critic"], "coordinator",
     "Critic — stress-test the emerging plan. Where does launch day actually hurt "
     "us? Every risk with a mitigation."),
    (DM["critic"], "critic",
     "Biggest risk isn't traffic — it's the gap between the demo and a cold install. "
     "If someone clones it and hits a wall in the first five minutes, the thread "
     "turns on us. Mitigation: a 'works in 60 seconds' quickstart we've tested on a "
     "clean machine, plus a pinned known-issues note. Second risk: support load."),

    # 3) Specialist ↔ specialist (A2A) — they genuinely debate.
    (A2A_RC, "researcher",
     "Critic — my read is Show HN is the highest-leverage single move. Push back if "
     "you see it."),
    (A2A_RC, "critic",
     "I don't disagree it's leverage — I disagree it's safe by default. Show HN "
     "rewards 'it works' and punishes 'it almost works.' What's your evidence the "
     "cold start holds up?"),
    (A2A_RC, "researcher",
     "Fair. Two of the four projects credited a tested quickstart for the "
     "conversion — the one that skipped it got a top comment about a broken install "
     "and never recovered. So your cold-start risk is the actual lever, not a side "
     "note."),
    (A2A_RC, "critic",
     "Then we agree: the demo gets attention, the quickstart keeps it. I'll hold "
     "the plan to a clean-machine test before we call it ready."),

    (A2A_BR, "builder",
     "Researcher — which of my five steps does your data actually support, and "
     "which am I assuming?"),
    (A2A_BR, "researcher",
     "Steps 1–3 are supported — the honest README, the 60s demo, and the Show HN "
     "timing all map to what converted. Step 4 is where you're under-resourcing: "
     "the data says load spikes for about six hours, not the afternoon you "
     "budgeted."),
    (A2A_BR, "builder",
     "Good catch — I'll widen the support window to a full day and name backups. "
     "Does the data say anything about the demo length?"),
    (A2A_BR, "researcher",
     "Under 90 seconds or people bounce. Sixty is the sweet spot — keep it."),

    # 4) Group round — the team converges.
    (GROUP, "coordinator",
     "Team — converging. One sentence each: your single most important point for "
     "the launch."),
    (GROUP, "researcher",
     "Lead with a tested 60-second demo and a clear 'what it is / what it isn't' — "
     "that's what actually converted."),
    (GROUP, "builder",
     "Ship the five-step checklist Tuesday; cut anything that isn't on it."),
    (GROUP, "critic",
     "Test the quickstart on a clean machine before we call it ready — the cold "
     "start is the whole game."),

    # 5) The owner-approved deliverable, back in the owner DM.
    (DM_COORDINATOR, "coordinator",
     "Sam — here's the synthesis. DECISION: a focused, honest launch — Show HN "
     "Tuesday 9am PT, led by a tested 60-second demo and a clear 'what it is / what "
     "it isn't' README. PLAN: (1) freeze scope + honest README, (2) record the 60s "
     "demo, (3) stage the Show HN post + first-comment FAQ, (4) tested clean-machine "
     "quickstart + pinned known-issues, (5) five people on support for the full "
     "launch day. TOP RISK: the gap between the demo and a cold install — we don't "
     "launch until the quickstart passes on a clean machine. That's the line."),
]

# The HITL approval trail for the one consequential action (delivering to Sam).
# Written to the mgr-approvals system-log channel (the convention from the
# Workspace HITL gate), so it's inspectable in the same dashboard.
APPROVAL_TRAIL: list[str] = [
    "[HITL] PROPOSED · final_deliverable · the launch synthesis for Sam",
    "[HITL] DECISION · APPROVED by owner (edited: tightened the top-risk line)",
    "[HITL] OUTCOME · delivered to dm-coordinator",
]

# Working relationships → the dashboard's connection-graph edges.
# (a, b, type, intimacy, dynamics)
RELATIONSHIPS: list[tuple[str, str, str, int, str]] = [
    ("coordinator", OWNER_ID, "lead", 82,
     "Runs the workspace for Sam; took the goal and delivered the synthesis."),
    ("coordinator", "researcher", "manages", 62,
     "Delegated the 'what converted' angle and folded the findings into the plan."),
    ("coordinator", "builder", "manages", 62,
     "Delegated the checklist and held it to a shippable five steps."),
    ("coordinator", "critic", "manages", 62,
     "Delegated the risk pass and adopted the clean-machine gate."),
    ("researcher", "critic", "collaborator", 78,
     "Debated the findings — converged on the cold-start gap as the real lever."),
    ("builder", "researcher", "collaborator", 70,
     "Grounded the checklist in the data — widened the support window to a full day."),
]

# Current emotion per agent (drives the agent cards + node tone).
EMOTIONS: dict[str, tuple[str, int]] = {
    "coordinator": ("focused", 7),
    "researcher": ("curious", 7),
    "builder": ("driven", 8),
    "critic": ("vigilant", 7),
}

# 5-layer memory: (agent, channel, level, content, importance, pinned).
MEMORIES: list[tuple[str, str, int, str, int, bool]] = [
    ("coordinator", DM_COORDINATOR, 2,
     "The launch decision: a focused, honest Show HN on Tuesday 9am PT, led by a "
     "tested 60-second demo.", 9, True),
    ("coordinator", GROUP, 1,
     "Each specialist's one-line point converged cleanly — demo, checklist, "
     "clean-machine test.", 6, False),
    ("researcher", A2A_RC, 2,
     "A tested quickstart was the difference between conversion and a broken-install "
     "top comment.", 8, True),
    ("researcher", DM["researcher"], 1,
     "Show HN plus one well-timed thread beat a scattered multi-channel push (3 of 4 "
     "cases).", 6, False),
    ("builder", DM["builder"], 1,
     "Five-step checklist; ship Tuesday; cut everything else.", 7, False),
    ("builder", A2A_BR, 2,
     "Support load spikes ~6 hours, not an afternoon — widened the window and named "
     "backups.", 7, True),
    ("critic", DM["critic"], 2,
     "The cold-start gap is the whole game — don't launch until the quickstart "
     "passes on a clean machine.", 9, True),
]

# Semantic facts (Layer 3): (agent, subject, predicate, object).
FACTS: list[tuple[str, str, str, str]] = [
    ("coordinator", "Sam", "wants", "a launch that doesn't overpromise"),
    ("coordinator", "the launch", "ships", "Tuesday 9am PT"),
    ("researcher", "Show HN", "rewards", "'it works'; punishes 'it almost works'"),
    ("builder", "the support window", "should be", "a full launch day, with named backups"),
    ("critic", "the biggest risk", "is", "the gap between the demo and a cold install"),
]

# A few illustrative observability rows so the dashboard's Tool-call Timeline shows
# the feature populated. (The capture plumbing is real — every adapter's tool calls
# flow through one choke-point; here we pre-seed a labeled showcase, like the rest
# of the demo. The live loop adds genuine echo-backend usage on top.)
TOOL_CALLS: list[tuple[str, str, str, dict, str]] = [
    # (agent, channel, tool_name, args, result_preview)
    ("researcher", A2A_RC, "recall_memory",
     {"query": "comparable launch conversion"},
     "3 memories: tested quickstart → conversion; Show HN timing; demo length"),
    ("critic", DM["critic"], "remember",
     {"content": "cold-start gap is the launch's biggest risk", "importance": 9},
     "stored (L2, pinned)"),
    ("builder", A2A_BR, "recall_memory",
     {"query": "support load window"},
     "1 memory: load spikes ~6h, not an afternoon"),
    ("coordinator", GROUP, "summarize_channel",
     {"channel": "group-team"},
     "3 points converged: demo, checklist, clean-machine test"),
]

# The live "launch prep" continuation — unfolded one turn per tick by the activity
# loop so a viewer watches the work move forward in real time.
CONTINUATION: list[tuple[str, str, str]] = [
    (GROUP, "builder", "Quickstart draft is up — testing it on a fresh VM now."),
    (A2A_BR, "researcher",
     "Clean-machine run: install to first output in 48 seconds. It holds."),
    (GROUP, "critic",
     "Confirmed the clean-machine run myself. Lifting my block on step 4."),
    (DM_COORDINATOR, "coordinator",
     "Sam — quickstart passes on a clean machine. We're go for Tuesday."),
    (GROUP, "researcher",
     "Demo cut to 58 seconds — lands on the working output, no preamble."),
    (A2A_RC, "critic",
     "Pinned known-issues note is drafted. One less thing to bite us."),
    (GROUP, "builder",
     "Show HN post + first-comment FAQ staged. Five people confirmed for support."),
    (DM_COORDINATOR, "coordinator", "Everything's staged, Sam. Holding for your go."),
]

# Emotions the continuation nudges as the work lands (speaker → new emotion).
_CONT_EMOTION: dict[str, tuple[str, int]] = {
    "builder": ("energized", 8),
    "researcher": ("confident", 8),
    "critic": ("reassured", 6),
    "coordinator": ("focused", 8),
}


# ── seeding ──────────────────────────────────────────────────────────────────

def _agent_type(agent_id: str) -> str:
    for aid, _name, atype, _persona in TEAM:
        if aid == agent_id:
            return atype
    return "persona"


def _est_tokens(text: str) -> int:
    """Estimate tokens for a turn (chars/4), via the kernel's own pricing helper
    when available, so the usage panel shows plausible — clearly estimated — counts."""
    try:
        from glimi.llm.pricing import estimate_tokens_from_chars
        return int(estimate_tokens_from_chars(len(text)))
    except Exception:
        return max(1, len(text) // 4)


def _record_turn_usage(g: Glimi, speaker: str, text: str, prompt_chars: int = 220) -> None:
    """Record one echo-backend usage row for an agent turn — local is $0, tokens
    are estimated (estimated=True), so the dashboard shows honest 'est. · $0'."""
    if speaker == OWNER_ID:
        return
    out_tok = _est_tokens(text)
    in_tok = _est_tokens("x" * prompt_chars)
    latency = 180 + (len(text) % 420)  # deterministic, plausible
    try:
        g.store.record_usage(
            agent_id=speaker, agent_type=_agent_type(speaker),
            model="echo (offline demo)", backend="echo",
            input_tokens=in_tok, output_tokens=out_tok,
            est_cost=0.0, estimated=True, latency_ms=latency,
        )
    except Exception:
        pass


def seed(g: Glimi) -> None:
    """Lay down the finished work + the relationships/memory/observability that the
    dashboard renders. Idempotent enough for a fresh store (the demo's normal case)."""
    store = g.store

    # Participants per channel (so the graph + channel viewer know who's in each).
    store.set_channel_participants(DM_COORDINATOR, [OWNER_ID, "coordinator"])
    for sid in SPECIALISTS:
        store.set_channel_participants(DM[sid], [OWNER_ID, "coordinator", sid])
    store.set_channel_participants(A2A_RC, ["researcher", "critic"])
    store.set_channel_participants(A2A_BR, ["builder", "researcher"])
    store.set_channel_participants(GROUP, [OWNER_ID, "coordinator", *SPECIALISTS])
    store.set_channel_participants(APPROVALS, ["coordinator"])

    # The transcript (+ honest echo usage per agent turn).
    for channel, speaker, text in TRANSCRIPT:
        store.log_message(channel, speaker, text)
        _record_turn_usage(g, speaker, text)

    # The HITL approval trail (system-log channel).
    for line in APPROVAL_TRAIL:
        store.log_message(APPROVALS, "coordinator", line)

    # Relationships → graph edges.
    for a, b, rtype, intimacy, dynamics in RELATIONSHIPS:
        store.set_relationship(a, b, rel_type=rtype, intimacy=intimacy, dynamics=dynamics)

    # Emotions.
    for aid, (emotion, intensity) in EMOTIONS.items():
        store.set_agent_emotion(aid, emotion, intensity)

    # 5-layer memory.
    for aid, channel, level, content, importance, pinned in MEMORIES:
        store.add_memory(aid, channel, level=level, content=content,
                         importance=importance, is_pinned=pinned)

    # Semantic facts (Layer 3).
    for aid, subject, predicate, obj in FACTS:
        store.add_fact(aid, subject=subject, predicate=predicate, object_value=obj)

    # Illustrative tool-call timeline rows.
    for aid, channel, tool_name, args, preview in TOOL_CALLS:
        try:
            store.record_tool_call(
                agent_id=aid, agent_type=_agent_type(aid), channel=channel,
                tool_name=tool_name, args_json=json.dumps(args, ensure_ascii=False),
                result_preview=preview, ok=True,
                latency_ms=40 + (len(preview) % 160),
            )
        except Exception:
            pass


# ── live activity loop ───────────────────────────────────────────────────────

class _Heartbeat:
    """Rotating emotion intensities so the dashboard keeps visibly ticking after the
    continuation has fully unfolded — no transcript spam, just signs of life."""

    def __init__(self) -> None:
        self._i = 0
        self._order = ["coordinator", "researcher", "builder", "critic"]

    def beat(self, g: Glimi) -> None:
        aid = self._order[self._i % len(self._order)]
        self._i += 1
        base = EMOTIONS.get(aid, ("focused", 6))
        # gently oscillate intensity 6↔8 so the agent cards change between polls.
        intensity = 6 + (self._i % 3)
        try:
            g.store.set_agent_emotion(aid, base[0], intensity)
            g.store.record_usage(
                agent_id=aid, agent_type=_agent_type(aid),
                model="echo (offline demo)", backend="echo",
                input_tokens=8, output_tokens=12, est_cost=0.0,
                estimated=True, latency_ms=90 + self._i % 60,
            )
        except Exception:
            pass


def activity_loop(g: Glimi, stop: threading.Event, interval: float = 6.0) -> None:
    """Unfold the launch-prep continuation one turn per tick, then heartbeat forever.

    Genuine store mutations on a timer → the auto-refreshing dashboard shows new
    activity without a reload. All offline (echo), so it never costs anything.
    """
    # Phase 1 — unfold the continuation (one believable new turn per tick).
    for channel, speaker, text in CONTINUATION:
        if stop.wait(interval):
            return
        try:
            g.store.log_message(channel, speaker, text)
            _record_turn_usage(g, speaker, text)
            emo = _CONT_EMOTION.get(speaker)
            if emo:
                g.store.set_agent_emotion(speaker, emo[0], emo[1])
        except Exception:
            pass

    # Phase 2 — heartbeat (keep it alive without spamming the transcript).
    hb = _Heartbeat()
    while not stop.wait(interval):
        hb.beat(g)


# ── orchestration ────────────────────────────────────────────────────────────

def build(backend: str = "echo") -> Glimi:
    """Build the seeded demo population on a fresh store and return the Glimi."""
    g = Glimi(backend=backend, owner_name=OWNER_NAME, owner_id=OWNER_ID)
    for aid, name, atype, persona in TEAM:
        g.add_agent(aid, name=name, persona=persona, agent_type=atype)
    seed(g)
    return g


def run_demo(*, host: str = "127.0.0.1", port: int = 8800,
             interval: float = 6.0, serve: bool = True,
             backend: str = "echo") -> int:
    """Seed the demo, start the live activity loop, and serve the Core dashboard.

    Returns a process exit code. When ``serve`` is False, builds + returns 0 after
    a single synchronous unfold-less seed (used by tests)."""
    g = build(backend=backend)

    if not serve:
        return 0

    stop = threading.Event()
    thread = threading.Thread(
        target=activity_loop, args=(g, stop, interval), daemon=True,
        name="glimi-workspace-demo-activity",
    )
    thread.start()

    url = f"http://{host}:{port}"
    print("=" * 64)
    print("  Glimi Workspace — LIVE DEMO")
    print("=" * 64)
    print(f"  goal    : {GOAL}")
    print(f"  team    : Coordinator, Researcher, Builder, Critic  (owner: {OWNER_NAME})")
    print(f"  backend : {backend} (offline — no API key, $0)")
    print(f"  view    : {url}   ← watch it update live (Ctrl-C to stop)")
    print("=" * 64 + "\n")

    try:
        import glimi.dashboard
        glimi.dashboard.serve(g.store, host=host, port=port)
    except ImportError as exc:
        stop.set()
        print(f"Dashboard deps not installed: {exc}")
        print('Install with:  pip install "glimi[dashboard]"')
        return 1
    except KeyboardInterrupt:
        print("\nDemo stopped.")
    finally:
        stop.set()
    return 0
