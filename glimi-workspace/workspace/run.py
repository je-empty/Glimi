#!/usr/bin/env python3
"""Glimi Workspace — a specialist team that genuinely INTERACTS, on Glimi Core.

A second app on the kernel, alongside the Discord "Community" social-sim — the
proof that **Glimi Core is a genuinely reusable core**. A manager agent
(**Coordinator**) plus three role specialists (**Researcher**, **Builder**,
**Critic**) take a work *goal* and produce a deliverable — not in one round-robin
room, but across several channels with distinct interaction shapes, exactly like
a real team:

1. **Owner ↔ Coordinator** (a DM): the owner gives the goal; the Coordinator
   plans and, at the end, delivers the synthesis.
2. **Coordinator ↔ each specialist** (per-specialist DMs): the Coordinator
   delegates a clear angle to the Researcher, the Builder, and the Critic.
3. **Specialist ↔ specialist** (internal A2A channels): pairs who should
   collaborate actually talk to each other — Researcher ↔ Critic debate the
   findings, Builder ↔ Researcher ground the plan — via the kernel's
   agent-to-agent engine (``runtime.generate_agent_to_agent``).
4. **Group** (a team channel): the whole team converges for one shared round.
5. The Coordinator delivers the final synthesis back in the owner DM.

As it runs, the app records the working **relationships** these interactions form
(``store.set_relationship``) — owner↔Coordinator (lead), Coordinator↔specialist
(manages), specialist↔specialist (collaborator, intimacy ∝ how much they talked).
Those relationships are exactly the edges the Core dashboard's connection graph
draws, so the **same** dashboard that serves Community now renders YOUR team as a
real interaction web. (A real backend ALSO grows these organically via the
kernel's memory extraction; here we also set them structurally so the graph is
populated on any backend, including the offline ``echo``.)

Built entirely on the ``glimi`` package: no Discord, no Community (``src``) code.

First run asks your **name** and **goal** (flags / env / interactive prompt).

Run it (offline echo by default — zero deps, no API key)::

    PYTHONPATH=. python workspace/run.py --name Owner --goal "Plan our launch"

A real model (genuine collaboration + memory + organic relationship growth)::

    GLIMI_LLM_BACKEND=claude_cli PYTHONPATH=. python workspace/run.py
    PYTHONPATH=. python workspace/run.py --backend ollama

View the finished team in the Core dashboard (needs ``pip install glimi[dashboard]``)::

    PYTHONPATH=. python workspace/run.py --serve   # → http://127.0.0.1:8800
"""
from __future__ import annotations

import argparse
import os
import sys

from glimi import Glimi

# Import the sibling ``team`` module whether this file is run as a script
# (``python workspace/run.py`` — its dir is on sys.path[0]) or imported as a
# package module (``workspace.run`` — use a relative import). Either way the
# kernel boundary holds: ``team`` imports nothing from glimi/src/discord.
try:  # script / flat-dir on sys.path
    from team import (
        COLLAB_TURNS, COORDINATOR_DM, DEFAULT_GOAL, GROUP_CHANNEL,
        READABILITY, RESERVED_IDS, TEAM, WS_AGENT_MODEL,
        angle_for, delegation_channel_for, derive_pairs, label_for,
        live_specialists, propose_roster, resolve_setup,
    )
    from approval import (
        APPROVALS_CHANNEL, ApprovalAction, ApprovalPolicy, WebApprovalQueue,
        first_line_elision, run_gate,
    )
except ImportError:  # imported as workspace.run
    from .team import (
        COLLAB_TURNS, COORDINATOR_DM, DEFAULT_GOAL, GROUP_CHANNEL,
        READABILITY, RESERVED_IDS, TEAM, WS_AGENT_MODEL,
        angle_for, delegation_channel_for, derive_pairs, label_for,
        live_specialists, propose_roster, resolve_setup,
    )
    from .approval import (
        APPROVALS_CHANNEL, ApprovalAction, ApprovalPolicy, WebApprovalQueue,
        first_line_elision, run_gate,
    )

DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 8800

# Relationship intimacy (0–100) for the structural edges we record. The dashboard
# graph weights edges by intimacy, so a real team's hub (Coordinator) and its
# closest pairings stand out.
INTIMACY_LEAD = 80      # owner ↔ Coordinator
INTIMACY_MANAGES = 60   # Coordinator ↔ each specialist


def banner(backend: str, owner_name: str, goal: str, approve_mode: str) -> None:
    print("=" * 64)
    print("  Glimi Workspace — a specialist team on Glimi Core")
    print("=" * 64)
    print(f"  owner   : {owner_name}")
    print(f"  goal    : {goal}")
    print(f"  backend : {backend}")
    print(f"  approval: {_approval_banner(approve_mode)}")
    print(f"  team    : " + ", ".join(name for _, name, _, _ in TEAM))
    print(
        "  shape   : owner↔Coordinator (DM), Coordinator↔each specialist (DMs),\n"
        "            specialist↔specialist (A2A), and a group round — a real web."
    )
    if backend == "echo":
        print(
            "\n  Note: 'echo' is the OFFLINE placeholder backend — replies are\n"
            "  stubbed, so the flow is illustrative. The interaction topology and\n"
            "  the relationship graph are REAL regardless. Run with\n"
            "  GLIMI_LLM_BACKEND=claude_cli (or --backend ollama) for real work."
        )
    print("=" * 64 + "\n")


