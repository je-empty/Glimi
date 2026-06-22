"""Unit tests for the autonomous owner-driver loop (workspace/driver.py +
workspace/owner_agent.py + the re-callable run.run_round).

All on the offline ``echo`` backend → free, deterministic, no API key, $0 — the
same discipline the rest of the Workspace tests hold. Covered:

- ``run_round`` is re-callable and idempotent: each call (with the instruction
  already in dm-coordinator) produces a non-empty deliverable from the
  Coordinator and delegates to every specialist;
- ``owner_review`` returns a progressing instruction + done flag and logs the
  owner's reasoning to the read-only ``internal-owner`` channel;
- ``drive_workspace`` honors max_rounds, records the owner notes in
  internal-owner, produces non-empty deliverables, and sets a stopped_reason;
- a ``budget_check=lambda: False`` stops the loop before any round runs (budget
  brake), and a mid-run budget trip stops after one round;
- cancellation stops the loop.

Kernel-only: imports ``glimi`` + the app's flat-dir modules, never ``src`` /
Discord.
"""
from __future__ import annotations

import asyncio
import os
import sys

# Workspace is English-default for the kernel A2A scaffolding, but the owner-agent
# echo script is Korean (UI default). Force GLIMI_LANG=en only for the A2A turns;
# the scripted echo reviews are language-independent (no LLM call).
os.environ.setdefault("GLIMI_LANG", "en")

# Make the flat-dir app modules (run, team, driver, owner_agent) importable like
# run.py does, regardless of the test runner's cwd.
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_WS_DIR = os.path.join(_REPO, "glimi-workspace", "workspace")
if _WS_DIR not in sys.path:
    sys.path.insert(0, _WS_DIR)

from glimi import Glimi  # noqa: E402

