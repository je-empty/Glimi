"""마음 열기 — 에이전트가 오너에게 처음 마음 연 발화 (= 친구의 첫 고백)."""
import re as _re
from typing import Optional
from src import db
from src.achievements.base import Achievement


# 에이전트의 고백/마음 열기 발화. 1인칭 직접 고백조 한정.
# 단순 "좋아해" 단어만으론 trigger 안 함 (의문문·일반 발화 false positive 차단).
# `마음에 들어`/`마음에 들었어` 같은 generic phrase 제외 (Yuna 가 "빈이가 마음에 들어하니까"
# 같이 말해도 confession 아님). 1인칭 + 너 대상 직접 고백만.
_CONFESS_PAT = _re.compile(
    r"(사랑해|반했|"
    r"고백할게|고백하고|고백한다|"
    r"(?:나|내가|나도)\s*(?:너|당신)?\s*(?:를|이|가|에게)?\s*(?:사랑해|좋아해)|"
    r"(?:너|당신|니가|네가|니|네)\s*(?:를|에게|이|만)?\s*좋아해|"
    r"너밖에|마음을?\s*(?:줘|받아)|진심이야)",
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

    # 2) 대화 fallback — **persona** 의 첫 고백 발화 1건. **오너·mgr·creator·dev 제외**.
    # 이 도전과제는 친구(persona)가 나한테 마음 연 순간이지 매니저가 챙겨주는 거랑 무관.
    # 메타 박살된 페르소나도 제외 (자각으로 사라진 친구는 카운트 X).
    # 채널은 dm-* / group-* 한정 (mgr-* 채널은 매니저 영역이라 confession 맥락 아님).
    try:
        rows = conn.execute(
            "SELECT c.id, c.channel, c.speaker, c.message FROM conversations c "
            "JOIN agents a ON a.id = c.speaker "
            "WHERE c.speaker != ? "
            "AND a.type = 'persona' "
            "AND a.meta_breached_at IS NULL "
            "AND (c.channel LIKE 'dm-%' OR c.channel LIKE 'group-%') "
            "ORDER BY c.id ASC",
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
