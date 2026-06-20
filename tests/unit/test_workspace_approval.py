"""Glimi Workspace HITL approval-gate unit tests (workspace/approval.py).

Verifies the human-in-the-loop seam end to end on the offline ``echo`` backend:

  - **ApprovalPolicy.decide**: auto_approve_all → AUTO for any kind; require_for
    → REQUIRE_APPROVAL for the named kinds, AUTO for the rest; a per-action
    callback policy is honored.
  - **run_gate routing** with an injected ``prompt_fn``: approve → APPROVED +
    proposed text; edit → EDITED + the owner's replacement; reject → REJECTED +
    the fallback text.
  - **auto path never prompts**: policy=auto → AUTO_APPROVED and prompt_fn is
    NEVER called (mirrors test_setup_non_interactive_never_prompts).
  - **non-interactive safety**: interactive=False with a require-approval policy →
    AUTO_APPROVED, input() never touched (no hang in CI).
  - **fallback on reject** keeps run_workspace returning a non-empty ``final`` and
    writes the HITL trail to the ``mgr-approvals`` store channel.
  - **observable trail**: after a gated echo run, the mgr-approvals channel is
    non-empty and carries proposed + decision lines.

Run:
    PYTHONPATH=<worktree> python -m pytest tests/unit/test_workspace_approval.py -q
"""
from __future__ import annotations

import os
import sys

import pytest

# Worktree root + workspace on sys.path so the flat app modules (run / team /
# approval) import the same way the script does. Mirrors test_glimi_workspace.py.
_WORKTREE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_APP_DIR = os.path.join(_WORKTREE, "workspace")
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)
if _WORKTREE not in sys.path:
    sys.path.insert(0, _WORKTREE)


@pytest.fixture(autouse=True)
def _restore_kernel_globals():
    """Restore the kernel DI globals around each test (Glimi() mutates them)."""
    from glimi import memory as _memory
    from glimi import runtime as _runtime
    saved = {
        "r_store": _runtime._store, "r_profiles": _runtime._profiles,
        "r_owner": _runtime._owner, "r_observer": _runtime._observer,
        "m_store": _memory._store, "m_profiles": _memory._profiles,
        "m_owner": _memory._owner, "m_observer": _memory._observer,
        "env": os.environ.get("GLIMI_LLM_BACKEND"),
    }
    yield
    _runtime.set_store(saved["r_store"]); _runtime.set_profiles(saved["r_profiles"])
    _runtime.set_owner(saved["r_owner"]); _runtime.set_observer(saved["r_observer"])
    _memory.set_store(saved["m_store"]); _memory.set_profiles(saved["m_profiles"])
    _memory.set_owner(saved["m_owner"]); _memory.set_observer(saved["m_observer"])
    if saved["env"] is None:
        os.environ.pop("GLIMI_LLM_BACKEND", None)
    else:
        os.environ["GLIMI_LLM_BACKEND"] = saved["env"]


def _action(kind="final_deliverable", text="PROPOSED DELIVERABLE"):
    import approval
    return approval.ApprovalAction(
        kind=kind, summary="goal: ship it", proposed_text=text,
        channel="dm-coordinator", metadata={},
    )


# ────────────────────────────────────────────────────
# ApprovalPolicy.decide — the three configurations
# ────────────────────────────────────────────────────

def test_policy_auto_approve_all():
    import approval
    p = approval.ApprovalPolicy.auto_approve_all()
    assert p.decide(_action("final_deliverable")) == approval.AUTO
    assert p.decide(_action("tool_call")) == approval.AUTO


def test_policy_require_for_class():
    import approval
    p = approval.ApprovalPolicy.require_for({"final_deliverable"})
    assert p.decide(_action("final_deliverable")) == approval.REQUIRE_APPROVAL
    # any other kind is still AUTO
    assert p.decide(_action("tool_call")) == approval.AUTO


def test_policy_callback_honored():
    import approval
    seen = []

    def cb(action):
        seen.append(action.kind)
        return action.kind == "tool_call"  # require approval only for tool calls

    p = approval.ApprovalPolicy(callback=cb)
    assert p.decide(_action("tool_call")) == approval.REQUIRE_APPROVAL
    assert p.decide(_action("final_deliverable")) == approval.AUTO
    assert seen == ["tool_call", "final_deliverable"]


# ────────────────────────────────────────────────────
# run_gate routing — approve / edit / reject
# ────────────────────────────────────────────────────

