"""
chaos.db SQLite 데이터베이스 레이어
"""
import sqlite3
import json
import os
from datetime import datetime
from typing import Optional

from src import community

DB_PATH = None  # community.get_db_path()로 동적 결정


def _get_db_path() -> str:
    global DB_PATH
    if DB_PATH:
        return DB_PATH
    DB_PATH = community.get_db_path()
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return DB_PATH


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """DB 테이블 초기화"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL CHECK(type IN ('persona', 'mgr', 'creator')),
            name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'inactive', 'archived')),
            current_emotion TEXT DEFAULT '평온',
            emotion_intensity INTEGER DEFAULT 5 CHECK(emotion_intensity BETWEEN 1 AND 10),
            last_active DATETIME DEFAULT CURRENT_TIMESTAMP,
            birth_year INTEGER,
            age INTEGER,
            mbti TEXT,
            enneagram TEXT,
            background TEXT,
            avatar_filename TEXT,
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
            level INTEGER NOT NULL DEFAULT 1,
            content TEXT NOT NULL,
            msg_id_from INTEGER,
            msg_id_to INTEGER,
            msg_count INTEGER DEFAULT 0,
            related_agent_id TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_mem_agent ON memories(agent_id, channel, level);

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

        -- ── 유저 테이블 (N명 지원) ──

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


def get_agent(agent_id: str) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute("SELECT * FROM agents WHERE id = ?", (agent_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_emotion(agent_id: str, emotion: str, intensity: int):
    conn = get_conn()
    conn.execute(
        "UPDATE agents SET current_emotion = ?, emotion_intensity = ?, last_active = ? WHERE id = ?",
        (emotion, intensity, datetime.now().isoformat(), agent_id)
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

def add_relationship(agent_a: str, agent_b: str, rel_type: str, intimacy: int = 50, dynamics: str = ""):
    conn = get_conn()
    conn.execute(
        """INSERT OR REPLACE INTO relationships (agent_a, agent_b, type, intimacy_score, dynamics, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (agent_a, agent_b, rel_type, intimacy, dynamics, datetime.now().isoformat())
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
        (delta, datetime.now().isoformat(), agent_a, agent_b)
    )
    conn.commit()
    conn.close()


# === Conversation Log ===

