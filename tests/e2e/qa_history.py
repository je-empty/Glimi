# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Glimi Community QA — generational history store.

Two surfaces, by design (the user's call):

1. **SQLite** (``results/qa_history.db``, gitignored) — the full, queryable log every
   run appends to. Powers the web dashboard's run list + quality-over-generations
   trend. Local artifact; not committed.

2. **Committed JSON generations** (``tests/e2e/qa_generations/*.json``) — one small,
   git-tracked summary per generation, stamped with the **git SHA** it ran against.
   This is what makes the eval flywheel legible in git: a bug the QA found, the commit
   that fixed it, and the next generation's higher score all live in the history.
   ``git log -- tests/e2e/qa_generations/`` reads as a measurable quality timeline.

A "generation" = one QA assessment (:func:`tests.e2e.qa_quality.assess`) of one run,
anchored to a git commit.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_HERE = Path(__file__).resolve().parent
RESULTS_DIR = _HERE / "results"
DB_PATH = RESULTS_DIR / "qa_history.db"               # gitignored
GENERATIONS_DIR = _HERE / "qa_generations"            # committed (the timeline)
_REPO_ROOT = _HERE.parent.parent                      # tests/e2e -> repo root


# ── git anchoring ────────────────────────────────────────────────────────────────

def git_sha() -> tuple[str, bool]:
    """Return ``(short_sha, dirty)`` for the repo HEAD, or ``("unknown", False)``."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=_REPO_ROOT,
            capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"], cwd=_REPO_ROOT,
            capture_output=True, text=True, timeout=10).stdout.strip())
        return (sha or "unknown", dirty)
    except Exception:
        return ("unknown", False)


def git_branch() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=_REPO_ROOT,
            capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# ── SQLite ───────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id         TEXT PRIMARY KEY,
    generated_at   TEXT NOT NULL,
    generation_no  INTEGER,
    git_sha        TEXT,
    git_dirty      INTEGER,
    git_branch     TEXT,
    backend        TEXT,
    owner_name     TEXT,
    goal           TEXT,
    overall_score  REAL,
    passed         INTEGER,
    judged         INTEGER,
    failing        TEXT,          -- json array of dim keys
    report_md      TEXT,
    report_pdf     TEXT
);
CREATE TABLE IF NOT EXISTS dimension_scores (
    run_id   TEXT NOT NULL,
    dim_key  TEXT NOT NULL,
    label    TEXT,
    kind     TEXT,
    weight   REAL,
    score    REAL,
    passed   INTEGER,
    skipped  INTEGER,
    detail   TEXT,
    PRIMARY KEY (run_id, dim_key)
);
"""


def _connect() -> sqlite3.Connection:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def _next_generation_no() -> int:
    """Sequential generation number = (committed generation files) + 1, so the count
    is reproducible from git alone (the DB may be wiped; the timeline isn't)."""
    GENERATIONS_DIR.mkdir(parents=True, exist_ok=True)
    return len(list(GENERATIONS_DIR.glob("gen-*.json"))) + 1


# ── public API ───────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_generation(
    assessment: dict, *, run_id: str, owner_name: str = "",
    goal: str = "", generated_at: Optional[str] = None,
    report_md: str = "", report_pdf: str = "",
) -> dict:
    """Persist one assessment as a generation → SQLite row(s) + committable JSON.

    Returns the committed generation record (also written to qa_generations/)."""
    generated_at = generated_at or now_iso()
    sha, dirty = git_sha()
    branch = git_branch()
    gen_no = _next_generation_no()

    record = {
        "generation_no": gen_no,
        "run_id": run_id,
        "generated_at": generated_at,
        "git": {"sha": sha, "dirty": dirty, "branch": branch},
        "owner_name": owner_name,
        "goal": goal,
        "backend": assessment.get("backend"),
        "judged": assessment.get("judged"),
        "overall_score": assessment.get("overall_score"),
        "passed": assessment.get("passed"),
        "min_overall": assessment.get("min_overall"),
        "failing": assessment.get("failing", []),
        "dimensions": [
            {k: dim.get(k) for k in
             ("key", "label", "kind", "weight", "score", "passed", "skipped", "detail")}
            for dim in assessment.get("dimensions", [])
        ],
        "report_md": report_md,
        "report_pdf": report_pdf,
    }

    # 1) committable JSON generation (the git-tracked timeline entry)
    GENERATIONS_DIR.mkdir(parents=True, exist_ok=True)
    fname = f"gen-{gen_no:04d}-{generated_at[:19].replace(':', '').replace('-', '')}-{sha}.json"
    gen_path = GENERATIONS_DIR / fname
    gen_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    record["_path"] = str(gen_path)

    # 2) SQLite (full queryable log for the dashboard/trends)
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO runs (run_id, generated_at, generation_no, git_sha, "
            "git_dirty, git_branch, backend, owner_name, goal, overall_score, passed, "
            "judged, failing, report_md, report_pdf) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, generated_at, gen_no, sha, int(dirty), branch,
             assessment.get("backend"), owner_name, goal,
             assessment.get("overall_score"), int(bool(assessment.get("passed"))),
             int(bool(assessment.get("judged"))),
             json.dumps(assessment.get("failing", []), ensure_ascii=False),
             report_md, report_pdf),
        )
        conn.execute("DELETE FROM dimension_scores WHERE run_id = ?", (run_id,))
        for dim in assessment.get("dimensions", []):
            conn.execute(
                "INSERT INTO dimension_scores (run_id, dim_key, label, kind, weight, "
                "score, passed, skipped, detail) VALUES (?,?,?,?,?,?,?,?,?)",
                (run_id, dim.get("key"), dim.get("label"), dim.get("kind"),
                 dim.get("weight"), dim.get("score"),
                 None if dim.get("passed") is None else int(dim.get("passed")),
                 int(bool(dim.get("skipped"))), dim.get("detail")),
            )
        conn.commit()
    finally:
        conn.close()

    return record


def load_generations() -> list[dict]:
    """All committed generations, chronological (the git-tracked timeline)."""
    GENERATIONS_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for p in sorted(GENERATIONS_DIR.glob("gen-*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return sorted(out, key=lambda r: r.get("generation_no", 0))


def load_runs(limit: int = 200) -> list[dict]:
    """Recent runs from SQLite (newest first) — for the dashboard run list."""
    if not DB_PATH.exists():
        return []
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY generated_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def dimensions_for(run_id: str) -> list[dict]:
    if not DB_PATH.exists():
        return []
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM dimension_scores WHERE run_id = ?", (run_id,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def quality_trend() -> list[dict]:
    """Generation_no → overall_score series for the trend chart (from committed gens,
    so the timeline survives a wiped DB)."""
    return [
        {"generation_no": g.get("generation_no"), "generated_at": g.get("generated_at"),
         "git_sha": (g.get("git") or {}).get("sha"), "overall_score": g.get("overall_score"),
         "passed": g.get("passed"), "backend": g.get("backend")}
        for g in load_generations()
    ]
