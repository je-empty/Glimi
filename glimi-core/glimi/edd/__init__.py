# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Glimi EDD — a domain-neutral eval-driven-development framework for Glimi apps.

This is the *integration* counterpart to the golden-set capability harness in
``eval/``: where that scores individual capabilities against fixed cases, EDD scores
a **full end-to-end run** of an app (driven by an autonomous owner agent) across
weighted **dimensions** into a single 0-100 **quality score**, and tracks that score
across **git-anchored generations** so quality is measured commit-over-commit — the
eval flywheel.

Core (this package) is domain-NEUTRAL — it knows nothing about Community friends or
Workspace deliverables. Each app supplies its own dimensions + evaluators and feeds
the resulting :class:`DimResult` list in:

    from glimi.edd import Dimension, DimResult, build_assessment, GenerationStore

    DIMS = [Dimension("onboarding", "온보딩", 1.0, "structural", "...")]   # app-domain
    results = [DimResult(... )]                                            # app evaluates
    assessment = build_assessment(results, min_overall=70)                # core scores
    store = GenerationStore(db_path=..., generations_dir=...)             # core persists
    store.record(assessment.as_dict(), run_id=...)                        # → SQLite + git JSON

Both Glimi Community and Glimi Workspace inherit this framework; only their dimension
sets and owner-agent drivers differ.
"""
from __future__ import annotations

from .dimensions import (
    Dimension,
    DimResult,
    Assessment,
    composite_score,
    build_assessment,
)
from .history import GenerationStore
from .report import generation_to_html, generation_to_pdf, html_to_pdf

__all__ = [
    "Dimension",
    "DimResult",
    "Assessment",
    "composite_score",
    "build_assessment",
    "GenerationStore",
    "generation_to_html",
    "generation_to_pdf",
    "html_to_pdf",
]
