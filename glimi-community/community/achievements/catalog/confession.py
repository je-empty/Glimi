"""마음 열기 — persona 가 오너에게 처음 마음 연 발화 (= 친구의 첫 고백).

Tier 2 (LLM judge):
  1. events 테이블 명시 기록 우선 (Tier 3 — scene·supervisor 가 기록)
  2. 없으면 candidate_pre_filter 로 confession 키워드 매치한 persona 발화 후보 좁힘
  3. Haiku judge 가 진짜 1인칭 직접 고백인지 batch 판정 (false-positive 차단)

이전 회귀: pure regex 가 "마음에 들어" 같은 generic phrase 까지 매치해서 매니저 (윤하나)
의 평범한 발화 ("빈이가 마음에 들어하니까") 가 confession 으로 잘못 trigger 됨.
"""
import re as _re
from typing import Optional
from community import db
from community.achievements.base import Achievement


# pre-filter 용 wide regex — LLM 호출 비용 통제 위해 후보 좁히기. 정밀 판정은 Haiku.
_CONFESS_KEYWORDS = _re.compile(
    r"(사랑|좋아해|반했|고백|마음.*(?:열|줘|받|들|와)|"
    r"너밖에|진심|짝사랑|혼자만 보고)",
    _re.IGNORECASE,
)


def check(user_id: str) -> Optional[dict]:
    """Tier 3 only — events 테이블에 명시 기록 있으면 즉시 done. 없으면 None
    (engine 이 candidate_pre_filter + judge_prompt 로 계속 진행)."""
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT participants, description FROM events "
            "WHERE event_type IN ('고백', '마음표현', '짝사랑') LIMIT 1"
        ).fetchone()
    except Exception:
        row = None
    finally:
        conn.close()
    if row:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {
                    "description": (row["description"] or "")[:80],
                    "source": "event",
                }}
    return None


def candidate_pre_filter(user_id: str) -> list[dict]:
    """persona 발화 중 confession 키워드 매치한 후보 (의문문 제외).
    judge 가 정밀 판정. mgr/creator/dev 는 제외 — 친구의 마음 열기 한정.
    """
    conn = db.get_conn()
    try:
        rows = conn.execute(
            "SELECT c.id, c.channel, c.speaker, c.message, c.timestamp, a.name as speaker_name "
            "FROM conversations c JOIN agents a ON a.id = c.speaker "
            "WHERE c.speaker != ? "
            "AND a.type = 'persona' "
            "AND a.meta_breached_at IS NULL "
            "AND (c.channel LIKE 'dm-%' OR c.channel LIKE 'group-%') "
            "ORDER BY c.id ASC",
            (user_id,),
        ).fetchall()
    except Exception:
        rows = []
    finally:
        conn.close()
    candidates = []
    for r in rows:
        msg = (r["message"] or "").strip()
        if not msg:
            continue
        # 의문문 제외 (질문은 confession 아님)
        if msg.rstrip().endswith("?") or msg.rstrip().endswith("?"):
            continue
        # 키워드 매치 안 하면 skip (LLM 호출 비용 절약)
        if not _CONFESS_KEYWORDS.search(msg):
            continue
        candidates.append({
            "id": r["id"],
            "channel": r["channel"],
            "speaker": r["speaker"],
            "speaker_name": r["speaker_name"] or r["speaker"],
            "message": msg,
            "timestamp": r["timestamp"],
        })
        if len(candidates) >= 8:  # batch 비용 통제
            break
    return candidates


_JUDGE_PROMPT = """You are classifying Korean chat messages.

Question: Is this message a Korean character's **first-person direct emotional confession** to another person — saying things like "(나) 너 좋아해" / "사랑해" / "마음 열렸어" / "너밖에 없어" / a clear love or deep-affection confession to a specific you?

Yes if: 1인칭이 너/당신/오빠/이름 대상으로 직접 사랑·좋아해·반함·진심·짝사랑·마음을 줘/열다 같은 표현. 진짜 confession 한 컷.

No if: 일반 친근감 표현 ("X가 마음에 들어", "맘에 든다", "좋아 좋아"), 의문문, 다른 사람 얘기 ("○○이 너 좋대"), 가벼운 칭찬, 농담, 영화·노래·음식 같은 외부 주제, 매니저가 챙겨주는 발화."""


ACHIEVEMENT = Achievement(
    key="confession",
    title="마음 열기",
    description="누군가 용기 내서 마음을 고백했다.",
    icon="💗",
    check=check,
    candidate_pre_filter=candidate_pre_filter,
    judge_prompt=_JUDGE_PROMPT,
)
