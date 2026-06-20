"""Glimi evaluation harness.

A real, runnable agent-evaluation suite for the Glimi runtime:

* ``eval/golden/*.jsonl`` — a curated golden set across five capabilities
  (persona, tool_use, memory, fallback, supervisor).
* :mod:`eval.runner` — runs each case through the real ``glimi`` runtime with a
  configurable backend, scores deterministic checks, and (on a real backend)
  runs the reused LLM-as-judge from ``tests/e2e/quality_judge.py``.
* :mod:`eval.regression` — a baseline-vs-run regression gate.
* :mod:`eval.from_production` — promote a flagged production turn into a golden
  case (the production feedback loop).

CLI: ``python -m eval run --backend echo|claude_cli`` / ``python -m eval gate``.
See ``eval/README.md``.
"""
from __future__ import annotations

from .schema import CAPABILITIES, GoldenCase, SchemaError, load_cases

__all__ = ["load_cases", "GoldenCase", "SchemaError", "CAPABILITIES"]
