"""
Cross-channel/universe scoping helpers.

페르소나의 universe 분리 + 환각 검출 + 오너 cross-channel 컨텍스트 헬퍼들.
ChatSupervisor (멈춘 대화 깨우기) 와 Runtime (일반 agent-to-agent 대화) 양쪽에서
공유 사용. Discord 의존 없음 — 코어 로직만.

기능:
  - looks_hallucinated(text): 발명 이벤트 클레임 감지
  - get_persona_universe / personas_in_same_universe: universe 태그 조회
  - channels_shared_with_owner: 페르소나가 오너와 함께 있던 채널 목록
  - owner_recent_end_signal: 오너 잠/종료 발화 검출 (universe 한정)
  - owner_recent_status: 오너 최근 활동 요약 (universe 한정, prompt 첨부용)
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from src import db


# ── 환각 검출 패턴 ─────────────────────────────────────
# 4가지 패턴 — 보수적, 명백한 케이스만 차단.
_HALLU_PAT_TIME_MSG = re.compile(
    r"(방금|지금|막\s|금방|이제\s)[^.\n]{0,20}?(DM|디엠|메시지|연락|카톡|문자|전화)[^.\n]{0,5}?(왔|받았|보냈)"
)
_HALLU_PAT_TIME_TOLD = re.compile(
    r"(방금|지금|막\s|금방)[^.\n]{0,20}?(말해줬|알려줬|얘기해줬|들었어|말했어|보내줬)"
)
_HALLU_PAT_DIRECT_MSG = re.compile(
    r"^\s*(어\s+)?(DM|디엠|카톡|메시지|문자|연락|전화)\s*(왔|받았)\s*[!~ㅋㅎ.?]?"
)
# 외부 인물 DM 수신 클레임 — 주어는 일반 호칭 + DB 의 페르소나 이름으로 동적 구성.
# 특정 커뮤니티의 캐릭터 이름을 코어에 하드코딩하지 않음 (5분 캐시).
_KINSHIP_TERMS = ("아빠", "엄마", "오빠", "누나", "언니", "형")
_EXTERNAL_SEND_CACHE: dict = {"pat": None, "ts": 0.0}
_EXTERNAL_SEND_TTL_SEC = 300.0


def _external_send_pattern() -> re.Pattern:
    import time
    now = time.monotonic()
    if (_EXTERNAL_SEND_CACHE["pat"] is not None
            and now - _EXTERNAL_SEND_CACHE["ts"] < _EXTERNAL_SEND_TTL_SEC):
        return _EXTERNAL_SEND_CACHE["pat"]
    names: list[str] = []
    try:
        conn = db.get_conn()
        rows = conn.execute("SELECT name FROM agents WHERE type='persona'").fetchall()
        conn.close()
        names = [re.escape(n) for r in rows if (n := (r["name"] or "").strip())]
    except Exception:
        pass  # DB 미초기화 등 — 일반 호칭만으로 동작
    subjects = "|".join(list(_KINSHIP_TERMS) + names)
    pat = re.compile(
        rf"({subjects})[^.\n]{{0,15}}?(DM|디엠|메시지|카톡|연락|문자)[^.\n]{{0,5}}?(왔어|받았어|보냈어|보내줬어)"
    )
    _EXTERNAL_SEND_CACHE["pat"] = pat
    _EXTERNAL_SEND_CACHE["ts"] = now
    return pat


# 오너 "취침/종료" 시그널 — 매치되면 그 시점부터 N시간 효력.
# "잘자/굿밤/자야겠다" 류 + "코 자자/얼른 자자" imperative + "이제 자야지" 류.
_OWNER_END_PATTERN = re.compile(
    r"잘\s*자|굿\s*밤|굿\s*나잇|자야겠다|자야지|자러\s*(간다|갈게|감|가)|"
    r"이만\s*(잔다|쉴게|자야지)|^\s*잔다\s*$|이제\s*(잔다|자야|자야겠)|"
    r"잘\s*거야|좀\s*잘게|자고\s*올게|"
    # imperative 형태 — "코 자자", "얼른 자자", "자자" 단독 등
    r"(코|이제|얼른|어서|빨리|다같이|다\s*같이)\s*자\s*자|^\s*자자[~!.\s]*$"
)


def looks_hallucinated(text: str) -> str | None:
    """응답이 명백한 환각 (컨텍스트에 없는 이벤트 발명) 으로 보이면 사유 반환.

    Returns: 매치 시 짧은 사유 문자열, 아니면 None.
    """
    t = (text or "").strip()
    if not t:
        return None
    for pat, label in (
        (_HALLU_PAT_TIME_MSG, "time-msg-arrival"),
        (_HALLU_PAT_DIRECT_MSG, "direct-msg-arrival"),
        (_external_send_pattern(), "external-send"),
        (_HALLU_PAT_TIME_TOLD, "time-told"),
    ):
        m = pat.search(t)
        if m:
            return f"{label}: {m.group()[:40]}"
    return None


def is_owner_end_signal(text: str) -> bool:
    """오너 발화에 잠/종료 시그널 포함 여부."""
    return bool(_OWNER_END_PATTERN.search(text or ""))


# ── Quiet hours (잠시간 — supervisor nudge 자제) ──────────
# 01:00 ~ 07:59 KST 동안 supervisor 가 페르소나 발화를 트리거하지 않음.
# 환각 방지 + 새벽 자율 대화 폭주 차단. 실제 사용자 활동 시간대 보호.
QUIET_HOUR_START = 1   # 1시부터
QUIET_HOUR_END = 8     # 8시 전까지 (01:00 ~ 07:59)


def is_quiet_hour() -> bool:
    """현재 KST 시각이 quiet hour 범위 안인지 (01:00 ~ 07:59).

    자정 가로지르는 범위도 처리. supervisor.check() 진입 직후 검사.
    """
    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    h = datetime.now(kst).hour
    # 자정 가로지르는 범위 — 23,0,1,2,3,4,5,6 시
    if QUIET_HOUR_START >= QUIET_HOUR_END:
        return h >= QUIET_HOUR_START or h < QUIET_HOUR_END
    return QUIET_HOUR_START <= h < QUIET_HOUR_END


def quiet_hour_label() -> str:
    """현재 quiet hour 인 경우 표시용 라벨 ('새벽 03시' 등). 아니면 빈 문자열."""
    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    if not is_quiet_hour():
        return ""
    h = now.hour
    if h < 5:
        period = "새벽"
    else:
        period = "이른 아침"
    return f"{period} {h:02d}시"


def _parse_iso_aware(ts: str):
    """ISO 타임스탬프 → tz-aware datetime. naive 면 UTC 로 간주."""
    try:
        dt = datetime.fromisoformat(ts)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ── universe 헬퍼 ──────────────────────────────────────

def get_persona_universe(persona_id: str) -> str | None:
    """agent_config.config_json 의 universe 필드 조회. 없으면 None."""
    import json as _json
    try:
        conn = db.get_conn()
        row = conn.execute(
            "SELECT config_json FROM agent_config WHERE agent_id=?", (persona_id,)
        ).fetchone()
        conn.close()
    except Exception:
        return None
    if not row or not row["config_json"]:
        return None
    try:
        cfg = _json.loads(row["config_json"])
    except Exception:
        return None
    return cfg.get("universe") or None


def personas_in_same_universe(persona_ids) -> set[str]:
    """주어진 페르소나들과 같은 universe 의 모든 페르소나 ID 집합.

    universe 미정 페르소나는 본인만 포함. universe 가 여러 개면 합집합.
    """
    pid_set = set(persona_ids or [])
    if not pid_set:
        return set()
    universes = set()
    for pid in pid_set:
        u = get_persona_universe(pid)
        if u:
            universes.add(u)
    if not universes:
        return pid_set  # universe 미정 — 본인만
    try:
        conn = db.get_conn()
        rows = conn.execute("SELECT id FROM agents WHERE type='persona'").fetchall()
        conn.close()
    except Exception:
        return pid_set
    result = set(pid_set)  # 본인 항상 포함
    for r in rows:
        u = get_persona_universe(r["id"])
        if u and u in universes:
            result.add(r["id"])
    return result


def channels_shared_with_owner(persona_ids) -> set[str]:
    """persona_ids 의 universe 와 같은 페르소나가 오너와 함께 발화한 모든 채널.

    dm-* 채널은 channels.participants 에 오너가 안 들어가는 모델 한계 때문에
    conversations 테이블 기반 교집합으로 채널 추출.
    """
    from src.core.profile import get_user_id

    user_id = get_user_id()
    pid_set = set(persona_ids or [])
    if not user_id or not pid_set:
        return set()
    expanded = personas_in_same_universe(pid_set)
    if not expanded:
        return set()
    try:
        conn = db.get_conn()
        owner_channels = {
            r["channel"] for r in conn.execute(
                "SELECT DISTINCT channel FROM conversations WHERE speaker=?", (user_id,)
            ).fetchall()
        }
        placeholders = ",".join("?" * len(expanded))
        persona_channels = {
            r["channel"] for r in conn.execute(
                f"SELECT DISTINCT channel FROM conversations WHERE speaker IN ({placeholders})",
                tuple(expanded)
            ).fetchall()
        }
        conn.close()
    except Exception:
        return set()
    return owner_channels & persona_channels


def owner_recent_end_signal(persona_ids, within_hours: float = 6.0):
    """오너의 최근 잠/종료 시그널 — persona_ids 가 함께 있던 채널 한정.

    Returns: (hours_ago, message, channel) tuple 또는 None.
    """
    from src.core.profile import get_user_id

    user_id = get_user_id()
    if not user_id:
        return None
    shared = channels_shared_with_owner(persona_ids)
    if not shared:
        return None
    try:
        conn = db.get_conn()
        placeholders = ",".join("?" * len(shared))
        rows = conn.execute(
            f"SELECT timestamp, message, channel FROM conversations WHERE speaker=? "
            f"AND channel IN ({placeholders}) "
            f"ORDER BY timestamp DESC LIMIT 30",
            (user_id, *shared)
        ).fetchall()
        conn.close()
    except Exception:
        return None
    now = datetime.now(timezone.utc)
    for r in rows:
        dt = _parse_iso_aware(r["timestamp"])
        if dt is None:
            continue
        hours_ago = (now - dt).total_seconds() / 3600.0
        if hours_ago > within_hours:
            return None
        if _OWNER_END_PATTERN.search(r["message"] or ""):
            return (hours_ago, r["message"][:80], r["channel"])
    return None


def owner_recent_status(persona_ids) -> str:
    """오너 최근 발화 — persona_ids 가 함께 있던 채널 한정 (universe-scoped).

    페르소나들이 본 적 없는 채널의 오너 발화는 노출 안 함.
    """
    from src.core.profile import get_user_id, get_user_display_name

    user_id = get_user_id()
    if not user_id:
        return ""
    shared = channels_shared_with_owner(persona_ids)
    if not shared:
        return ""
    try:
        conn = db.get_conn()
        placeholders = ",".join("?" * len(shared))
        row = conn.execute(
            f"SELECT timestamp, channel, message FROM conversations WHERE speaker=? "
            f"AND channel IN ({placeholders}) "
            f"ORDER BY timestamp DESC LIMIT 1",
            (user_id, *shared)
        ).fetchone()
        conn.close()
    except Exception:
        return ""
    if not row:
        return ""
    dt = _parse_iso_aware(row["timestamp"])
    if dt is None:
        return ""
    hours_ago = (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0
    owner = get_user_display_name() or "오너"
    if hours_ago < 1.0:
        age = f"{int(hours_ago * 60)}분 전"
    elif hours_ago < 24.0:
        age = f"{hours_ago:.1f}시간 전"
    else:
        age = f"{int(hours_ago / 24)}일 전"
    msg_preview = (row["message"] or "")[:80]
    return (
        f"\n[오너({owner}) 최근 상태] {age} #{row['channel']} 에서: \"{msg_preview}\". "
        f"그 이후 새 오너 메시지 없음 — 오너로부터 DM/연락 받은 것처럼 발명 절대 금지. "
        f"오너가 자러 갔거나 바쁘다면 그 사실에 맞춰 자연스럽게 대화."
    )


# ── C: 잠 시그널 시 universe 채널 강제 종료 ──────────────

def idle_internal_channels_for_universe(persona_ids, reason: str = "owner end signal") -> list[str]:
    """주어진 페르소나들과 같은 universe 의 internal-* 채널을 모두 status='idle' 처리.

    오너가 group/dm 에서 잠 시그널 발화 시 호출. 같은 universe 의 internal 대화가
    오너 부재 중 환각/모순 상태로 진행되는 것 방지.

    Returns: idle 처리한 채널 목록.
    """
    expanded = personas_in_same_universe(persona_ids)
    if not expanded:
        return []
    import json as _json
    try:
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT channel, participants, status FROM channels "
            "WHERE channel LIKE 'internal-%' AND status='running'"
        ).fetchall()
        idled = []
        for r in rows:
            try:
                parts = set(_json.loads(r["participants"] or "[]"))
            except Exception:
                continue
            if parts & expanded:
                conn.execute(
                    "UPDATE channels SET status='idle' WHERE channel=?",
                    (r["channel"],)
                )
                idled.append(r["channel"])
        conn.commit()
        conn.close()
        return idled
    except Exception:
        return []
