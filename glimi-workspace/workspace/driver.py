# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""workspace/driver.py — the autonomous owner-driver loop.

This is the work-clone analogue of the Community's autonomous social-sim: instead
of a human typing each follow-up, the **owner-agent** (``workspace/owner_agent``)
runs the loop a human owner normally runs by hand — *give a goal → let the team
work → review what came back → hand down the next concrete ask → repeat until it's
good enough*.

:func:`drive_workspace` is one cancellable coroutine that, each round:

  1. **gates first** — checks cancellation and the budget BEFORE any kernel turn,
     so a runaway loop can't spend past its caps;
  2. **owner turn** — :func:`owner_agent.owner_review` decides the next concrete
     instruction (or that the work is done) and logs its reasoning to the
     read-only ``internal-owner`` channel (the "owner thinking" the web shows);
  3. **posts the instruction** to ``dm-coordinator`` AS THE OWNER (``owner_id``) —
     exactly as a human typing would — so the post→run ordering lives in one place;
  4. **runs the round** — :func:`run.run_round` (Coordinator delegates →
     specialists reply → A2A on ``internal-*`` → group round → gated deliverable);
  5. **records + emits** the deliverable, then sleeps a cancellable beat.

Three independent brakes, all checked at the top of each round (never after a
turn has already been issued):

  - **round cap** ``max_rounds`` — a hard ceiling even if the owner never says
    done (reason ``"max_rounds"``);
  - **budget cap** — ``budget_check`` defaults to the SAME monthly ledger the
    kernel's per-turn guard uses (``budget.allow_claude(community_id())``), so the
    workspace and the Community share one cap (reason ``"budget"``);
  - **cancellation** — a ``threading.Event`` checked at the round top and during
    the inter-round sleep (reason ``"cancelled"``).

On the offline **echo** backend everything is free and deterministic (scripted
owner reviews + stubbed team turns), so the public demo and the tests run the
full loop at ``$0``.

Kernel boundary holds: imports ``glimi`` + the sibling app modules only.
"""
from __future__ import annotations

import asyncio
from typing import Callable, Optional

from glimi import Glimi

try:  # script / flat-dir on sys.path
    from owner_agent import OWNER_REVIEW_CHANNEL, owner_review
    from run import run_round
    from team import COORDINATOR_DM
except ImportError:  # imported as workspace.driver
    from .owner_agent import OWNER_REVIEW_CHANNEL, owner_review
    from .run import run_round
    from .team import COORDINATOR_DM

# Default pause between rounds (seconds). Cancellable — split into short waits so
# /auto/stop interrupts a sleeping driver promptly. Tests pass round_delay=0.
DEFAULT_ROUND_DELAY = 2.0


def _default_budget_check() -> bool:
    """Default budget gate: the SAME monthly cap the kernel's per-turn guard uses,
    scoped to the active community so workspace + Community share one ledger.
    Degrades open (returns True) if budget can't be measured."""
    try:
        from glimi import budget
        from glimi import runtime as _rt
        return budget.allow_claude(_rt.community_id())
    except Exception:
        return True


def _fire(on_event: Optional[Callable], frame: dict) -> None:
    """Invoke the optional event sink, swallowing any error so a bad sink can't
    kill the loop."""
    if on_event is None:
        return
    try:
        on_event(frame)
    except Exception:
        pass


def _cancelled(cancel) -> bool:
    """True if a cancellation Event was supplied and is set."""
    return bool(cancel is not None and cancel.is_set())


async def _sleep_cancellable(delay: float, cancel) -> bool:
    """Sleep up to ``delay`` seconds, returning early (True) if cancelled.

    Polls the cancel Event in short slices so /auto/stop interrupts a sleeping
    driver within ~0.1s instead of waiting out the full delay."""
    if delay <= 0:
        return _cancelled(cancel)
    waited = 0.0
    step = 0.1
    while waited < delay:
        if _cancelled(cancel):
            return True
        await asyncio.sleep(min(step, delay - waited))
        waited += step
    return _cancelled(cancel)


