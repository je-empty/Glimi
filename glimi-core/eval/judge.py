"""LLM-as-judge wrapper — reuses the offline judge from ``tests/e2e/quality_judge.py``.

We do NOT re-implement an LLM judge. The project already ships an offline,
Haiku-backed quality judge used by QA automation; this module reuses its building
blocks (:func:`call_haiku`, :func:`extract_json`, ``JUDGE_PROMPT``, ``MODEL``) so
the eval harness and production QA share the exact same judging surface.

Two judging modes:

* :func:`judge_response` — for agent-turn cases: scores the agent's actual reply
  against the case's ``judge_rubric`` (subjective quality / persona / grounding).
* :func:`judge_transcript` — for supervisor cases: feeds a transcript to the
  reused ``JUDGE_PROMPT`` and returns the supervisor verdict (severity/score/
  issues). This is the offline mirror of ``glimi/conversation.py``'s production
  supervisor control loop (there is **no** ``supervisor_judge`` agent_type in the
  runtime — see eval/README.md).

The judge spawns the ``claude`` CLI, so it is only invoked when a real backend is
selected AND the CLI is present. In echo mode the runner skips it entirely and
marks the judge ``SKIPPED`` — no fabricated scores.
"""
from __future__ import annotations

import json
import shutil
from typing import Any, Optional

# Reuse the project's offline judge primitives. tests/e2e is importable
# (tests/e2e/__init__.py exists); this is the same judge production QA uses.
from tests.e2e.quality_judge import (  # noqa: E402
    JUDGE_PROMPT,
    MODEL,
    call_haiku,
    extract_json,
)


def judge_available() -> bool:
    """True when the Claude CLI is on PATH (so the Haiku judge can run)."""
    return shutil.which("claude") is not None


# ── rubric prompt for agent-turn cases ────────────────────────────────
_RESPONSE_JUDGE_PROMPT = """You are an evaluator scoring a single AI-companion reply.

CAPABILITY UNDER TEST: {capability}

RUBRIC (what a good reply must do):
{criteria}

THE USER SAID:
{user_input}

THE AGENT REPLIED:
{agent_output}

Score the reply against the rubric. Output STRICT JSON only — no prose, no markdown:
{{"score": 0-10, "pass": true|false, "reasons": "one short sentence"}}

Scoring: 8-10 = clearly meets the rubric; 5-7 = partial; 0-4 = fails or breaks character.
"""


def judge_response(
    *,
    capability: str,
    criteria: str,
    user_input: str,
    agent_output: str,
    min_score: int = 6,
    timeout: int = 90,
) -> dict[str, Any]:
    """Score an agent's reply with the reused Haiku judge.

    Returns a dict: {status, score, pass, reasons, model}. ``status`` is
    ``scored`` or ``error`` (judge call failed — counts as not-passed but is not
    a fabricated score).
    """
    prompt = _RESPONSE_JUDGE_PROMPT.format(
        capability=capability,
        criteria=criteria or "Reply should be coherent and in-character.",
        user_input=user_input,
        agent_output=agent_output,
    )
    raw = call_haiku(prompt, timeout=timeout)
    if not raw or raw.startswith("__ERROR__"):
        return {"status": "error", "score": None, "pass": False,
                "reasons": f"judge call failed: {raw[:80]}", "model": MODEL}
    data = extract_json(raw) or {}
    score = data.get("score")
    passed = bool(data.get("pass")) if "pass" in data else (
        isinstance(score, (int, float)) and score >= min_score
    )
    return {
        "status": "scored",
        "score": score,
        "pass": passed,
        "reasons": data.get("reasons", ""),
        "model": MODEL,
    }


def judge_transcript(transcript: list[dict], *, timeout: int = 90) -> dict[str, Any]:
    """Run the reused supervisor ``JUDGE_PROMPT`` over a transcript.

    Returns the supervisor verdict normalized to:
    {status, severity, score, issues, summary, model}. ``status`` is ``scored``
    or ``error``. This is the offline LLM-as-judge that mirrors the production
    supervisor; ``supervisor_judge`` does not exist as a runtime agent_type.
    """
    lines = []
    for turn in transcript:
        ch = turn.get("channel", "chat")
        spk = turn.get("speaker", "?")
        msg = (turn.get("message", "") or "")[:180].replace("\n", " ")
        lines.append(f"[{ch}] {spk}: {msg}")
    convo = "\n".join(lines)
    raw = call_haiku(JUDGE_PROMPT + convo, timeout=timeout)
    if not raw or raw.startswith("__ERROR__"):
        return {"status": "error", "severity": None, "score": None,
                "issues": [], "summary": f"judge call failed: {raw[:80]}", "model": MODEL}
    data = extract_json(raw) or {}
    return {
        "status": "scored",
        "severity": data.get("severity"),
        "score": data.get("score"),
        "issues": data.get("issues", []),
        "summary": data.get("summary", ""),
        "model": MODEL,
    }
