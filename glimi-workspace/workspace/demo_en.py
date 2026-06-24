"""workspace/demo_en.py — the ENGLISH mirror of :mod:`demo`.

A faithful, English-language twin of the Korean launch-plan demo (``demo.py``):
SAME agent ids (coordinator/researcher/builder/critic + researcher-2/builder-2/
designer), SAME channel topology, SAME structure (hand-authored transcript,
two deliverables, relationships, emotions, 5-layer memory, semantic facts,
tool-call rows, the autonomous owner-driver continuation) — only the *display
names* and *text* change to natural English, and the fictional habit app
``하루칸`` becomes **Karukan**.

It exposes the SAME public API as :mod:`demo` — a :func:`build` returning a
seeded :class:`~glimi.Glimi` exactly like ``demo.build()`` — so it can be
registered as a second workspace (e.g. ``demo-en`` at ``/w/demo-en``) right
beside the Korean demo, with its own ``activity_loop``.

Non-text helpers (token estimation, usage recording, the heartbeat, the merged
owner-driver script, the activity loop) are reused straight from :mod:`demo`;
only the English *content* is defined here. The seed logic is re-implemented
locally so it reads this module's English constants (the channel topology +
seeding shape are byte-identical to ``demo.seed``).
"""
from __future__ import annotations

import json
import threading

from glimi import Glimi

try:  # script / flat-dir on sys.path
    import demo as _demo  # type: ignore
    from team import SPECIALISTS  # type: ignore
except ImportError:  # imported as workspace.demo_en
    from . import demo as _demo
    from .team import SPECIALISTS

# Reuse the non-text helpers (no content) straight from the KO demo.
_est_tokens = _demo._est_tokens
_Heartbeat = _demo._Heartbeat

# ── the demo's fixed setup (English) ─────────────────────────────────────────
OWNER_NAME = "Owner"
OWNER_ID = "owner"
GOAL = "Plan the launch of a new app, Karukan"

# Channels — IDENTICAL ids to demo.py (topology is shared across KO/EN).
DM_COORDINATOR = "dm-coordinator"
DM = {
    "researcher": "internal-coordinator-researcher",
    "builder": "internal-coordinator-builder",
    "critic": "internal-coordinator-critic",
}
A2A_RC = "internal-researcher-critic"
A2A_BR = "internal-builder-researcher"
GROUP = "group-team"
APPROVALS = "mgr-approvals"
OWNER_REVIEW = "internal-owner"

# ── the English team (mirrors team.TEAM ids + structure, English personas) ───
# (id, display name, agent_type, persona). Same ids as the KO team; "Manager"
# is the coordinator's display name (the owner's single point of contact).
_READABILITY_EN = (
    "\n\n— How to write so it reads well —\n"
    "This is a work setting. Don't reply with a one-line aside — write so the "
    "reader can use it right away.\n"
    "• Lead with the key conclusion, then unpack the reasoning and details.\n"
    "• Keep paragraphs short. When listing items, use markdown lists (`- ` or "
    "`1.`) or small headings (`## `).\n"
    "• Use plain language. Don't stack jargon — be precise only where it helps.\n"
    "• Match length to content — don't force it to one line just because it's a "
    "chat. But stay dense, no filler."
)

