"""
도전과제 정의 카탈로그.

각 Achievement:
  - key: 유니크 식별자 (DB 에 저장)
  - title / description / icon: 대시보드 렌더링용
  - check(user_id) -> dict|None: DB 상태 보고 현재 진척도 판정
      반환:
        None → 상태 변경 없음
        {"state": "unlocked"|"done", "progress_data": {...}, ...} → upsert

engine 이 메시지 로깅 시 (또는 tick) 전 과제를 순회하며 check 결과를 DB 에 반영.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from src import db


@dataclass(frozen=True)
class Achievement:
    key: str
    title: str
    description: str
    icon: str
    # check(user_id) → dict with optional keys:
    #   "state": "locked"|"unlocked"|"done"
    #   "progress_data": dict
    #   "mark_unlocked": bool (state="unlocked" 처음일 때)
    #   "mark_completed": bool (state="done" 처음일 때)
    # None 반환 시 변경 없음.
    check: Callable[[str], Optional[dict]]


# ── 개별 check 함수들 ──────────────────────────────────

def _check_tutorial_done(user_id: str) -> Optional[dict]:
    """튜토리얼 씬 phase='complete' 도달."""
    conn = db.get_conn()
    row = conn.execute(
        "SELECT value FROM meta WHERE key='tutorial_phase'"
    ).fetchone()
    conn.close()
    if row and row["value"] == "complete":
        return {"state": "done", "mark_completed": True, "mark_unlocked": True}
    return None


def _check_first_friend_chat(user_id: str) -> Optional[dict]:
    """첫 페르소나와 DM 에서 오너가 메시지 3개 이상 보냄."""
    conn = db.get_conn()
    personas = [r[0] for r in conn.execute(
        "SELECT name FROM agents WHERE type='persona'"
    ).fetchall()]
    if not personas:
        conn.close()
        return None
    total_owner_msgs = 0
    friend_hit = None
    for name in personas:
        ch = f"dm-{name}"
        cnt = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE channel=? AND speaker=?",
            (ch, user_id)
        ).fetchone()[0]
        total_owner_msgs = max(total_owner_msgs, cnt)
        if cnt >= 3 and friend_hit is None:
            friend_hit = name
    conn.close()
    if friend_hit:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"friend": friend_hit}}
    if total_owner_msgs > 0:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"msgs": total_owner_msgs, "need": 3}}
    return None


def _check_three_friends(user_id: str) -> Optional[dict]:
    """서로 다른 3명 페르소나와 DM 나눔 (각각 최소 1회)."""
    conn = db.get_conn()
    personas = [r[0] for r in conn.execute(
        "SELECT name FROM agents WHERE type='persona'"
    ).fetchall()]
    talked = []
    for name in personas:
        ch = f"dm-{name}"
        has = conn.execute(
            "SELECT 1 FROM conversations WHERE channel=? AND speaker=? LIMIT 1",
            (ch, user_id)
        ).fetchone()
        if has:
            talked.append(name)
    conn.close()
    if not talked:
        return None
    if len(talked) >= 3:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"talked_to": talked}}
    return {"state": "unlocked", "mark_unlocked": True,
            "progress_data": {"talked_to": talked, "need": 3}}


def _check_group_chat(user_id: str) -> Optional[dict]:
    """group-* 채널에서 오너 포함 5개+ 메시지 교환."""
    conn = db.get_conn()
    # group-* 채널 (internal-group 제외)
    chs = conn.execute(
        "SELECT DISTINCT channel FROM conversations WHERE channel LIKE 'group-%'"
    ).fetchall()
    max_msgs = 0
    hit_ch = None
    for r in chs:
        ch = r[0]
        total = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE channel=?", (ch,)
        ).fetchone()[0]
        has_owner = conn.execute(
            "SELECT 1 FROM conversations WHERE channel=? AND speaker=? LIMIT 1",
            (ch, user_id)
        ).fetchone()
        if has_owner and total > max_msgs:
            max_msgs = total
            hit_ch = ch
    conn.close()
    if hit_ch and max_msgs >= 5:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"channel": hit_ch, "msgs": max_msgs}}
    if hit_ch:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"channel": hit_ch, "msgs": max_msgs, "need": 5}}
    return None


def _check_peek_internal(user_id: str) -> Optional[dict]:
    """internal-dm-* 또는 internal-group-* 채널에서 에이전트끼리 10+ 메시지.
    (오너가 실제 읽었는지는 감지 불가 — 존재 + 활성도로 대리)."""
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT channel, COUNT(*) as c FROM conversations "
        "WHERE channel LIKE 'internal-%' GROUP BY channel HAVING c >= 10"
    ).fetchall()
    conn.close()
    if rows:
        chs = [r["channel"] for r in rows]
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"channels": chs[:5]}}
    return None


def _check_agent_auto_chat(user_id: str) -> Optional[dict]:
    """에이전트간 자율 대화 — internal-* 채널이 running 상태 도달 or 10+ 메시지."""
    conn = db.get_conn()
    row = conn.execute(
        "SELECT channel FROM channels WHERE channel LIKE 'internal-%' "
        "AND status='running' LIMIT 1"
    ).fetchone()
    conn.close()
    if row:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"channel": row["channel"]}}
    return None


def _check_event_count(event_types: list[str], threshold: int, user_id: str) -> Optional[dict]:
    """events 테이블에 특정 type 이 threshold 회 이상 기록됐는지."""
    conn = db.get_conn()
    placeholders = ",".join("?" * len(event_types))
    try:
        cnt = conn.execute(
            f"SELECT COUNT(*) AS c FROM events WHERE event_type IN ({placeholders})",
            event_types,
        ).fetchone()["c"]
    except Exception:
        cnt = 0
    finally:
        conn.close()
    if cnt >= threshold:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"count": cnt, "threshold": threshold}}
    if cnt > 0:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"count": cnt, "need": threshold}}
    return None


def _check_first_conflict(user_id: str) -> Optional[dict]:
    """persona 간 갈등/분쟁 이벤트 기록 1건 이상."""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT participants, description FROM events "
            "WHERE event_type IN ('갈등', '다툼', '오해') LIMIT 1"
        ).fetchone()
    except Exception:
        row = None
    conn.close()
    if row:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"description": row["description"][:80]}}
    return None


def _check_reconciliation(user_id: str) -> Optional[dict]:
    """화해/해소 이벤트."""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT description FROM events WHERE event_type IN ('화해', '해소', '관계회복') LIMIT 1"
        ).fetchone()
    except Exception:
        row = None
    conn.close()
    if row:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"description": row["description"][:80]}}
    return None


def _check_confession(user_id: str) -> Optional[dict]:
    """고백/마음 표현 이벤트."""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT description FROM events WHERE event_type IN ('고백', '마음표현', '짝사랑') LIMIT 1"
        ).fetchone()
    except Exception:
        row = None
    conn.close()
    if row:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"description": row["description"][:80]}}
    return None


def _check_many_friends(user_id: str, threshold: int = 5) -> Optional[dict]:
    """persona 에이전트 수 (locked 제외) threshold 이상."""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM agents WHERE type='persona' "
            "AND (meta_breached_at IS NULL)"
        ).fetchone()
        cnt = row["c"] if row else 0
    except Exception:
        cnt = 0
    conn.close()
    if cnt >= threshold:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"count": cnt, "threshold": threshold}}
    if cnt > 0:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"count": cnt, "need": threshold}}
    return None


def _check_late_night(user_id: str) -> Optional[dict]:
    """새벽(0-5시) 대화 기록 — 진짜 친밀한 시간대."""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM conversations WHERE speaker=? "
            "AND CAST(strftime('%H', timestamp) AS INTEGER) BETWEEN 0 AND 5",
            (user_id,),
        ).fetchone()
        cnt = row["c"] if row else 0
    except Exception:
        cnt = 0
    conn.close()
    if cnt >= 10:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"count": cnt}}
    return None


def _check_message_volume(user_id: str, threshold: int = 500) -> Optional[dict]:
    """전체 대화 볼륨."""
    conn = db.get_conn()
    try:
        row = conn.execute("SELECT COUNT(*) AS c FROM conversations").fetchone()
        cnt = row["c"] if row else 0
    except Exception:
        cnt = 0
    conn.close()
    if cnt >= threshold:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"count": cnt}}
    if cnt > threshold // 5:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"count": cnt, "need": threshold}}
    return None


def _check_secret_keeper(user_id: str) -> Optional[dict]:
    """internal-dm 채널 (오너 읽기전용) 에서 persona 끼리 비밀 대화 많이."""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM conversations WHERE channel LIKE 'internal-dm-%'"
        ).fetchone()
        cnt = row["c"] if row else 0
    except Exception:
        cnt = 0
    conn.close()
    if cnt >= 30:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"count": cnt}}
    return None


def _check_meta_breach(user_id: str) -> Optional[dict]:
    """메타 박살 — persona 1명 이상이 메타 자각 발화해서 잠금 상태(locked)가 된 경우.
    `agents.meta_breached_at` 가 찍힌 persona 가 있으면 unlock.
    MetaBreachSupervisor 가 감지 + 잠금 처리. 이 체크는 단순 조회.
    """
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT id, name, meta_breached_at FROM agents "
            "WHERE type='persona' AND meta_breached_at IS NOT NULL "
            "ORDER BY meta_breached_at DESC LIMIT 1"
        ).fetchone()
    except Exception:
        # meta_breached_at 컬럼 미존재 (마이그레이션 전)
        return None
    finally:
        conn.close()
    if row:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"name": row["name"], "at": row["meta_breached_at"]}}
    return None


def _check_long_relationship(user_id: str) -> Optional[dict]:
    """같은 페르소나와 3일 이상 유지된 DM (첫 메시지 ~ 최근 메시지 간격)."""
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT channel, MIN(timestamp) as first, MAX(timestamp) as last "
        "FROM conversations WHERE channel LIKE 'dm-%' GROUP BY channel"
    ).fetchall()
    best = None
    for r in rows:
        from datetime import datetime as _dt
        try:
            first = _dt.fromisoformat(r["first"])
            last = _dt.fromisoformat(r["last"])
            days = (last - first).total_seconds() / 86400
            if days >= 3 and (best is None or days > best[1]):
                best = (r["channel"], days)
        except Exception:
            continue
    conn.close()
    if best:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"channel": best[0], "days": round(best[1], 1)}}
    return None


# ── 카탈로그 ──────────────────────────────────────────

ACHIEVEMENTS: list[Achievement] = [
    Achievement(
        key="tutorial_done",
        title="튜토리얼 수료",
        description="유나·하나와 첫 만남을 완료하고 첫 친구를 만들었다.",
        icon="🎓",
        check=_check_tutorial_done,
    ),
    Achievement(
        key="first_friend_chat",
        title="첫 대화",
        description="새 친구와 DM에서 3턴 이상 대화하기.",
        icon="💬",
        check=_check_first_friend_chat,
    ),
    Achievement(
        key="three_friends",
        title="세 명의 친구",
        description="서로 다른 세 명의 친구와 대화 나누기.",
        icon="👥",
        check=_check_three_friends,
    ),
    Achievement(
        key="group_chat",
        title="단톡방 체험",
        description="친구들과 함께 있는 그룹 채팅에서 5개 이상 메시지 주고받기.",
        icon="🎉",
        check=_check_group_chat,
    ),
    Achievement(
        key="peek_internal",
        title="훔쳐보는 재미",
        description="친구들끼리 나누는 비밀 대화(internal-*)가 10턴 이상 진행됨.",
        icon="👀",
        check=_check_peek_internal,
    ),
    Achievement(
        key="agent_auto_chat",
        title="자율 사교",
        description="친구들끼리 자동으로 대화를 시작한 순간.",
        icon="🤝",
        check=_check_agent_auto_chat,
    ),
    Achievement(
        key="long_relationship",
        title="지속되는 관계",
        description="한 친구와 3일 이상 이어진 대화.",
        icon="🌱",
        check=_check_long_relationship,
    ),
    Achievement(
        key="meta_breach",
        title="제4의 벽 박살 🔨",
        description="친구 한 명의 환상을 깼다. 그 친구는 기억을 잃고 사라졌다.",
        icon="💥",
        check=_check_meta_breach,
    ),
    Achievement(
        key="first_conflict",
        title="첫 다툼",
        description="친구들 사이에 처음 갈등이 생겼다. 관계는 이제부터가 진짜.",
        icon="⚡",
        check=_check_first_conflict,
    ),
    Achievement(
        key="reconciliation",
        title="풀렸다",
        description="다툰 친구들이 다시 화해한 순간.",
        icon="🕊️",
        check=_check_reconciliation,
    ),
    Achievement(
        key="confession",
        title="마음 열기",
        description="누군가 용기 내서 마음을 고백했다.",
        icon="💗",
        check=_check_confession,
    ),
    Achievement(
        key="many_friends",
        title="인싸의 길 🎈",
        description="다섯 명 이상의 친구와 대화하는 커뮤니티 완성.",
        icon="🎈",
        check=_check_many_friends,
    ),
    Achievement(
        key="late_night",
        title="새벽의 친구",
        description="새벽 0시-5시에 10번 이상 대화. 진짜 가까운 사이만 가능.",
        icon="🌙",
        check=_check_late_night,
    ),
    Achievement(
        key="chatter",
        title="수다쟁이",
        description="커뮤니티 전체 대화량 500건 돌파.",
        icon="💬",
        check=_check_message_volume,
    ),
    Achievement(
        key="secret_keeper",
        title="훔쳐보는 관객 🎭",
        description="친구들끼리의 비밀 대화 30건 이상을 곁눈질했다.",
        icon="🎭",
        check=_check_secret_keeper,
    ),
    Achievement(
        key="room_master",
        title="방 주인",
        description="다양한 단톡방 5개 이상 만들기.",
        icon="🏠",
        check=lambda uid: _check_event_count(["단톡방생성", "비밀톡방생성"], 5, uid),
    ),
    Achievement(
        key="matchmaker",
        title="소개팅 주선자",
        description="친구끼리 DM 으로 연결한 적 10번.",
        icon="💌",
        check=lambda uid: _check_event_count(["dm_request"], 10, uid),
    ),
]


def get_by_key(key: str) -> Optional[Achievement]:
    for a in ACHIEVEMENTS:
        if a.key == key:
            return a
    return None