def _label(g: Glimi, speaker_id: str) -> str:
    """Display name for a speaker id (agent label, or the owner's name).

    Resolves dynamic-roster ids via the live store (``label_for``), then the
    static LABELS, then the raw id — so a manager-proposed specialist renders its
    real display name, not its slug."""
    if speaker_id == g.owner.id():
        return g.owner.name()
    return label_for(g, speaker_id)


def _gen(g: Glimi, agent_id: str, guidance: str, channel: str) -> str:
    """Generate an agent's reply using ``guidance`` as the prompt WITHOUT logging the
    guidance as a visible message — only the agent's reply is stored. The owner's
    real instruction (posted once by the caller — run_workspace / driver) stays the
    single owner message; the per-turn framing ('You are X's Coordinator, restate
    it…') is generation context only and never leaks into the chat transcript."""
    return "\n".join(
        g.runtime.generate_response(agent_id, channel, guidance, log_user_message=False)
    )


def _trail_sink(g: Glimi):
    """Build the injectable trail sink that writes each HITL line to BOTH the
    kernel observer (console/app) AND the ``mgr-approvals`` store channel, so the
    proposed→decision→outcome trail is inspectable in the SAME Core dashboard that
    renders the team (an mgr-system-log-style channel, per CLAUDE.md)."""
    def on_log(message: str) -> None:
        g.observer.system(f"[HITL] {message}")
        g.store.log_message(APPROVALS_CHANNEL, "coordinator", message)
    return on_log


# A document skeleton for the FINAL deliverable. The Coordinator's synthesis is
# the workspace's actual work product, so it gets a structured template (clear
# sections) rather than a free-form chat turn — the difference between a 1-line
# punchline and a brief the owner can act on. Kept content-neutral (no domain
# wording) so any goal fills it; the model adapts the headings as needed.
_DELIVERABLE_TEMPLATE = (
    "이 결과물을 아래 골격에 맞춰 마크다운으로 작성하세요 — 빈 칸 채우기가 아니라, "
    "각 절을 팀이 실제로 논의한 구체(이름·수치·트레이드오프)로 채운 진짜 문서로:\n\n"
    "## 한눈에 보기\n"
    "(2~3문장: 무엇을 정했고, 왜 그게 답인지.)\n\n"
    "## 결정 / 방향\n"
    "(핵심 선택과 그 근거. 검토한 대안과 탈락 이유도 짧게.)\n\n"
    "## 실행 계획\n"
    "(번호 매긴 순서 있는 단계. 각 단계에 담당 역할과 대략적 일정/순서를 붙이세요.)\n\n"
    "## 가장 큰 리스크와 완화책\n"
    "(크리틱이 짚은 상위 리스크 1~3개 + 각각의 구체적 완화책.)\n\n"
    "## 다음 한 걸음\n"
    "(오너가 지금 당장 할 수 있는 단 하나의 행동.)\n"
)

# Token ceiling for the final deliverable. Far above a chat turn so the document
# can be a real multi-section brief; echo ignores it (deterministic offline),
# real backends honor it. Override via env for tuning without a code change.
_DELIVERABLE_MAX_TOKENS = int(os.environ.get("GLIMI_WS_DELIVERABLE_MAX_TOKENS", "2560") or "2560")


def _facade_backend_for(provider: str) -> str:
    """Map the kernel runtime's provider decision to a ``glimi.llm.generate``
    ``backend=`` argument. The runtime returns ``'claude'`` for the direct path
    (NOT a facade backend name) and a budget sentinel for CAPPED — in both cases
    we pass ``''`` so the facade does its own selection (SDK→CLI) and re-applies
    the budget guard. Explicit local backends (echo / ollama / SDK / CLI names)
    pass straight through so the deliverable runs on the SAME backend as the turns."""
    p = (provider or "").strip().lower()
    if p in ("echo", "ollama", "claude_cli", "anthropic_sdk"):
        return p
    return ""  # 'claude' / CAPPED / unknown → let the facade select + guard