import owner_agent  # noqa: E402
import driver  # noqa: E402
import run  # noqa: E402
from team import (  # noqa: E402
    COORDINATOR_DM, DELEGATION_CHANNELS, SPECIALISTS, TEAM,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _fresh_workspace() -> Glimi:
    """A fresh echo-backed Glimi with the full team seeded (own store)."""
    g = Glimi(backend="echo", owner_name="테스터", owner_id="owner")
    for aid, name, atype, persona in TEAM:
        g.add_agent(aid, name=name, persona=persona, agent_type=atype)
    # Each fresh store gets its own scripted-review counter; reset to be safe.
    owner_agent.reset_echo_state(g)
    return g


def _msgs(g: Glimi, channel: str) -> list:
    return g.store.get_recent_messages(channel, limit=500)


def _drive(g: Glimi, **kw) -> dict:
    """Run drive_workspace to completion on a fresh event loop."""
    kw.setdefault("goal", "오픈소스 프로젝트 공개 런칭 기획")
    kw.setdefault("owner_name", "테스터")
    kw.setdefault("round_delay", 0.0)
    return asyncio.run(driver.drive_workspace(g, **kw))


# ── run_round: re-callable + delegates ─────────────────────────────────────────

def test_run_round_is_recallable_and_produces_deliverable():
    g = _fresh_workspace()
    # Instruction must already be in dm-coordinator (the driver/human posts it).
    g.store.set_channel_participants(COORDINATOR_DM, ["owner", "coordinator"])
    g.store.log_message(COORDINATOR_DM, "owner", "런칭 기획 시작해요")

    d1 = run.run_round(g, "런칭 기획 시작해요", "테스터")
    assert d1 and d1.strip(), "round 1 produced an empty deliverable"
    assert "[오류]" not in d1

    # The deliverable was logged to dm-coordinator from the Coordinator.
    coord_msgs = [m for m in _msgs(g, COORDINATOR_DM) if m["speaker"] == "coordinator"]
    assert coord_msgs, "no coordinator message in dm-coordinator"

    # Each specialist got a delegation (Coordinator spoke into every dm-*).
    for sid in SPECIALISTS:
        ch = DELEGATION_CHANNELS[sid]
        coord_in_ch = [m for m in _msgs(g, ch) if m["speaker"] == "coordinator"]
        assert coord_in_ch, f"Coordinator did not delegate in {ch}"

    # Re-callable: a SECOND round on the same store produces another deliverable
    # (idempotent in the sense of "runs again cleanly, no crash, fresh output").
    g.store.log_message(COORDINATOR_DM, "owner", "다음 단계로 진행해요")
    d2 = run.run_round(g, "다음 단계로 진행해요", "테스터")
    assert d2 and d2.strip(), "round 2 produced an empty deliverable"
    assert "[오류]" not in d2


def test_run_workspace_still_works_once():
    """The one-time create/CLI path is unchanged: run_workspace logs the goal as
    the owner then runs a single round, returning a non-empty deliverable."""
    g = _fresh_workspace()
    final = run.run_workspace(g, "테스터", "오픈소스 런칭 기획")
    assert final and final.strip()
    # The owner's goal landed in dm-coordinator as the owner's own message.
    owner_msgs = [m for m in _msgs(g, COORDINATOR_DM) if m["speaker"] == "owner"]
    assert owner_msgs, "run_workspace did not log the owner goal to dm-coordinator"


# ── owner_review: progressing instruction + internal-owner reasoning ───────────

def test_owner_review_returns_decision_and_logs_internal_owner():
    g = _fresh_workspace()
    d = owner_agent.owner_review(
        g, goal="런칭 기획", context="정직한 기조",
        transcript=[], last_deliverable="", owner_name="테스터",
    )
    assert set(("done", "instruction", "note")).issubset(d.keys())
    assert d["done"] is False, "first echo review should not be done"
    assert d["instruction"].strip(), "first review should produce an instruction"

    # Reasoning logged to the read-only internal-owner channel from the owner.
    notes = _msgs(g, owner_agent.OWNER_REVIEW_CHANNEL)
    assert notes, "owner reasoning not logged to internal-owner"
    assert all(m["speaker"] == "owner" for m in notes)


def test_owner_review_progresses_across_rounds():
    """Successive echo reviews give DISTINCT, advancing instructions (not a loop)
    and converge to done."""
    g = _fresh_workspace()
    instructions = []
    transcript = []
    last = ""
    done_seen = False
    for rnd in range(1, 5):
        d = owner_agent.owner_review(
            g, goal="런칭 기획", transcript=transcript,
            last_deliverable=last, owner_name="테스터",
        )
        if d["done"]:
            done_seen = True
            break
        instructions.append(d["instruction"])
        transcript.append((rnd, d["instruction"], f"deliverable {rnd}", d["note"]))
        last = f"deliverable {rnd}"
    assert done_seen, "echo owner never declared done"
    assert len(instructions) >= 2, "expected at least two work instructions"
    assert len(set(instructions)) == len(instructions), \
        "owner instructions repeated — not progressing"


# ── drive_workspace: full loop, max_rounds, internal-owner, deliverables ───────

def test_drive_workspace_runs_rounds_and_logs_everything():
    g = _fresh_workspace()
    result = _drive(g, max_rounds=2)

    assert result["rounds"] >= 1, "driver ran zero rounds"
    assert result["stopped_reason"] in ("done", "max_rounds"), result["stopped_reason"]

    # Every recorded round produced a non-empty deliverable.
    assert result["deliverables"], "no deliverables produced"
    for d in result["deliverables"]:
        assert d and d.strip(), "a round produced an empty deliverable"
        assert "[오류]" not in d

    # internal-owner has one owner reasoning message per owner turn (>= rounds).
    notes = _msgs(g, owner_agent.OWNER_REVIEW_CHANNEL)
    assert len(notes) >= result["rounds"], \
        "internal-owner missing owner notes"
    assert all(m["speaker"] == "owner" for m in notes)

    # The owner posted its instruction(s) to dm-coordinator as the owner.
    owner_instr = [m for m in _msgs(g, COORDINATOR_DM) if m["speaker"] == "owner"]
    assert len(owner_instr) >= result["rounds"], \
        "owner did not post instructions to dm-coordinator"


def test_drive_workspace_respects_max_rounds():
    """Even if the owner never says 'done', the hard round cap stops the loop."""
    g = _fresh_workspace()
    # Force the owner to never finish so only the round cap can stop it.
    result = asyncio.run(driver.drive_workspace(
        g, goal="끝없는 목표", owner_name="테스터", round_delay=0.0, max_rounds=2,
        budget_check=lambda: True,
        # Owner that always wants more, never done, distinct each round.
        run_scoped=None,
    ))
    # The scripted echo owner converges at round 3, so with max_rounds=2 it must
    # hit the cap OR finish early; either way it never exceeds the cap.
    assert result["rounds"] <= 2


# ── budget brake ──────────────────────────────────────────────────────────────

def test_budget_check_false_stops_before_any_round():
    g = _fresh_workspace()
    result = _drive(g, max_rounds=5, budget_check=lambda: False)
    assert result["rounds"] == 0, "budget brake should stop before any round runs"
    assert result["stopped_reason"] == "budget"
    assert not result["deliverables"]
    # No team turns were issued (no deliverable in dm-coordinator from coordinator).
    coord = [m for m in _msgs(g, COORDINATOR_DM) if m["speaker"] == "coordinator"]
    assert not coord, "budget brake leaked a coordinator turn"


def test_budget_trips_after_first_round():
    """A budget check that allows round 1 then trips stops after exactly 1 round."""
    g = _fresh_workspace()
    calls = {"n": 0}

    def budget():
        calls["n"] += 1
        return calls["n"] <= 1  # allow round 1's pre-check, deny round 2's

    result = _drive(g, max_rounds=5, budget_check=budget)
    assert result["rounds"] == 1, f"expected exactly 1 round, got {result['rounds']}"
    assert result["stopped_reason"] == "budget"


# ── cancellation ──────────────────────────────────────────────────────────────

def test_cancel_before_start_stops_immediately():
    import threading
    g = _fresh_workspace()
    cancel = threading.Event()
    cancel.set()
    result = _drive(g, max_rounds=5, cancel=cancel)
    assert result["rounds"] == 0
    assert result["stopped_reason"] == "cancelled"
