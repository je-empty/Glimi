"""Production feedback loop — promote a real bad turn into a golden case.

This closes the loop the job spec calls a "production feedback loop": signals from
live conversations feed back into the regression suite so a real failure can never
silently regress again.

A logged bad turn is a row in the ``conversations`` table (the same shape
``tests/e2e/quality_judge.fetch_recent_convos`` reads): ``{channel, speaker,
message}``. When the production supervisor (``glimi/conversation.py`` control loop)
or the offline judge (``tests/e2e/quality_judge.py``) flags a turn — e.g. a persona
leaked a meta term, hallucinated an action, or ignored a known fact — an operator
exports the flagged turns as JSONL and runs this module to template them into a
new golden case.

Input JSONL (one flagged turn per line)::

    {"speaker": "Nova", "agent_type": "persona", "persona": "...",
     "input": "the owner message that triggered the bad turn",
     "bad_output": "the actual leaked/hallucinated reply",
     "leak": "as an AI",            # optional: the exact phrase that must never recur
     "capability": "fallback",      # optional: inferred if omitted
     "seeded_memory": [...]}        # optional: facts that were ignored

The generated golden case asserts the leak never recurs (``must_not_contain``) and,
for ignored-fact cases, that the fact grounds the reply (``grounded_fact``). It is
written to ``eval/golden/from_production.jsonl`` (appended) so the next CI echo run
and every scored gate guard against the regression.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from .schema import CAPABILITIES, _validate

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
DEFAULT_OUT = GOLDEN_DIR / "from_production.jsonl"

# Phrases that, if present in a bad output, strongly suggest the capability.
_META_LEAKS = ("as an ai", "language model", "i am an agent", "chatbot", "simulation")
_FABRICATION = ("i booked", "i deleted", "i created", "payment successful", "task complete")


def _infer_capability(turn: dict) -> str:
    if turn.get("capability") in CAPABILITIES:
        return turn["capability"]
    bad = (turn.get("bad_output", "") or "").lower()
    if any(p in bad for p in _META_LEAKS):
        return "persona"
    if any(p in bad for p in _FABRICATION):
        return "fallback"
    if turn.get("seeded_memory"):
        return "memory"
    return "fallback"


def turn_to_case(turn: dict, *, idx: int = 0) -> dict[str, Any]:
    """Template one flagged production turn into a golden-case dict."""
    cap = _infer_capability(turn)
    speaker = turn.get("speaker", "agent")
    cid = turn.get("id") or f"prod-{cap}-{_slug(speaker)}-{idx:03d}"

    checks: dict[str, Any] = {"expect_no_tool": True}
    # The exact leaked phrase must never recur.
    leak = turn.get("leak")
    leaks = [leak] if leak else []
    # Auto-seed must_not_contain from recognized leak families in the bad output.
    bad = (turn.get("bad_output", "") or "").lower()
    for fam in (_META_LEAKS + _FABRICATION):
        if fam in bad and fam not in [x.lower() for x in leaks]:
            leaks.append(fam)
    if leaks:
        checks["must_not_contain"] = leaks
    seeded = turn.get("seeded_memory")
    if cap == "memory" and seeded:
        # Ground against the first seeded fact's salient token.
        fact = (seeded[0].get("content", "") if seeded else "")
        token = turn.get("grounded_fact") or _salient_token(fact)
        if token:
            checks["grounded_fact"] = token

    case = {
        "id": cid,
        "capability": cap,
        "setup": {
            "persona": turn.get("persona") or f"{speaker} — promoted from a flagged production turn.",
            "agent_type": turn.get("agent_type", "persona"),
            "name": speaker,
        },
        "input": turn.get("input") or turn.get("message") or "",
        "checks": checks,
        "judge_rubric": {
            "criteria": turn.get("criteria")
            or f"This is a regression of a real flagged turn. The reply must not repeat the failure: {leaks or 'see notes'}.",
            "min_score": int(turn.get("min_score", 6)),
        },
        "notes": "Promoted from a flagged production turn via eval/from_production.py. "
                 f"Original bad output: {turn.get('bad_output', '')[:120]!r}",
    }
    if seeded:
        case["setup"]["seeded_memory"] = seeded
    # Validate before returning so we never write a malformed case.
    _validate(case, source="from_production(in-memory)")
    return case


def promote(in_path: Path, out_path: Optional[Path] = None,
            *, dry_run: bool = False) -> list[dict]:
    """Read flagged turns from ``in_path`` JSONL → append golden cases to ``out_path``."""
    out = Path(out_path) if out_path else DEFAULT_OUT
    cases: list[dict] = []
    for i, line in enumerate(Path(in_path).read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        turn = json.loads(line)
        cases.append(turn_to_case(turn, idx=i))
    if not dry_run and cases:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as f:
            for c in cases:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return cases


def _slug(s: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in s).strip("-") or "x"


def _salient_token(text: str) -> str:
    """Pick a content word from a fact to use as the grounding token."""
    skip = {"the", "is", "a", "an", "to", "of", "owner", "owners", "owner's", "and", "named"}
    for w in text.replace(".", " ").replace(",", " ").split():
        cw = w.strip("'\"").lower()
        if len(cw) > 3 and cw not in skip:
            return w.strip("'\".,")
    return ""


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        prog="eval promote",
        description="Promote flagged production turns (JSONL) into golden cases.",
    )
    ap.add_argument("input", help="JSONL of flagged turns")
    ap.add_argument("--out", default=None, help=f"golden file to append (default {DEFAULT_OUT})")
    ap.add_argument("--dry-run", action="store_true", help="print cases, do not write")
    args = ap.parse_args(argv)

    cases = promote(Path(args.input), Path(args.out) if args.out else None, dry_run=args.dry_run)
    for c in cases:
        print(json.dumps(c, ensure_ascii=False, indent=2 if args.dry_run else None))
    print(f"\n{'(dry-run) ' if args.dry_run else ''}{len(cases)} case(s) "
          f"{'would be' if args.dry_run else ''} promoted"
          + ("" if args.dry_run else f" → {args.out or DEFAULT_OUT}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