def _write_deliverable(g: Glimi, channel: str, prompt: str) -> str:
    """Generate the FINAL deliverable through the kernel's LLM choke-point
    (:func:`glimi.llm.generate`) DIRECTLY, with a raised ``max_tokens`` and a
    document-template skeleton — so the synthesis is a structured brief, not a
    one-line chat reply (which ``generate_response`` would cap at chat length).

    It still uses the Coordinator's REAL system prompt + the kernel-injected
    channel context/memory (built via the runtime's own ``_build_prompt``), so the
    deliverable is grounded in everything the team actually said this round. The
    result is logged to ``channel`` as the Coordinator (same as a normal turn), so
    it shows in the dashboard/chat and the HITL gate can wrap it.

    Returns the deliverable text (possibly empty on a capped/failed backend, in
    which case the caller falls back to a normal gated turn)."""
    from glimi import llm as _llm  # kernel choke-point (A2A uses the same facade)

    rt = g.runtime
    if "coordinator" not in rt._active_agents:
        rt.activate_agent("coordinator")
    agent_info = rt._active_agents.get("coordinator")
    if agent_info is None:
        return ""  # caller falls back to a normal gated turn

    profile = agent_info["profile"]
    atype = profile.get("type", "mgr")
    # The user message = the deliverable instruction + the structured skeleton.
    user_message = f"{prompt}\n\n{_DELIVERABLE_TEMPLATE}"
    # RAW_WINDOW recent turns so the synthesis sees the round's discussion; the
    # runtime's _build_prompt folds in memory + the channel transcript + the real
    # system prompt, and returns the resolved model.
    try:
        from glimi.runtime import RAW_WINDOW as _RAW
    except Exception:
        _RAW = 15
    recent = g.store.get_recent_messages(channel, limit=_RAW)
    full_prompt, system_prompt, model = rt._build_prompt(
        agent_info, channel, recent, user_message
    )

    # Which backend the runtime would route to (claude/ollama/echo/CAPPED), mapped
    # to the facade's backend= contract.
    try:
        from glimi.runtime import _provider_for
        provider = _provider_for(atype, model)
    except Exception:
        provider = ""
    backend = _facade_backend_for(provider)

    g.observer.agent_thinking("coordinator", f"최종 결과물 작성 (max_tokens={_DELIVERABLE_MAX_TOKENS})")
    resp = _llm.generate(
        system=system_prompt, user=full_prompt, model=model,
        agent_type=atype, backend=backend,
        max_tokens=_DELIVERABLE_MAX_TOKENS, timeout=120,
    )
    text = (getattr(resp, "text", "") or "").strip()
    if not text:
        return ""
    # Log the deliverable to the channel as the Coordinator (mirrors a real turn).
    try:
        agent_db = g.store.get_agent("coordinator") or {}
        emotion = agent_db.get("current_emotion")
        g.store.log_message(channel, "coordinator", text, emotion=emotion)
    except Exception:
        g.store.log_message(channel, "coordinator", text)
    return text


def gated_deliver(
    g: Glimi, policy: ApprovalPolicy, *, prompt: str, channel: str,
    kind: str, summary: str, interactive: bool,
    web_queue: WebApprovalQueue | None = None,
) -> str:
    """Generate a candidate deliverable, then run it through the HITL gate.

    The CONSEQUENTIAL action: the Coordinator finalizes the deliverable. We (a)
    generate the candidate via :func:`_write_deliverable` — the kernel LLM
    choke-point called DIRECTLY with a raised ``max_tokens`` + a document skeleton,
    so it's a real structured brief, not a chat-length one-liner (with a graceful
    fall back to a normal gated turn if that path returns nothing, e.g. a capped
    backend) — (b) wrap it in an :class:`ApprovalAction`, (c) run the gate — AUTO /
    non-interactive → auto-approve; REQUIRE_APPROVAL + interactive → owner
    approve/edit/reject; reject → graceful fallback — and (d) return the approved /
    edited / fallback text. The candidate is gated BEFORE it is returned as the
    owner-facing deliverable, so approve/edit/reject can rewrite or withhold it.

    A ``web_queue`` (``--serve`` stub) records the action as a PendingApproval and
    auto-approves, so the seam is visible in the dashboard without a web UI.
    """
    candidate = _write_deliverable(g, channel, prompt)
    if not candidate:
        # Capped/failed deliverable path → fall back to a normal gated turn so the
        # round always produces SOMETHING (and the HITL gate still wraps it).
        candidate = _gen(g, "coordinator", prompt, channel)
    print(f"{_label(g, 'coordinator')}:\n{candidate}\n")

    action = ApprovalAction(kind=kind, summary=summary, proposed_text=candidate,
                            channel=channel, metadata={"agent": "coordinator"})
    on_log = _trail_sink(g)

    if web_queue is not None:
        # --serve / headless: no live mid-run input channel → record + auto-approve.
        outcome = web_queue.enqueue(action)
    else:
        outcome = run_gate(action, policy, interactive=interactive, on_log=on_log)

    if outcome.decision != "AUTO_APPROVED" or web_queue is None:
        # One-line console summary of the decision (the AUTO/web cases already
        # log their trail above; this keeps the interactive console readable).
        print(f"  [HITL] {kind}: {outcome.decision} — "
              f"{first_line_elision(outcome.final_text)}\n")
    return outcome.final_text


# The action classes the HITL gate can require approval for. Today only the
# Coordinator's finalization is gated; classifying by ``kind`` means adding more
# gate points later (e.g. a side-effecting "tool_call") is config, not plumbing.
APPROVE_FINAL_KINDS = {"final_deliverable"}


