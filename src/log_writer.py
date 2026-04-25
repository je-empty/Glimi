"""
Project Glimi — 로그 라이터

로그:
  logs/system.log    — 시스템 이벤트 (유일한 로그 파일)
  logs/.thinking-{id} — 추론중 플래그 (파일 존재 = 추론중)
  logs/.dev-active    — 개발모드 플래그
"""
import os
import time
from datetime import datetime
from threading import Lock

from src import community

LOG_DIR = None  # community.get_log_dir()로 동적 결정
_lock = Lock()


def _get_log_dir() -> str:
    global LOG_DIR
    if LOG_DIR:
        return LOG_DIR
    LOG_DIR = community.get_log_dir()
    os.makedirs(LOG_DIR, exist_ok=True)
    return LOG_DIR


def get_log_dir() -> str:
    """외부 모듈용 — 현재 커뮤니티의 로그 디렉토리 반환"""
    return _get_log_dir()


def _ts():
    return datetime.now().strftime("%H:%M:%S")


def _append(path: str, line: str):
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


# ── System (유일한 로그 파일) ────────────────────────

def system(msg: str):
    _append(os.path.join(_get_log_dir(), "system.log"), f"[{_ts()}] {msg}")


def error(msg: str, exc: Exception = None):
    """에러 로그 — system.log + runtime_error.log 양쪽에 기록"""
    import traceback as _tb
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"[{ts}] {msg}"]
    if exc:
        lines.append(_tb.format_exc())
    entry = "\n".join(lines)
    _append(os.path.join(_get_log_dir(), "system.log"), f"[{_ts()}] ❌ {msg}")
    _append(os.path.join(_get_log_dir(), "runtime_error.log"), entry)


# ── Agent (no-op — 로그 파일 안 만듦) ────────────────

def agent_thinking(agent_id: str, msg: str):
    """추론 과정 — 시스템 로그에 기록"""
    system(f"💭 [{agent_id}] {msg}")


def agent_discord(agent_id: str, channel: str, msg: str):
    """디스코드 전송 — 시스템 로그에 기록"""
    system(f"📤 [{channel}] {msg}")


# ── Chat (no-op) ─────────────────────────────────────

def chat(channel: str, speaker_name: str, msg: str):
    """채팅 — 로그 파일 생성하지 않음"""
    pass


# ── Dev (no-op) ──────────────────────────────────────

def dev(msg: str):
    system(f"🔧 {msg}")


# ── Status flags ─────────────────────────────────────

def mark_thinking(agent_id: str, channel: str = ""):
    """thinking flag 파일에 채널명 기록 — 그래프 / 대시보드가 어느 채널에서 thinking 중인지 식별."""
    p = os.path.join(_get_log_dir(), f".thinking-{agent_id}")
    try:
        with open(p, "w") as f:
            f.write(channel or "")
    except OSError:
        pass


def mark_done(agent_id: str):
    p = os.path.join(_get_log_dir(), f".thinking-{agent_id}")
    try:
        os.remove(p)
    except FileNotFoundError:
        pass


def is_thinking(agent_id: str) -> bool:
    return os.path.exists(os.path.join(_get_log_dir(), f".thinking-{agent_id}"))


def thinking_channel(agent_id: str) -> str:
    """현재 thinking 중인 채널 이름. 안 하고 있거나 채널 정보 없으면 빈 문자열."""
    p = os.path.join(_get_log_dir(), f".thinking-{agent_id}")
    try:
        with open(p) as f:
            return f.read().strip()
    except (FileNotFoundError, OSError):
        return ""


def thinking_seconds(agent_id: str) -> float:
    """추론 시작 후 경과 초 (추론 중이 아니면 0)"""
    p = os.path.join(_get_log_dir(), f".thinking-{agent_id}")
    try:
        return time.time() - os.path.getmtime(p)
    except (FileNotFoundError, OSError):
        return 0


