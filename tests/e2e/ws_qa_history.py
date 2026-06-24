# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Glimi Workspace — QA generation history (thin wrapper over :mod:`glimi.edd`).

The store itself (SQLite + git-anchored committed JSON generations) is domain-neutral
and lives in core (:class:`glimi.edd.GenerationStore`). This module just points it at
the Workspace QA paths and re-exports the call surface ``ws_e2e`` uses — the exact
Workspace analogue of :mod:`tests.e2e.qa_history`. The paths are kept DISTINCT from
Community's so the two eval flywheels never collide:

- ``tests/e2e/results/ws_qa_history.db``   — SQLite, gitignored (local trend/dashboard log).
- ``tests/e2e/ws_qa_generations/``         — committed git-SHA-stamped generation summaries.
"""
from __future__ import annotations

from pathlib import Path

from glimi.edd import GenerationStore

_HERE = Path(__file__).resolve().parent
RESULTS_DIR = _HERE / "results"
DB_PATH = RESULTS_DIR / "ws_qa_history.db"        # gitignored (tests/e2e/results/ is)
GENERATIONS_DIR = _HERE / "ws_qa_generations"     # committed (the timeline)
_REPO_ROOT = _HERE.parent.parent                  # tests/e2e -> repo root

_store = GenerationStore(db_path=DB_PATH, generations_dir=GENERATIONS_DIR,
                         repo_root=_REPO_ROOT)


def record_generation(assessment: dict, *, run_id: str, owner_name: str = "",
                      goal: str = "", generated_at=None,
                      report_md: str = "", report_pdf: str = "") -> dict:
    return _store.record(assessment, run_id=run_id, owner_name=owner_name, goal=goal,
                         generated_at=generated_at, report_md=report_md,
                         report_pdf=report_pdf)


def load_generations() -> list[dict]:
    return _store.load_generations()


def load_runs(limit: int = 200) -> list[dict]:
    return _store.load_runs(limit)


def dimensions_for(run_id: str) -> list[dict]:
    return _store.dimensions_for(run_id)


def quality_trend() -> list[dict]:
    return _store.quality_trend()


def git_sha() -> tuple[str, bool]:
    return _store.git_sha()