def build_policy(approve_mode: str) -> ApprovalPolicy:
    """Map the ``--approve`` flag to an :class:`~approval.ApprovalPolicy`.

    - ``auto`` (default): auto-approve everything — CI / echo / demo, never blocks.
    - ``final``: require owner approval for the final deliverable; AUTO for the rest.
    - ``off``:  same as ``auto`` (no human gate) — explicit "no approval" alias.
    """
    if approve_mode == "final":
        return ApprovalPolicy.require_for(APPROVE_FINAL_KINDS)
    return ApprovalPolicy.auto_approve_all()


def _approval_banner(approve_mode: str) -> str:
    """One-line description of the approval mode for the startup banner."""
    if approve_mode == "final":
        return ("require owner approval for the final deliverable "
                "(approve / edit / reject)")
    return "auto-approve all (no human gate)"


def a2a_exchange(g: Glimi, a: str, b: str, channel: str, brief: str,
                 turns: int, *, on_event=None) -> int:
    """Run a genuine agent-to-agent exchange between ``a`` and ``b`` on ``channel``.

    Drives the kernel's ``runtime.generate_agent_to_agent`` directly, alternating
    speakers, so each agent reads the shared channel (via injected memory) and
    answers the other — a real back-and-forth, not the owner relaying messages.
    (We drive the per-turn engine rather than ``conversation.start_conversation``
    so the offline demo and the tests stay fast and deterministic: no 2–5s
    inter-turn sleeps and no language-specific closure heuristics. The turns it
    produces are identical — ``start_conversation`` calls the same function.)

    Returns the number of turns that actually produced output.
    """
    g.store.set_channel_participants(channel, [a, b])
    print(f"--- {_label(g, a)} ↔ {_label(g, b)}  ({channel}) ---\n")
    spoken = 0
    pair = (a, b)
    for i in range(turns):
        speaker = pair[i % 2]
        listener = pair[(i + 1) % 2]
        ctx = (
            f"You and {_label(g, listener)} are working the goal together — {brief}"
            if i == 0 else
            f"Continue with {_label(g, listener)}: build on what was just said, "
            f"push back where warranted, and move toward something usable."
        )
        lines = g.runtime.generate_agent_to_agent(speaker, listener, channel, context=ctx)
        if lines:
            spoken += 1
            text = "\n".join(lines)
            _emit(on_event, channel, speaker, text, g)
            print(f"{_label(g, speaker)}:\n" + text + "\n")
    return spoken


def form_relationships(g: Glimi, collab_turns: dict[tuple[str, str], int]) -> None:
    """Record the working relationships the run's interactions formed.

    These become the connection-graph edges in the Core dashboard:

    - owner ↔ Coordinator  → ``lead``        (the Coordinator leads for the owner)
    - Coordinator ↔ each specialist → ``manages``
    - specialist ↔ specialist → ``collaborator``, intimacy ∝ how much they talked

    Iterates the LIVE roster (``live_specialists``), not the static SPECIALISTS, so
    a dynamic / mid-run-grown team gets the right manages-edges + display names.

    A real backend also grows these organically through memory extraction over the
    same channels; setting them structurally guarantees the graph is populated on
    *any* backend — the structural truth of who worked with whom.
    """
    owner_id = g.owner.id()
    g.store.set_relationship("coordinator", owner_id, rel_type="lead",
                             intimacy=INTIMACY_LEAD,
                             dynamics="Runs the workspace for the owner; takes the "
                                      "goal and delivers the synthesis.")
    for sid in live_specialists(g):
        g.store.set_relationship("coordinator", sid, rel_type="manages",
                                 intimacy=INTIMACY_MANAGES,
                                 dynamics=f"Delegates an angle to {label_for(g, sid)} "
                                          f"and folds the result into the plan.")
    for (a, b), n in collab_turns.items():
        # intimacy grows with how much the pair actually talked (clamped 40–90).
        intimacy = max(40, min(90, 40 + n * 12))
        g.store.set_relationship(a, b, rel_type="collaborator", intimacy=intimacy,
                                 dynamics=f"{label_for(g, a)} and {label_for(g, b)} worked the "
                                          f"goal together over {n} exchange(s).")


def _emit(on_event, channel: str, speaker_id: str, text: str,
          g: Glimi | None = None, *, is_user: bool = False) -> None:
    """Fire the optional per-turn ``on_event`` callback for live streaming.

    Default ``None`` → silent, so the CLI + create paths behave exactly as before
    and existing tests are unaffected. The driver/WS pass a callback to stream
    each turn to the web as a ``{type:'text', ...}`` frame.
    """
    if on_event is None:
        return
    speaker = _label(g, speaker_id) if g is not None else speaker_id
    try:
        on_event({
            "type": "text", "channel": channel,
            "speaker_id": speaker_id, "speaker": speaker,
            "text": text, "is_user": is_user,
        })
    except Exception:
        pass


# ── team seeding + runtime mutation ─────────────────────────────────────────