def test_gate_approve_returns_proposed():
    import approval
    p = approval.ApprovalPolicy.require_for({"final_deliverable"})
    out = approval.run_gate(_action(text="ORIGINAL"), p, interactive=True,
                            prompt_fn=lambda _msg: "a")
    assert out.decision == approval.APPROVED
    assert out.final_text == "ORIGINAL"


def test_gate_edit_returns_edited():
    import approval
    p = approval.ApprovalPolicy.require_for({"final_deliverable"})
    # First prompt: choose 'e'. Then multi-line edit: one line, then blank to end.
    answers = iter(["e", "REVISED DELIVERABLE", ""])
    out = approval.run_gate(_action(text="ORIGINAL"), p, interactive=True,
                            prompt_fn=lambda _msg: next(answers))
    assert out.decision == approval.EDITED
    assert out.final_text == "REVISED DELIVERABLE"


def test_gate_reject_runs_fallback():
    import approval
    p = approval.ApprovalPolicy.require_for({"final_deliverable"})
    out = approval.run_gate(_action(text="ORIGINAL"), p, interactive=True,
                            prompt_fn=lambda _msg: "r")
    assert out.decision == approval.REJECTED
    # default safe-default fallback → non-empty, clearly labeled, != proposal
    assert out.final_text
    assert "withheld" in out.final_text.lower()
    assert out.final_text != "ORIGINAL"


def test_gate_reject_custom_fallback():
    import approval
    p = approval.ApprovalPolicy.require_for({"final_deliverable"})
    out = approval.run_gate(
        _action(text="ORIGINAL"), p, interactive=True,
        prompt_fn=lambda _msg: "r",
        fallback=lambda action: f"REVISED-AFTER-REJECT for {action.kind}",
    )
    assert out.decision == approval.REJECTED
    assert out.final_text == "REVISED-AFTER-REJECT for final_deliverable"


# ────────────────────────────────────────────────────
# auto path + non-interactive safety — NEVER prompts
# ────────────────────────────────────────────────────

def test_gate_auto_never_prompts():
    """policy=auto → AUTO_APPROVED, prompt_fn must NEVER be called."""
    import approval

    def _boom(_msg):  # prompt_fn must never run on the AUTO path
        raise AssertionError("run_gate prompted on the AUTO path")

    p = approval.ApprovalPolicy.auto_approve_all()
    out = approval.run_gate(_action(text="ORIGINAL"), p, interactive=True,
                            prompt_fn=_boom)
    assert out.decision == approval.AUTO_APPROVED
    assert out.final_text == "ORIGINAL"


def test_gate_non_interactive_never_prompts():
    """require-approval policy but non-interactive → AUTO_APPROVED, no input()."""
    import approval

    def _boom(_msg):
        raise AssertionError("run_gate prompted in non-interactive mode (would hang)")

    p = approval.ApprovalPolicy.require_for({"final_deliverable"})
    out = approval.run_gate(_action(text="ORIGINAL"), p, interactive=False,
                            prompt_fn=_boom)
    assert out.decision == approval.AUTO_APPROVED
    assert out.final_text == "ORIGINAL"


def test_gate_writes_trail_via_on_log():
    """The proposed→decision→outcome trail is emitted through the on_log sink."""
    import approval
    lines = []
    p = approval.ApprovalPolicy.require_for({"final_deliverable"})
    approval.run_gate(_action(text="ORIGINAL"), p, interactive=True,
                      prompt_fn=lambda _msg: "a", on_log=lines.append)
    assert any(l.startswith("PROPOSED") for l in lines)
    assert any("DECISION" in l and approval.APPROVED in l for l in lines)
    assert any(l.startswith("OUTCOME") for l in lines)


# ────────────────────────────────────────────────────
# end-to-end run_workspace — gate integrated on the echo backend
# ────────────────────────────────────────────────────

def test_run_workspace_auto_policy_unchanged(capsys):
    """No explicit policy (existing callers) → auto-approve, final is non-empty."""
    import run
    from glimi import Glimi

    g = Glimi(backend="echo", owner_name="Owner")
    for aid, name, agent_type, persona in run.TEAM:
        g.add_agent(aid, name=name, persona=persona, agent_type=agent_type)
    # default policy/interactive: backward-compatible auto-approve, never hangs
    final = run.run_workspace(g, "Owner", "Plan our launch")
    assert final
    assert "withheld" not in final.lower()  # auto-approved → real deliverable


