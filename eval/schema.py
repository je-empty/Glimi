"""Golden-case schema + loader for the Glimi evaluation harness.

A *golden case* is one curated, machine-checkable example of a capability the
runtime is supposed to have. Cases live as JSONL under ``eval/golden/*.jsonl``
(one JSON object per line). This module loads them, validates the schema, and
hands the runner a list of :class:`GoldenCase` dataclasses.

The schema is deliberately small and explicit so a contributor can add a case
by hand without reading the runner. Validation is strict: a malformed case
fails CI (the echo run loads + validates every case before running anything).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

# Capabilities the harness knows how to score. Adding a new one means teaching
# the runner how to run/score it — keep this list in sync with runner.py.
CAPABILITIES = {"persona", "tool_use", "memory", "fallback", "supervisor"}


class SchemaError(ValueError):
    """A golden case failed validation."""


@dataclass
class GoldenCase:
    id: str
    capability: str
    setup: dict[str, Any] = field(default_factory=dict)
    input: str = ""
    checks: dict[str, Any] = field(default_factory=dict)
    judge_rubric: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    # Supervisor (judge-only) cases carry these instead of input/agent setup:
    supervisor_judge: bool = False
    transcript: list[dict] = field(default_factory=list)
    expect: dict[str, Any] = field(default_factory=dict)
    # Where the case came from (source file) — for reporting.
    source: str = ""

    @property
    def backend_required(self) -> Optional[str]:
        """If the case can only be meaningfully scored on a real backend.

        Supervisor cases need the Claude CLI judge. Tool-emission cases note in
        their data that real emission needs claude_cli, but they still run a
        deterministic (no-hallucination) assertion under echo, so they are NOT
        backend-required — only their judge step is gated by backend.
        """
        if self.capability == "supervisor":
            return "claude_cli"
        return self.setup.get("backend_required") if self.setup else None


def _validate(obj: dict, source: str) -> GoldenCase:
    if not isinstance(obj, dict):
        raise SchemaError(f"{source}: each line must be a JSON object")
    cid = obj.get("id")
    if not cid or not isinstance(cid, str):
        raise SchemaError(f"{source}: case missing string 'id'")
    cap = obj.get("capability")
    if cap not in CAPABILITIES:
        raise SchemaError(
            f"{source}:{cid}: capability must be one of {sorted(CAPABILITIES)}, got {cap!r}"
        )

    supervisor = bool(obj.get("supervisor_judge"))
    if cap == "supervisor":
        supervisor = True

    if supervisor:
        # Judge-only case: needs a transcript + an expectation, NOT an agent turn.
        transcript = obj.get("transcript")
        if not isinstance(transcript, list) or not transcript:
            raise SchemaError(f"{source}:{cid}: supervisor case needs a non-empty 'transcript' list")
        for turn in transcript:
            if not isinstance(turn, dict) or "speaker" not in turn or "message" not in turn:
                raise SchemaError(f"{source}:{cid}: each transcript turn needs 'speaker' + 'message'")
        if not isinstance(obj.get("expect"), dict) or not obj.get("expect"):
            raise SchemaError(f"{source}:{cid}: supervisor case needs an 'expect' object")
    else:
        # Agent-turn case: needs an input string and a setup with a persona.
        if not isinstance(obj.get("input"), str) or not obj.get("input").strip():
            raise SchemaError(f"{source}:{cid}: case needs a non-empty 'input' string")
        setup = obj.get("setup")
        if not isinstance(setup, dict):
            raise SchemaError(f"{source}:{cid}: case needs a 'setup' object")
        if not setup.get("persona"):
            raise SchemaError(f"{source}:{cid}: setup needs a 'persona'")
        at = setup.get("agent_type", "persona")
        if at not in {"persona", "mgr", "creator"}:
            raise SchemaError(f"{source}:{cid}: setup.agent_type must be persona|mgr|creator, got {at!r}")
        checks = obj.get("checks")
        if checks is not None and not isinstance(checks, dict):
            raise SchemaError(f"{source}:{cid}: 'checks' must be an object")

    rubric = obj.get("judge_rubric")
    if rubric is not None and not isinstance(rubric, dict):
        raise SchemaError(f"{source}:{cid}: 'judge_rubric' must be an object")

    return GoldenCase(
        id=cid,
        capability=cap,
        setup=obj.get("setup", {}) or {},
        input=obj.get("input", "") or "",
        checks=obj.get("checks", {}) or {},
        judge_rubric=obj.get("judge_rubric", {}) or {},
        notes=obj.get("notes", "") or "",
        supervisor_judge=supervisor,
        transcript=obj.get("transcript", []) or [],
        expect=obj.get("expect", {}) or {},
        source=source,
    )


def load_cases(golden_dir: Optional[Path] = None) -> list[GoldenCase]:
    """Load + validate every golden case under ``golden_dir`` (default ``eval/golden``).

    Raises :class:`SchemaError` on the first malformed case. Returns cases sorted
    by (capability, id) for stable ordering across runs.
    """
    d = Path(golden_dir) if golden_dir else GOLDEN_DIR
    if not d.exists():
        raise SchemaError(f"golden dir not found: {d}")
    cases: list[GoldenCase] = []
    seen: set[str] = set()
    for path in sorted(d.glob("*.jsonl")):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError as e:
                raise SchemaError(f"{path.name}:{lineno}: invalid JSON: {e}") from e
            case = _validate(obj, source=path.name)
            if case.id in seen:
                raise SchemaError(f"{path.name}: duplicate case id {case.id!r}")
            seen.add(case.id)
            cases.append(case)
    if not cases:
        raise SchemaError(f"no golden cases found under {d}")
    cases.sort(key=lambda c: (c.capability, c.id))
    return cases
