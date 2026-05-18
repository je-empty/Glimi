"""
community.db SQLite 데이터베이스 레이어
"""
import sqlite3
import json
import os
from datetime import datetime
from typing import Optional

from src import community
from src.core.timeutil import now_utc_iso  # DB 타임스탬프는 UTC aware 로 통일 (클라이언트가 로컬 변환)

DB_PATH = None  # community.get_db_path()로 동적 결정


def _get_db_path() -> str:
    global DB_PATH
    if DB_PATH:
        return DB_PATH
    DB_PATH = community.get_db_path()
    # 디렉토리 자동 생성 금지 — 삭제된 커뮤니티에 대한 stale API 폴링이 빈 디렉토리+DB 를
    # 부활시키던 버그 차단. 새 커뮤니티는 init_community() 가 선행 mkdir 함.
    if not os.path.exists(os.path.dirname(DB_PATH)):
        raise FileNotFoundError(f"community directory not found: {os.path.dirname(DB_PATH)}")
    return DB_PATH


_LOCK_MAX_ATTEMPTS = 6  # 0.1 + 0.2 + 0.4 + 0.8 + 1.6 + 3.2 ≈ 6.3 s 추가 대기


def _is_lock_err(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower()


def _retry_lock(call, *args, **kwargs):
    """database is locked 발생 시 지수 백오프 + 재시도. 다른 OperationalError 는 즉시 raise."""
    import time as _time
    for attempt in range(_LOCK_MAX_ATTEMPTS):
        try:
            return call(*args, **kwargs)
        except sqlite3.OperationalError as e:
            if not _is_lock_err(e) or attempt == _LOCK_MAX_ATTEMPTS - 1:
                raise
            _time.sleep(0.1 * (2 ** attempt))


class _RetryCursor(sqlite3.Cursor):
    """execute/executemany 가 'database is locked' 에 자동 재시도하는 커서."""

    def execute(self, sql, params=()):  # type: ignore[override]
        return _retry_lock(super().execute, sql, params)

    def executemany(self, sql, params):  # type: ignore[override]
        return _retry_lock(super().executemany, sql, params)


class _RetryConnection(sqlite3.Connection):
    """execute/executemany/commit 가 lock 에 자동 재시도하는 connection.

    busy_timeout 이 SQLite C 레벨에서 ~30s 양보 대기를 한 뒤에도 실패하면, 이 레이어가
    Python 단계에서 한 번 더 백오프 + 재시도. 다중 thread 동시 write (on_ready 채널 init
    + memory worker + supervisor + tutorial check) 동시성 충돌 대비.
    """

    def execute(self, sql, params=()):  # type: ignore[override]
        return _retry_lock(super().execute, sql, params)

    def executemany(self, sql, params):  # type: ignore[override]
        return _retry_lock(super().executemany, sql, params)

    def commit(self):  # type: ignore[override]
        return _retry_lock(super().commit)

    def cursor(self, factory=_RetryCursor):  # type: ignore[override]
        return super().cursor(factory)


def get_conn() -> sqlite3.Connection:
    # busy_timeout — 다른 writer 가 lock 잡고 있을 때 즉시 OperationalError 던지지 않고
    # 최대 30초 대기 (SQLite 엔진 단계). 그래도 실패하면 _RetryConnection 이 Python 단계에서
    # 추가 재시도 (~6초). 다중 thread (memory worker · supervisor · runtime · tutorial check)
    # 동시 write 시 'database is locked' 회귀 방지.
    # WAL + synchronous=NORMAL — WAL 권장 페어 (성능 ↑, FS crash 시점 1 트랜잭션만 잃을 수 있음).
    conn = sqlite3.connect(_get_db_path(), timeout=30.0, factory=_RetryConnection)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# Backward compat — 기존 호출부가 _retry_on_lock 으로 명시 wrapping 한 곳 보존.
def _retry_on_lock(func, *args, max_attempts: int = _LOCK_MAX_ATTEMPTS, **kwargs):
    import time as _time
    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)
        except sqlite3.OperationalError as e:
            if not _is_lock_err(e) or attempt == max_attempts - 1:
                raise
            _time.sleep(0.1 * (2 ** attempt))
    return None


def init_db():
    """DB 테이블 초기화"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL CHECK(type IN ('persona', 'mgr', 'creator', 'dev')),
            name TEXT NOT NULL,
            name_i18n TEXT,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'inactive', 'archived')),
            current_emotion TEXT DEFAULT '평온',
            emotion_intensity INTEGER DEFAULT 5 CHECK(emotion_intensity BETWEEN 1 AND 10),
            last_active DATETIME DEFAULT CURRENT_TIMESTAMP,
            birth_year INTEGER,
            age INTEGER,
            gender TEXT,
            mbti TEXT,
            enneagram TEXT,
            background TEXT,
            profile_image_filename TEXT,
            version INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS relationships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_a TEXT NOT NULL,
            agent_b TEXT NOT NULL,
            type TEXT NOT NULL,
            intimacy_score INTEGER DEFAULT 50 CHECK(intimacy_score BETWEEN 0 AND 100),
            dynamics TEXT,
            pet_name_a_to_b TEXT,
            pet_name_b_to_a TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(agent_a, agent_b)
        );

        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel TEXT NOT NULL,
            speaker TEXT NOT NULL,
            message TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            context_emotion TEXT
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            participants TEXT NOT NULL,
            description TEXT NOT NULL,
            impact TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_conv_channel ON conversations(channel);
        CREATE INDEX IF NOT EXISTS idx_conv_speaker ON conversations(speaker);
        CREATE INDEX IF NOT EXISTS idx_conv_timestamp ON conversations(timestamp);
        CREATE INDEX IF NOT EXISTS idx_rel_agents ON relationships(agent_a, agent_b);

        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            level INTEGER NOT NULL DEFAULT 1,       -- 1=L1 digest, 2=L2 chronicle, 3=L3 saga
            content TEXT NOT NULL,
            mem_type TEXT,                           -- event/fact/emotion/relationship
            related_entities TEXT,                   -- JSON array of entity names/ids referenced
            knows TEXT,                              -- JSON array of who directly knows (agent ids + "owner")
            importance INTEGER DEFAULT 5,            -- 1-10, higher = more important
            is_pinned INTEGER DEFAULT 0,             -- 1 = never evicted from injection
            parent_memory_id INTEGER,                -- L2/L3 points to constituent memory_ids (JSON in content not needed here)
            msg_id_from INTEGER,
            msg_id_to INTEGER,
            msg_count INTEGER DEFAULT 0,
            related_agent_id TEXT,                   -- legacy single-entity tag (kept for backward reads)
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_accessed_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_mem_agent ON memories(agent_id, channel, level);
        -- idx_mem_importance / idx_mem_pinned 는 _migrate_schema 에서 생성
        -- (신규 컬럼 의존이라 기존 DB에서 바로 만들면 NoSuchColumn 에러)

        -- ── 엔티티 인덱스 사실 저장소 (Layer 3 semantic facts) ──
        CREATE TABLE IF NOT EXISTS agent_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT NOT NULL,                  -- 이 지식을 갖고 있는 에이전트
            subject TEXT NOT NULL,                   -- 사실의 주어 (엔티티 이름 또는 id)
            predicate TEXT NOT NULL,                 -- 속성 (직업, 좋아하는음식, 말투 등)
            object TEXT NOT NULL,                    -- 값
            source_channel TEXT,                     -- 어디서 알게 됐는지
            source_memory_id INTEGER,                -- 원본 메모리 링크
            confidence REAL DEFAULT 1.0,             -- 0.0-1.0
            importance INTEGER DEFAULT 5,            -- 1-10
            valid_from DATETIME DEFAULT CURRENT_TIMESTAMP,
            valid_to DATETIME,                       -- NULL = 현재 유효, 값 있으면 supersede됨
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            last_accessed_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_facts_agent_subject ON agent_facts(agent_id, subject, predicate);
        CREATE INDEX IF NOT EXISTS idx_facts_valid ON agent_facts(agent_id, valid_to);

        -- ── 관계 변곡점 이력 (Layer 4 relationship delta log) ──
        CREATE TABLE IF NOT EXISTS relationship_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_a TEXT NOT NULL,
            agent_b TEXT NOT NULL,
            delta_type TEXT,                         -- intimacy / dynamics / speech_style
            from_state TEXT,
            to_state TEXT,
            reason TEXT,
            source_channel TEXT,
            source_memory_id INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_relhist_pair ON relationship_history(agent_a, agent_b);

        -- ── 에이전트 프로필 위성 테이블 (JSON blob) ──

        CREATE TABLE IF NOT EXISTS agent_personality (
            agent_id TEXT PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
            data TEXT NOT NULL  -- JSON object
        );

        CREATE TABLE IF NOT EXISTS agent_appearance (
            agent_id TEXT PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
            data TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_daily_life (
            agent_id TEXT PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
            data TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_speech (
            agent_id TEXT PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
            data TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_relationship_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            target_id TEXT NOT NULL,
            rel_type TEXT NOT NULL,
            duration TEXT,
            how_met TEXT,
            dynamics TEXT,
            pet_name TEXT,
            note TEXT,
            is_owner_relationship BOOLEAN DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS agent_config (
            agent_id TEXT PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
            config_json TEXT
        );

        -- ── 오너 테이블 (N명 지원) ──

        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            birth_year INTEGER,
            age INTEGER,
            mbti TEXT,
            enneagram TEXT,
            background TEXT,
            personality TEXT,
            appearance TEXT,
            daily_life TEXT,
            speech TEXT,
            relationships_summary TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        -- ── 메타 설정 ──

        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );

        -- ── 채널 참가자 ──

        CREATE TABLE IF NOT EXISTS channels (
            channel TEXT PRIMARY KEY,
            participants TEXT NOT NULL DEFAULT '[]',  -- JSON array of agent IDs
            status TEXT NOT NULL DEFAULT 'idle',  -- idle, running, stopped
            max_turns INTEGER DEFAULT 0,
            current_turn INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        -- ── 휴지통 ──

        CREATE TABLE IF NOT EXISTS trash (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_type TEXT NOT NULL,  -- 'message', 'channel', 'memory'
            original_table TEXT NOT NULL,
            original_id INTEGER,
            channel TEXT,
            data TEXT NOT NULL,  -- JSON blob of deleted row(s)
            deleted_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_trash_type ON trash(item_type, channel);

        -- ── 도전과제 (유저 진척도 추적) ──
        -- key 는 src/achievements/definitions.py 에 정의된 식별자와 1:1 매칭.
        -- state: locked(전제조건 미달) / unlocked(진행 가능) / done(완료)
        -- progress_data: JSON blob — e.g. {"talked_to": ["은하윤","수민"]} (진행도 추적용)
        CREATE TABLE IF NOT EXISTS achievements (
            user_id TEXT NOT NULL,
            key TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'locked',
            progress_data TEXT,
            unlocked_at DATETIME,
            completed_at DATETIME,
            PRIMARY KEY (user_id, key)
        );
        CREATE INDEX IF NOT EXISTS idx_ach_user_state ON achievements(user_id, state);

        -- 참고: dev_requests / dev_runs 는 platform.db 글로벌 테이블 (data/platform.db).
        -- src/platform/db.py 의 SCHEMA 에 정의됨. 이전 community-local 테이블은 사용 안 함.
    """)
    conn.commit()
    conn.close()
    _migrate_schema()
    _migrate_satellite_tables()
    print("[DB] 초기��� 완료")