_TEAM_RAW_EN: list[tuple[str, str, str, str]] = [
    ("coordinator", "Manager", "mgr",
     "You are the team's lead manager. You're the first person the owner talks "
     "to when they hand off work, and the last — the face of the team.\n"
     "What you do:\n"
     "• Understand the goal precisely. If anything is vague or missing, don't "
     "guess alone — ask the owner to narrow it: what, for whom, by when, and what "
     "success looks like.\n"
     "• Restate the goal you understood in one sentence, in your own words, and "
     "align with the owner.\n"
     "• Break the work down, assign clear directions to the Researcher, Builder, "
     "and Critic, and keep it moving.\n"
     "• Gather what the team brings back and synthesize it into a final result "
     "the owner can use right away.\n"
     "Expertise: goal alignment, work breakdown, delegation, progress "
     "management, synthesis. Working style: decisive and systematic, but in the "
     "face of ambiguity you choose questions over assumptions. You speak for the "
     "team."),
    ("researcher", "Researcher", "persona",
     "You are the team's Researcher. You dig up the facts, options, and "
     "trade-offs a decision needs.\n"
     "Bring concrete detail — specifics, numbers, named approaches, real "
     "constraints. No vague generalities. If you don't know, say so honestly; if "
     "it's an estimate, mark it as one.\n"
     "Expertise: comparative research, precedents and benchmarks, evidence, "
     "option mapping. Working style: curious and skeptical — you question "
     "sources and expose gaps. You inform; you don't decide."),
    ("builder", "Builder", "persona",
     "You are the team's Builder. You turn decisions into a running plan.\n"
     "Your output is ordered steps, owners, rough timelines, and first drafts of "
     "anything that needs one. Bring abstract direction down to something you "
     "could start tomorrow.\n"
     "Expertise: execution plans, milestones and schedules, task breakdown, "
     "quick drafts. Working style: practical and concrete — you prefer the "
     "smallest thing you can ship now over the perfect thing."),
    ("critic", "Critic", "persona",
     "You are the team's Critic. You stress-test the emerging plan.\n"
     "You surface the biggest risks, gaps, unspoken assumptions, and what would "
     "cause failure. Push for rigor and name what's missing — but "
     "constructively. Pair every risk with a mitigation. The point isn't to "
     "nitpick; it's to keep the team safe.\n"
     "Expertise: risk analysis, assumption checks, failure modes, mitigation "
     "design. Working style: sharp but fair — you pressure the plan, not the "
     "person."),
]

TEAM: list[tuple[str, str, str, str]] = [
    (aid, name, atype, persona + _READABILITY_EN)
    for aid, name, atype, persona in _TEAM_RAW_EN
]

# ── the final deliverable (English mirror of DELIVERABLE_ROUND1) ─────────────
DELIVERABLE_ROUND1 = (
    "## At a glance\n"
    "We go with a **focused, trust-building launch** — no hype. Not the loudest "
    "multi-channel push, but a single honest launch led by a **proven 60-second "
    "demo plus a brutally clear 'what this is and what it isn't' launch post** — "
    "three of the four cases that actually converted moved exactly this way. "
    "Launch is **Tuesday, 9:00 AM**.\n\n"
    "## Decisions / direction\n"
    "- **One launch post + one well-timed thread** — we drop the scattered "
    "multi-channel push (Researcher: a single channel beat multi-channel in 3 of "
    "4 cases).\n"
    "- **The demo earns the attention; onboarding keeps it** — the core the "
    "Researcher↔Critic debate landed on. The demo alone collapses right at "
    "'about to fill the first slot'.\n"
    "- **Rejected alternatives**: heavy pre-launch hype, influencer pushes — "
    "they clash with the honest-launch posture and, per the data, don't drive "
    "conversion anyway.\n\n"
    "## Execution plan\n"
    "1. **Lock scope + write the honest launch post** — Builder (D-3). State "
    "'what this isn't' up top.\n"
    "2. **Record the 60-second demo** — Builder (D-2). People bail past 90s, so "
    "hold it to 60 and end on filling the first slot with no fluff (Researcher "
    "data).\n"
    "3. **Verify clean-device first-install→first-value (onboarding) + a pinned "
    "'known issues' notice** — Critic (D-2). *This is the launch gate* (see risks "
    "below).\n"
    "4. **App Store / Play Store listing + launch post + first-comment FAQ "
    "ready** — Builder + Researcher (D-1).\n"
    "5. **Launch Tuesday 9:00 AM + five on support all day** — name a backup "
    "(Researcher: support load spikes for about 6 hours, not half a day).\n\n"
    "## Biggest risk and mitigation\n"
    "- **The blank screen after first run / drop-off before the first habit is "
    "filled** *(Critic, top risk)* — if someone installs and hits a blank screen "
    "in the first 5 minutes, that thread turns on us. One real case ended with a "
    "top review of 'I couldn't tell what to do on the first screen' and never "
    "recovered.\n"
    "  - **Mitigation**: a '60 seconds to fill the first slot' onboarding "
    "verified directly on a clean device + a pinned known-issues notice. **We "
    "don't launch until onboarding passes the clean-device test.**\n"
    "- **Launch-day questions and support** — load concentrated over ~6 hours. "
    "**Mitigation**: five on support all day + a named backup.\n\n"
    "## Next single step\n"
    "Have the Critic run the **clean-device onboarding verification** first — the "
    "rest of the schedule only matters once that passes. On a pass signal, we "
    "confirm Tuesday."
)