def seed_team(g: Glimi, goal: str, owner_name: str = "") -> list[str]:
    """Build the workspace's team on ``g``: the coordinator (manager) + a roster
    of specialists. The manager PROPOSES a goal-appropriate roster (2-4 roles) on
    a real backend; on echo / no-backend / a failed proposal it falls back to the
    DEFAULT researcher/builder/critic — so echo create + the tests are
    deterministic and byte-identical to the historical static TEAM.

    Each specialist is created via ``add_agent`` with its proposed persona + the
    shared READABILITY clause + the Sonnet model override (quality over latency),
    exactly like the static seed used to. The role keyword rides into the store as
    the agent row's ``role_keyword`` extra so the avatar route can pick a sensible
    emoji for a dynamic role. Returns the specialist ids added (the live roster).

    MUST be called with the kernel globals already pointed at ``g`` (it calls
    ``propose_roster`` → ``llm.generate`` on a real backend): in server.create
    that's true because the Glimi was just constructed (last-wins), and the create
    body runs inside the build lock.
    """
    # Coordinator (manager) — always TEAM[0], its id/persona load-bearing.
    cid, cname, ctype, cpersona = TEAM[0]
    g.add_agent(cid, name=cname, persona=cpersona, agent_type=ctype,
                model=WS_AGENT_MODEL)

    roster = propose_roster(g, goal, owner_name)
    added: list[str] = []
    for role_id, display, role_keyword, persona in roster:
        if role_id in RESERVED_IDS or g.store.get_agent(role_id):
            continue  # never shadow the manager/owner or clobber an existing id
        g.add_agent(role_id, name=display, persona=persona + READABILITY,
                    agent_type="persona", model=WS_AGENT_MODEL)
        _stamp_role_keyword(g, role_id, role_keyword)
        added.append(role_id)
    return added


def _stamp_role_keyword(g: Glimi, agent_id: str, role_keyword: str) -> None:
    """Record a role keyword on the agent's store row (best-effort) so the avatar
    route can map a DYNAMIC role to a sensible emoji. ``upsert_agent`` accepts
    ``**extra`` (setdefault), so we re-upsert with the existing fields + the
    keyword; a store without the field just ignores it."""
    if not role_keyword:
        return
    try:
        row = g.store.get_agent(agent_id) or {}
        g.store.upsert_agent(
            agent_id, name=row.get("name") or agent_id,
            agent_type=row.get("type", "persona"),
            model_override=row.get("model_override"),
            role_keyword=role_keyword,
        )
    except Exception:
        pass


def add_team_member(g: Glimi, role_id: str, name: str, persona: str,
                    role_keyword: str = "") -> bool:
    """Add ONE specialist to the live team at runtime, safely.

    The brief's "invalidate_cache + refresh_agent" comes from the Community's
    DB-backed provider; THIS kernel uses ``SimpleProfileProvider`` (no cache) and
    has NO ``runtime.invalidate_cache``. The correct refresh here is:

      1. ``g.add_agent`` → ``profiles.add`` + ``store.upsert_agent`` (one call);
      2. drop any stale ``_active_agents[role_id]`` so the next ``generate_*``
         re-activates it from the freshly-written profile/store;
      3. (defensive) honor the CLAUDE.md phrasing IF the provider ever grows a
         cache — guarded by ``hasattr`` so it's a no-op on this kernel.

    Returns False (no-op) on a reserved id or an id already on the team (so a
    double-add / collision can't clobber the manager or an existing specialist).

    MUST be called with the kernel globals scoped to ``g`` (under the server's
    ``run_in_ws`` for the live path) — every generate_* + add writes the
    process-global store, so an unscoped add would leak across workspaces.
    """
    role_id = (role_id or "").strip().lower()
    if not role_id or role_id in RESERVED_IDS:
        return False
    try:
        if g.store.get_agent(role_id):
            return False
    except Exception:
        return False

    g.add_agent(role_id, name=(name or role_id), persona=(persona or "") + READABILITY,
                agent_type="persona", model=WS_AGENT_MODEL)
    _stamp_role_keyword(g, role_id, role_keyword or role_id)

    rt = getattr(g, "runtime", None)
    if rt is not None:
        try:
            rt._active_agents.pop(role_id, None)  # force lazy re-activation
        except Exception:
            pass
        # Community DB provider exposes invalidate_cache; SimpleProfileProvider
        # does not — guard so this stays correct if the provider is ever swapped.
        if hasattr(rt, "invalidate_cache"):
            try:
                rt.invalidate_cache(role_id)
            except Exception:
                pass
        # refresh_agent only matters for an ALREADY-active id whose prompt changed;
        # for a brand-new id it's a no-op, but call it if the id somehow re-activated.
        if role_id in getattr(rt, "_active_agents", {}):
            try:
                rt.refresh_agent(role_id)
            except Exception:
                pass
    return True