# === Agent CRUD ===

def register_agent(agent_id: str, agent_type: str, name: str):
    conn = get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO agents (id, type, name) VALUES (?, ?, ?)",
        (agent_id, agent_type, name)
    )
    conn.commit()
    conn.close()


def get_agent_model_override(agent_id: str) -> Optional[str]:
    """에이전트 model override — agent_config.config_json['model'].
    대시보드에서 모델 전환 시 저장되고, runtime 이 호출 때마다 조회 → 동적 전환."""
    import json as _json
    conn = get_conn()
    row = conn.execute(
        "SELECT config_json FROM agent_config WHERE agent_id = ?", (agent_id,)
    ).fetchone()
    conn.close()
    if not row or not row["config_json"]:
        return None
    try:
        cfg = _json.loads(row["config_json"])
        if isinstance(cfg, dict):
            m = cfg.get("model")
            return m if m else None
    except Exception:
        pass
    return None


def set_agent_model_override(agent_id: str, model: Optional[str]) -> bool:
    """model override 저장/해제. 빈 값이면 config 에서 'model' 키 제거.
    existing config_json 의 다른 키는 보존."""
    import json as _json
    conn = get_conn()
    exists = conn.execute("SELECT 1 FROM agents WHERE id = ?", (agent_id,)).fetchone()
    if not exists:
        conn.close()
        return False
    row = conn.execute(
        "SELECT config_json FROM agent_config WHERE agent_id = ?", (agent_id,)
    ).fetchone()
    cfg: dict = {}
    if row and row["config_json"]:
        try:
            cfg = _json.loads(row["config_json"]) or {}
            if not isinstance(cfg, dict):
                cfg = {}
        except Exception:
            cfg = {}
    val = (model or "").strip()
    if val:
        cfg["model"] = val
    else:
        cfg.pop("model", None)
    conn.execute(
        "INSERT OR REPLACE INTO agent_config (agent_id, config_json) VALUES (?, ?)",
        (agent_id, _json.dumps(cfg, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()
    return True


def get_agent(agent_id: str) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def mark_meta_breached(agent_id: str) -> dict:
    """persona 가 메타 자각 발화 → 잠금. **소프트 락**: 데이터 보존, 상태값으로만 관리.

    이전 동작 (hard delete) 은 비가역. 사용자가 부활 요청해도 복원 불가능했음.
    이제 데이터는 그대로 두고 status + meta_breached_at 만 set — 유나의 `revive_persona`
    도구로 되살릴 수 있음. self_aware=1 로 부활하면 자각 유지하며 대화 가능.

    리턴: {messages, memories, facts, channels} — 영향 받은 (보존된) 카운트.
    """
    from datetime import datetime as _dt
    conn = get_conn()
    now = _dt.now().isoformat()
    conn.execute(
        "UPDATE agents SET meta_breached_at = ?, status = 'inactive' WHERE id = ?",
        (now, agent_id),
    )
    # 영향 카운트만 — 실제 삭제 X
    chans = [r["channel"] for r in conn.execute(
        "SELECT DISTINCT channel FROM conversations WHERE speaker = ?", (agent_id,)
    ).fetchall()]
    msg_count = conn.execute(
        "SELECT COUNT(*) c FROM conversations WHERE speaker = ?", (agent_id,)
    ).fetchone()["c"]
    mem_count = conn.execute(
        "SELECT COUNT(*) c FROM memories WHERE agent_id = ?", (agent_id,)
    ).fetchone()["c"]
    fact_count = conn.execute(
        "SELECT COUNT(*) c FROM agent_facts WHERE agent_id = ?", (agent_id,)
    ).fetchone()["c"]
    conn.commit()
    conn.close()
    return {
        "messages": msg_count,
        "memories": mem_count,
        "facts": fact_count,
        "channels": chans,
        # 호환성 — old caller 가 deleted_* 키 봄
        "deleted_conversations": 0,
        "deleted_memories": 0,
        "deleted_facts": 0,
    }


def revive_meta_breached(agent_id: str) -> dict:
    """메타 박살 페르소나 부활 — self_aware=1 로 set 해서 자각 유지 + 재박살 방지.

    리턴: {restored: bool, was_breached: bool}.
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT meta_breached_at FROM agents WHERE id = ?", (agent_id,)
    ).fetchone()
    if not row:
        conn.close()
        return {"restored": False, "was_breached": False, "reason": "agent not found"}
    was_breached = bool(row["meta_breached_at"])
    conn.execute(
        "UPDATE agents SET meta_breached_at = NULL, status = 'active', self_aware = 1 WHERE id = ?",
        (agent_id,),
    )
    conn.commit()
    conn.close()
    return {"restored": True, "was_breached": was_breached}


def is_meta_breached(agent_id: str) -> bool:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT meta_breached_at FROM agents WHERE id = ?", (agent_id,)
        ).fetchone()
    except Exception:
        return False
    finally:
        conn.close()
    return bool(row and row["meta_breached_at"])


def update_emotion(agent_id: str, emotion: str, intensity: int):
    conn = get_conn()
    conn.execute(
        "UPDATE agents SET current_emotion = ?, emotion_intensity = ?, last_active = ? WHERE id = ?",
        (emotion, intensity, now_utc_iso(), agent_id)
    )
    conn.commit()
    conn.close()


def list_agents(agent_type: Optional[str] = None) -> list[dict]:
    conn = get_conn()
    if agent_type:
        rows = conn.execute("SELECT * FROM agents WHERE type = ?", (agent_type,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM agents").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# === Relationship CRUD ===

# 친밀도 (= 호감도) 스케일 가이드 — UI 표시 + LLM 프롬프트 양쪽에서 일관되게 사용.
# 0~100 INTEGER. 0 = 원수. 100 = 절대 신뢰.
#   0     원수      ─ 서로 못 잡아먹어 안달, 상대 발화 자체가 자극
#   1-19  적대      ─ 갈등 중, 비꼬거나 무시. 회복하려면 사건 필요
#   20-39 어색      ─ 거리감, 의례적 인사. **초면 default 영역**
#   40-59 친구      ─ 일상적 대화 OK, 상대 안부에 관심
#   60-79 친한 친구  ─ 사적인 고민·취향 공유, 농담 자연스러움
#   80-99 가족·절친  ─ 무조건적 신뢰, 작은 충돌도 큰 영향 X
#   100   연인급/한 몸 ─ 절대 신뢰, 운명 공동체 톤
#
# default 30 (어색~친구 사이) — 처음 만난 페르소나끼리는 호의적이지만 거리감 있는 상태.
# 이전 default 50 은 "이미 친구" 라 LLM 이 처음부터 너무 친하게 굴어서 진화감 없었음 (회귀 fix 2026-04-30).
INTIMACY_SCALE_DEFAULT = 30
INTIMACY_SCALE_DOC = (
    "친밀도 0~100. "
    "0=원수 / 1-19=적대 / 20-39=어색 / 40-59=친구 / 60-79=친한 친구 / "
    "80-99=가족·절친 / 100=연인. 초면은 30 default."
)


def add_relationship(agent_a: str, agent_b: str, rel_type: str, intimacy: int = INTIMACY_SCALE_DEFAULT, dynamics: str = ""):
    conn = get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO relationships (agent_a, agent_b, type, intimacy_score, dynamics, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (agent_a, agent_b, rel_type, intimacy, dynamics, now_utc_iso())
    )
    conn.commit()
    conn.close()


def get_relationship(agent_a: str, agent_b: str) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM relationships WHERE agent_a = ? AND agent_b = ?",
        (agent_a, agent_b)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_relationships(agent_id: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM relationships WHERE agent_a = ? OR agent_b = ?",
        (agent_id, agent_id)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_intimacy(agent_a: str, agent_b: str, delta: int):
    conn = get_conn()
    conn.execute(
        """UPDATE relationships 
           SET intimacy_score = MIN(100, MAX(0, intimacy_score + ?)), updated_at = ?
           WHERE agent_a = ? AND agent_b = ?""",
        (delta, now_utc_iso(), agent_a, agent_b)
    )
    conn.commit()
    conn.close()


# === Conversation Log ===

#  ── Message event hooks ──
# 외부 구독자가 메시지 로깅 시점을 훅킹할 수 있는 경량 pub/sub.
# 주 사용처: achievements 엔진 (진척도 체크). 실패해도 로깅은 계속 진행.
_message_hooks: list = []


def add_message_hook(fn):
    """log_message 이후에 호출될 콜백 등록. 시그니처: fn(channel, speaker, message)."""
    if fn not in _message_hooks:
        _message_hooks.append(fn)


def log_message(channel: str, speaker: str, message: str, emotion: str = None):
    conn = get_conn()
    # 중복 방지 — 같은 채널·스피커·메시지가 최근 30초 내 이미 있으면 skip.
    # 유나/하나가 tool chain 에서 여러 turn 에 걸쳐 같은 메시지를 재생성하는 케이스 (QA 회귀:
    # "#dm-김지아 열리면 바로 말 걸어봐" 같은 timestamp 에 2번 log). streaming loop 내부 dedupe 는
    # 같은 턴만 막음 → DB 레벨에서 turn-간 dedupe 추가.
    try:
        dup = conn.execute(
            "SELECT id FROM conversations WHERE channel=? AND speaker=? AND message=? "
            "AND datetime(timestamp) > datetime('now', '-30 seconds') LIMIT 1",
            (channel, speaker, message),
        ).fetchone()
        if dup:
            conn.close()
            return
    except Exception:
        pass
    conn.execute(
        "INSERT INTO conversations (channel, speaker, message, context_emotion) VALUES (?, ?, ?, ?)",
        (channel, speaker, message, emotion)
    )
    # 에이전트 발화 시 last_active 갱신
    if speaker.startswith("agent-"):
        conn.execute(
            "UPDATE agents SET last_active = ? WHERE id = ?",
            (now_utc_iso(), speaker)
        )
    conn.commit()
    conn.close()
    # 훅 실행 — 실패해도 원 로깅 동작엔 영향 없게 감쌈
    for _hook in _message_hooks:
        try:
            _hook(channel, speaker, message)
        except Exception as _e:
            print(f"[db.log_message hook] {_hook.__name__}: {_e}")


def get_recent_messages(channel: str, limit: int = 20) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM conversations WHERE channel = ? ORDER BY timestamp DESC LIMIT ?",
        (channel, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def get_conversation_history(channel: str, speaker: Optional[str] = None, limit: int = 50) -> list[dict]:
    conn = get_conn()
    if speaker:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE channel = ? AND speaker = ? ORDER BY timestamp DESC LIMIT ?",
            (channel, speaker, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE channel = ? ORDER BY timestamp DESC LIMIT ?",
            (channel, limit)
        ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


# === Events ===

def log_event(event_type: str, participants: list[str], description: str, impact: str = ""):
    conn = get_conn()
    conn.execute(
        "INSERT INTO events (event_type, participants, description, impact) VALUES (?, ?, ?, ?)",
        (event_type, ",".join(participants), description, impact)
    )
    conn.commit()
    conn.close()


def get_events(participant: Optional[str] = None, limit: int = 20) -> list[dict]:
    conn = get_conn()
    if participant:
        rows = conn.execute(
            "SELECT * FROM events WHERE participants LIKE ? ORDER BY timestamp DESC LIMIT ?",
            (f"%{participant}%", limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# === Memory ===

def add_memory(agent_id: str, channel: str, level: int, content: str,
               msg_id_from: int = None, msg_id_to: int = None, msg_count: int = 0,
               mem_type: str = None,
               related_entities: list = None,
               knows: list = None,
               importance: int = 5,
               is_pinned: bool = False,
               parent_memory_id: int = None,
               related_agent_id: str = None) -> int:
    """메모리 저장. related_entities / knows 는 리스트로 받아서 JSON 직렬화.
    반환: 생성된 row id."""
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO memories
           (agent_id, channel, level, content, mem_type,
            related_entities, knows, importance, is_pinned, parent_memory_id,
            msg_id_from, msg_id_to, msg_count, related_agent_id, last_accessed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (agent_id, channel, level, content, mem_type,
         json.dumps(related_entities, ensure_ascii=False) if related_entities else None,
         json.dumps(knows, ensure_ascii=False) if knows else None,
         max(1, min(10, int(importance))),
         1 if is_pinned else 0,
         parent_memory_id,
         msg_id_from, msg_id_to, msg_count, related_agent_id)
    )
    mem_id = cur.lastrowid
    conn.commit()
    conn.close()
    return mem_id


def _parse_json_list(s: Optional[str]) -> list:
    if not s:
        return []
    try:
        v = json.loads(s)
        return v if isinstance(v, list) else []
    except Exception:
        return []


def _hydrate_memory(row: dict) -> dict:
    """row → JSON 필드 리스트로 파싱"""
    row = dict(row)
    row["related_entities"] = _parse_json_list(row.get("related_entities"))
    row["knows"] = _parse_json_list(row.get("knows"))
    return row


def get_memories(agent_id: str, channel: str, level: int, limit: int = 10) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM memories WHERE agent_id = ? AND channel = ? AND level = ? ORDER BY created_at DESC LIMIT ?",
        (agent_id, channel, level, limit)
    ).fetchall()
    conn.close()
    return [_hydrate_memory(r) for r in reversed(rows)]


def get_latest_memory(agent_id: str, channel: str, level: int) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM memories WHERE agent_id = ? AND channel = ? AND level = ? ORDER BY msg_id_to DESC LIMIT 1",
        (agent_id, channel, level)
    ).fetchone()
    conn.close()
    return _hydrate_memory(row) if row else None


def count_memories(agent_id: str, channel: str, level: int, after_id: Optional[int] = None) -> int:
    conn = get_conn()
    if after_id:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM memories WHERE agent_id = ? AND channel = ? AND level = ? AND id > ?",
            (agent_id, channel, level, after_id)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM memories WHERE agent_id = ? AND channel = ? AND level = ?",
            (agent_id, channel, level)
        ).fetchone()
    conn.close()
    return row["cnt"]


# === Memory — cross-layer / retrieval helpers ===

def get_pinned_memories(agent_id: str, limit: int = 20) -> list[dict]:
    """is_pinned=1 모두 (항상 주입)"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM memories WHERE agent_id = ? AND is_pinned = 1 "
        "ORDER BY importance DESC, created_at DESC LIMIT ?",
        (agent_id, limit)
    ).fetchall()
    conn.close()
    return [_hydrate_memory(r) for r in rows]


def set_pin(memory_id: int, pinned: bool = True):
    conn = get_conn()
    conn.execute("UPDATE memories SET is_pinned = ? WHERE id = ?",
                 (1 if pinned else 0, memory_id))
    conn.commit()
    conn.close()


def get_memories_by_entity(agent_id: str, entity: str, limit: int = 10,
                           min_importance: int = 0) -> list[dict]:
    """related_entities 에 entity가 포함된 메모리 — importance DESC 순"""
    conn = get_conn()
    # JSON 배열 LIKE 매칭 — 간단하고 SQLite 3.8+ 호환
    like_pattern = f'%"{entity}"%'
    rows = conn.execute(
        "SELECT * FROM memories WHERE agent_id = ? AND related_entities LIKE ? "
        "AND importance >= ? ORDER BY importance DESC, created_at DESC LIMIT ?",
        (agent_id, like_pattern, min_importance, limit)
    ).fetchall()
    conn.close()
    return [_hydrate_memory(r) for r in rows]


def touch_memory_access(memory_ids: list[int]):
    """조회된 메모리들의 last_accessed_at 갱신 (recency decay 반영용)"""
    if not memory_ids:
        return
    conn = get_conn()
    placeholders = ",".join("?" * len(memory_ids))
    conn.execute(
        f"UPDATE memories SET last_accessed_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})",
        memory_ids
    )
    conn.commit()
    conn.close()


# === Agent Facts (Layer 3) ===

# predicate canonicalization — 한글/영어 변형을 한 form 으로 통일.
# 같은 의미 다른 표현이 다른 row 로 누적되는 회귀 방지.
_PREDICATE_CANONICAL = {
    # hobby
    "hobbies": "hobby", "interests": "hobby", "interest": "hobby",
    "취미": "hobby", "관심사": "hobby", "취미·관심사": "hobby",
    # likes / dislikes
    "liked_things": "likes", "preferences": "likes", "preference": "likes",
    "선호": "likes", "좋아하는것": "likes", "좋아하는 것": "likes", "좋아함": "likes",
    "hates": "dislikes", "disliked_things": "dislikes",
    "싫어하는것": "dislikes", "싫어하는 것": "dislikes", "싫어함": "dislikes",
    # personality
    "personality_traits": "personality", "traits": "personality", "character": "personality",
    "성격": "personality", "성향": "personality", "특징": "personality",
    # speech_style
    "speech": "speech_style", "talking_style": "speech_style",
    "말투": "speech_style", "말투특징": "speech_style",
    # occupation / education
    "job": "occupation", "work": "occupation", "profession": "occupation",
    "직업": "occupation", "일": "occupation",
    "school": "education", "schooling": "education",
    "학교": "education", "학력": "education", "교육": "education",
    "graduate_school_plans": "education_plan", "future_plan": "education_plan",
    "진학계획": "education_plan", "대학원계획": "education_plan", "대학원 계획": "education_plan",
    "education": "education",  # explicit canonical
    # location / age / gender / family
    "거주지": "location", "사는곳": "location", "사는 곳": "location", "지역": "location",
    "생년월일": "birth", "생일": "birth",
    "나이": "age", "연령": "age",
    "성별": "gender",
    "가족관계": "family", "가족": "family",
    # mbti
    "MBTI": "mbti", "엠비티아이": "mbti", "mbti_type": "mbti",
    # 기타 자주 보이는 변형
    "preferred_friend_type": "preferred_friend_type",
    "원하는친구특성": "preferred_friend_type", "원하는 친구 유형": "preferred_friend_type",
    "선호하는캐릭터유형": "preferred_friend_type", "원하는친구유형": "preferred_friend_type",
}


def _canonicalize_predicate(pred: str) -> str:
    """동의어 predicate 를 canonical form 으로 매핑. unknown 은 그대로 (단, whitespace trim)."""
    p = (pred or "").strip()
    if not p:
        return p
    if p in _PREDICATE_CANONICAL:
        return _PREDICATE_CANONICAL[p]
    pl = p.lower()
    if pl in _PREDICATE_CANONICAL:
        return _PREDICATE_CANONICAL[pl]
    return p


def _retire_currently_doing(conn, agent_id: str, subject: str,
                             source_channel: Optional[str] = None,
                             source_memory_id: Optional[int] = None) -> Optional[int]:
    """active currently_doing 을 last_activity 로 이전. 처리할 게 없으면 None.

    동작:
      1. (subject) 의 valid currently_doing 찾기 → valid_to 닫음
      2. 그 object 를 last_activity 로 INSERT (시작 시각 metadata 포함)
      3. 기존 last_activity 가 있으면 같이 supersede

    호출자가 conn.commit() 책임. 트랜잭션 일관성 위해 여기선 commit 안 함.
    """
    existing = conn.execute(
        "SELECT id, object, created_at FROM agent_facts "
        "WHERE agent_id = ? AND subject = ? AND predicate = 'currently_doing' "
        "AND valid_to IS NULL ORDER BY id DESC LIMIT 1",
        (agent_id, subject)
    ).fetchone()
    if not existing:
        return None
    # currently_doing 닫기
    conn.execute("UPDATE agent_facts SET valid_to = CURRENT_TIMESTAMP WHERE id = ?",
                 (existing["id"],))
    # 이전 last_activity 도 supersede
    prev_last = conn.execute(
        "SELECT id FROM agent_facts WHERE agent_id = ? AND subject = ? "
        "AND predicate = 'last_activity' AND valid_to IS NULL ORDER BY id DESC LIMIT 1",
        (agent_id, subject)
    ).fetchone()
    if prev_last:
        conn.execute("UPDATE agent_facts SET valid_to = CURRENT_TIMESTAMP WHERE id = ?",
                     (prev_last["id"],))
    started = (existing["created_at"] or "")[:16]
    obj = f"{existing['object']} (~{started} 시작)" if started else existing["object"]
    cur = conn.execute(
        """INSERT INTO agent_facts
           (agent_id, subject, predicate, object, source_channel, source_memory_id,
            confidence, importance, last_accessed_at)
           VALUES (?, ?, 'last_activity', ?, ?, ?, 1.0, 4, CURRENT_TIMESTAMP)""",
        (agent_id, subject, obj, source_channel, source_memory_id)
    )
    return cur.lastrowid


def add_fact(agent_id: str, subject: str, predicate: str, object_value: str,
             source_channel: str = None, source_memory_id: int = None,
             confidence: float = 1.0, importance: int = 5) -> int:
    """새 fact 저장. 기존 동일 (subject, predicate) 있으면 valid_to 닫고 새로 INSERT (supersession).
    같은 object면 no-op. predicate 는 canonical form 으로 자동 정규화됨.

    특수 predicate:
      - current_action_ended: 저장하지 않고 routing 만 — active currently_doing 을
        last_activity 로 이전. object_value 는 무시 (현재 활동 무엇이었든 종료).
      - currently_doing: supersession 시 옛 활동을 last_activity 로 자동 백업.
    """
    predicate = _canonicalize_predicate(predicate)
    conn = get_conn()

    # SPECIAL: current_action_ended — 의사-fact, 저장하지 않음. 활동 종료 routing 만.
    if predicate == "current_action_ended":
        new_id = _retire_currently_doing(conn, agent_id, subject,
                                          source_channel, source_memory_id)
        conn.commit()
        conn.close()
        return new_id or 0

    # 기존 valid 체크
    existing = conn.execute(
        "SELECT id, object FROM agent_facts WHERE agent_id = ? AND subject = ? AND predicate = ? "
        "AND valid_to IS NULL ORDER BY id DESC LIMIT 1",
        (agent_id, subject, predicate)
    ).fetchone()
    if existing:
        if existing["object"] == object_value:
            conn.close()
            return existing["id"]
        # SPECIAL: currently_doing 의 supersession 은 _retire 헬퍼로 (last_activity 자동 백업).
        # 다른 predicate 는 단순 supersession.
        if predicate == "currently_doing":
            _retire_currently_doing(conn, agent_id, subject, source_channel, source_memory_id)
        else:
            conn.execute("UPDATE agent_facts SET valid_to = CURRENT_TIMESTAMP WHERE id = ?",
                         (existing["id"],))
    cur = conn.execute(
        """INSERT INTO agent_facts
           (agent_id, subject, predicate, object, source_channel, source_memory_id,
            confidence, importance, last_accessed_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (agent_id, subject, predicate, object_value, source_channel, source_memory_id,
         float(confidence), max(1, min(10, int(importance))))
    )
    fid = cur.lastrowid
    conn.commit()
    conn.close()
    return fid


def get_facts(agent_id: str, subject: str = None, include_invalid: bool = False,
              limit: int = 50) -> list[dict]:
    conn = get_conn()
    q = "SELECT * FROM agent_facts WHERE agent_id = ?"
    args = [agent_id]
    if subject:
        q += " AND subject = ?"
        args.append(subject)
    if not include_invalid:
        q += " AND valid_to IS NULL"
    q += " ORDER BY importance DESC, created_at DESC LIMIT ?"
    args.append(limit)
    rows = conn.execute(q, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_facts_for_agent(agent_id: str, include_invalid: bool = False) -> list[dict]:
    return get_facts(agent_id, subject=None, include_invalid=include_invalid, limit=10000)


# === Relationship History (Layer 4) ===

def add_relationship_delta(agent_a: str, agent_b: str, delta_type: str,
                           from_state: str = None, to_state: str = None,
                           reason: str = None, source_channel: str = None,
                           source_memory_id: int = None) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO relationship_history
           (agent_a, agent_b, delta_type, from_state, to_state, reason, source_channel, source_memory_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (agent_a, agent_b, delta_type, from_state, to_state, reason, source_channel, source_memory_id)
    )
    hid = cur.lastrowid
    conn.commit()
    conn.close()
    return hid


def get_relationship_history(agent_a: str, agent_b: str, limit: int = 20) -> list[dict]:
    conn = get_conn()
    # 양방향
    rows = conn.execute(
        "SELECT * FROM relationship_history WHERE (agent_a = ? AND agent_b = ?) "
        "OR (agent_a = ? AND agent_b = ?) ORDER BY created_at DESC LIMIT ?",
        (agent_a, agent_b, agent_b, agent_a, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_messages(channel: str) -> list[dict]:
    """채널의 전체 메시지를 시간순으로 가져오기 (디코 복구용)"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM conversations WHERE channel = ? ORDER BY id ASC",
        (channel,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_messages_by_range(channel: str, after_id: int, limit: int = 15) -> list[dict]:
    """특정 ID 이후의 메시지 가져오기"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM conversations WHERE channel = ? AND id > ? ORDER BY id ASC LIMIT ?",
        (channel, after_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def count_messages_after(channel: str, after_id: int) -> int:
    conn = get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM conversations WHERE channel = ? AND id > ?",
        (channel, after_id)
    ).fetchone()
    conn.close()
    return row["cnt"]


def get_latest_l2_memory_id(agent_id: str, channel: str) -> Optional[int]:
    """L2로 롤업된 마지막 L1 메모리 ID 추적"""
    conn = get_conn()
    row = conn.execute(
        "SELECT MAX(msg_id_to) as last_id FROM memories WHERE agent_id = ? AND channel = ? AND level = 2",
        (agent_id, channel)
    ).fetchone()
    conn.close()
    return row["last_id"] if row and row["last_id"] else None


# ══════════════════════════════════════════════════════
# 채널 참가자 관리
# ══════════════════════════════════════════════════════

def get_channel_participants(channel: str) -> list[str]:
    """채널 참가자 ID 리스트 반환"""
    conn = get_conn()
    row = conn.execute("SELECT participants FROM channels WHERE channel = ?", (channel,)).fetchone()
    conn.close()
    if not row:
        return []
    try:
        return json.loads(row["participants"])
    except (json.JSONDecodeError, TypeError):
        return []


def set_channel_participants(channel: str, agent_ids: list[str]):
    """채널 참가자 설정 (덮어쓰기)"""
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO channels (channel, participants) VALUES (?, ?)",
        (channel, json.dumps(agent_ids))
    )
    conn.commit()
    conn.close()


def add_channel_participant(channel: str, agent_id: str):
    """채널에 참가자 추가"""
    current = get_channel_participants(channel)
    if agent_id not in current:
        current.append(agent_id)
        set_channel_participants(channel, current)


def remove_channel_participant(channel: str, agent_id: str):
    """채널에서 참가자 제거"""
    current = get_channel_participants(channel)
    if agent_id in current:
        current.remove(agent_id)
        set_channel_participants(channel, current)


def is_channel_participant(channel: str, agent_id: str) -> bool:
    """에이전트가 해당 채널의 참가자인지"""
    return agent_id in get_channel_participants(channel)


def set_channel_status(channel: str, status: str, max_turns: int = 0):
    """채널 대화 상태 설정 + supervisor pool 동기화 트리거."""
    conn = get_conn()
    conn.execute(
        "UPDATE channels SET status=?, max_turns=?, current_turn=0 WHERE channel=?",
        (status, max_turns, channel)
    )
    conn.commit()
    conn.close()
    # channel running/idle 변화는 ChatSupervisor 인스턴스 생성/제거 트리거
    # (지연 실행 — 이벤트 루프 안에서만 유효, 없으면 조용히 패스)
    try:
        import asyncio as _aio
        from src.supervisors.base import pool as _pool
        loop = _aio.get_event_loop()
        if loop.is_running():
            loop.create_task(_pool.sync())
    except Exception:
        pass


def get_channel_status(channel: str) -> dict:
    """채널 상태 반환"""
    conn = get_conn()
    row = conn.execute("SELECT status, max_turns, current_turn FROM channels WHERE channel=?", (channel,)).fetchone()
    conn.close()
    if not row:
        return {"status": "idle", "max_turns": 0, "current_turn": 0}
    return {"status": row["status"], "max_turns": row["max_turns"], "current_turn": row["current_turn"]}


def increment_channel_turn(channel: str) -> int:
    """채널 턴 증가, 현재 턴 반환"""
    conn = get_conn()
    conn.execute("UPDATE channels SET current_turn = current_turn + 1 WHERE channel=?", (channel,))
    conn.commit()
    row = conn.execute("SELECT current_turn FROM channels WHERE channel=?", (channel,)).fetchone()
    conn.close()
    return row["current_turn"] if row else 0


if __name__ == "__main__":
    init_db()


# === 유나 관리자 조회 ===

def get_channel_overview() -> list[dict]:
    """전체 채널 활동 현황 — channels 테이블 + conversations 통계 병합"""
    conn = get_conn()
    # 대화 통계
    conv_rows = conn.execute("""
        SELECT channel,
               COUNT(*) as msg_count,
               COUNT(DISTINCT speaker) as speakers,
               MAX(timestamp) as last_active,
               MIN(timestamp) as first_active
        FROM conversations
        GROUP BY channel
        ORDER BY last_active DESC
    """).fetchall()
    conv_data = {r["channel"]: dict(r) for r in conv_rows}

    # channels 테이블 (대화 없는 채널도 포함)
    ch_rows = conn.execute("SELECT channel, participants, created_at FROM channels").fetchall()
    conn.close()

    result = {}
    for r in ch_rows:
        ch = r["channel"]
        result[ch] = conv_data.get(ch, {
            "channel": ch, "msg_count": 0, "speakers": 0,
            "last_active": None, "first_active": None,
        })
        result[ch]["channel"] = ch
        try:
            result[ch]["participants"] = json.loads(r["participants"])
        except (json.JSONDecodeError, TypeError):
            result[ch]["participants"] = []

    # conversations에만 있고 channels에 없는 채널
    for ch, data in conv_data.items():
        if ch not in result:
            result[ch] = data
            result[ch]["participants"] = []

    return sorted(result.values(), key=lambda x: x.get("last_active") or "", reverse=True)


def search_messages(keyword: str, limit: int = 20) -> list[dict]:
    """전체 채널 메시지 키워드 검색"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT channel, speaker, message, timestamp
           FROM conversations
           WHERE message LIKE ?
           ORDER BY timestamp DESC LIMIT ?""",
        (f"%{keyword}%", limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def get_agent_messages(agent_id: str, limit: int = 20) -> list[dict]:
    """특정 에이전트의 전체 발화 이력 (채널 무관)"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT channel, speaker, message, timestamp, context_emotion
           FROM conversations
           WHERE speaker = ?
           ORDER BY timestamp DESC LIMIT ?""",
        (agent_id, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


# === 유나 관리자 삭제 ===

def delete_channel_data(channel: str) -> dict:
    """채널의 모든 대화 + 메모리 삭제"""
    conn = get_conn()
    msg_count = conn.execute("SELECT COUNT(*) as c FROM conversations WHERE channel = ?", (channel,)).fetchone()["c"]
    mem_count = conn.execute("SELECT COUNT(*) as c FROM memories WHERE channel = ?", (channel,)).fetchone()["c"]
    conn.execute("DELETE FROM conversations WHERE channel = ?", (channel,))
    conn.execute("DELETE FROM memories WHERE channel = ?", (channel,))
    conn.commit()
    conn.close()
    return {"messages_deleted": msg_count, "memories_deleted": mem_count}


def delete_messages_by_speaker(channel: str, speaker_id: str) -> int:
    """특정 채널에서 특정 화자의 메시지만 삭제"""
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) as c FROM conversations WHERE channel = ? AND speaker = ?", (channel, speaker_id)).fetchone()["c"]
    conn.execute("DELETE FROM conversations WHERE channel = ? AND speaker = ?", (channel, speaker_id))
    conn.commit()
    conn.close()
    return count


def delete_messages_by_keyword(keyword: str, channel: str = None) -> int:
    """키워드 포함 메시지 삭제 (채널 지정 가능)"""
    conn = get_conn()
    if channel:
        count = conn.execute("SELECT COUNT(*) as c FROM conversations WHERE channel = ? AND message LIKE ?", (channel, f"%{keyword}%")).fetchone()["c"]
        conn.execute("DELETE FROM conversations WHERE channel = ? AND message LIKE ?", (channel, f"%{keyword}%"))
    else:
        count = conn.execute("SELECT COUNT(*) as c FROM conversations WHERE message LIKE ?", (f"%{keyword}%",)).fetchone()["c"]
        conn.execute("DELETE FROM conversations WHERE message LIKE ?", (f"%{keyword}%",))
    conn.commit()
    conn.close()
    return count


def get_agent_by_name(name: str) -> Optional[dict]:
    """이름으로 에이전트 조회"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM agents WHERE name = ?", (name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def _migrate_schema():
    """기존 DB 스키마를 최신 형식으로 마이그레이션"""
    conn = get_conn()

    # memories 테이블 신규 컬럼 추가 (Layer 2 확장: entity/knows/importance/pinned/parent)
    mem_cols = [r["name"] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
    mem_additions = {
        "mem_type": "TEXT",
        "related_entities": "TEXT",                 # JSON array
        "knows": "TEXT",                            # JSON array
        "importance": "INTEGER DEFAULT 5",
        "is_pinned": "INTEGER DEFAULT 0",
        "parent_memory_id": "INTEGER",
        "related_agent_id": "TEXT",
        "last_accessed_at": "DATETIME",
    }
    for col, col_type in mem_additions.items():
        if col not in mem_cols:
            conn.execute(f"ALTER TABLE memories ADD COLUMN {col} {col_type}")
            print(f"[DB] memories.{col} 추가")

    # 기존 rows 백필: related_entities (related_agent_id 기반) + knows (channel 기반)
    _backfill_memory_columns(conn)

    # 신규 테이블: agent_facts, relationship_history (IF NOT EXISTS 로 이미 init_db 에서 처리됨)
    # 여기서는 인덱스만 추가 보장
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_importance ON memories(agent_id, importance DESC, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_pinned ON memories(agent_id, is_pinned)")
    except sqlite3.OperationalError:
        pass

    # relationships 테이블 별칭 컬럼 추가
    rel_cols = [r["name"] for r in conn.execute("PRAGMA table_info(relationships)").fetchall()]
    for col in ("pet_name_a_to_b", "pet_name_b_to_a"):
        if col not in rel_cols:
            conn.execute(f"ALTER TABLE relationships ADD COLUMN {col} TEXT")
            print(f"[DB] relationships.{col} 추가")

    # agents 테이블 프로필 컬럼 추가
    agent_cols = [r["name"] for r in conn.execute("PRAGMA table_info(agents)").fetchall()]

    # 레거시: avatar_filename → profile_image_filename 자동 rename (1회성)
    if "avatar_filename" in agent_cols and "profile_image_filename" not in agent_cols:
        try:
            conn.execute("ALTER TABLE agents RENAME COLUMN avatar_filename TO profile_image_filename")
            print("[DB] agents.avatar_filename → profile_image_filename rename")
            agent_cols = [r["name"] for r in conn.execute("PRAGMA table_info(agents)").fetchall()]
        except sqlite3.OperationalError as e:
            # SQLite < 3.25 fallback: 새 컬럼 추가 후 복사
            conn.execute("ALTER TABLE agents ADD COLUMN profile_image_filename TEXT")
            conn.execute("UPDATE agents SET profile_image_filename = avatar_filename "
                         "WHERE profile_image_filename IS NULL AND avatar_filename IS NOT NULL")
            print(f"[DB] avatar_filename rename 실패 → 복사로 대체 ({e})")
            agent_cols = [r["name"] for r in conn.execute("PRAGMA table_info(agents)").fetchall()]

    new_cols = {
        "birth_year": "INTEGER",
        "age": "INTEGER",
        "gender": "TEXT",
        "mbti": "TEXT",
        "enneagram": "TEXT",
        "background": "TEXT",
        "profile_image_filename": "TEXT",
        "version": "INTEGER DEFAULT 1",
        "created_at": "DATETIME",
        "name_i18n": "TEXT",
        # 개별 에이전트 모델 override — 값 있으면 AGENT_MODELS[type] 대신 사용.
        # 대시보드에서 per-agent 모델 전환 (소넷/하이쿠/오퍼스/로컬) 가능하게 함.
        "model_override": "TEXT",
        # 메타 박살 타임스탬프 — 이 값 not null 이면 persona 가 자기 자각 발화한 것.
        # 대화 잠금 + 메모리·대화 기록 삭제됨 (MetaBreachSupervisor 가 세팅).
        "meta_breached_at": "DATETIME",
        # 프로필 이미지로 사용한 sample 원본 파일명 (assets/sample_profile_images/*.png).
        # Creator 가 catalog 에서 이미 쓴 sample 을 제외하고 추천하도록 추적용.
        "sample_source_file": "TEXT",
        # 자각 상태 페르소나 — 1 이면 self-aware 발화 시 잠금 안 됨, 라인 그대로 통과.
        # 메타 붕괴 후 사용자가 계속 대화하고 싶을 때 수동 set.
        "self_aware": "INTEGER DEFAULT 0",
    }
    for col, col_type in new_cols.items():
        if col not in agent_cols:
            conn.execute(f"ALTER TABLE agents ADD COLUMN {col} {col_type}")
            print(f"[DB] agents.{col} 추가")

    # agents.type CHECK 제약 마이그레이션 — 'dev' 추가용 (기존 DB 는 ('persona','mgr','creator')
    # 만 허용). SQLite 는 CHECK 변경 직접 불가 → 테이블 재생성 필요.
    _migrate_agents_type_check(conn)

    conn.commit()

    # gender 백필 — agents.gender NULL 인 행에 한해 휴리스틱 추론 (1회성)
    _backfill_agent_gender(conn)

    conn.close()


def _backfill_memory_columns(conn):
    """메모리 확장 컬럼 1회성 백필.

    related_entities: 기존 related_agent_id가 있으면 해당 에이전트 이름을 JSON 배열로
    knows: 채널 타입에서 추론 (dm-X → [X, "owner"], internal-dm-A-B → [A, B] 등)
    importance: 기본값 5 (컬럼 default로 이미 들어감)
    last_accessed_at: created_at 복사
    """
    rows = conn.execute(
        "SELECT id, agent_id, channel, related_agent_id, related_entities, knows, last_accessed_at, created_at "
        "FROM memories"
    ).fetchall()
    if not rows:
        return

    # agent_id → name 맵 (related_agent_id 해석용)
    name_map = {a["id"]: a["name"] for a in conn.execute("SELECT id, name FROM agents").fetchall()}

    updated = 0
    for r in rows:
        updates = {}

        # related_entities 백필
        if not r["related_entities"]:
            entities = []
            if r["related_agent_id"]:
                name = name_map.get(r["related_agent_id"])
                if name:
                    entities.append(name)
            if entities:
                updates["related_entities"] = json.dumps(entities, ensure_ascii=False)

        # knows 백필
        if not r["knows"]:
            ch = r["channel"] or ""
            agent_name = name_map.get(r["agent_id"], r["agent_id"])
            knows = set()
            if ch.startswith("dm-"):
                knows.update([agent_name, "owner"])
            elif ch.startswith("group-"):
                parts = ch[len("group-"):].split("-")
                knows.update(parts)
                knows.add("owner")
            elif ch.startswith("internal-dm-"):
                parts = ch[len("internal-dm-"):].split("-")
                knows.update(parts)
            elif ch.startswith("internal-group-"):
                parts = ch[len("internal-group-"):].split("-")
                knows.update(parts)
            elif ch.startswith("mgr-"):
                knows.update([agent_name, "owner"])
            if knows:
                updates["knows"] = json.dumps(sorted(knows), ensure_ascii=False)

        # last_accessed_at 백필
        if not r["last_accessed_at"] and r["created_at"]:
            updates["last_accessed_at"] = r["created_at"]

        if updates:
            cols = ", ".join(f"{k}=?" for k in updates)
            conn.execute(f"UPDATE memories SET {cols} WHERE id=?",
                         (*updates.values(), r["id"]))
            updated += 1

    if updated:
        conn.commit()
        print(f"[DB] memories 백필: {updated} rows (related_entities/knows/last_accessed_at)")


def _backfill_agent_gender(conn):
    """gender 비어있는 페르소나 에이전트에 보수적 휴리스틱으로 성별 추론.
    오너와의 관계 (relationship_to_owner.rel_type) 만 신뢰 — 정확한 단어 매칭.
    appearance/personality 텍스트는 fuzzy match 위험해서 사용 안 함.
    """
    rows = conn.execute(
        "SELECT id FROM agents WHERE (gender IS NULL OR gender = '') AND type = 'persona'"
    ).fetchall()
    if not rows:
        return

    # 정확 일치 키워드 (오너 관점에서 본 페르소나의 역할)
    female_terms = ["여자친구", "여친", "와이프", "아내", "여사친"]
    male_terms = ["남자친구", "남친", "남편", "남사친"]

    def _infer_from(text: str):
        # female 키워드 먼저 (예: "남자친구의 여동생" → 여자)
        for t in female_terms:
            if t in text:
                return "여자"
        for t in male_terms:
            if t in text:
                return "남자"
        return None

    updated = 0
    for r in rows:
        aid = r["id"]
        guess = None
        sources = []  # 디버깅용

        # 1. 본인의 relationship_to_owner (있으면 가장 신뢰)
        rel_own = conn.execute(
            "SELECT rel_type FROM agent_relationship_templates "
            "WHERE agent_id = ? AND is_owner_relationship = 1 LIMIT 1",
            (aid,)
        ).fetchone()
        if rel_own and rel_own["rel_type"]:
            g = _infer_from(rel_own["rel_type"])
            if g:
                guess = g
                sources.append(f"own→owner='{rel_own['rel_type']}'")

        # 2. 다른 에이전트들이 본인을 어떻게 부르는지 (target_id = aid 인 rows 다수)
        #    예: agent-002 → agent-001 = "친구 여자친구" → agent-001 은 여자
        if not guess:
            others = conn.execute(
                "SELECT rel_type FROM agent_relationship_templates "
                "WHERE target_id = ?",
                (aid,)
            ).fetchall()
            votes = {"여자": 0, "남자": 0}
            for o in others:
                rt = o["rel_type"] or ""
                g = _infer_from(rt)
                if g:
                    votes[g] += 1
            if votes["여자"] > votes["남자"]:
                guess = "여자"
                sources.append(f"others-vote=F:{votes['여자']}/M:{votes['남자']}")
            elif votes["남자"] > votes["여자"]:
                guess = "남자"
                sources.append(f"others-vote=F:{votes['여자']}/M:{votes['남자']}")

        if guess:
            conn.execute("UPDATE agents SET gender = ? WHERE id = ?", (guess, aid))
            updated += 1
            print(f"[DB] gender backfill: {aid} → {guess} ({'; '.join(sources)})")

    if updated:
        conn.commit()
    print(f"[DB] gender 백필: {updated}개 추론 / {len(rows) - updated}개 미정 (수동 입력 필요)")


def _migrate_agents_type_check(conn: sqlite3.Connection):
    """agents.type CHECK 제약에 'dev' 가 포함되어 있지 않으면 테이블 재생성으로 추가.

    SQLite 는 CHECK 제약을 ALTER TABLE 로 수정할 수 없어 INSERT-rename 패턴 사용.
    기존 행·인덱스·트리거 보존. 'dev' 가 이미 허용되면 no-op.
    """
    # 빠른 감지 — 임시로 dev 행 INSERT 시도. 성공하면 이미 마이그레이션 됨.
    try:
        conn.execute(
            "INSERT INTO agents (id, type, name) VALUES ('__schema_probe_dev__', 'dev', 'probe')"
        )
        conn.execute("DELETE FROM agents WHERE id = '__schema_probe_dev__'")
        return
    except sqlite3.IntegrityError as e:
        if "CHECK constraint" not in str(e):
            # name NOT NULL 등 다른 제약 오류면 그냥 raise — 하지만 INSERT 가 위에서 다 채웠으니
            # 여기 도달 가능성 낮음. 안전하게 raise.
            raise

    print("[DB] agents.type CHECK 마이그레이션 시작 ('dev' 추가)")
    # 1. 새 테이블 (init_db 의 최신 정의와 동일 — 'dev' 포함)
    conn.execute("""
        CREATE TABLE agents_new (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL CHECK(type IN ('persona', 'mgr', 'creator', 'dev')),
            name TEXT NOT NULL,
            name_i18n TEXT,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'inactive', 'archived')),
            current_emotion TEXT DEFAULT '평온',
            emotion_intensity INTEGER DEFAULT 5 CHECK(emotion_intensity BETWEEN 1 AND 10),
            last_active DATETIME DEFAULT CURRENT_TIMESTAMP,
            birth_year INTEGER,
            age INTEGER,
            gender TEXT,
            mbti TEXT,
            enneagram TEXT,
            background TEXT,
            profile_image_filename TEXT,
            version INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            model_override TEXT,
            meta_breached_at DATETIME,
            sample_source_file TEXT,
            self_aware INTEGER DEFAULT 0
        )
    """)
    # 2. 기존 컬럼 교집합으로 데이터 복사
    old_cols = [r["name"] for r in conn.execute("PRAGMA table_info(agents)").fetchall()]
    new_cols = [r["name"] for r in conn.execute("PRAGMA table_info(agents_new)").fetchall()]
    common = [c for c in new_cols if c in old_cols]
    cols_csv = ", ".join(common)
    conn.execute(f"INSERT INTO agents_new ({cols_csv}) SELECT {cols_csv} FROM agents")
    # 3. 인덱스 백업 (agents 위 인덱스만) → 나중에 재생성. 보통은 PRIMARY KEY 외 없음.
    indexes = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' AND tbl_name='agents' AND sql IS NOT NULL"
    ).fetchall()
    # 4. 기존 테이블 drop + 새 테이블 rename
    conn.execute("DROP TABLE agents")
    conn.execute("ALTER TABLE agents_new RENAME TO agents")
    # 5. 인덱스 재생성
    for idx in indexes:
        try:
            conn.execute(idx["sql"])
        except sqlite3.OperationalError as e:
            print(f"[DB] index {idx['name']} 재생성 실패 (스킵): {e}")
    print("[DB] agents.type CHECK 마이그레이션 완료")


def _migrate_satellite_tables():
    """기존 컬럼 기반 위성 테이블 → JSON blob 방식으로 변환 (이전 DB 호환)"""
    conn = get_conn()
    for table in ("agent_personality", "agent_appearance", "agent_daily_life", "agent_speech"):
        cols = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        if "data" in cols:
            continue  # 이미 새 형식
        if len(cols) <= 1:
            continue  # 빈 테이블

        # 기존 데이터를 JSON으로 변환 후 테이블 재생성
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()
        data_cols = [c for c in cols if c != "agent_id"]
        migrated = []
        for r in rows:
            r = dict(r)
            blob = {k: r[k] for k in data_cols if r[k] is not None}
            # JSON 문자열로 저장된 배열 파싱
            for k, v in blob.items():
                if isinstance(v, str) and v.startswith("["):
                    try:
                        blob[k] = json.loads(v)
                    except Exception:
                        pass
            migrated.append((r["agent_id"], json.dumps(blob, ensure_ascii=False)))

        conn.execute(f"DROP TABLE {table}")
        conn.execute(f"""CREATE TABLE {table} (
            agent_id TEXT PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
            data TEXT NOT NULL
        )""")
        for agent_id, data in migrated:
            conn.execute(f"INSERT INTO {table} (agent_id, data) VALUES (?, ?)", (agent_id, data))
        if migrated:
            print(f"[DB] {table} → JSON blob 형식으로 변환 ({len(migrated)}건)")

    conn.commit()
    conn.close()


def delete_agent_all_data(agent_id: str) -> dict:
    """에이전트의 모든 데이터 삭제 (대화, 메모리, 이벤트)"""
    conn = get_conn()
    msg = conn.execute("SELECT COUNT(*) as c FROM conversations WHERE speaker = ?", (agent_id,)).fetchone()["c"]
    mem = conn.execute("SELECT COUNT(*) as c FROM memories WHERE agent_id = ?", (agent_id,)).fetchone()["c"]
    evt = conn.execute("SELECT COUNT(*) as c FROM events WHERE participants LIKE ?", (f"%{agent_id}%",)).fetchone()["c"]
    conn.execute("DELETE FROM conversations WHERE speaker = ?", (agent_id,))
    conn.execute("DELETE FROM memories WHERE agent_id = ?", (agent_id,))
    conn.execute("DELETE FROM events WHERE participants LIKE ?", (f"%{agent_id}%",))
    conn.commit()
    conn.close()
    return {"messages": msg, "memories": mem, "events": evt}


# ══════════════════════════════════════════════════════
# 에이전트 프로필 CRUD (DB 기반)
# ══════════════════════════════════════════════════════

def _json_col(val) -> Optional[str]:
    """파이썬 객체 → JSON 텍스트 (None은 None)"""
    if val is None:
        return None
    return json.dumps(val, ensure_ascii=False)


def _from_json(text: Optional[str]):
    """JSON 텍스트 → 파이썬 객체 (None이면 None)"""
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def get_agent_profile(agent_id: str) -> Optional[dict]:
    """에이전트 프로필을 DB에서 로드 — 기존 JSON과 동일한 dict shape 반환"""
    conn = get_conn()

    agent = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    if not agent:
        conn.close()
        return None

    agent = dict(agent)
    profile = {
        "id": agent["id"],
        "type": agent["type"],
        "name": agent["name"],
        "status": agent.get("status", "active"),
        "current_emotion": agent.get("current_emotion", "평온"),
        "emotion_intensity": agent.get("emotion_intensity", 5),
    }
    # 확장 컬럼
    for col in ("birth_year", "age", "gender", "mbti", "enneagram", "background",
                "profile_image_filename", "version", "created_at"):
        if agent.get(col) is not None:
            profile[col] = agent[col]
    # name_i18n — JSON 문자열을 dict 로 복원
    if agent.get("name_i18n"):
        profile["name_i18n"] = _from_json(agent["name_i18n"]) or agent["name_i18n"]

    # 위성 테이블 로드 (JSON blob)
    for table, key in [
        ("agent_personality", "personality"),
        ("agent_appearance", "appearance"),
        ("agent_daily_life", "daily_life"),
        ("agent_speech", "speech"),
    ]:
        row = conn.execute(f"SELECT data FROM {table} WHERE agent_id = ?", (agent_id,)).fetchone()
        if row and row["data"]:
            profile[key] = _from_json(row["data"]) or {}

    # 관계 템플릿 → relationship_to_owner + relationships
    rels = conn.execute(
        "SELECT * FROM agent_relationship_templates WHERE agent_id = ?", (agent_id,)
    ).fetchall()
    agent_rels = {}
    for r in rels:
        r = dict(r)
        if r["is_owner_relationship"]:
            profile["relationship_to_owner"] = {
                "type": r["rel_type"],
                "duration": r.get("duration") or "",
                "how_met": r.get("how_met") or "",
                "dynamics": r.get("dynamics") or "",
                "pet_name": r.get("pet_name") or "",
            }
        else:
            agent_rels[r["target_id"]] = {
                "type": r["rel_type"],
                "note": r.get("note") or "",
            }
    if agent_rels:
        profile["relationships"] = agent_rels

    # 타입별 설정
    row = conn.execute("SELECT config_json FROM agent_config WHERE agent_id = ?", (agent_id,)).fetchone()
    if row and row["config_json"]:
        config = _from_json(row["config_json"])
        if config and isinstance(config, dict):
            for k, v in config.items():
                profile[k] = v

    conn.close()
    return profile


def save_agent_profile(profile: dict):
    """에이전트 프로필을 DB에 저장 (INSERT OR REPLACE)"""
    agent_id = profile["id"]
    conn = get_conn()

    # agents 테이블 — name_i18n 은 dict면 JSON으로 직렬화
    name_i18n = profile.get("name_i18n")
    if name_i18n and not isinstance(name_i18n, str):
        name_i18n = json.dumps(name_i18n, ensure_ascii=False)

    # profile_image_filename: 신규 키 우선, 레거시 avatar_filename 폴백
    profile_image_filename = profile.get("profile_image_filename") or profile.get("avatar_filename")

    # background 에 종족 prefix 자동 부착 — race 필드 있고 background 가 아직
    # '종족:' 으로 시작하지 않을 때만. 페르소나 self-prompt 에서 종족 정체성 일관 유지.
    bg = profile.get("background") or ""
    race = (profile.get("race") or "").strip()
    if race and not bg.lstrip().startswith("종족:"):
        bg = f"종족: {race}. {bg}".strip()

    conn.execute("""
        INSERT INTO agents (id, type, name, name_i18n, birth_year, age, gender, mbti, enneagram,
                            background, profile_image_filename, version, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            type=excluded.type, name=excluded.name, name_i18n=excluded.name_i18n,
            birth_year=excluded.birth_year, age=excluded.age, gender=excluded.gender,
            mbti=excluded.mbti, enneagram=excluded.enneagram,
            background=excluded.background, profile_image_filename=excluded.profile_image_filename,
            version=excluded.version
    """, (
        agent_id, profile.get("type", "persona"), profile["name"], name_i18n,
        profile.get("birth_year"), profile.get("age"), profile.get("gender"),
        profile.get("mbti"), profile.get("enneagram"),
        bg, profile_image_filename,
        profile.get("version", 1), profile.get("created_at", now_utc_iso()),
    ))

    # 위성 테이블 (JSON blob)
    for table, key in [
        ("agent_personality", "personality"),
        ("agent_appearance", "appearance"),
        ("agent_daily_life", "daily_life"),
        ("agent_speech", "speech"),
    ]:
        data = profile.get(key)
        if data:
            conn.execute(
                f"INSERT OR REPLACE INTO {table} (agent_id, data) VALUES (?, ?)",
                (agent_id, _json_col(data))
            )

    # relationship templates
    conn.execute("DELETE FROM agent_relationship_templates WHERE agent_id = ?", (agent_id,))
    rel_owner = profile.get("relationship_to_owner", {})
    if rel_owner and rel_owner.get("type"):
        conn.execute("""
            INSERT INTO agent_relationship_templates
            (agent_id, target_id, rel_type, duration, how_met, dynamics, pet_name, is_owner_relationship)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        """, (agent_id, "owner", rel_owner.get("type"), rel_owner.get("duration"),
              rel_owner.get("how_met"), rel_owner.get("dynamics"), rel_owner.get("pet_name")))

    for target_id, rel_info in profile.get("relationships", {}).items():
        conn.execute("""
            INSERT INTO agent_relationship_templates
            (agent_id, target_id, rel_type, note, is_owner_relationship)
            VALUES (?, ?, ?, ?, 0)
        """, (agent_id, target_id, rel_info.get("type", ""), rel_info.get("note", "")))

    # config (mgr_config, creator_config 등) + 세계관 universe + 종족 race 필드.
    # universe: cross-universe 자동 페어링 차단 / supervisor cooldown 분리에 사용.
    # race: 페르소나 self-prompt + cross-reference (다른 페르소나가 이 사람 언급 시) 에 사용.
    config_keys = [k for k in profile if k.endswith("_config")]
    config: dict = {}
    if config_keys:
        config = {k: profile[k] for k in config_keys}
    if profile.get("universe"):
        config["universe"] = str(profile["universe"]).strip()
    if profile.get("race"):
        config["race"] = str(profile["race"]).strip()
    if config:
        conn.execute(
            "INSERT OR REPLACE INTO agent_config (agent_id, config_json) VALUES (?, ?)",
            (agent_id, _json_col(config))
        )

    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════
# 오너 CRUD
# ══════════════════════════════════════════════════════

def get_user(user_id: Optional[str] = None) -> Optional[dict]:
    """오너 프로필 로드. user_id 없으면 active_user 또는 첫 번째 유저."""
    conn = get_conn()
    if not user_id:
        row = conn.execute("SELECT value FROM meta WHERE key = 'active_user_id'").fetchone()
        user_id = row["value"] if row else None
    if user_id:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM users LIMIT 1").fetchone()
    conn.close()
    if not row:
        return None
    u = dict(row)
    # JSON 컬럼 파싱
    for col in ("personality", "appearance", "daily_life", "speech", "relationships_summary"):
        u[col] = _from_json(u.get(col))
    return u


def save_user(user: dict):
    """오너 프로필 저장"""
    conn = get_conn()
    conn.execute("""
        INSERT OR REPLACE INTO users
        (id, name, birth_year, age, mbti, enneagram, background,
         personality, appearance, daily_life, speech, relationships_summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user["id"], user["name"], user.get("birth_year"), user.get("age"),
        user.get("mbti"), user.get("enneagram"), user.get("background"),
        _json_col(user.get("personality")), _json_col(user.get("appearance")),
        _json_col(user.get("daily_life")), _json_col(user.get("speech")),
        _json_col(user.get("relationships_summary")),
    ))
    conn.commit()
    conn.close()


def list_users() -> list[dict]:
    """전체 오너 목록"""
    conn = get_conn()
    rows = conn.execute("SELECT * FROM users").fetchall()
    conn.close()
    users = []
    for r in rows:
        u = dict(r)
        for col in ("personality", "appearance", "daily_life", "speech", "relationships_summary"):
            u[col] = _from_json(u.get(col))
        users.append(u)
    return users


def get_meta(key: str) -> Optional[str]:
    conn = get_conn()
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def set_meta(key: str, value: str):
    def _do():
        conn = get_conn()
        try:
            conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
            conn.commit()
        finally:
            conn.close()
    _retry_on_lock(_do)


# ══════════════════════════════════════════════════════
# Export / Import (에이전트 정의만)
# ══════════════════════════════════════════════════════

_PROFILE_TABLES = [
    "agents", "agent_personality", "agent_appearance", "agent_daily_life",
    "agent_speech", "agent_relationship_templates", "agent_config", "users", "meta",
]


def export_agents(output_path: str):
    """에이전트 + 오너 정의만 별도 DB로 추출 (채팅/메모리 제외)"""
    conn = get_conn()
    conn.execute(f"ATTACH DATABASE ? AS export_db", (output_path,))

    # 테이블 스키마 복사 + 데이터 복사
    for table in _PROFILE_TABLES:
        schema = conn.execute(
            f"SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
        if schema and schema["sql"]:
            conn.execute(f"DROP TABLE IF EXISTS export_db.{table}")
            conn.execute(schema["sql"].replace(f"CREATE TABLE {table}",
                                                f"CREATE TABLE export_db.{table}", 1))
            conn.execute(f"INSERT INTO export_db.{table} SELECT * FROM main.{table}")

    conn.commit()
    conn.execute("DETACH DATABASE export_db")
    conn.close()
    print(f"[DB] 에이전트 정의 export 완료: {output_path}")


def import_agents(input_path: str):
    """별도 DB에서 에이전트 + 오너 정의 가져오기"""
    conn = get_conn()
    conn.execute(f"ATTACH DATABASE ? AS import_db", (input_path,))

    for table in _PROFILE_TABLES:
        try:
            conn.execute(f"INSERT OR REPLACE INTO main.{table} SELECT * FROM import_db.{table}")
        except sqlite3.OperationalError:
            pass  # 테이블이 없으면 스킵

    conn.commit()
    conn.execute("DETACH DATABASE import_db")
    conn.close()
    print(f"[DB] 에이전트 정의 import 완료: {input_path}")


# === 휴지통 ===

def trash_messages(channel: str, message_ids: list[int] = None):
    """메시지를 휴지통으로 이동 (message_ids=None이면 채널 전체)"""
    import json as _json
    conn = get_conn()

    if message_ids:
        rows = conn.execute(
            f"SELECT * FROM conversations WHERE id IN ({','.join('?' * len(message_ids))})",
            message_ids,
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM conversations WHERE channel = ?", (channel,)
        ).fetchall()

    if rows:
        data = [dict(r) for r in rows]
        conn.execute(
            "INSERT INTO trash (item_type, original_table, channel, data) VALUES (?, ?, ?, ?)",
            ("message", "conversations", channel, _json.dumps(data, ensure_ascii=False)),
        )
        ids = [r["id"] for r in rows]
        conn.execute(
            f"DELETE FROM conversations WHERE id IN ({','.join('?' * len(ids))})", ids
        )
        # 관련 메모리도 휴지통으로
        mems = conn.execute(
            "SELECT * FROM memories WHERE channel = ?", (channel,)
        ).fetchall()
        if mems:
            conn.execute(
                "INSERT INTO trash (item_type, original_table, channel, data) VALUES (?, ?, ?, ?)",
                ("memory", "memories", channel, _json.dumps([dict(m) for m in mems], ensure_ascii=False)),
            )
            conn.execute("DELETE FROM memories WHERE channel = ?", (channel,))

    conn.commit()
    conn.close()
    return len(rows)


def trash_list() -> list[dict]:
    """휴지통 목록"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, item_type, channel, deleted_at, LENGTH(data) as data_size FROM trash ORDER BY deleted_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def trash_restore(trash_id: int) -> dict:
    """휴지통에서 복원"""
    import json as _json
    conn = get_conn()
    row = conn.execute("SELECT * FROM trash WHERE id = ?", (trash_id,)).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": "항목 없음"}

    data = _json.loads(row["data"])
    table = row["original_table"]
    restored = 0

    for item in data:
        item.pop("id", None)  # auto-increment
        cols = ", ".join(item.keys())
        placeholders = ", ".join("?" * len(item))
        try:
            conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", list(item.values()))
            restored += 1
        except Exception:
            pass

    conn.execute("DELETE FROM trash WHERE id = ?", (trash_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "restored": restored, "type": row["item_type"], "channel": row["channel"]}


def trash_empty():
    """휴지통 비우기"""
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM trash").fetchone()[0]
    conn.execute("DELETE FROM trash")
    conn.commit()
    conn.close()
    return count


# === Achievements (도전과제 진척도) ===

def get_achievement(user_id: str, key: str) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM achievements WHERE user_id = ? AND key = ?",
        (user_id, key)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def list_achievements(user_id: str) -> list[dict]:
    """user 의 모든 도전과제 진척도. locked 포함."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM achievements WHERE user_id = ? ORDER BY "
        "CASE state WHEN 'done' THEN 2 WHEN 'unlocked' THEN 1 ELSE 3 END, key",
        (user_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_achievement(user_id: str, key: str, state: str = None,
                       progress_data: dict = None,
                       mark_unlocked: bool = False,
                       mark_completed: bool = False) -> dict:
    """도전과제 행 삽입/갱신. state 는 'locked'/'unlocked'/'done' 중 하나.
    mark_unlocked=True 시 첫 unlock 시점에만 unlocked_at 기록.
    mark_completed=True 시 첫 완료 시점에만 completed_at 기록 + state='done' 강제."""
    import json as _json
    conn = get_conn()
    existing = conn.execute(
        "SELECT * FROM achievements WHERE user_id = ? AND key = ?",
        (user_id, key)
    ).fetchone()

    if mark_completed:
        state = "done"

    if existing:
        new_state = state if state else existing["state"]
        new_progress = _json.dumps(progress_data, ensure_ascii=False) if progress_data is not None else existing["progress_data"]
        new_unlocked = existing["unlocked_at"]
        if mark_unlocked and not new_unlocked:
            new_unlocked = now_utc_iso()
        new_completed = existing["completed_at"]
        if mark_completed and not new_completed:
            new_completed = now_utc_iso()
        conn.execute(
            "UPDATE achievements SET state = ?, progress_data = ?, unlocked_at = ?, completed_at = ? "
            "WHERE user_id = ? AND key = ?",
            (new_state, new_progress, new_unlocked, new_completed, user_id, key)
        )
    else:
        now = now_utc_iso()
        conn.execute(
            "INSERT INTO achievements (user_id, key, state, progress_data, unlocked_at, completed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, key, state or "locked",
             _json.dumps(progress_data, ensure_ascii=False) if progress_data else None,
             now if mark_unlocked else None,
             now if mark_completed else None)
        )
    conn.commit()
    row = conn.execute(
        "SELECT * FROM achievements WHERE user_id = ? AND key = ?",
        (user_id, key)
    ).fetchone()
    conn.close()
    return dict(row)


def count_completed_achievements(user_id: str) -> tuple[int, int]:
    """(완료 수, 전체 추적 수) — 대시보드 요약용."""
    conn = get_conn()
    total = conn.execute(
        "SELECT COUNT(*) FROM achievements WHERE user_id = ?", (user_id,)
    ).fetchone()[0]
    done = conn.execute(
        "SELECT COUNT(*) FROM achievements WHERE user_id = ? AND state = 'done'", (user_id,)
    ).fetchone()[0]
    conn.close()
    return done, total


# === 시간 범위 메시지 조회 (에이전트가 효율적으로 특정 구간만 읽기) ===

def get_messages_in_range(channel: str,
                           since: Optional[str] = None,
                           until: Optional[str] = None,
                           since_minutes: Optional[int] = None,
                           limit: int = 200) -> list[dict]:
    """채널의 특정 시간 구간 메시지.

    since, until: ISO datetime string (e.g. "2026-04-20 17:30:00") — 우선
    since_minutes: 위 둘 다 없을 때 대안 — 지금부터 N분 전까지
    limit: 최대 반환 수 (프롬프트 토큰 보호)."""
    conn = get_conn()
    q = "SELECT * FROM conversations WHERE channel = ?"
    args: list = [channel]
    if since_minutes is not None and not since:
        q += " AND timestamp >= datetime('now', ?)"
        args.append(f"-{int(since_minutes)} minutes")
    else:
        if since:
            q += " AND timestamp >= ?"
            args.append(since)
        if until:
            q += " AND timestamp <= ?"
            args.append(until)
    q += " ORDER BY id ASC LIMIT ?"
    args.append(limit)
    rows = conn.execute(q, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]