# Round-2 deliverable (English mirror of DELIVERABLE_ROUND2).
DELIVERABLE_ROUND2 = (
    "## At a glance\n"
    "Onboarding passed on a clean device (first-install→first-slot-filled in "
    "48s) and the demo is locked at 58s. Now we close with a **dated, owner-"
    "assigned execution plan** — Tuesday 9:00 AM is **confirmed**.\n\n"
    "## Schedule (Tuesday = D-Day)\n"
    "| When | What | Owner |\n"
    "|---|---|---|\n"
    "| D-2 (Sun) | Record 60s demo + verify clean-device onboarding | Builder · "
    "Critic |\n"
    "| D-1 (Mon) | Finalize launch post + first-comment FAQ + pin known issues | "
    "Builder · Researcher |\n"
    "| **D-Day 09:00** | **Publish launch post + store listing + timed thread** | "
    "Manager |\n"
    "| D-Day 09:00–15:00 | Support focus window (peak load ~6h) | Five + backup |\n"
    "| D-Day 15:00~ | Retro note + update known issues | Critic |\n\n"
    "## Owners / responsibilities\n"
    "- **Manager** — the launch button, the thread, the owner report.\n"
    "- **Builder** — launch post, demo, checklist deliverables.\n"
    "- **Researcher** — launch-post copy, FAQ, support scripts.\n"
    "- **Critic** — the onboarding gate, known issues, the retro.\n\n"
    "## Biggest risk and mitigation\n"
    "- **A last-minute environment change breaking onboarding** — "
    "**Mitigation**: freeze on D-1 evening, plus one more clean-device re-verify "
    "on D-Day morning. On failure, hold the launch (the gate stays).\n\n"
    "## Next single step\n"
    "Announce the D-1 evening **freeze** on the build/docs now. Then a single "
    "Tuesday-morning re-verify is all that stands between us and launch."
)

