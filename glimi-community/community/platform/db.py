"""platform.db — 플랫폼 레벨 메타 (계정, 커뮤니티 접근 권한).

커뮤니티 데이터(에이전트·대화·기억)는 각 `communities/{id}/community.db` 가 관리.
이 DB 는 그와 별개 — 플랫폼 사용자 관리 전용.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .config import PLATFORM_DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user',  -- 'admin' | 'user'
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_communities (
    user_id INTEGER NOT NULL,
    community_id TEXT NOT NULL,
    granted_at TEXT NOT NULL,
    PRIMARY KEY (user_id, community_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_user_communities_user ON user_communities(user_id);
CREATE INDEX IF NOT EXISTS idx_user_communities_community ON user_communities(community_id);

-- ── Dev requests (admin 전용 글로벌 큐) ──
-- 어느 community 에서 발생했는지 기록 + 한세나(dev) 가 정리한 후 admin 검토/승인/실행.
-- status flow:
--   pending          ← request_dev_fix 호출 직후 (세나 처리 대기)
--   analyzed         ← 세나가 task_brief 정리 완료 (admin 검토 대기)
--   approved         ← admin 승인 (Run 대기 큐)
--   queued           ← Run 클릭 직후 (Claude Code dispatch 대기)
--   processing       ← Claude Code subprocess 작업 중
--   completed        ← 작업 완료 (commit_sha 있음, PR open 또는 merged)
--   failed           ← dispatch 실패
--   needs_human_review ← 세나가 LOW confidence 로 escalate (admin 만 처리 가능)
--   rejected         ← admin reject
CREATE TABLE IF NOT EXISTS dev_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    community_id TEXT NOT NULL,             -- 어디서 발생했나
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','analyzed','approved','rejected',
                         'queued','processing','completed','failed','needs_human_review')),
    requested_by TEXT NOT NULL,              -- agent_id 또는 'owner'
    payload_json TEXT NOT NULL,              -- {channel, severity, repro, expected, actual, notes}
    severity TEXT,                            -- 'low' | 'med' | 'high' (payload 에서 추출 — 빠른 정렬용)
    confidence TEXT,                          -- 세나 판정: 'high' | 'low'
    task_brief TEXT,                          -- 세나가 정리한 작업 지시 (Claude Code 에 전달용)
    files_hint TEXT,                          -- JSON array — 수정 가능성 높은 파일 경로
    analysis_notes TEXT,                      -- 세나 분석 메모 (admin 이 검토 시 참고)
    sera_summary TEXT,                        -- 세나 한 줄 요약 (카드 표시용)
    result_json TEXT,                         -- 작업 결과 (summary, files_changed 등)
    commit_sha TEXT,                          -- Claude Code 가 만든 commit
    branch_name TEXT,                         -- dev-requests/run-{ts}
    pr_url TEXT,                              -- GitHub PR URL
    pr_merged_at TEXT,                        -- merge 시각 (ISO)
    run_id INTEGER,                           -- 같은 batch run 묶음 (run_id 동일하면 같은 brief)
    requested_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    analyzed_at TEXT,
    approved_at TEXT,
    started_at TEXT,
    completed_at TEXT,
    approved_by TEXT,                         -- admin user_id (검토자 추적)
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_dev_req_status ON dev_requests(status, requested_at);
CREATE INDEX IF NOT EXISTS idx_dev_req_community ON dev_requests(community_id, status);
CREATE INDEX IF NOT EXISTS idx_dev_req_run ON dev_requests(run_id);

-- ── Dev runs (한 batch run 의 메타) ──
-- run_id 가 dev_requests.run_id 로 join. 라이브 출력 파일 경로 + 전체 상태 추적.
CREATE TABLE IF NOT EXISTS dev_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    status TEXT NOT NULL DEFAULT 'starting'
        CHECK(status IN ('starting','running','completed','failed','aborted')),
    branch_name TEXT NOT NULL,
    pr_url TEXT,
    pr_merged_at TEXT,
    log_path TEXT,                            -- tmux pipe-pane 출력 파일 경로
    request_count INTEGER NOT NULL DEFAULT 0,
    completed_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    started_by TEXT NOT NULL,                 -- admin user_id
    started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    completed_at TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_dev_runs_status ON dev_runs(status, started_at DESC);

-- 방문자 세션 추적 — 공개 랜딩/데모 페이지의 익명 방문을 sid(탭 세션) 단위로 묶어
-- "누가 어떤 페이지에 몇 초 머물렀나" 를 관리자 화면에서 본다. path·referrer·체류·UA·IP 만
-- (폼/키 입력 추적 아님). 조회는 admin 인증 필수. je-empty resume.iruyo.com 이식.
CREATE TABLE IF NOT EXISTS visit_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,        -- 사람이 읽는 시각 (UTC ISO)
    ts_epoch  REAL NOT NULL,        -- 정렬·구간계산용 epoch
    ip        TEXT,
    country   TEXT, city TEXT, asorg TEXT, asn TEXT,   -- 지오/ISP (프록시 헤더 있으면)
    ua        TEXT,
    path      TEXT,
    referrer  TEXT,
    is_owner  INTEGER DEFAULT 0,    -- 운영자(자기 IP) 방문 구분 (GLIMI_OWNER_IPS)
    sid       TEXT,                 -- sessionStorage UUID (탭 세션)
    dwell_ms  INTEGER               -- 체류시간 (이탈 비콘이 채움)
);
CREATE INDEX IF NOT EXISTS idx_visit_ip  ON visit_log(ip);
CREATE INDEX IF NOT EXISTS idx_visit_ts  ON visit_log(ts_epoch);
CREATE INDEX IF NOT EXISTS idx_visit_sid ON visit_log(sid);
"""


def init_db() -> None:
    """테이블 생성 (idempotent)."""
    Path(PLATFORM_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(PLATFORM_DB_PATH) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def conn() -> Iterator[sqlite3.Connection]:
    """평상시 사용하는 DB 연결. row_factory=sqlite3.Row."""
    init_db()
    c = sqlite3.connect(PLATFORM_DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys = ON")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
