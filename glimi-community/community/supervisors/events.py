"""Supervisor 활동 이벤트 로그.

각 supervisor 가 실제로 행동(intervene)할 때마다 구조화된 이벤트를 append.
대시보드 그래프가 이걸 읽어서 supervisor → target edge 를 활성화 + 클릭 시
히스토리 모달 노출.

저장 위치: `communities/{cid}/logs/.supervisor_events.jsonl` (append-only NDJSON).

이벤트 스키마:
    {
      "ts": "2026-05-01T06:30:12+00:00",   // ISO UTC
      "sup_id": "commitment.tracker",       // supervisor 식별자
      "action": "nudge",                    // 액션 라벨 — supervisor 별 vocabulary
      "targets": ["agent-creator-001"],     // 영향받은 agent_id (그래프 edge 그릴 대상)
      "summary": "윤하나 → #mgr-creator nudge", // 한 줄 사람 가독
      "outcome": "ok",                      // ok | failed | skipped
      "details": {...}                      // 자유 dict — 모달에서 펼침
    }

설계 원칙:
  - 슈퍼바이저가 "검사만 하고 아무 일 없음" 케이스는 기록 X (노이즈 ↑)
  - 실제 intervene / nudge / state change / 발견 만 기록
  - tail 형태로 최근 N (= 50) 만 유지 (rotation 은 일단 없음 — 나중에 클일 때만)
"""
from __future__ import annotations

import json as _json
import os as _os
from typing import Optional

from community import log_writer
from community.core.timeutil import now_utc_iso


_MAX_BUFFER_LINES = 1000  # 파일이 너무 커지면 tail 로 잘라냄


def _events_path() -> Optional[str]:
    """현재 community 의 events 파일 경로. community 미설정 시 None."""
    try:
        from community import db, community
        cid = community.get_community_id()
        if not cid:
            return None
        # community.db 와 같은 디렉터리 (logs/ 하위) 에 둠
        db_path = db._get_db_path()
        logs_dir = _os.path.join(_os.path.dirname(db_path), "logs")
        _os.makedirs(logs_dir, exist_ok=True)
        return _os.path.join(logs_dir, ".supervisor_events.jsonl")
    except Exception:
        return None


def log_event(
    sup_id: str,
    action: str,
    targets: list[str],
    summary: str,
    outcome: str = "ok",
    details: Optional[dict] = None,
) -> None:
    """supervisor 활동 한 건 기록. 실패해도 무시 (감시 자체가 깨지면 안 됨)."""
    if not sup_id or not action:
        return
    path = _events_path()
    if not path:
        return
    record = {
        "ts": now_utc_iso(),
        "sup_id": sup_id,
        "action": action,
        "targets": list(targets or []),
        "summary": (summary or "")[:240],
        "outcome": outcome,
        "details": details or {},
    }
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(_json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as e:
        try:
            log_writer.system(f"[sup:{sup_id}] event write fail: {e}")
        except Exception:
            pass


def read_recent(sup_id: Optional[str] = None, limit: int = 50, since_seconds: Optional[int] = None) -> list[dict]:
    """events tail 읽기. sup_id 지정 시 그 supervisor 만 필터.
    since_seconds 지정 시 그 이내 발생한 것만.
    """
    path = _events_path()
    if not path or not _os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception:
        return []
    # tail
    lines = lines[-_MAX_BUFFER_LINES:]
    out: list[dict] = []
    cutoff_ts: Optional[float] = None
    if since_seconds:
        import time as _t
        cutoff_ts = _t.time() - since_seconds
    for ln in reversed(lines):
        ln = ln.strip()
        if not ln:
            continue
        try:
            rec = _json.loads(ln)
        except Exception:
            continue
        if sup_id and rec.get("sup_id") != sup_id:
            continue
        if cutoff_ts is not None:
            try:
                from datetime import datetime as _dt
                t = _dt.fromisoformat(rec["ts"].replace("Z", "+00:00")).timestamp()
                if t < cutoff_ts:
                    break  # reverse 순회 — 더 오래된 건 다 cutoff 밖
            except Exception:
                pass
        out.append(rec)
        if len(out) >= limit:
            break
    return out


__all__ = ["log_event", "read_recent"]
