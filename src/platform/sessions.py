"""세션 토큰 — itsdangerous 서명된 쿠키."""
from itsdangerous import BadSignature, SignatureExpired, TimestampSigner

from .config import get_secret_key, SESSION_MAX_AGE_SEC


def _signer() -> TimestampSigner:
    return TimestampSigner(get_secret_key())


def sign_session(user_id: int) -> str:
    return _signer().sign(str(user_id).encode("utf-8")).decode("utf-8")


def verify_session(token: str) -> int | None:
    """토큰 검증. 유효하면 user_id, 아니면 None."""
    if not token:
        return None
    try:
        raw = _signer().unsign(token.encode("utf-8"), max_age=SESSION_MAX_AGE_SEC)
        return int(raw.decode("utf-8"))
    except (BadSignature, SignatureExpired, ValueError):
        return None
