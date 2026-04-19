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
]


def get_by_key(key: str) -> Optional[Achievement]:
    for a in ACHIEVEMENTS:
        if a.key == key:
            return a
    return None