async def drive_workspace(
    g: Glimi, *,
    goal: str,
    context: str = "",
    backlog=None,
    owner_name: str = "",
    max_rounds: int = 5,
    round_delay: float = DEFAULT_ROUND_DELAY,
    budget_check: Optional[Callable[[], bool]] = None,
    on_event: Optional[Callable[[dict], None]] = None,
    cancel=None,
    run_scoped: Optional[Callable] = None,
) -> dict:
    """Run the autonomous owner-driver loop on ``g`` for up to ``max_rounds``.

    Returns ``{"rounds": int, "deliverables": list[str], "done": bool,
    "stopped_reason": str, "last_deliverable": str}`` where ``stopped_reason`` is
    one of ``"done" | "max_rounds" | "cancelled" | "budget"``.

    Parameters:
      goal: the work goal the owner is driving toward.
      context / backlog: extra brief the owner-agent factors into its reviews.
      owner_name: display name for the owner's seat (defaults to ``g.owner.name()``).
      max_rounds: hard round ceiling (the loop stops here even if never "done").
      round_delay: cancellable pause between rounds (0 in tests).
      budget_check: called BEFORE each round; False → stop with reason ``"budget"``.
        Defaults to the kernel's monthly cap (echo is always within budget).
      on_event: optional sink for live frames — ``{type:'text', ...}`` per turn
        (run_round emits these) and ``{type:'auto', phase, ...}`` lifecycle frames.
      cancel: a ``threading.Event``; set it (e.g. from /auto/stop) to stop the loop.
      run_scoped: optional callable ``run_scoped(fn) -> result`` that runs a sync
        ``fn`` under the server's per-workspace scoping lock (``reg.run_in_ws``).
        When provided, EVERY kernel-touching step (owner turn + instruction post +
        run_round) is routed through it so the global-singleton write path stays
        serialized and pointed at THIS workspace. When ``None`` (CLI / tests on a
        dedicated store) steps run directly.
    """
    if budget_check is None:
        budget_check = _default_budget_check
    if not owner_name:
        owner_name = g.owner.name()
    owner_id = g.owner.id()
    max_rounds = max(1, int(max_rounds))

    # Route a kernel-touching sync step through the server's scoping lock if one
    # was supplied; otherwise run it inline (the CLI/test case on a dedicated store).
    loop = asyncio.get_event_loop()

    async def _scoped(fn):
        if run_scoped is not None:
            return await loop.run_in_executor(None, run_scoped, fn)
        return await loop.run_in_executor(None, fn)

    transcript: list[tuple] = []            # (round_idx, instruction, deliverable, note)
    deliverables: list[str] = []
    last_deliverable = ""
    done = False
    stopped_reason = "max_rounds"

    for rnd in range(1, max_rounds + 1):
        # 1) Gate FIRST — cancellation, then budget — before any kernel turn.
        if _cancelled(cancel):
            stopped_reason = "cancelled"
            _fire(on_event, {"type": "auto", "phase": "cancelled", "round": rnd - 1})
            break
        try:
            within_budget = budget_check()
        except Exception:
            within_budget = True  # degrade open — accounting must never block
        if not within_budget:
            stopped_reason = "budget"
            _fire(on_event, {"type": "auto", "phase": "budget_exhausted",
                             "round": rnd - 1})
            break

        # 2) Owner turn — decide the next instruction (or done) + log reasoning to
        #    the read-only internal-owner channel. Runs under the scoping lock so
        #    the internal-owner write hits THIS workspace's store.
        decision = await _scoped(lambda: owner_review(
            g, goal=goal, context=context, backlog=backlog,
            transcript=transcript, last_deliverable=last_deliverable,
            owner_name=owner_name,
        ))
        if decision.get("done"):
            done = True
            stopped_reason = "done"
            _fire(on_event, {"type": "auto", "phase": "done", "round": rnd - 1})
            break

        instruction = (decision.get("instruction") or "").strip()
        if not instruction:
            # Owner produced neither a 'done' nor an instruction — treat as done
            # rather than spinning an empty round.
            done = True
            stopped_reason = "done"
            _fire(on_event, {"type": "auto", "phase": "done", "round": rnd - 1})
            break

        # 3) Post the instruction to dm-coordinator AS THE OWNER (human-typing
        #    parity). This is the single place the instruction is posted.
        def _post_instruction(text=instruction):
            g.store.set_channel_participants(COORDINATOR_DM, [owner_id, "coordinator"])
            g.store.log_message(COORDINATOR_DM, owner_id, text)
        await _scoped(_post_instruction)
        _fire(on_event, {
            "type": "text", "channel": COORDINATOR_DM,
            "speaker": owner_name, "speaker_id": owner_id,
            "text": instruction, "is_user": True,
        })

        # 4) Run the round (Coordinator → specialists → A2A → group → deliverable).
        #    run_round emits its own per-turn {type:'text'} frames via on_event.
        deliverable = await _scoped(lambda: run_round(
            g, instruction, owner_name, on_event=on_event,
        ))

        # 5) Record + emit the round result.
        note = (decision.get("note") or "").strip()
        transcript.append((rnd, instruction, deliverable, note))
        deliverables.append(deliverable)
        last_deliverable = deliverable
        _fire(on_event, {
            "type": "auto", "phase": "round_done", "round": rnd,
            "deliverable_preview": (deliverable or "")[:200],
        })

        # 6) Cancellable inter-round pause.
        if await _sleep_cancellable(round_delay, cancel):
            stopped_reason = "cancelled"
            _fire(on_event, {"type": "auto", "phase": "cancelled", "round": rnd})
            break

    return {
        "rounds": len(deliverables),
        "deliverables": deliverables,
        "done": done,
        "stopped_reason": stopped_reason,
        "last_deliverable": last_deliverable,
    }