def test_run_workspace_reject_keeps_final_and_logs_trail():
    """A require-approval policy + an injected reject prompt → run still returns a
    non-empty (safe-default) deliverable, and the mgr-approvals trail is logged."""
    import approval
    import run
    from glimi import Glimi

    g = Glimi(backend="echo", owner_name="Owner")
    for aid, name, agent_type, persona in run.TEAM:
        g.add_agent(aid, name=name, persona=persona, agent_type=agent_type)

    # Drive the gate to REJECT by monkeypatching run_gate's prompt_fn via a policy
    # that requires approval + an interactive=True run with a rejecting prompt.
    # gated_deliver uses approval.run_gate(...) with prompt_fn=input by default, so
    # we patch builtins.input to reject.
    import builtins
    orig_input = builtins.input
    builtins.input = lambda _msg="": "r"
    try:
        final = run.run_workspace(
            g, "Owner", "Plan our launch",
            policy=approval.ApprovalPolicy.require_for({"final_deliverable"}),
            interactive=True,
        )
    finally:
        builtins.input = orig_input

    # run still returns a non-empty deliverable (the safe-default fallback)
    assert final
    assert "withheld" in final.lower()

    # the HITL trail is inspectable in the mgr-approvals store channel
    trail = g.store.get_recent_messages(approval.APPROVALS_CHANNEL, limit=99)
    assert trail, "mgr-approvals channel must carry the HITL trail"
    blob = "\n".join(m["message"] for m in trail)
    assert "PROPOSED" in blob
    assert "DECISION" in blob and approval.REJECTED in blob
    assert "OUTCOME" in blob


def test_run_workspace_edit_replaces_deliverable():
    """approve-with-edit → the run returns the owner's edited deliverable."""
    import approval
    import run
    from glimi import Glimi

    g = Glimi(backend="echo", owner_name="Owner")
    for aid, name, agent_type, persona in run.TEAM:
        g.add_agent(aid, name=name, persona=persona, agent_type=agent_type)

    import builtins
    orig_input = builtins.input
    answers = iter(["e", "OWNER-EDITED FINAL", ""])
    builtins.input = lambda _msg="": next(answers)
    try:
        final = run.run_workspace(
            g, "Owner", "Plan our launch",
            policy=approval.ApprovalPolicy.require_for({"final_deliverable"}),
            interactive=True,
        )
    finally:
        builtins.input = orig_input

    assert final == "OWNER-EDITED FINAL"


def test_run_workspace_non_interactive_never_hangs():
    """require-approval policy but interactive=False → auto-approve, input() never
    called (proves a non-TTY CI run with a strict policy still completes)."""
    import approval
    import run
    from glimi import Glimi

    g = Glimi(backend="echo", owner_name="Owner")
    for aid, name, agent_type, persona in run.TEAM:
        g.add_agent(aid, name=name, persona=persona, agent_type=agent_type)

    import builtins
    orig_input = builtins.input

    def _boom(_msg=""):
        raise AssertionError("run_workspace prompted in non-interactive mode")

    builtins.input = _boom
    try:
        final = run.run_workspace(
            g, "Owner", "Plan our launch",
            policy=approval.ApprovalPolicy.require_for({"final_deliverable"}),
            interactive=False,
        )
    finally:
        builtins.input = orig_input

    assert final
    assert "withheld" not in final.lower()  # auto-approved, not rejected


def test_web_queue_stub_records_and_auto_approves():
    """The --serve WebApprovalQueue stub records a PendingApproval + auto-approves."""
    import approval

    lines = []
    q = approval.WebApprovalQueue(on_log=lines.append)
    out = q.enqueue(_action(text="ORIGINAL"))
    assert out.decision == approval.AUTO_APPROVED
    assert out.final_text == "ORIGINAL"
    assert q.pending and q.pending[0].kind == "final_deliverable"
    assert any(l.startswith("PENDING") for l in lines)


# ────────────────────────────────────────────────────
# kernel-only — approval.py imports nothing from discord/src/glimi
# ────────────────────────────────────────────────────

def test_approval_is_kernel_neutral():
    """approval.py must import nothing from discord, the Community app (src), or
    even glimi — it is pure policy + I/O over plain values (keeps the boundary
    obvious and the kernel-only guard meaningful)."""
    import re
    path = os.path.join(_APP_DIR, "approval.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    forbidden = re.compile(
        r"^\s*(import\s+(discord|glimi)|from\s+(src|glimi|discord)\b)", re.M)
    assert not forbidden.search(src), "approval.py must not import discord/src/glimi"
