"""오너 프로필 이상치 감지 — 매니저(유나)가 자연스럽게 정정 요청할 단서 제공.

너무 빡세게 잡지 않음. 명백히 이상한 케이스만 (placeholder·magic value·구조적 결함).
정상 범위는 다양성 인정 (예: 30대 직장인, 50대 중년 등 모두 OK).
"""
from __future__ import annotations

import re as _re
from datetime import datetime
from typing import Optional


# placeholder·dash·언더스코어만 / 공백만 / 단일문자 등
_TRIVIAL_PAT = _re.compile(r"^[\s\-_.,]*$|^.{1}$")


def check_user_profile_anomalies(user_profile: dict) -> list[dict]:
    """오너 프로필을 검사해 이상 항목 dict 리스트 반환.

    각 dict: {"field": str, "value": str, "issue": str, "suggestion": str}
    값이 명백히 무의미하거나 비현실적인 경우만. 정상 범위는 무시.
    """
    if not user_profile:
        return []
    out: list[dict] = []

    # 이름 — placeholder/단일문자/특수문자만
    name = (user_profile.get("name") or "").strip()
    if not name:
        out.append({
            "field": "이름", "value": "(비어있음)",
            "issue": "이름이 등록 안 됨",
            "suggestion": "어떻게 불러줘야 할지 자연스럽게 물어봐.",
        })
    elif _TRIVIAL_PAT.match(name) and len(name) < 2:
        out.append({
            "field": "이름", "value": name or "(없음)",
            "issue": "placeholder/의미 없는 값 ('-', '_' 등)",
            "suggestion": "진짜 이름 알려달라고 자연스럽게 요청.",
        })

    # 별명 — 비어있는 경우 (선택사항이지만 있으면 친근). 모호해서 빡세게 검사 X.
    # 일단 검사 안 함 — 사용자 요청 없는 한.

    # 생년월일·나이 — 0001, 9999, 미래, 음수, 비현실 큰 값
    by = user_profile.get("birth_year")
    age = user_profile.get("age")
    now_year = datetime.now().year
    if by:
        try:
            by_int = int(by)
            if by_int < 1920 or by_int > now_year:
                out.append({
                    "field": "생년월일",
                    "value": f"{by}년생",
                    "issue": "비현실적 연도 (placeholder 가능성)",
                    "suggestion": "정확한 생년 자연스럽게 물어봐.",
                })
        except (ValueError, TypeError):
            out.append({
                "field": "생년월일",
                "value": str(by),
                "issue": "숫자 아님",
                "suggestion": "생년 다시 알려달라고 자연스럽게 요청.",
            })
    if age is not None:
        try:
            age_int = int(age)
            if age_int < 0 or age_int > 120:
                out.append({
                    "field": "나이",
                    "value": str(age),
                    "issue": "비현실적 값",
                    "suggestion": "실제 나이 자연스럽게 물어봐.",
                })
        except (ValueError, TypeError):
            pass

    return out


def format_anomaly_hint(anomalies: list[dict]) -> str:
    """anomaly list → 매니저 prompt 에 넣을 system-reminder 텍스트."""
    if not anomalies:
        return ""
    lines = ["[오너 프로필 이상치 — 대화 흐름에 어색하지 않게 자연스레 정정 요청. 빡세게 추궁 X, 가볍게 한 번.]"]
    for a in anomalies:
        lines.append(f"- {a['field']}: '{a['value']}' — {a['issue']}. {a['suggestion']}")
    return "\n".join(lines)
