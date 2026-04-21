"""시간 유틸 — 프로젝트 전역 규칙.

**규칙**: DB·API·JSON 응답의 모든 타임스탬프는 **UTC aware ISO** (예: `2026-04-22T14:30:00+00:00`) 로 저장한다.
클라이언트(웹 대시보드 등)가 viewer 로컬 tz 로 변환해 표시하므로 서버는 tz 정보 포함이 필수.

**왜**: 외국인 유저·해외 배포 고려. 서버가 naive 로컬시간을 저장하면 뷰어가 어떤 tz 인지 알 수 없어 오해석됨.

**레거시**: 기존 DB 의 naive 문자열은 KST 라고 가정 (클라이언트 fmtLocal 이 fallback 처리).
신규 write 는 `now_utc_iso()` 로 해서 `+00:00` 꼬리를 붙인다.
"""
from datetime import datetime, timezone


def now_utc_iso() -> str:
    """UTC 기준 현재 시각 ISO (`...+00:00`). DB·API 에 기록할 때 이걸 사용."""
    return datetime.now(timezone.utc).isoformat()


def now_utc() -> datetime:
    """UTC aware datetime 객체."""
    return datetime.now(timezone.utc)


def to_utc_iso(dt: datetime) -> str:
    """임의 datetime → UTC aware ISO. naive 면 KST 로 가정 (레거시 호환)."""
    if dt.tzinfo is None:
        # KST 로 간주
        from datetime import timedelta
        dt = dt.replace(tzinfo=timezone(timedelta(hours=9)))
    return dt.astimezone(timezone.utc).isoformat()