def mark_speaking(agent_id: str, channel: str = ""):
    p = os.path.join(_get_log_dir(), f".speaking-{agent_id}")
    try:
        with open(p, "w") as f:
            f.write(channel or "")
    except OSError:
        pass


def mark_speaking_done(agent_id: str):
    try:
        os.remove(os.path.join(_get_log_dir(), f".speaking-{agent_id}"))
    except FileNotFoundError:
        pass


def speaking_channel(agent_id: str) -> str:
    p = os.path.join(_get_log_dir(), f".speaking-{agent_id}")
    try:
        with open(p) as f:
            return f.read().strip()
    except (FileNotFoundError, OSError):
        return ""


def is_speaking(agent_id: str) -> bool:
    return os.path.exists(os.path.join(_get_log_dir(), f".speaking-{agent_id}"))


def speaking_seconds(agent_id: str) -> float:
    p = os.path.join(_get_log_dir(), f".speaking-{agent_id}")
    try:
        return time.time() - os.path.getmtime(p)
    except (FileNotFoundError, OSError):
        return 0


def mark_bot_ready():
    try:
        open(os.path.join(_get_log_dir(), ".bot-ready"), "w").close()
    except OSError:
        pass


def clear_bot_ready():
    try:
        os.remove(os.path.join(_get_log_dir(), ".bot-ready"))
    except FileNotFoundError:
        pass


def is_bot_ready() -> bool:
    return os.path.exists(os.path.join(_get_log_dir(), ".bot-ready"))


def mark_tutorial():
    try:
        open(os.path.join(_get_log_dir(), ".tutorial"), "w").close()
    except OSError:
        pass


def mark_tutorial_done():
    """유나 첫 인사 완료 시점 마킹 (대시보드용 '봇 준비 완료' 시그널).
    실제 튜토리얼 전체 완료는 mark_tutorial_complete()를 사용."""
    try:
        os.remove(os.path.join(_get_log_dir(), ".tutorial"))
    except FileNotFoundError:
        pass
    try:
        open(os.path.join(_get_log_dir(), ".tutorial-done"), "w").close()
    except OSError:
        pass


def mark_tutorial_complete():
    """튜토리얼 전체 완료 마킹 — phase == 'complete'로 전환될 때만 호출."""
    try:
        open(os.path.join(_get_log_dir(), ".tutorial-complete"), "w").close()
    except OSError:
        pass


def is_tutorial() -> bool:
    return os.path.exists(os.path.join(_get_log_dir(), ".tutorial"))


def is_tutorial_done() -> bool:
    return os.path.exists(os.path.join(_get_log_dir(), ".tutorial-done"))


def is_tutorial_complete() -> bool:
    return os.path.exists(os.path.join(_get_log_dir(), ".tutorial-complete"))


def mark_dev_active():
    try:
        open(os.path.join(_get_log_dir(), ".dev-active"), "w").close()
    except OSError:
        pass


def mark_dev_done():
    try:
        os.remove(os.path.join(_get_log_dir(), ".dev-active"))
    except FileNotFoundError:
        pass


def is_dev_active() -> bool:
    return os.path.exists(os.path.join(_get_log_dir(), ".dev-active"))


# ── Utility ──────────────────────────────────────────

def tail(path: str, n: int = 20) -> list[str]:
    """파일의 마지막 n줄"""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        return [l.rstrip("\n") for l in lines[-n:]]
    except Exception:
        return []


def clear_flags():
    """모든 상태 플래그 정리 (시작 시 호출)"""
    log_dir = _get_log_dir()
    if not os.path.exists(log_dir):
        return
    for name in os.listdir(log_dir):
        if name.startswith(".thinking-") or name.startswith(".speaking-") or name in (".dev-active", ".bot-ready", ".tutorial", ".tutorial-done", ".tutorial-complete"):
            try:
                os.remove(os.path.join(log_dir, name))
            except FileNotFoundError:
                pass