def log_message(channel: str, speaker: str, message: str, emotion: str = None):
    conn = get_conn()
    conn.execute(
        "INSERT INTO conversations (channel, speaker, message, context_emotion) VALUES (?, ?, ?, ?)",
        (channel, speaker, message, emotion)
    )
    # 에이전트 발화 시 last_active 갱신
    if speaker.startswith("agent-"):
        conn.execute(
            "UPDATE agents SET last_active = ? WHERE id = ?",
            (datetime.now().isoformat(), speaker)
        )
    conn.commit()
    conn.close()


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
               msg_id_from: int, msg_id_to: int, msg_count: int,
               related_agent_id: str = None):
    conn = get_conn()
    conn.execute(
        """INSERT INTO memories (agent_id, channel, level, content, msg_id_from, msg_id_to, msg_count, related_agent_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (agent_id, channel, level, content, msg_id_from, msg_id_to, msg_count, related_agent_id)
    )
    conn.commit()
    conn.close()


def get_memories(agent_id: str, channel: str, level: int, limit: int = 10) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM memories WHERE agent_id = ? AND channel = ? AND level = ? ORDER BY created_at DESC LIMIT ?",
        (agent_id, channel, level, limit)
    ).fetchall()
    conn.close()
    return [dict(r) for r in reversed(rows)]


def get_latest_memory(agent_id: str, channel: str, level: int) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM memories WHERE agent_id = ? AND channel = ? AND level = ? ORDER BY msg_id_to DESC LIMIT 1",
        (agent_id, channel, level)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


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


if __name__ == "__main__":
    init_db()


# === 유나 관리자 조회 ===

def get_channel_overview() -> list[dict]:
    """전체 채널 활동 현황 (유나 대시보드용)"""
    conn = get_conn()
    rows = conn.execute("""
        SELECT channel,
               COUNT(*) as msg_count,
               COUNT(DISTINCT speaker) as speakers,
               MAX(timestamp) as last_active,
               MIN(timestamp) as first_active
        FROM conversations
        GROUP BY channel
        ORDER BY last_active DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


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

    # memories.related_agent_id 추가
    mem_cols = [r["name"] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
    if "related_agent_id" not in mem_cols:
        conn.execute("ALTER TABLE memories ADD COLUMN related_agent_id TEXT")
        print("[DB] memories.related_agent_id 추가")

    # relationships 테이블 별칭 컬럼 추가
    rel_cols = [r["name"] for r in conn.execute("PRAGMA table_info(relationships)").fetchall()]
    for col in ("pet_name_a_to_b", "pet_name_b_to_a"):
        if col not in rel_cols:
            conn.execute(f"ALTER TABLE relationships ADD COLUMN {col} TEXT")
            print(f"[DB] relationships.{col} 추가")

    # agents 테이블 프로필 컬럼 추가
    agent_cols = [r["name"] for r in conn.execute("PRAGMA table_info(agents)").fetchall()]
    new_cols = {
        "birth_year": "INTEGER",
        "age": "INTEGER",
        "mbti": "TEXT",
        "enneagram": "TEXT",
        "background": "TEXT",
        "avatar_filename": "TEXT",
        "version": "INTEGER DEFAULT 1",
        "created_at": "DATETIME",
    }
    for col, col_type in new_cols.items():
        if col not in agent_cols:
            conn.execute(f"ALTER TABLE agents ADD COLUMN {col} {col_type}")
            print(f"[DB] agents.{col} 추가")

    conn.commit()
    conn.close()


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
    for col in ("birth_year", "age", "mbti", "enneagram", "background",
                "avatar_filename", "version", "created_at"):
        if agent.get(col) is not None:
            profile[col] = agent[col]

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

    # agents 테이블
    conn.execute("""
        INSERT INTO agents (id, type, name, birth_year, age, mbti, enneagram,
                            background, avatar_filename, version, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            type=excluded.type, name=excluded.name,
            birth_year=excluded.birth_year, age=excluded.age,
            mbti=excluded.mbti, enneagram=excluded.enneagram,
            background=excluded.background, avatar_filename=excluded.avatar_filename,
            version=excluded.version
    """, (
        agent_id, profile.get("type", "persona"), profile["name"],
        profile.get("birth_year"), profile.get("age"),
        profile.get("mbti"), profile.get("enneagram"),
        profile.get("background"), profile.get("avatar_filename"),
        profile.get("version", 1), profile.get("created_at", datetime.now().isoformat()),
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

    # config (mgr_config, creator_config 등)
    config_keys = [k for k in profile if k.endswith("_config")]
    if config_keys:
        config = {k: profile[k] for k in config_keys}
        conn.execute(
            "INSERT OR REPLACE INTO agent_config (agent_id, config_json) VALUES (?, ?)",
            (agent_id, _json_col(config))
        )

    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════
# 유저 CRUD
# ══════════════════════════════════════════════════════

def get_user(user_id: Optional[str] = None) -> Optional[dict]:
    """유저 프로필 로드. user_id 없으면 active_user 또는 첫 번째 유저."""
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
    """유저 프로필 저장"""
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
    """전체 유저 목록"""
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
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


# ══════════════════════════════════════════════════════
# Export / Import (에이전트 정의만)
# ══════════════════════════════════════════════════════

_PROFILE_TABLES = [
    "agents", "agent_personality", "agent_appearance", "agent_daily_life",
    "agent_speech", "agent_relationship_templates", "agent_config", "users", "meta",
]


def export_agents(output_path: str):
    """에이전트 + 유저 정의만 별도 DB로 추출 (채팅/메모리 제외)"""
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
    """별도 DB에서 에이전트 + 유저 정의 가져오기"""
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
