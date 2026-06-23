# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""EDD generational history store (domain-neutral).

A **generation** = one :class:`~glimi.edd.dimensions.Assessment` of one run, anchored
to a git commit. :class:`GenerationStore` persists each generation two ways:

1. **SQLite** (``db_path``) — the full, queryable log. Powers a dashboard run-list +
   quality-over-generations trend. A local artifact (the caller gitignores it).
2. **Committed JSON** (``generations_dir``) — one small, git-tracked summary per
   generation, stamped with the **git SHA** it ran against. This is what makes the
   eval flywheel legible in git: ``git log -- <generations_dir>`` reads as a
   measurable quality timeline.

The store is path-parametrized so each app points it at its own dirs; the schema and
git anchoring are shared.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class GenerationStore:
    """SQLite + committed-JSON store for EDD generations, anchored to git.

    ``db_path``          — SQLite file (caller gitignores it).
    ``generations_dir``  — dir for committed ``gen-NNNN-*.json`` files (git-tracked).
    ``repo_root``        — where to run git (defaults to generations_dir's repo)."""

    def __init__(self, *, db_path: Path | str, generations_dir: Path | str,
                 repo_root: Optional[Path | str] = None):
        self.db_path = Path(db_path)
        self.generations_dir = Path(generations_dir)
        self.repo_root = Path(repo_root) if repo_root else self.generations_dir

    # ── git anchoring ────────────────────────────────────────────────────────────
    def git_sha(self) -> tuple[str, bool]:
        """``(short_sha, dirty)`` for HEAD, or ``("unknown", False)``."""
        try:
            sha = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"], cwd=self.repo_root,
                capture_output=True, text=True, timeout=10).stdout.strip()
            dirty = bool(subprocess.run(
                ["git", "status", "--porcelain"], cwd=self.repo_root,
                capture_output=True, text=True, timeout=10).stdout.strip())
            return (sha or "unknown", dirty)
        except Exception:
            return ("unknown", False)

    def git_branch(self) -> str:
        try:
            return subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=self.repo_root,
                capture_output=True, text=True, timeout=10).stdout.strip() or "unknown"
        except Exception:
            return "unknown"

    # ── SQLite ───────────────────────────────────────────────────────────────────
    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        return conn

    def _next_generation_no(self) -> int:
        """Sequential number = (committed generation files) + 1, so the count is
        reproducible from git alone (the DB may be wiped; the timeline isn't)."""
        self.generations_dir.mkdir(parents=True, exist_ok=True)
        return len(list(self.generations_dir.glob("gen-*.json"))) + 1

    # ── record + read ─────────────────────────────────────────────────────────────
    def record(self, assessment: dict, *, run_id: str, owner_name: str = "",
               goal: str = "", generated_at: Optional[str] = None,
               report_md: str = "", report_pdf: str = "") -> dict:
        """Persist one assessment dict (see ``Assessment.as_dict``) as a generation →
        SQLite row(s) + a committable JSON file. Returns the generation record."""
        generated_at = generated_at or now_iso()
        sha, dirty = self.git_sha()
        branch = self.git_branch()
        gen_no = self._next_generation_no()

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
        self.generations_dir.mkdir(parents=True, exist_ok=True)
        stamp = generated_at[:19].replace(":", "").replace("-", "")
        gen_path = self.generations_dir / f"gen-{gen_no:04d}-{stamp}-{sha}.json"
        gen_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        record["_path"] = str(gen_path)

        # 2) SQLite (full queryable log for dashboard/trends)
        conn = self._connect()
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

    def load_generations(self) -> list[dict]:
        """All committed generations, chronological (the git-tracked timeline)."""
        self.generations_dir.mkdir(parents=True, exist_ok=True)
        out: list[dict] = []
        for p in sorted(self.generations_dir.glob("gen-*.json")):
            try:
                out.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        return sorted(out, key=lambda r: r.get("generation_no", 0))

    def load_runs(self, limit: int = 200) -> list[dict]:
        """Recent runs from SQLite (newest first) — for the dashboard run list."""
        if not self.db_path.exists():
            return []
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM runs ORDER BY generated_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def dimensions_for(self, run_id: str) -> list[dict]:
        if not self.db_path.exists():
            return []
        conn = self._connect()
        try:
            rows = conn.execute(
                "SELECT * FROM dimension_scores WHERE run_id = ?", (run_id,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def quality_trend(self) -> list[dict]:
        """generation_no → overall_score series for the trend chart (from committed
        gens, so the timeline survives a wiped DB)."""
        return [
            {"generation_no": g.get("generation_no"), "generated_at": g.get("generated_at"),
             "git_sha": (g.get("git") or {}).get("sha"), "overall_score": g.get("overall_score"),
             "passed": g.get("passed"), "backend": g.get("backend")}
            for g in self.load_generations()
        ]
