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
