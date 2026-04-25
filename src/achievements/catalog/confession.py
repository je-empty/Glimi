"""마음 열기 — 에이전트가 오너에게 처음 마음 연 발화 (= 친구의 첫 고백)."""
import re as _re
from typing import Optional
from src import db
from src.achievements.base import Achievement


# 에이전트의 고백/마음 열기 발화. 1인칭 직접 고백조 한정.
# 단순 "좋아해" 단어만으론 trigger 안 함 (의문문·일반 발화 false positive 차단).
_CONFESS_PAT = _re.compile(
    r"(사랑해|고백|반했|"
    r"(?:나|내가|나도)\s*(?:너|당신)?\s*(?:를|이|가|에게)?\s*(?:사랑|좋아)|"
    r"(?:너|당신|니가|네가|니|네)\s*(?:를|에게|이|만)?\s*좋아\s*해|"
    r"너밖에|마음을?\s*(?:줘|받아)|진심이야|마음에\s*들어)",
    _re.IGNORECASE,
)


def check(user_id: str) -> Optional[dict]:
    conn = db.get_conn()
    # 1) events 테이블 (정통 trigger — Scene·supervisor 가 명시 기록한 경우)
    try:
        row = conn.execute(
            "SELECT participants, description FROM events "
            "WHERE event_type IN ('고백', '마음표현', '짝사랑') LIMIT 1"
        ).fetchone()
    except Exception:
        row = None
    if row:
        conn.close()
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {
                    "description": (row["description"] or "")[:80],
                    "source": "event",
                }}

    # 2) 대화 fallback — 에이전트의 첫 고백 발화 1건. **오너 (user_id) 발화는 제외**
    # (이 도전과제는 친구가 나한테 마음 연 순간 — 반대 방향은 무관).
    # 메타 박살된 페르소나 발화도 제외 (자각으로 사라진 친구는 카운트 X).
    try:
        rows = conn.execute(
            "SELECT id, channel, speaker, message FROM conversations "
            "WHERE speaker != ? "
            "AND (channel LIKE 'dm-%' OR channel LIKE 'mgr-%' OR channel LIKE 'group-%') "
            "AND speaker NOT IN (SELECT id FROM agents WHERE meta_breached_at IS NOT NULL) "
            "ORDER BY id ASC",
            (user_id,),
        ).fetchall()
    except Exception:
        rows = []
    conn.close()
    for r in rows:
        msg = r["message"] or ""
        # 의문문 제외 — "혼자 있는 거 좋아해?" 같은 false positive 방지
        if msg.rstrip().endswith("?") or msg.rstrip().endswith("?"):
            continue
        if _CONFESS_PAT.search(msg):
            agent = db.get_agent(r["speaker"])
            agent_name = (agent or {}).get("name", "") or r["speaker"]
            return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                    "progress_data": {
                        "agent": r["speaker"],
                        "agent_name": agent_name,
                        "channel": r["channel"],
                        "message": msg[:80],
                        "source": "conversation",
                    }}
    return None


ACHIEVEMENT = Achievement(
    key="confession",
    title="마음 열기",
    description="누군가 용기 내서 마음을 고백했다.",
    icon="💗",
    check=check,
)
