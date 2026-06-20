"""오너 메시지 실시간 프로필 자동 추출.

튜토리얼 collect_profile phase 에서 유나가 `update_profile` 툴을 제때 호출 안 할
때 대비한 안전망. 오너 메시지 올 때마다 패턴 매칭으로 즉시 DB 반영 → 다음 턴에
유나 프롬프트가 "?" 대신 실제 값 보게 됨 → 재질문 방지.

현재 커버: MBTI (regex). 향후 확장 (직업·취미·연애니어그램) 가능.
"""
from __future__ import annotations

import re

# 16 MBTI 유형 — 단어 경계로만 매칭 (ENTP, entp, INFJ 등)
_MBTI_PAT = re.compile(
    r"\b([EI][SN][TF][JP])\b",
    re.IGNORECASE,
)

# 명백한 부정 문맥 (MBTI 모른다고 하는 경우)
_NEGATIVE_MARKERS = ("모르", "몰라", "안 해", "안 봤", "안 찾", "안 해봤", "잘 몰")


def autoextract_profile(owner_message: str) -> dict:
    """오너의 단일 메시지에서 추출 가능한 프로필 필드 반환.

    반환: {"mbti": "ENTP", ...} 형태. 추출 불가면 빈 dict.
    호출측이 db.update_user 같은 걸로 반영.
    """
    if not owner_message or not owner_message.strip():
        return {}

    out: dict = {}
    text = owner_message.strip()

    # 부정 문맥이면 MBTI 추출 안 함
    lower = text.lower()
    neg = any(n in text for n in _NEGATIVE_MARKERS)

    mbti_match = _MBTI_PAT.search(text)
    if mbti_match and not neg:
        out["mbti"] = mbti_match.group(1).upper()

    return out


def apply_autoextract(owner_message: str) -> dict:
    """autoextract 결과를 users 테이블에 즉시 반영. 이미 저장된 값은 덮어쓰지 않음.

    반환: 실제로 저장된 필드 dict (변경 없으면 빈 dict).
    튜토리얼 collect_profile phase 에서만 호출 권장.
    """
    extracted = autoextract_profile(owner_message)
    if not extracted:
        return {}

    try:
        from community import db
    except Exception:
        return {}

    saved: dict = {}
    try:
        conn = db.get_conn()
        row = conn.execute("SELECT id, mbti FROM users LIMIT 1").fetchone()
        if not row:
            conn.close()
            return {}
        user_id = row["id"]
        for field, value in extracted.items():
            existing = row[field] if field in row.keys() else None
            if existing:
                continue  # 이미 값 있으면 덮어쓰지 않음
            conn.execute(f"UPDATE users SET {field} = ? WHERE id = ?", (value, user_id))
            saved[field] = value
        conn.commit()
        conn.close()
    except Exception as e:
        try:
            from community import log_writer
            log_writer.system(f"[profile_autoextract] DB 반영 실패: {e}")
        except Exception:
            pass
        return {}

    if saved:
        # 프로필 캐시 + 활성 에이전트 system prompt 동기화 — 안 하면 mgr 이 옛날 값으로 재질문.
        try:
            from community.core.profile import invalidate_cache as _inv
            _inv()
        except Exception:
            pass
        try:
            from community.core.runtime import runtime as _rt
            for aid in list(_rt._active_agents.keys()):
                _rt.refresh_agent(aid)
        except Exception:
            pass
        try:
            from community import log_writer
            log_writer.system(f"[profile_autoextract] 자동 저장: {saved}")
        except Exception:
            pass
    return saved
