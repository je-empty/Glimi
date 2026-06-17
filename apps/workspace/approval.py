"""Human-in-the-loop (HITL) approval gate for Glimi Workspace.

A real team can let routine work flow autonomously, but a **consequential**
action — the Coordinator finalizing the deliverable, an agent firing a
side-effecting tool — is exactly where a human should stay in the loop. This
module is the seam that decides, for a proposed action, whether the owner must
approve it (REQUIRE_APPROVAL) or it may proceed on its own (AUTO), and runs the
approve / edit / reject interaction when approval is required.

Design goals (matching the Applied-AI JD: *judge what an agent can own vs where a
human must intervene*, plus a graceful **fallback**):

- :class:`ApprovalPolicy` — the judgment. Three ways to configure it, covering the
  spectrum from fully autonomous to fully supervised:
    * :meth:`ApprovalPolicy.auto_approve_all` — AUTO for everything (the CI /
      headless / demo default, so a non-interactive run never blocks);
    * :meth:`ApprovalPolicy.require_for` — REQUIRE_APPROVAL for a *class* of
      actions (e.g. ``{"final_deliverable"}`` or side-effecting tool calls), AUTO
      for the rest;
    * ``ApprovalPolicy(callback=fn)`` — a per-action predicate ``fn(action)->bool``.
- :func:`run_gate` — the interaction. AUTO → auto-approve; non-interactive →
  auto-approve (the SAME ``sys.stdin.isatty`` discipline as setup, so it never
  hangs in CI); otherwise prompt the owner approve / edit / reject. On **reject**
  it runs a graceful :func:`safe_default_fallback` so the run still produces a
  (clearly-labeled, withheld) deliverable rather than crashing.
- :class:`WebApprovalQueue` — a documented STUB seam for the ``--serve`` path
  (read-only dashboard has no live mid-run input channel). It enqueues a pending
  approval into the store-log so the HITL seam is *visible* in the dashboard, and
  auto-approves for now. NO web UI is built here.

This module imports nothing from ``glimi`` / ``src`` / ``discord`` on purpose: it
is pure policy + I/O over plain values, so it is trivially testable and the kernel
boundary stays obvious (the kernel-only guard test stays green). The observability
trail is written via injected callables, so the caller wires the kernel sinks
(``g.observer.system`` + ``g.store.log_message``) without this module importing
them.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

# ── verdicts + decisions ─────────────────────────────────────────────────────

# What the POLICY decides for a proposed action (does a human need to look?).
REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
AUTO = "AUTO"

# What actually HAPPENED at the gate (the recorded HITL outcome).
AUTO_APPROVED = "AUTO_APPROVED"  # policy said AUTO, or non-interactive fallback
APPROVED = "APPROVED"            # owner approved the proposal as-is
EDITED = "EDITED"               # owner supplied a replacement deliverable
REJECTED = "REJECTED"           # owner rejected → fallback ran

# Channel the HITL trail is written to (an mgr-system-log-style channel, per
# CLAUDE.md: system/tool logs live in an mgr-* channel, never a conversation one).
APPROVALS_CHANNEL = "mgr-approvals"


@dataclass
class ApprovalAction:
    """A consequential action proposed by an agent, awaiting a gate decision.

    ``kind`` classifies the action (e.g. ``"final_deliverable"``,
    ``"tool_call"``); the policy decides by ``kind``, so adding more gate points
    later is configuration, not new plumbing. ``proposed_text`` is the candidate
    the agent produced; ``summary`` is a short human-readable description (the
    goal, the tool name…) shown at the prompt and logged to the trail.
    """

    kind: str
    summary: str
    proposed_text: str
    channel: str
    metadata: dict = field(default_factory=dict)


@dataclass
class ApprovalOutcome:
    """The result of running the gate on an :class:`ApprovalAction`."""

    action: ApprovalAction
    decision: str          # one of AUTO_APPROVED | APPROVED | EDITED | REJECTED
    final_text: str        # the text to actually use (approved/edited/fallback)
    note: str = ""         # short human-readable note for the trail


# ── the policy: REQUIRE_APPROVAL vs AUTO ─────────────────────────────────────


class ApprovalPolicy:
    """Decides, per :class:`ApprovalAction`, REQUIRE_APPROVAL vs AUTO.

    Construct it one of three ways:

    - :meth:`auto_approve_all` — AUTO for every action (default for CI / headless
      / the offline echo demo, so a non-interactive run finishes without blocking).
    - :meth:`require_for` — REQUIRE_APPROVAL for a set of ``kind``s, AUTO otherwise.
    - ``ApprovalPolicy(callback=fn)`` — call ``fn(action) -> bool``; ``True`` means
      require approval. A callback wins over ``require_kinds`` if both are given.
    """

    def __init__(
        self,
        *,
        require_kinds: Optional[set[str]] = None,
        callback: Optional[Callable[[ApprovalAction], bool]] = None,
    ) -> None:
        self.require_kinds = set(require_kinds or ())
        self.callback = callback

    # ── named constructors (the three JD-required configurations) ──
    @classmethod
    def auto_approve_all(cls) -> "ApprovalPolicy":
        """Never require approval — the CLI / headless / demo default."""
        return cls()

    @classmethod
    def require_for(cls, kinds: set[str]) -> "ApprovalPolicy":
        """Require approval for actions whose ``kind`` is in ``kinds``."""
        return cls(require_kinds=set(kinds))

    def decide(self, action: ApprovalAction) -> str:
        """Return :data:`REQUIRE_APPROVAL` or :data:`AUTO` for ``action``."""
        if self.callback is not None:
            return REQUIRE_APPROVAL if self.callback(action) else AUTO
        if action.kind in self.require_kinds:
            return REQUIRE_APPROVAL
        return AUTO


# ── fallbacks (what happens on REJECT) ───────────────────────────────────────


def safe_default_fallback(action: ApprovalAction) -> str:
    """Deterministic safe default on reject: a short, clearly-labeled placeholder.

    Keeps the run intact (the caller still gets a non-empty deliverable string, so
    the summary + relationship recording stay valid) while making it unmistakable
    that the synthesis was withheld at the owner's instruction.
    """
    return (
        f"[Deliverable withheld — owner rejected the {action.kind}. "
        f"Re-run or revise. Goal: {action.summary}]"
    )


# ``fallback(action) -> str``. Default = the deterministic safe default above.
# A REVISE-style fallback (ask the agent to revise once with the reject reason)
# can be supplied by the caller; kept out of the default so CI stays deterministic.
FallbackFn = Callable[[ApprovalAction], str]


# ── the trail (observable HITL log) ──────────────────────────────────────────


def log_trail(on_log: Optional[Callable[[str], None]], message: str) -> None:
    """Write one line to the HITL trail via the injected sink (no-op if None)."""
    if on_log is not None:
        on_log(message)


# ── the gate: approve / edit / reject ────────────────────────────────────────


def run_gate(
    action: ApprovalAction,
    policy: ApprovalPolicy,
    *,
    interactive: Optional[bool] = None,
    prompt_fn: Optional[Callable[[str], str]] = None,
    fallback: FallbackFn = safe_default_fallback,
    on_log: Optional[Callable[[str], None]] = None,
) -> ApprovalOutcome:
    """Run the HITL gate on ``action`` and return the :class:`ApprovalOutcome`.

    Flow:

    1. ``policy.decide(action)`` == AUTO → :data:`AUTO_APPROVED` with the proposed
       text (no prompt).
    2. Not interactive (defaults to ``sys.stdin.isatty()``) → :data:`AUTO_APPROVED`
       too — the same discipline as setup, so a non-TTY run NEVER hangs on input.
    3. Otherwise prompt the owner: **a**pprove / **e**dit / **r**eject.
         - approve → :data:`APPROVED`, proposed text.
         - edit    → :data:`EDITED`, the owner's replacement (multi-line until a
                     blank line; an empty edit falls back to the proposal).
         - reject  → :data:`REJECTED`, ``fallback(action)``.

    The trail is written via ``on_log`` (PROPOSED → DECISION → OUTCOME), so the
    decision is inspectable. ``prompt_fn`` is injectable so tests drive the gate
    without a TTY.
    """
    if interactive is None:
        interactive = sys.stdin.isatty()
    # Resolve ``input`` at CALL time (not as a def-time default) so tests that
    # monkeypatch ``builtins.input`` are honored.
    if prompt_fn is None:
        prompt_fn = input

    log_trail(on_log, f"PROPOSED [{action.kind}] {action.summary}")

    verdict = policy.decide(action)
    if verdict == AUTO or not interactive:
        note = "policy:AUTO" if verdict == AUTO else "non-interactive→auto"
        log_trail(on_log, f"DECISION [{action.kind}] {AUTO_APPROVED} ({note})")
        outcome = ApprovalOutcome(action, AUTO_APPROVED, action.proposed_text, note)
        log_trail(on_log, f"OUTCOME  [{action.kind}] using proposed deliverable")
        return outcome

    # Interactive + REQUIRE_APPROVAL → ask the owner.
    return _prompt_owner(action, prompt_fn, fallback, on_log)


def _prompt_owner(
    action: ApprovalAction,
    prompt_fn: Callable[[str], str],
    fallback: FallbackFn,
    on_log: Optional[Callable[[str], None]],
) -> ApprovalOutcome:
    """The interactive approve / edit / reject conversation (already gated)."""
    preview = _first_lines(action.proposed_text, 8)
    banner = (
        "\n" + "=" * 64 + "\n"
        f"  HITL APPROVAL REQUIRED — {action.kind}\n"
        f"  {action.summary}\n" + "-" * 64 + "\n"
        f"{preview}\n" + "=" * 64
    )
    print(banner)

    while True:
        try:
            choice = prompt_fn(
                "Approve this deliverable?  [a]pprove / [e]dit / [r]eject: "
            ).strip().lower()
        except EOFError:
            # Lost the TTY mid-prompt → fail safe to approve (never hang/crash).
            choice = "a"

        if choice in ("a", "approve", "y", "yes", ""):
            log_trail(on_log, f"DECISION [{action.kind}] {APPROVED} (owner approved)")
            outcome = ApprovalOutcome(action, APPROVED, action.proposed_text,
                                      "owner approved")
            log_trail(on_log, f"OUTCOME  [{action.kind}] delivered as proposed")
            return outcome

        if choice in ("e", "edit"):
            edited = _read_multiline(prompt_fn)
            if not edited.strip():
                # Empty edit → treat as approve-as-is (nothing to replace with).
                log_trail(on_log,
                          f"DECISION [{action.kind}] {APPROVED} (empty edit→approve)")
                outcome = ApprovalOutcome(action, APPROVED, action.proposed_text,
                                          "empty edit, approved as proposed")
                log_trail(on_log, f"OUTCOME  [{action.kind}] delivered as proposed")
                return outcome
            log_trail(on_log, f"DECISION [{action.kind}] {EDITED} (owner edited)")
            outcome = ApprovalOutcome(action, EDITED, edited, "owner edited")
            log_trail(on_log, f"OUTCOME  [{action.kind}] delivered owner's edit")
            return outcome

        if choice in ("r", "reject", "n", "no"):
            replacement = fallback(action)
            log_trail(on_log, f"DECISION [{action.kind}] {REJECTED} (owner rejected)")
            outcome = ApprovalOutcome(action, REJECTED, replacement,
                                      "owner rejected → fallback")
            log_trail(on_log, f"OUTCOME  [{action.kind}] fallback engaged")
            return outcome

        print("  Please answer 'a' (approve), 'e' (edit), or 'r' (reject).")


def _read_multiline(prompt_fn: Callable[[str], str]) -> str:
    """Read a replacement deliverable: lines until a blank line (or EOF)."""
    print("  Enter the replacement deliverable; end with an empty line:")
    lines: list[str] = []
    while True:
        try:
            line = prompt_fn("  > ")
        except EOFError:
            break
        if line == "":
            break
        lines.append(line)
    return "\n".join(lines)


def _first_lines(text: str, n: int) -> str:
    """First ``n`` lines of ``text`` for the prompt preview (elided if longer)."""
    lines = (text or "").splitlines()
    head = lines[:n]
    if len(lines) > n:
        head.append(f"  … ({len(lines) - n} more line(s))")
    return "\n".join(head)


def first_line_elision(text: str, limit: int = 120) -> str:
    """One-line elision of ``text`` for the store trail (the deliverable preview)."""
    first = (text or "").strip().splitlines()
    if not first:
        return "(empty)"
    line = first[0]
    if len(line) > limit:
        line = line[:limit] + "…"
    if len(first) > 1:
        line += f" (+{len(first) - 1} more line(s))"
    return line


# ── --serve stub: a documented approval-queue seam (NO web UI) ───────────────


class WebApprovalQueue:
    """STUB seam for the ``--serve`` / headless path. Auto-approves for now.

    The dashboard (``glimi.dashboard.serve``) is read-only and runs *after* the
    team finishes, so there is no live mid-run input channel to prompt the owner
    over. Rather than half-build a web approval UI, ``--serve`` defaults the policy
    to AUTO and instantiates this queue, which records each gated action as a
    ``PendingApproval`` line into the store-log (the same ``mgr-approvals`` channel
    the CLI trail uses) so the HITL seam is *visible and inspectable in the
    dashboard*. Approval is auto for now.

    TODO(serve): drain this queue from a dashboard approve/reject endpoint —
        e.g. ``POST /api/approvals/{id}/{approve|reject}`` in
        ``glimi/dashboard/app.py`` — so a human can clear pending approvals from
        the running dashboard. That endpoint would flip the recorded decision and
        resume the held action. Until then this is a no-op auto-approve.
    """

    def __init__(self, on_log: Optional[Callable[[str], None]] = None) -> None:
        self.on_log = on_log
        self.pending: list[ApprovalAction] = []

    def enqueue(self, action: ApprovalAction) -> ApprovalOutcome:
        """Record a PendingApproval to the trail and AUTO-approve (stub)."""
        self.pending.append(action)
        log_trail(
            self.on_log,
            f"PENDING  [{action.kind}] {action.summary} "
            f"(queued for dashboard approve/reject — auto-approved for now)",
        )
        return ApprovalOutcome(action, AUTO_APPROVED, action.proposed_text,
                               "web-queue stub: auto-approved")