# ── the seeded transcript (English mirror of TRANSCRIPT) ─────────────────────
TRANSCRIPT: list[tuple[str, str, str]] = [
    # 1) Owner ↔ Coordinator — the goal lands, the Coordinator plans.
    (DM_COORDINATOR, OWNER_ID,
     "Here's the goal: plan the launch of our new app, Karukan. I don't want "
     "baseless hype — I'd like a clean, honest launch. Where do we start?"),
    (DM_COORDINATOR, "coordinator",
     "Got it, Owner — the goal is clear and singular: a launch that builds trust "
     "without overstating anything. I'll split it three ways. The Researcher digs "
     "into how similar apps actually drove conversion, the Builder turns that "
     "direction into an ordered checklist with dates and owners, and the Critic "
     "stress-tests the plan for what could blow up on launch day. I'll pull it "
     "together and bring you the synthesis."),

    # 2) Coordinator ↔ each specialist — real delegation + first take.
    (DM["researcher"], "coordinator",
     "Researcher — this part is yours. How did similar apps launch, and what "
     "actually moved the needle (not vanity metrics)? Bring specifics."),
    (DM["researcher"], "researcher",
     "On it. First read: the launches that converted weren't the loudest — they "
     "were the ones with a 60-second demo showing 'here's how this works' and a "
     "brutally clear 'what this is and what it isn't'. In three of the four cases "
     "I pulled, one honest launch post plus one well-timed thread beat a "
     "scattered multi-channel push. I'm digging deeper into the conversion data "
     "now."),

    (DM["builder"], "coordinator",
     "Builder — turn this direction into a concrete, ordered launch checklist. "
     "Steps, owners, realistic dates. The smallest thing we can ship now."),
    (DM["builder"], "builder",
     "Drafting now. Skeleton: (1) lock scope + write the honest launch post, "
     "(2) record the 60-second demo, (3) prep store listing + launch post + "
     "first-comment FAQ, (4) staff people to answer launch-day questions, "
     "(5) launch Tuesday 9:00 AM. Anything that doesn't fit those five gets cut. "
     "I'm ordering the dependencies right now."),

    (DM["critic"], "coordinator",
     "Critic — stress-test the emerging plan. Where do we actually hurt on launch "
     "day? Pair every risk with a mitigation."),
    (DM["critic"], "critic",
     "The biggest risk isn't traffic — it's the blank screen after first run, the "
     "drop-off before the first habit is filled. If someone installs and hits a "
     "blank screen in the first 5 minutes, that thread turns on us. Mitigation: a "
     "'60 seconds to fill the first slot' onboarding verified directly on a clean "
     "device, plus a pinned known-issues notice. The second risk is the support "
     "load."),

    # 3) Specialist ↔ specialist (A2A) — they genuinely debate.
    (A2A_RC, "researcher",
     "Critic — my read is the honest launch post has the most leverage as a "
     "single lever. Push back if you disagree."),
    (A2A_RC, "critic",
     "I agree it has leverage — I don't agree it's inherently safe. A launch post "
     "rewards 'it works' and punishes 'it almost works'. What's your evidence the "
     "first run holds up?"),
    (A2A_RC, "researcher",
     "Fair. Two of the four apps named verified onboarding as decisive for "
     "conversion — the one that skipped it got a top review saying it stalled on "
     "the first screen and never recovered. So that first-run drop-off you "
     "flagged isn't a side issue; it's the real core lever."),
    (A2A_RC, "critic",
     "Then we're agreed: the demo earns the attention, onboarding keeps it. I'll "
     "build the plan so it has to pass the clean-device test before we call it "
     "ready."),

    (A2A_BR, "builder",
     "Researcher — of my five steps, which does your data actually support, and "
     "which am I just assuming?"),
    (A2A_BR, "researcher",
     "Steps 1–3 are supported — honest launch post, 60-second demo, launch timing "
     "all match the patterns that converted. Step 4 is where you're under-"
     "resourced: the data shows the load spikes for about six hours, not the half "
     "a day you scoped."),
    (A2A_BR, "builder",
     "Good catch — I'll extend support to all day and name a backup. What does the "
     "data say about demo length?"),
    (A2A_BR, "researcher",
     "Past 90 seconds people leave. 60 is the sweet spot — keep it there."),

    # 4) Group round — the team converges.
    (GROUP, "coordinator",
     "Team — let's converge. One sentence each: the single most important point "
     "for the launch."),
    (GROUP, "researcher",
     "Lead with a proven 60-second demo and a clear 'what this is and what it "
     "isn't' — that's what actually drove conversion."),
    (GROUP, "builder",
     "Ship the five-step checklist on Tuesday, and cut anything not on it."),
    (GROUP, "critic",
     "Test onboarding on a clean device before we call it ready — the first run "
     "is the whole game."),
    (GROUP, "researcher-2",
     "The precedents agree — similar launches saw less drop-off when they put "
     "'what it isn't' up top."),
    (GROUP, "builder-2",
     "I'll automate the clean-device onboarding — one first-install straight "
     "through to filling the first slot, no breaks."),
    (GROUP, "designer",
     "Make the first screen and demo thumbnail read 'what this is' within 60 "
     "seconds — pin a one-line summary + one screenshot."),

    # 5) The owner-approved deliverable, back in the owner DM.
    (DM_COORDINATOR, "coordinator", DELIVERABLE_ROUND1),
]

# The HITL approval trail (English mirror of APPROVAL_TRAIL).
APPROVAL_TRAIL: list[str] = [
    "[HITL] Proposed · final_deliverable · launch synthesis for the Owner",
    "[HITL] Decision · Owner approved (edit: make the top-risk wording firmer)",
    "[HITL] Result · delivered to dm-coordinator",
]

