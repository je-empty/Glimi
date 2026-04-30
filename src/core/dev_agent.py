"""Dev manager (Sena) — agent seed + dev_requests 큐 helper.

dev_requests / dev_runs 는 **platform.db 글로벌 테이블** — 모든 community 의 요청이 한 곳에
모이고 admin 이 통합 페이지에서 batch 검토/승인/실행. helper 들은 platform DB 직접 접근.

세나 자체는 community-local 에이전트 — community 별로 mgr-dev-request 채널에서 활동.
시각적으로는 admin 만 보임 (가시성 필터는 monitor.py + snapshot 라우터 책임).
"""
from __future__ import annotations

import json as _json
import sqlite3
from pathlib import Path
from typing import Optional

from src import db, log_writer

DEV_ID = "agent-dev-001"
DEV_NAME = "한세나"
DEV_CHANNEL = "mgr-dev-request"


def _platform_conn() -> sqlite3.Connection:
    """platform.db 연결 — dev_requests / dev_runs 글로벌 테이블 전용."""
    from src.platform.config import PLATFORM_DB_PATH
    from src.platform.db import init_db as _init_platform_db
    _init_platform_db()
    c = sqlite3.connect(PLATFORM_DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    return c


# ── Agent seed (community-local) ───────────────────────────

def ensure_dev_seeded() -> bool:
    """Dev 에이전트 (한세나) 가 community DB 에 없으면 seed_agents.json 에서 등록.

    반환: 새로 등록했으면 True, 이미 있어서 skip 했거나 실패면 False.
    """
    if db.get_agent(DEV_ID):
        return False
    seed_path = Path(__file__).resolve().parents[2] / "assets" / "seed_agents.json"
    if not seed_path.exists():
        log_writer.system(f"❌ dev 시드 파일 없음: {seed_path}")
        return False
    try:
        with open(seed_path, "r", encoding="utf-8") as f:
            seeds = _json.load(f)
        dev_seed = next((a for a in seeds if a.get("id") == DEV_ID), None)
        if not dev_seed:
            log_writer.system(f"❌ dev 시드 엔트리 없음 in {seed_path.name}")
            return False
        db.save_agent_profile(dev_seed)
        try:
            from src.bot import CHANNEL_AGENT_MAP, AGENT_CHANNEL_MAP
            CHANNEL_AGENT_MAP[DEV_CHANNEL] = DEV_ID
            AGENT_CHANNEL_MAP[DEV_ID] = DEV_CHANNEL
        except Exception:
            pass
        log_writer.system(f"✓ dev lazy 시드 등록: {DEV_ID} ({DEV_NAME})")
        return True
    except Exception as e:
        log_writer.system(f"❌ dev 시드 로드 실패: {type(e).__name__}: {e}")
        return False


def _now_iso() -> str:
    from src.core.timeutil import now_utc_iso
    return now_utc_iso()


# ── dev_requests 큐 (platform.db, 글로벌) ──────────────────

def find_similar_recent_request(
    community_id: str,
    payload: dict,
    window_minutes: int = 60,
) -> Optional[dict]:
    """같은 community 의 pending/analyzed 요청 중, 같은 channel · 같은 severity 로
    최근 N 분 안에 적재된 row 가 있으면 반환. dedup gate 용.

    호출 측이 None 이 아니면 새 INSERT 안 하고 기존 request_id 반환해서
    동일 버그 중복 보고 차단 (2026-04-30 유나가 같은 "메시지 중복 버그" 7회 보고 회귀).
    """
    ch = (payload or {}).get("channel", "")
    sev = (payload or {}).get("severity", "")
    if not ch or not sev:
        return None
    conn = _platform_conn()
    try:
        row = conn.execute(
            "SELECT * FROM dev_requests "
            "WHERE community_id=? AND status IN ('pending','analyzed') "
            "  AND severity=? "
            "  AND json_extract(payload_json, '$.channel')=? "
            "  AND requested_at >= datetime('now', ?) "
            "ORDER BY id DESC LIMIT 1",
            (community_id, sev, ch, f"-{window_minutes} minutes"),
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def enqueue_dev_request(
    community_id: str,
    requested_by: str,
    payload: dict,
) -> int:
    """`request_dev_fix` 툴 호출 시 적재. 성공 시 새 row id 반환.

    payload schema:
        channel:  str           — 발생 채널 (e.g. "dm-서연")
        severity: 'low'|'med'|'high'
        repro:    str
        expected: str
        actual:   str
        notes:    str (optional)
    """
    payload_json = _json.dumps(payload, ensure_ascii=False)
    severity = payload.get("severity", "med")
    conn = _platform_conn()
    try:
        cur = conn.execute(
            "INSERT INTO dev_requests (community_id, status, requested_by, payload_json, severity) "
            "VALUES (?, 'pending', ?, ?, ?)",
            (community_id, requested_by, payload_json, severity),
        )
        new_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    log_writer.system(
        f"[dev] 요청 #{new_id} 적재 (community={community_id}, by={requested_by}, "
        f"channel={payload.get('channel','?')}, severity={severity})"
    )
    return new_id


def get_pending_for_community(community_id: str, limit: int = 5) -> list[dict]:
    """status='pending' 인 요청 — 세나가 처리할 대상 (해당 community 발생 한정)."""
    conn = _platform_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM dev_requests WHERE community_id=? AND status='pending' "
            "ORDER BY requested_at ASC LIMIT ?",
            (community_id, limit),
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def get_request(request_id: int) -> Optional[dict]:
    conn = _platform_conn()
    try:
        row = conn.execute(
            "SELECT * FROM dev_requests WHERE id=?", (request_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def list_requests(
    community_id: Optional[str] = None,
    statuses: Optional[list[str]] = None,
    limit: int = 200,
) -> list[dict]:
    """admin 페이지용 — 필터 가능한 list."""
    where = []
    params: list = []
    if community_id:
        where.append("community_id=?")
        params.append(community_id)
    if statuses:
        placeholders = ",".join("?" for _ in statuses)
        where.append(f"status IN ({placeholders})")
        params.extend(statuses)
    sql = "SELECT * FROM dev_requests"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY requested_at DESC LIMIT ?"
    params.append(limit)
    conn = _platform_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def count_pending_for_community(community_id: str) -> int:
    """Community dashboard 의 'N pending' 인디케이터용 (admin 만 보임)."""
    conn = _platform_conn()
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM dev_requests "
            "WHERE community_id=? AND status NOT IN ('completed','rejected')",
            (community_id,),
        ).fetchone()[0]
    finally:
        conn.close()
    return n


def has_active_work() -> bool:
    """현재 큐에 작업/검토 중인 항목이 있는지 — agent display status 동적 결정."""
    conn = _platform_conn()
    try:
        n = conn.execute(
            "SELECT COUNT(*) FROM dev_requests "
            "WHERE status IN ('pending','analyzed','approved','queued','processing')"
        ).fetchone()[0]
    finally:
        conn.close()
    return n > 0


# ── status 전이 helper ─────────────────────────────────────

def mark_analyzed(
    request_id: int,
    task_brief: str,
    files_hint: list[str],
    analysis_notes: str,
    sera_summary: str,
    confidence: str,  # 'high' | 'low'
) -> None:
    """세나가 pending → analyzed 로 전환. admin 검토 대기 상태."""
    conn = _platform_conn()
    try:
        conn.execute(
            "UPDATE dev_requests SET status='analyzed', task_brief=?, files_hint=?, "
            "analysis_notes=?, sera_summary=?, confidence=?, analyzed_at=? "
            "WHERE id=? AND status='pending'",
            (task_brief, _json.dumps(files_hint, ensure_ascii=False),
             analysis_notes, sera_summary, confidence, _now_iso(), request_id),
        )
        conn.commit()
    finally:
        conn.close()
    log_writer.system(f"[dev] #{request_id} analyzed (confidence={confidence})")


def mark_needs_human_review(request_id: int, report: dict) -> None:
    """세나 LOW confidence 직접 escalate — admin 만 처리 가능."""
    conn = _platform_conn()
    try:
        conn.execute(
            "UPDATE dev_requests SET status='needs_human_review', result_json=?, "
            "sera_summary=?, confidence='low', analyzed_at=? WHERE id=?",
            (_json.dumps(report, ensure_ascii=False),
             (report.get("summary") or "")[:200], _now_iso(), request_id),
        )
        conn.commit()
    finally:
        conn.close()
    log_writer.system(f"[dev] #{request_id} → needs_human_review")


def mark_approved(request_id: int, admin_user_id: str) -> None:
    conn = _platform_conn()
    try:
        conn.execute(
            "UPDATE dev_requests SET status='approved', approved_at=?, approved_by=? WHERE id=?",
            (_now_iso(), admin_user_id, request_id),
        )
        conn.commit()
    finally:
        conn.close()
    log_writer.system(f"[dev] #{request_id} approved by {admin_user_id}")


def mark_rejected(request_id: int, admin_user_id: str) -> None:
    conn = _platform_conn()
    try:
        conn.execute(
            "UPDATE dev_requests SET status='rejected', completed_at=?, approved_by=? WHERE id=?",
            (_now_iso(), admin_user_id, request_id),
        )
        conn.commit()
    finally:
        conn.close()
    log_writer.system(f"[dev] #{request_id} rejected by {admin_user_id}")


def mark_queued_batch(request_ids: list[int], run_id: int, branch_name: str) -> None:
    """admin Run 클릭 시 approved 항목들을 queued + branch 매핑."""
    if not request_ids:
        return
    placeholders = ",".join("?" for _ in request_ids)
    conn = _platform_conn()
    try:
        conn.execute(
            f"UPDATE dev_requests SET status='queued', run_id=?, branch_name=? "
            f"WHERE id IN ({placeholders}) AND status='approved'",
            (run_id, branch_name, *request_ids),
        )
        conn.commit()
    finally:
        conn.close()
    log_writer.system(
        f"[dev] queued batch run_id={run_id} ({len(request_ids)} items) on {branch_name}"
    )


def mark_processing(request_id: int) -> None:
    conn = _platform_conn()
    try:
        conn.execute(
            "UPDATE dev_requests SET status='processing', started_at=? WHERE id=?",
            (_now_iso(), request_id),
        )
        conn.commit()
    finally:
        conn.close()


def mark_completed(
    request_id: int, result: dict, commit_sha: Optional[str] = None,
    pr_url: Optional[str] = None,
) -> None:
    conn = _platform_conn()
    try:
        conn.execute(
            "UPDATE dev_requests SET status='completed', result_json=?, commit_sha=?, "
            "pr_url=COALESCE(?, pr_url), completed_at=? WHERE id=?",
            (_json.dumps(result, ensure_ascii=False), commit_sha, pr_url,
             _now_iso(), request_id),
        )
        conn.commit()
    finally:
        conn.close()
    log_writer.system(f"[dev] #{request_id} completed (commit={commit_sha or 'none'})")


def mark_failed(request_id: int, error: str) -> None:
    conn = _platform_conn()
    try:
        conn.execute(
            "UPDATE dev_requests SET status='failed', error=?, completed_at=? WHERE id=?",
            (error[:500], _now_iso(), request_id),
        )
        conn.commit()
    finally:
        conn.close()
    log_writer.system(f"[dev] ❌ #{request_id} failed: {error[:120]}")


def mark_pr_merged(request_id: int) -> None:
    conn = _platform_conn()
    try:
        conn.execute(
            "UPDATE dev_requests SET pr_merged_at=? WHERE id=?",
            (_now_iso(), request_id),
        )
        conn.commit()
    finally:
        conn.close()


# ── dev_runs CRUD ──────────────────────────────────────────

def create_run(branch_name: str, request_ids: list[int], started_by: str,
               log_path: str) -> int:
    conn = _platform_conn()
    try:
        cur = conn.execute(
            "INSERT INTO dev_runs (status, branch_name, log_path, request_count, started_by) "
            "VALUES ('starting', ?, ?, ?, ?)",
            (branch_name, log_path, len(request_ids), started_by),
        )
        run_id = cur.lastrowid
        conn.commit()
    finally:
        conn.close()
    log_writer.system(f"[dev] run #{run_id} created — {len(request_ids)} requests on {branch_name}")
    return run_id


def update_run_status(run_id: int, status: str, **fields) -> None:
    """status 와 임의의 추가 필드 (pr_url, completed_count, failed_count, error 등) 갱신."""
    sets = ["status=?"]
    params: list = [status]
    for k, v in fields.items():
        if v is not None:
            sets.append(f"{k}=?")
            params.append(v)
    if status in ("completed", "failed", "aborted") and "completed_at" not in fields:
        sets.append("completed_at=?")
        params.append(_now_iso())
    params.append(run_id)
    conn = _platform_conn()
    try:
        conn.execute(f"UPDATE dev_runs SET {', '.join(sets)} WHERE id=?", params)
        conn.commit()
    finally:
        conn.close()


def get_run(run_id: int) -> Optional[dict]:
    conn = _platform_conn()
    try:
        row = conn.execute("SELECT * FROM dev_runs WHERE id=?", (run_id,)).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def get_active_run() -> Optional[dict]:
    """현재 starting/running 상태의 run — 동시에 1개만 허용."""
    conn = _platform_conn()
    try:
        row = conn.execute(
            "SELECT * FROM dev_runs WHERE status IN ('starting','running') "
            "ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def list_runs(limit: int = 30) -> list[dict]:
    conn = _platform_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM dev_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


__all__ = [
    "DEV_ID", "DEV_NAME", "DEV_CHANNEL",
    "ensure_dev_seeded",
    "enqueue_dev_request", "get_pending_for_community", "get_request",
    "list_requests", "count_pending_for_community", "has_active_work",
    "mark_analyzed", "mark_needs_human_review", "mark_approved", "mark_rejected",
    "mark_queued_batch", "mark_processing", "mark_completed", "mark_failed",
    "mark_pr_merged",
    "create_run", "update_run_status", "get_run", "get_active_run", "list_runs",
]