def run_round(
    g: Glimi, instruction: str, owner_name: str, *,
    policy: ApprovalPolicy | None = None,
    interactive: bool | None = None,
    web_queue: WebApprovalQueue | None = None,
    on_event=None,
) -> str:
    """One re-callable work round, keyed off ``instruction`` (the round's directive).

    ASSUMES the round's instruction is ALREADY in ``dm-coordinator`` (the human —
    or, in the autonomous loop, the owner-agent driver — posts it first). The
    round then runs the full interaction topology, starting at "the Coordinator
    reads dm-coordinator and plans":

      1. Coordinator reads ``dm-coordinator`` and lays out the plan.
      2. Coordinator delegates an angle to each specialist (per-specialist DMs).
      3. Specialist ↔ specialist A2A exchanges on the ``internal-*`` channels.
      4. The group round on ``group-team``.
      5. Coordinator delivers the synthesis back in ``dm-coordinator`` — the
         consequential action, gated by the HITL :class:`~approval.ApprovalPolicy`.

    Then records the relationships the round's interactions formed. Returns the
    gated deliverable (the round's result).

    ``instruction`` is the round's directive (the goal on round 1, then each
    owner follow-up). The optional ``on_event`` callback fires after each turn so
    the driver/WS can stream live; default ``None`` keeps the CLI + create path
    silent and existing tests unchanged.
    """
    if policy is None:
        policy = ApprovalPolicy.auto_approve_all()
    if interactive is None:
        interactive = sys.stdin.isatty()
    owner_id = g.owner.id()

    # Derive the LIVE roster ONCE at the top — the specialists actually on THIS
    # team's store (the default 3, a manager-proposed roster, or a roster grown
    # mid-run). Everything below (delegation, A2A pairs, the group round) keys off
    # this, so a freshly added agent joins the next round with no constant to edit.
    specialists = live_specialists(g)
    roster_names = ", ".join(label_for(g, s) for s in specialists)

    # 1) Coordinator reads dm-coordinator (the instruction is already there) and
    #    greets / restates / lays out who it will hand which angle to.
    plan = _gen(
        g, "coordinator",
        f"You are {owner_name}'s Coordinator. Read dm-coordinator: {owner_name} "
        f"just brought this directive: \"{instruction}\".\nGreet {owner_name} by "
        f"name, restate it in one crisp sentence, then lay out the plan: which "
        f"angle you'll hand each of your specialists ({roster_names}). Keep it "
        f"tight.",
        COORDINATOR_DM,
    )
    print(f"{_label(g, 'coordinator')}:\n{plan}\n")
    _emit(on_event, COORDINATOR_DM, "coordinator", plan, g)

    # 2) Coordinator ↔ each specialist (per-specialist DMs): real delegation. The
    #    Coordinator speaks into each specialist's channel; the specialist replies.
    print("--- The Coordinator delegates ---\n")
    for sid in specialists:
        ch = delegation_channel_for(sid)
        angle = angle_for(g, sid)
        # The Coordinator's delegating message, logged to the specialist's channel.
        # Behind-the-scenes (internal-coordinator-<sid>): coordinator + specialist
        # only — the owner watches but doesn't participate.
        g.store.set_channel_participants(ch, ["coordinator", sid])
        delegation = (
            f"{label_for(g, sid)}, on \"{instruction}\": your angle is to {angle}. "
            f"Take it and report back."
        )
        g.store.log_message(ch, "coordinator", delegation)
        _emit(on_event, ch, "coordinator", delegation, g)
        print(f"Coordinator → {label_for(g, sid)} ({ch}):\n"
              f"  your angle is to {angle}.\n")
        # The specialist reads the delegation from the channel and responds.
        reply = _gen(
            g, sid,
            f"Your Coordinator just gave you an angle on \"{instruction}\". "
            f"Read the channel and respond with your first concrete take: "
            f"what you'll dig into and one substantive starting point.",
            ch,
        )
        _emit(on_event, ch, sid, reply, g)
        print(f"{label_for(g, sid)}:\n{reply}\n")

    # 3) Specialist ↔ specialist (A2A): pairs who should collaborate actually do.
    #    Pairs are DERIVED from the live roster (default team → today's two pairs;
    #    a dynamic roster → round-robin adjacent pairs, capped).
    print("--- The specialists collaborate (agent-to-agent) ---\n")
    collab_turns: dict[tuple[str, str], int] = {}
    for a, b, channel, brief in derive_pairs(g, specialists):
        n = a2a_exchange(g, a, b, channel, brief, COLLAB_TURNS, on_event=on_event)
        collab_turns[(a, b)] = n

    # 4) Group round: the whole team converges on one channel.
    print(f"--- The team converges ({GROUP_CHANNEL}) ---\n")
    g.store.set_channel_participants(
        GROUP_CHANNEL, [owner_id, "coordinator", *specialists])
    call = _gen(
        g, "coordinator",
        f"Open the group room for the team on \"{instruction}\". In one or two "
        f"lines, call the team together and ask each specialist to drop their "
        f"single most important point.",
        GROUP_CHANNEL,
    )
    _emit(on_event, GROUP_CHANNEL, "coordinator", call, g)
    print(f"Coordinator ({GROUP_CHANNEL}):\n  (called the team together)\n")
    for sid in specialists:
        reply = _gen(
            g, sid,
            f"You're in the group room with the whole team on \"{instruction}\". "
            f"Read the room and drop your single most important point for the group.",
            GROUP_CHANNEL,
        )
        _emit(on_event, GROUP_CHANNEL, sid, reply, g)
        print(f"{label_for(g, sid)}:\n{reply}\n")

    # 5) Coordinator delivers the synthesis — back in the owner DM. THIS is the
    #    consequential action: gated by the HITL approval policy, so the owner
    #    stays in the loop (approve / edit / reject) before it is committed.
    print("--- The Coordinator delivers ---\n")
    final = gated_deliver(
        g, policy,
        prompt=(
            f"As {owner_name}'s Coordinator, you've heard the whole team across the "
            f"workspace. Now write the actual DELIVERABLE for {owner_name} on "
            f"\"{instruction}\" — NOT a one-line takeaway, but the complete work "
            f"product they can act on directly. Synthesize the team's real findings "
            f"into clear sections: the decision/direction, the concrete plan or next "
            f"steps (specific, ordered), and the top risk — pulling in the actual "
            f"specifics raised in the discussion (names, numbers, trade-offs). Make "
            f"it substantial: a tight structured brief (several short sections or a "
            f"detailed list), not a summary sentence."
        ),
        channel=COORDINATOR_DM,
        kind="final_deliverable",
        summary=f"deliverable for {owner_name} — {instruction}",
        interactive=interactive,
        web_queue=web_queue,
    )
    _emit(on_event, COORDINATOR_DM, "coordinator", final, g)

    # Record the relationships this round's interactions formed → graph edges.
    form_relationships(g, collab_turns)
    return final