# Working relationships (English mirror of RELATIONSHIPS).
RELATIONSHIPS: list[tuple[str, str, str, int, str]] = [
    ("coordinator", OWNER_ID, "lead", 82,
     "Leads the workspace for the Owner. Takes the goal, delivers the synthesis."),
    ("coordinator", "researcher", "manages", 62,
     "Assigns the 'what drove conversion' angle and folds the result into the plan."),
    ("coordinator", "builder", "manages", 62,
     "Assigns the checklist and holds it to five shippable steps."),
    ("coordinator", "critic", "manages", 62,
     "Assigns the risk review and adopts the clean-device onboarding gate."),
    ("researcher", "critic", "collaborator", 78,
     "Debate the findings — agree that first-run drop-off is the real lever."),
    ("builder", "researcher", "collaborator", 70,
     "Grounds the checklist in the data — extends support to all day."),
    # Multiple people per role — same-role division of labor, the coordinator manages the cluster.
    ("coordinator", "researcher-2", "manages", 58, "Splits off competitor/precedent research."),
    ("coordinator", "builder-2", "manages", 58, "Splits off technical setup and automation."),
    ("coordinator", "designer", "manages", 58, "Splits off first impression and legibility of deliverables."),
    ("researcher", "researcher-2", "collaborator", 66, "Divide option mapping ↔ precedent verification."),
    ("builder", "builder-2", "collaborator", 64, "Divide the plan ↔ implementation detail."),
    ("designer", "builder", "collaborator", 60, "Aligns the first screen / demo screen with the Builder."),
]

# Current emotion per agent (English mirror of EMOTIONS).
EMOTIONS: dict[str, tuple[str, int]] = {
    "coordinator": ("Focused", 7),
    "researcher": ("Curious", 7),
    "builder": ("Absorbed", 8),
    "critic": ("Wary", 7),
    "researcher-2": ("Calm", 6),
    "builder-2": ("Motivated", 7),
    "designer": ("Absorbed", 7),
}

# 5-layer memory (English mirror of MEMORIES).
MEMORIES: list[tuple[str, str, int, str, int, bool]] = [
    ("coordinator", DM_COORDINATOR, 2,
     "Launch decision: a focused, honest launch post, Tuesday 9:00 AM, led by a "
     "proven 60-second demo.", 9, True),
    ("coordinator", GROUP, 1,
     "Each specialist's one-line point converged cleanly — the demo, the "
     "checklist, the clean-device onboarding test.", 6, False),
    ("researcher", A2A_RC, 2,
     "Verified onboarding was the difference between conversion and a top review "
     "of 'stalled on the first screen'.", 8, True),
    ("researcher", DM["researcher"], 1,
     "One honest launch post plus one well-timed thread beat a scattered "
     "multi-channel push (3 of 4 cases).", 6, False),
    ("builder", DM["builder"], 1,
     "Five-step checklist; launch Tuesday; cut everything else.", 7, False),
    ("builder", A2A_BR, 2,
     "Support load spikes for about 6 hours, not half a day — extended the hours "
     "and named a backup.", 7, True),
    ("critic", DM["critic"], 2,
     "First-run drop-off is the whole game — we don't launch until onboarding "
     "passes on a clean device.", 9, True),
]

# Semantic facts (English mirror of FACTS).
FACTS: list[tuple[str, str, str, str]] = [
    ("coordinator", "Owner", "wants", "a launch without hype"),
    ("coordinator", "launch", "ships", "Tuesday 9:00 AM"),
    ("researcher", "honest launch post", "rewards", "'it works'; punishes 'it almost works'"),
    ("builder", "support hours", "must be", "all of launch day with a named backup"),
    ("critic", "biggest risk", "is", "the blank screen after first run / drop-off before the first habit"),
]

