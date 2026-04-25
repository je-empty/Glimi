"""마음 열기 — 고백·사랑·좋아해 류 표현 1+ (events 테이블 또는 대화 직접 감지)."""
import re as _re
from typing import Optional
from src import db
from src.achievements.base import Achievement


# 고백/마음 표현 발화 패턴 — 1인칭 + 2인칭 직접 고백조 한정. 단순 "좋아해" 단어만은 제외
# (의문문·일반 취향 발화 false positive 차단). "사랑해", "고백" 같은 강한 단어는 단독 OK.
_CONFESS_PAT = _re.compile(
    r"(사랑해|고백|반했|"
    r"(?:너|당신|니가|네가|니|네)\s*(?:를|에게|이|만)?\s*좋아|"
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

    # 2) 대화 패턴 fallback — 사용자 (또는 친구) 가 마음 표현한 첫 발화 1건.
    # 메타 박살된 페르소나 발화는 제외.
    try:
        rows = conn.execute(
            "SELECT id, channel, speaker, message FROM conversations "
            "WHERE (channel LIKE 'dm-%' OR channel LIKE 'mgr-%' OR channel LIKE 'group-%') "
            "AND speaker NOT IN (SELECT id FROM agents WHERE meta_breached_at IS NOT NULL) "
            "ORDER BY id ASC"
        ).fetchall()
    except Exception:
        rows = []
    conn.close()
    for r in rows:
        if _CONFESS_PAT.search(r["message"] or ""):
            # 발화자 이름 — 오너면 user_name, 에이전트면 agent.name
            speaker = r["speaker"]
            speaker_name = ""
            if speaker == user_id:
                from src.core.profile import get_user_name
                speaker_name = get_user_name() or "오너"
            else:
                agent = db.get_agent(speaker)
                speaker_name = (agent or {}).get("name", "") or speaker
            return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                    "progress_data": {
                        "speaker": speaker,
                        "speaker_name": speaker_name,
                        "channel": r["channel"],
                        "message": (r["message"] or "")[:80],
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