def run_workspace(
    g: Glimi, owner_name: str, goal: str, *,
    policy: ApprovalPolicy | None = None,
    interactive: bool | None = None,
    web_queue: WebApprovalQueue | None = None,
    on_event=None,
) -> str:
    """Drive the full interaction topology ONCE on one shared store; return the
    final deliverable. Records relationships as the interactions form them.

    This is the one-time orchestration the create/CLI paths use: it posts the
    owner's goal to ``dm-coordinator`` (the owner's opening turn) then runs a
    single :func:`run_round` keyed off that goal. The autonomous multi-round loop
    lives in ``workspace/driver.py``, which posts each follow-up itself and calls
    :func:`run_round` per round.

    The Coordinator's FINALIZATION is gated by the HITL
    :class:`~approval.ApprovalPolicy` (approve / edit / reject + fallback).
    Defaults keep existing callers behaviorally unchanged: ``policy=None`` →
    auto-approve-all, ``interactive=None`` → ``sys.stdin.isatty()``, so a
    non-interactive run never blocks and the deliverable is still produced.
    """
    owner_id = g.owner.id()
    print("--- The workspace opens ---\n")

    # Owner ↔ Coordinator (DM): the owner gives the goal. We log it as the owner's
    # own message into dm-coordinator (same as a human typing), then run_round
    # starts at "the Coordinator reads dm-coordinator and plans".
    g.store.set_channel_participants(COORDINATOR_DM, [owner_id, "coordinator"])
    g.store.log_message(COORDINATOR_DM, owner_id, goal)
    _emit(on_event, COORDINATOR_DM, owner_id, goal, g, is_user=True)

    return run_round(
        g, goal, owner_name,
        policy=policy, interactive=interactive, web_queue=web_queue,
        on_event=on_event,
    )


def summary(g: Glimi, owner_name: str, goal: str, final: str) -> None:
    """A clean closing summary: the interaction web + the deliverable."""
    print("--- Summary ---")
    print(f"  goal         : {goal}")

    # Channels touched — the shape of the interaction web.
    chans = g.store.get_channel_overview()
    if chans:
        print("  channels     : the team worked across "
              f"{len(chans)} channels (a real interaction web):")
        for c in sorted(chans, key=lambda c: c["channel"]):
            print(f"                 - {c['channel']} "
                  f"({c.get('msg_count', 0)} msgs)")

    # Relationships formed — exactly the dashboard's connection-graph edges.
    rels = _relationship_lines(g)
    if rels:
        print("  relationships: the run formed these working ties "
              "(these are the graph edges):")
        for line in rels:
            print(f"                 - {line}")

    print(f"\n  Deliverable for {owner_name}:")
    print("  " + "-" * 60)
    for line in (final or "").splitlines() or ["(no output)"]:
        print(f"  {line}")
    print("  " + "-" * 60 + "\n")


def _relationship_lines(g: Glimi) -> list[str]:
    """Human-readable lines for every relationship edge in the store (the same
    edges the dashboard graph draws), via the store-driven DashboardReader."""
    try:
        from glimi.dashboard import DashboardReader
    except Exception:
        return []
    snap = DashboardReader(g.store).snapshot()
    lines = []
    for e in snap.get("relationships", []):
        s, t = _label(g, e["source"]), _label(g, e["target"])
        lines.append(f"{s} ↔ {t}  [{e.get('type') or '?'}, "
                     f"intimacy {e.get('intimacy', 0)}]")
    return lines


