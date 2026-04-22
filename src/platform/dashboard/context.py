"""커뮤니티 컨텍스트 전환 + reader-writer lock.

원본: scripts/web_dashboard.py lines 4048-4147
"""
import os
import threading
from typing import Optional
from urllib.parse import parse_qs, urlparse

# 커뮤니티 전환은 전역 상태 (GLIMI_COMMUNITY env, _comm._current_id, db.DB_PATH)
# 를 건드림 → 동시 요청이 서로 다른 커뮤니티를 지정하면 race로 섞임
# (예: private 요청 중 qa 요청이 env를 덮어쓰면 private이 qa DB를 읽게 됨).
# reader-writer 패턴:
#   - 같은 community 의 짧은 요청들은 직렬화되지만 서로 금방 풀림.
#   - 장시간 작업(sync/scan/restore) 은 "maintenance pin" 을 잡고 lock 해제 →
#     같은 community 의 read 는 계속 응답, 다른 community 의 switch 는 대기.
_COMMUNITY_LOCK = threading.Lock()
_MAINTENANCE_CV = threading.Condition(_COMMUNITY_LOCK)

# startup 시점에 resolve된 community — 이후 ?community= 없는 요청의 기본값
_STARTUP_COMMUNITY: Optional[str] = None

# 현재 프로세스에 active 인 community — idempotent switch 용
_ACTIVE_COMMUNITY: Optional[str] = None
# 장시간 mutation 이 잡고 있는 pin — 다른 community 로의 switch 를 블록
_MAINTENANCE_COMMUNITY: Optional[str] = None


def set_startup_community(cid: Optional[str]) -> None:
    global _STARTUP_COMMUNITY
    _STARTUP_COMMUNITY = cid


def read_community(path: str) -> Optional[str]:
    q = parse_qs(urlparse(path).query)
    return q.get("community", [None])[0]


def read_query(path: str, key: str, default: Optional[str] = None) -> Optional[str]:
    q = parse_qs(urlparse(path).query)
    return q.get(key, [default])[0]


def _apply_community(cid: Optional[str]) -> None:
    """실제 프로세스 전역 상태 전환 + 캐시 invalidate. lock 안에서만 호출."""
    if cid:
        os.environ["GLIMI_COMMUNITY"] = cid
    from src import community as _comm
    if cid:
        _comm.set_community(cid)
    try:
        import src.db as _db
        _db.DB_PATH = None
    except Exception:
        pass
    try:
        # log_writer 도 커뮤니티별 logs 디렉토리를 전역변수에 캐싱 — 전환 시 리셋 필수.
        # 이거 안 하면 is_thinking/is_speaking 이 엉뚱한 커뮤니티 logs 폴더를 봐서
        # thinking/speaking 인디케이터가 대시보드에 안 뜸.
        import src.log_writer as _lw
        _lw.LOG_DIR = None
    except Exception:
        pass
    try:
        from src.core.profile import invalidate_cache as _inv_profile
        _inv_profile()
    except Exception:
        pass
    try:
        import src.bot as _bot
        if hasattr(_bot, "_webhook_cache"):
            _bot._webhook_cache.clear()
    except Exception:
        pass


def _set_active_community(cid: Optional[str]) -> None:
    """Idempotent 전환. 이미 active 면 캐시 invalidate 생략 → 같은 community 연속 요청 시 cache hit 유지.
    다른 community 의 maintenance pin 이 걸려 있으면 해제까지 대기 (lock 안에서 CV wait)."""
    global _ACTIVE_COMMUNITY
    target = cid
    while _MAINTENANCE_COMMUNITY is not None and target is not None and _MAINTENANCE_COMMUNITY != target:
        _MAINTENANCE_CV.wait()
    if _ACTIVE_COMMUNITY == target:
        return
    _apply_community(target)
    _ACTIVE_COMMUNITY = target


def with_community(path: str, fn):
    """URL ?community= 파라미터로 커뮤니티 전환 후 fn 호출.
    전역 상태 변경을 lock으로 직렬화 → race condition 방지."""
    cid = read_community(path) or _STARTUP_COMMUNITY
    with _COMMUNITY_LOCK:
        _set_active_community(cid)
        return fn()


def with_community_nonblocking(path: str, fn):
    """장시간 실행 작업(sync/scan/restore/server 제어)용.
    community 전환 + maintenance pin 획득만 lock 안에서, 실제 작업은 lock 해제 후 수행.
    → 같은 community 의 snapshot/health 는 pin 무시하고 통과.
    → 다른 community 로의 switch 요청은 pin 해제까지 CV wait."""
    global _MAINTENANCE_COMMUNITY
    cid = read_community(path) or _STARTUP_COMMUNITY
    with _COMMUNITY_LOCK:
        _set_active_community(cid)
        _MAINTENANCE_COMMUNITY = cid
    try:
        return fn()
    finally:
        with _COMMUNITY_LOCK:
            _MAINTENANCE_COMMUNITY = None
            _MAINTENANCE_CV.notify_all()


# ── 헬퍼 (mutations 이 쓰는 state 체크) ─────────────────────────

def bot_running_for(community_id: str) -> bool:
    """플랫폼 supervisor 에 해당 커뮤니티 봇이 등록·실행 중인지."""
    try:
        from src.platform.supervisor import supervisor
        status = supervisor.status(community_id)
        return bool(status.get("running"))
    except Exception:
        return False


def require_server_stopped(community_id: str) -> Optional[dict]:
    """운영 중 mutation 방지. 실행 중이면 에러 dict 반환, 아니면 None."""
    if bot_running_for(community_id):
        return {
            "ok": False,
            "error": "server_running",
            "message": "커뮤니티 봇이 실행 중입니다. 먼저 중지하세요.",
        }
    return None


def maintenance_flag_path(community_id: str) -> str:
    """봇 루프가 체크하는 maintenance flag — communities/{id}/logs/.maintenance."""
    from src.community import COMMUNITIES_DIR
    return str(COMMUNITIES_DIR / community_id / "logs" / ".maintenance")


def maintenance_on(community_id: str, reason: str) -> None:
    from pathlib import Path
    p = Path(maintenance_flag_path(community_id))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(reason)


def maintenance_off(community_id: str) -> None:
    from pathlib import Path
    try:
        Path(maintenance_flag_path(community_id)).unlink()
    except FileNotFoundError:
        pass