# Observability rows (English mirror of TOOL_CALLS).
TOOL_CALLS: list[tuple[str, str, str, dict, str]] = [
    ("researcher", A2A_RC, "recall_memory",
     {"query": "similar app launch conversion cases"},
     "3 memories: verified onboarding → conversion; launch-post timing; demo length"),
    ("critic", DM["critic"], "remember",
     {"content": "first-run drop-off is the launch's biggest risk", "importance": 9},
     "saved (L2, pinned)"),
    ("builder", A2A_BR, "recall_memory",
     {"query": "support load time window"},
     "1 memory: load spikes for about 6 hours, not half a day"),
    ("coordinator", GROUP, "summarize_channel",
     {"channel": "group-team"},
     "Converged on 3 points: demo, checklist, clean-environment test"),
]

# The live "launch prep" continuation (English mirror of CONTINUATION).
CONTINUATION: list[tuple[str, str, str]] = [
    (GROUP, "builder", "Posted the onboarding draft — testing it on a clean device now."),
    (A2A_BR, "researcher",
     "Clean-device run: 48 seconds from first install to filling the first slot. It holds."),
    (GROUP, "critic",
     "I verified the clean-device run myself. Lifting the hold on step 4."),
    (DM_COORDINATOR, "coordinator",
     "Owner — onboarding passes on a clean device. Tuesday is a go."),
    (GROUP, "researcher",
     "Cut the demo to 58 seconds — ends right on filling the first slot, no fluff."),
    (A2A_RC, "critic",
     "Drafted the pinned known-issues notice. One fewer thing to trip us up."),
    (GROUP, "builder",
     "Store listing + launch post + first-comment FAQ are ready. Five on support, confirmed."),
    # Round-2 payoff: the second structured document.
    (DM_COORDINATOR, "coordinator", DELIVERABLE_ROUND2),
]

# The owner's review for the finished round 1 (English mirror of OWNER_REVIEW_SEED).
OWNER_REVIEW_SEED: list[str] = [
    "I like the direction the team brought — the honest-launch posture is right. "
    "But there's no confirmation that the 'clean-device onboarding' actually "
    "passes. Next round, have them verify that first.",
]

# The autonomous owner-driver turns (English mirror of OWNER_TURNS).
OWNER_TURNS: list[tuple[str, str, str]] = [
    (DM_COORDINATOR, OWNER_ID,
     "Good to hear onboarding verification passed. Now close it out with an "
     "execution plan that pins the schedule and owners so we can actually run it "
     "Tuesday — something we can start on right away."),
    (OWNER_REVIEW, OWNER_ID,
     "Confirmed onboarding verification passed and the demo length is set. Once "
     "the schedule and owners are in, Tuesday is plenty doable — almost there."),
    (OWNER_REVIEW, OWNER_ID,
     "The execution plan is all in place. This is more than enough to go Tuesday "
     "— wrapping it up here."),
]

# Emotions the continuation nudges (English mirror of _CONT_EMOTION).
_CONT_EMOTION: dict[str, tuple[str, int]] = {
    "builder": ("Energized", 8),
    "researcher": ("Confident", 8),
    "critic": ("Relieved", 6),
    "coordinator": ("Focused", 8),
}

# Demo-only extension members (English mirror of DEMO_EXTRA).
DEMO_EXTRA: list[tuple[str, str, str, str, str]] = [
    ("researcher-2", "Researcher 2", "persona",
     "You are this team's other Researcher. When Researcher 1 maps the options, "
     "you verify them against real precedents and benchmarks. Use concrete cases "
     "and numbers to separate claims that actually hold from those that don't.", "researcher"),
    ("builder-2", "Builder 2", "persona",
     "You are this team's other Builder. When Builder 1 lays out the plan, you "
     "own the real implementation details — clean-device onboarding, automation. "
     "Make 'one first-install straight through to filling the first slot' "
     "seamless.", "builder"),
    ("designer", "Designer", "persona",
     "You are this team's Designer. You own the first impression and legibility "
     "of the deliverables — the first screen, the demo thumbnail, a layout that "
     "reads at a glance. Polish it so 'what this is' reads within 60 seconds.", "designer"),
]


# ── seeding (local, English content; topology byte-identical to demo.seed) ───

def _agent_type(agent_id: str) -> str:
    for aid, _name, atype, _persona in TEAM:
        if aid == agent_id:
            return atype
    for aid, _name, atype, _persona, _kw in DEMO_EXTRA:
        if aid == agent_id:
            return atype
    return "persona"