def serve_dashboard(g: Glimi, host: str = DASHBOARD_HOST,
                    port: int = DASHBOARD_PORT) -> int:
    """Serve the finished workspace in the Core dashboard (blocking).

    This is the payoff: the *same* store-driven dashboard that serves Community
    now renders YOUR work team — the connection graph (owner + Coordinator hubs +
    specialists + collaboration edges) plus each member's 5-layer memory. Needs
    the optional web deps (``pip install glimi[dashboard]``).
    """
    import glimi.dashboard

    url = f"http://{host}:{port}"
    print(f"--- Serving the workspace in the Core dashboard at {url} ---")
    print("    (the same dashboard that serves Community — Ctrl-C to stop)\n")
    try:
        glimi.dashboard.serve(g.store, host=host, port=port)
    except ImportError as exc:
        print(f"Dashboard deps not installed: {exc}", file=sys.stderr)
        print("Install with:  pip install glimi[dashboard]", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nDashboard stopped.")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="glimi-workspace",
        description="A specialist team that genuinely interacts, built on Glimi Core.",
    )
    ap.add_argument("--name", help="Owner name (else env GLIMI_WORKSPACE_NAME / prompt / default).")
    ap.add_argument("--goal", help=f"Work goal (else env / prompt / default: {DEFAULT_GOAL!r}).")
    ap.add_argument(
        "--backend",
        default=os.environ.get("GLIMI_LLM_BACKEND", "echo"),
        help="LLM backend: echo (offline default), claude_cli, ollama, ...",
    )
    ap.add_argument(
        "--serve", action="store_true",
        help="After the work, serve the team in the Core dashboard (default OFF).",
    )
    ap.add_argument(
        "--demo", action="store_true",
        help="Serve a seeded, real-time-viewable LIVE demo (a hand-authored launch "
             "team that keeps updating) in the Core dashboard. Offline, no API key.",
    )
    ap.add_argument(
        "--server", action="store_true",
        help="Run the multi-workspace SERVER: a home page listing workspaces (a "
             "read-only Demo + any you create) and a per-workspace Core dashboard. "
             "Create new workspaces from a name + goal. Offline default, no API key.",
    )
    ap.add_argument(
        "--host", default=DASHBOARD_HOST,
        help=f"Dashboard bind host for --serve/--demo (default {DASHBOARD_HOST}; "
             f"use 0.0.0.0 to expose).",
    )
    ap.add_argument(
        "--port", type=int, default=DASHBOARD_PORT,
        help=f"Dashboard port for --serve/--demo (default {DASHBOARD_PORT}).",
    )
    ap.add_argument(
        "--approve", choices=["auto", "final", "off"], default="auto",
        help="HITL approval mode: 'auto' (default — auto-approve all, never "
             "blocks; for CI/echo/demos), 'final' (require owner approval for the "
             "final deliverable: approve/edit/reject), 'off' (alias for auto).",
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    backend = args.backend

    # Glimi Workspace is English-default; tell the kernel's A2A scaffolding so
    # agent-to-agent turns come back in English (Community stays ko by default).
    os.environ.setdefault("GLIMI_LANG", "en")

    # --server: the multi-workspace host — a home page + per-workspace dashboards
    # (a read-only Demo always present + workspaces you create). Self-contained;
    # bypasses first-run setup + the single-team work run.
    if args.server:
        try:
            from server import serve as serve_server
        except ImportError:
            from .server import serve as serve_server
        return serve_server(host=args.host, port=args.port)

    # --demo: a seeded, real-time-viewable showcase (its own population + live
    # activity loop). Self-contained — bypasses first-run setup + the work run.
    if args.demo:
        try:
            from demo import run_demo
        except ImportError:
            from .demo import run_demo
        return run_demo(host=args.host, port=args.port, backend=backend)

    setup = resolve_setup(name_flag=args.name, goal_flag=args.goal)
    banner(backend, setup.owner_name, setup.goal, args.approve)

    # One Glimi instance == one shared store for the whole team. The manager
    # proposes a goal-appropriate roster on a real backend; echo → the default
    # researcher/builder/critic (deterministic). seed_team adds coordinator + the
    # roster (each on Sonnet, persona+READABILITY, an emoji-keyword + memory).
    g = Glimi(backend=backend, owner_name=setup.owner_name)
    seed_team(g, setup.goal, setup.owner_name)

    # HITL approval gate. The owner can interactively approve/edit/reject the
    # consequential finalization only on a real TTY; non-TTY (CI, pipes, echo
    # demo) auto-approves so the run never hangs — same isatty discipline as setup.
    interactive = sys.stdin.isatty()
    policy = build_policy(args.approve)
    web_queue = None
    if args.serve:
        # --serve dashboard is read-only + post-run → no live mid-run input
        # channel. Force auto-approve and record the seam via the queue stub.
        policy = ApprovalPolicy.auto_approve_all()
        web_queue = WebApprovalQueue(on_log=_trail_sink(g))

    final = run_workspace(g, setup.owner_name, setup.goal,
                          policy=policy, interactive=interactive,
                          web_queue=web_queue)
    summary(g, setup.owner_name, setup.goal, final)

    if args.serve:
        return serve_dashboard(g, host=args.host, port=args.port)

    print("Done — Coordinator + three specialists, one shared store, a real "
          "interaction web, kernel-only.")
    return 0


if __name__ == "__main__":
    # Allow `python workspace/run.py` to import the sibling `team` module
    # without packaging gymnastics: ensure this dir is on sys.path.
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    sys.exit(main())
