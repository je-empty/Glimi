# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""EDD dimension model + composite scoring (domain-neutral).

A **dimension** is one axis of quality (e.g. "onboarding", "deliverable completeness")
scored 0-10 with a weight. An app evaluates each dimension into a :class:`DimResult`;
:func:`build_assessment` folds the list into a single 0-100 composite + pass/fail.

LLM-judge dimensions an app cannot honestly score (e.g. on the offline ``echo``
backend) are marked ``skipped=True`` and excluded from the composite — never scored
with a fabricated number.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Dimension:
    """An app-supplied quality axis. ``kind`` is "structural" | "judge" (free-form —
    used only for display/grouping). ``what`` is a one-line description surfaced in
    reports so a reader sees what the score means."""
    key: str
    label: str
    weight: float
    kind: str
    what: str = ""


@dataclass
class DimResult:
    """The evaluated result for one dimension on one run."""
    key: str
    label: str
    kind: str
    weight: float
    what: str
    score: Optional[float]      # 0-10, or None if skipped
    passed: Optional[bool]      # None if skipped
    detail: str
    skipped: bool = False
    skip_reason: str = ""

    def as_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "kind": self.kind,
            "weight": self.weight, "what": self.what, "score": self.score,
            "passed": self.passed, "detail": self.detail,
            "skipped": self.skipped, "skip_reason": self.skip_reason,
        }

    @classmethod
    def for_dim(cls, dim: Dimension, *, score: Optional[float], passed: Optional[bool],
                detail: str, skipped: bool = False, skip_reason: str = "") -> "DimResult":
        """Build a result carrying a :class:`Dimension`'s static fields — so evaluators
        don't restate key/label/weight/kind/what."""
        return cls(dim.key, dim.label, dim.kind, dim.weight, dim.what,
                   score, passed, detail, skipped, skip_reason)


def composite_score(results: list[DimResult]) -> Optional[float]:
    """Weighted average of the non-skipped dimension scores, normalized to 0-100.

    Skipped dimensions are excluded from BOTH numerator and denominator, so an
    honestly-skipped judge (e.g. echo) neither helps nor hurts the score. Returns
    None when nothing scorable ran."""
    active = [r for r in results if not r.skipped and r.score is not None]
    wtot = sum(r.weight for r in active)
    if not wtot:
        return None
    wsum = sum(r.score * r.weight for r in active)
    return round(100.0 * wsum / (10.0 * wtot), 1)


@dataclass
class Assessment:
    """The whole-run quality verdict: a 0-100 composite over weighted dimensions."""
    overall_score: Optional[float]
    passed: bool
    min_overall: int
    results: list[DimResult] = field(default_factory=list)
    failing: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)   # app context: backend, judged, goal, etc.

    def as_dict(self) -> dict:
        return {
            "overall_score": self.overall_score,
            "passed": self.passed,
            "min_overall": self.min_overall,
            "failing": self.failing,
            "dimensions": [r.as_dict() for r in self.results],
            **self.meta,
        }


def build_assessment(results: list[DimResult], *, min_overall: int = 70,
                     meta: Optional[dict] = None) -> Assessment:
    """Fold evaluated dimension results into a composite Assessment. ``passed`` =
    composite present AND >= ``min_overall``. ``failing`` = dims that hard-failed
    (``passed is False``; skipped dims are not failures)."""
    overall = composite_score(results)
    passed = overall is not None and overall >= min_overall
    failing = [r.key for r in results if r.passed is False]
    return Assessment(overall, passed, min_overall, results, failing, dict(meta or {}))
