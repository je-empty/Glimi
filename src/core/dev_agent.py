"""Dev manager (Sena) — lazy seed + channel ensure + queue helpers.

Lifecycle:
  - First `request_dev_fix` tool call lazy-seeds the dev agent (한세나) from
    `assets/seed_agents.json` and creates the `mgr-dev-request` channel.
  - The DevQueueSupervisor (in supervisors/) polls `dev_requests` and activates the dev
    agent when there's work.
  - Dev agent's processing flow (see runtime activate_agent + custom hooks) reads the
    pending row, decides HIGH/LOW confidence, then dispatches via `dev_dispatch_fix`
    (Claude Code Opus subprocess) or escalates via `dev_escalate`.

Platform decoupling: this module does NOT import from src.bot. The channel-creation step
takes a `guild` parameter (Discord-typed for now) but the call site (tool handler) is in
the bot adapter layer.
"""
from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Optional

from src import db, log_writer

DEV_ID = "agent-dev-001"
DEV_NAME = "한세나"
DEV_CHANNEL = "mgr-dev-request"


def ensure_dev_seeded() -> bool:
    """Dev 에이전트 (한세나) 가 DB 에 없으면 seed_agents.json 에서 등록.

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
        # 채널 매핑 — 봇 startup 의 _build_channel_maps 이후 추가됐을 수 있어 lazy 갱신
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


# ── dev_requests 큐 헬퍼 ───────────────────────────────────

def enqueue_dev_request(
    requested_by: str,
    payload: dict,
) -> int:
    """`request_dev_fix` 툴 호출이 들어오면 호출. 성공 시 새 row id 반환.

    payload schema (validated by tool handler before this is called):
        channel:  str           — 어디서 발생 (e.g. "dm-서하")
        severity: 'low'|'med'|'high'
        repro:    str           — 재현 방법 / 상황 설명
        expected: str           — 기대 동작
        actual:   str           — 실제 동작
        notes:    str (optional)— 추가 컨텍스트
    """
    payload_json = _json.dumps(payload, ensure_ascii=False)
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO dev_requests (status, requested_by, payload_json) VALUES (?, ?, ?)",
        ("pending", requested_by, payload_json),
    )
    new_id = cur.lastrowid
    conn.commit()
    conn.close()
    log_writer.system(f"[dev] 요청 #{new_id} 적재 by {requested_by}: {payload.get('channel','?')} / {payload.get('severity','?')}")
    return new_id


def get_pending_requests(limit: int = 5) -> list[dict]:
    """status='pending' 인 요청들을 오래된 순으로 반환."""
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM dev_requests WHERE status = 'pending' ORDER BY requested_at ASC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_request(request_id: int) -> Optional[dict]:
    conn = db.get_conn()
    row = conn.execute(
        "SELECT * FROM dev_requests WHERE id = ?", (request_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_processing(request_id: int) -> None:
    from src.core.timeutil import now_utc_iso
    conn = db.get_conn()
    conn.execute(
        "UPDATE dev_requests SET status='processing', started_at=? WHERE id=? AND status='pending'",
        (now_utc_iso(), request_id),
    )
    conn.commit()
    conn.close()


def mark_completed(request_id: int, result: dict, commit_sha: Optional[str] = None) -> None:
    from src.core.timeutil import now_utc_iso
    conn = db.get_conn()
    conn.execute(
        "UPDATE dev_requests SET status='completed', result_json=?, commit_sha=?, completed_at=?, "
        "confidence=COALESCE(confidence, 'high') WHERE id=?",
        (_json.dumps(result, ensure_ascii=False), commit_sha, now_utc_iso(), request_id),
    )
    conn.commit()
    conn.close()
    log_writer.system(f"[dev] 요청 #{request_id} 완료 ({commit_sha or 'no-commit'})")


def mark_needs_human_review(request_id: int, report: dict) -> None:
    from src.core.timeutil import now_utc_iso
    conn = db.get_conn()
    conn.execute(
        "UPDATE dev_requests SET status='needs_human_review', result_json=?, completed_at=?, "
        "confidence='low' WHERE id=?",
        (_json.dumps(report, ensure_ascii=False), now_utc_iso(), request_id),
    )
    conn.commit()
    conn.close()
    log_writer.system(f"[dev] 요청 #{request_id} → 오너 검토 대기")


def mark_failed(request_id: int, error: str) -> None:
    from src.core.timeutil import now_utc_iso
    conn = db.get_conn()
    conn.execute(
        "UPDATE dev_requests SET status='failed', error=?, completed_at=? WHERE id=?",
        (error[:500], now_utc_iso(), request_id),
    )
    conn.commit()
    conn.close()
    log_writer.system(f"[dev] ❌ 요청 #{request_id} 실패: {error[:120]}")


__all__ = [
    "DEV_ID", "DEV_NAME", "DEV_CHANNEL",
    "ensure_dev_seeded",
    "enqueue_dev_request", "get_pending_requests", "get_request",
    "mark_processing", "mark_completed", "mark_needs_human_review", "mark_failed",
]