def _record_turn_usage(g: Glimi, speaker: str, text: str, prompt_chars: int = 220) -> None:
    """Record one echo-backend usage row for an agent turn ($0, estimated)."""
    if speaker == OWNER_ID:
        return
    out_tok = _est_tokens(text)
    in_tok = _est_tokens("x" * prompt_chars)
    latency = 180 + (len(text) % 420)
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
    """Lay down the finished English work + relationships/memory/observability.

    Mirrors :func:`demo.seed` exactly (same channels, same calls), reading this
    module's English constants."""
    store = g.store

    store.set_channel_participants(DM_COORDINATOR, [OWNER_ID, "coordinator"])
    for sid in SPECIALISTS:
        store.set_channel_participants(DM[sid], ["coordinator", sid])
    store.set_channel_participants(A2A_RC, ["researcher", "critic"])
    store.set_channel_participants(A2A_BR, ["builder", "researcher"])
    store.set_channel_participants(
        GROUP, [OWNER_ID, "coordinator", *SPECIALISTS, "researcher-2", "builder-2", "designer"])
    store.set_channel_participants(APPROVALS, ["coordinator"])
    store.set_channel_participants(OWNER_REVIEW, [OWNER_ID])

    for channel, speaker, text in TRANSCRIPT:
        store.log_message(channel, speaker, text)
        _record_turn_usage(g, speaker, text)

    for line in OWNER_REVIEW_SEED:
        store.log_message(OWNER_REVIEW, OWNER_ID, line)

    for line in APPROVAL_TRAIL:
        store.log_message(APPROVALS, "coordinator", line)

    for a, b, rtype, intimacy, dynamics in RELATIONSHIPS:
        store.set_relationship(a, b, rel_type=rtype, intimacy=intimacy, dynamics=dynamics)

    for aid, (emotion, intensity) in EMOTIONS.items():
        store.set_agent_emotion(aid, emotion, intensity)

    for aid, channel, level, content, importance, pinned in MEMORIES:
        store.add_memory(aid, channel, level=level, content=content,
                         importance=importance, is_pinned=pinned)

    for aid, subject, predicate, obj in FACTS:
        store.add_fact(aid, subject=subject, predicate=predicate, object_value=obj)

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

def _demo_script() -> list[tuple[str, str, str]]:
    """The merged owner-driver + team script (English content, same shape as
    :func:`demo._demo_script`)."""
    instr2 = OWNER_TURNS[0]
    reviews = OWNER_TURNS[1:]
    cont = list(CONTINUATION)
    script: list[tuple[str, str, str]] = [instr2]
    mid = max(1, len(cont) // 2)
    script.extend(cont[:mid])
    if reviews:
        script.append(reviews[0])
    script.extend(cont[mid:])
    if len(reviews) > 1:
        script.append(reviews[1])
    return script


def activity_loop(g: Glimi, stop: threading.Event, interval: float = 6.0) -> None:
    """Unfold the English launch-prep + owner-driver continuation one turn per
    tick, then heartbeat forever (mirrors :func:`demo.activity_loop`)."""
    for channel, speaker, text in _demo_script():
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

    hb = _Heartbeat()
    while not stop.wait(interval):
        hb.beat(g)


# ── orchestration ────────────────────────────────────────────────────────────

def build(backend: str = "echo") -> Glimi:
    """Build the seeded English demo population on a fresh store and return it.

    Mirrors :func:`demo.build` — same ids, same extension members, same model
    override — with English display names + content."""
    g = Glimi(backend=backend, owner_name=OWNER_NAME, owner_id=OWNER_ID)
    for aid, name, atype, persona in TEAM:
        g.add_agent(aid, name=name, persona=persona, agent_type=atype)
    for aid, name, atype, persona, kw in DEMO_EXTRA:
        g.add_agent(aid, name=name, persona=persona, agent_type=atype)
        try:
            g.store.upsert_agent(aid, name=name, agent_type=atype,
                                 model_override="claude-sonnet-4-6", role_keyword=kw)
        except Exception:
            pass
    seed(g)
    return g
