"""GET 엔드포인트 — snapshot, agent, channel, logs, health, dev, usage, achievements, i18n.

원본: scripts/web_dashboard.py lines 4149-4316 (api_*)
"""
import json
from pathlib import Path

from .context import read_query, with_community

ROOT = Path(__file__).resolve().parent.parent.parent.parent


def api_snapshot(path: str) -> dict:
    def _run():
        from src.core import monitor
        snap = monitor.snapshot()
        # demo 커뮤니티는 실제 봇이 안 돌아도 "운영 중" 처럼 보여야 함 (시연용).
        # 자체 UI 코드는 건드리지 않고 snapshot dict 의 플래그만 덮어씀 → 코드 바뀌어도 자동 반영.
        if snap.get("community_id") == "demo":
            try:
                from src.platform.demo_mock import inject as _demo_inject
                snap = _demo_inject(snap)
            except Exception:
                pass  # mock 실패해도 실제 스냅샷은 반환
        for c in snap["channels"]:
            c["last_ago"] = monitor.human_ago(c["last_ts"])
        return snap
    return with_community(path, _run)


def api_logs(path: str) -> dict:
    def _run():
        from src.core import monitor
        tail = int(read_query(path, "tail", "150") or 150)
        return {"lines": monitor.get_recent_system_logs(tail_lines=tail)}
    return with_community(path, _run)


def api_agent_activity(path: str) -> dict:
    def _run():
        from src.core import monitor
        aid = read_query(path, "id", "")
        if not aid:
            return {"logs": [], "chat": []}
        return {
            "logs": monitor.get_agent_thinking_logs(aid, n=5),
            "chat": monitor.get_agent_recent_chat(aid, limit=3),
        }
    return with_community(path, _run)


def api_agent_detail(path: str) -> dict:
    def _run():
        from src.core import monitor
        aid = read_query(path, "id", "")
        if not aid:
            return {"error": "missing id"}
        return monitor.get_agent_detail(aid)
    return with_community(path, _run)


def api_channel_detail(path: str) -> dict:
    def _run():
        from src.core import monitor
        name = read_query(path, "name", "")
        if not name:
            return {"error": "missing name"}
        return monitor.get_channel_detail(name)
    return with_community(path, _run)


def api_health(path: str) -> dict:
    def _run():
        from src.core import monitor
        return monitor.get_health()
    return with_community(path, _run)


def api_dev(path: str) -> dict:
    def _run():
        from src.core import monitor
        return monitor.get_dev_state()
    return with_community(path, _run)


def api_usage(path: str) -> dict:
    def _run():
        from src.core import monitor
        return monitor.get_usage_stats()
    return with_community(path, _run)


def api_achievements(path: str) -> dict:
    """현재 커뮤니티의 도전과제 진척도."""
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(path).query)

    def _run():
        try:
            from src.achievements import engine as _eng
            if q.get("recompute", ["0"])[0] in ("1", "true", "yes"):
                _eng.recompute_all()
            return _eng.dashboard_summary()
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e), "items": [], "done": 0, "total": 0}
    return with_community(path, _run)


def api_achievement_detail(path: str) -> dict:
    """단일 도전과제 상세 + trigger 메시지 주변 대화 (모달용)."""
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(path).query)
    key = (q.get("key", [""])[0] or "").strip()

    def _run():
        if not key:
            return {"error": "missing key"}
        try:
            from src.achievements import engine as _eng
            from src import db as _db
            from src.core.profile import get_user_id
            # 도전과제 row
            user_id = get_user_id() or "owner"
            conn = _db.get_conn()
            row = conn.execute(
                "SELECT key, state, progress_data, unlocked_at, completed_at "
                "FROM achievements WHERE user_id=? AND key=?",
                (user_id, key),
            ).fetchone()
            ach_def = next((a for a in _eng.dashboard_summary().get("items", [])
                            if a.get("key") == key), None)
            base = dict(ach_def) if ach_def else {"key": key}
            if row:
                import json as _json
                pd = {}
                try:
                    pd = _json.loads(row["progress_data"] or "{}")
                except Exception:
                    pass
                base["state"] = row["state"]
                base["progress"] = pd
                base["unlocked_at"] = row["unlocked_at"]
                base["completed_at"] = row["completed_at"]
            else:
                base["state"] = base.get("state", "locked")
                base["progress"] = base.get("progress") or {}

            # trigger 메시지 주변 대화 5건 ± (progress.message / progress.channel 기반)
            context = []
            p = base.get("progress") or {}
            channel = p.get("channel") or (p.get("channels") or [None])[0]
            trigger_msg = p.get("message") or p.get("agent_msg") or p.get("owner_msg")
            trigger_id = None
            if channel and trigger_msg:
                # message text 매칭으로 row id 찾기
                tr = conn.execute(
                    "SELECT id FROM conversations WHERE channel=? AND message LIKE ? "
                    "ORDER BY id ASC LIMIT 1",
                    (channel, f"%{trigger_msg[:60]}%"),
                ).fetchone()
                if tr:
                    trigger_id = tr["id"]
            if channel:
                if trigger_id is not None:
                    rows = conn.execute(
                        "SELECT id, channel, speaker, message, timestamp FROM conversations "
                        "WHERE channel=? AND id BETWEEN ? AND ? ORDER BY id ASC",
                        (channel, max(1, trigger_id - 5), trigger_id + 5),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT id, channel, speaker, message, timestamp FROM conversations "
                        "WHERE channel=? ORDER BY id DESC LIMIT 10",
                        (channel,),
                    ).fetchall()
                    rows = list(reversed(rows))
                # speaker → name resolve
                from src.core.profile import get_user_id, get_user_name
                _uid = get_user_id()
                _uname = get_user_name() or "오너"
                for r in rows:
                    d = dict(r)
                    sid = d["speaker"]
                    if sid == _uid:
                        d["speaker_name"] = _uname
                        d["is_owner"] = True
                    else:
                        a = _db.get_agent(sid)
                        d["speaker_name"] = (a or {}).get("name") or sid
                        d["is_owner"] = False
                    d["is_trigger"] = (trigger_id is not None and d["id"] == trigger_id)
                    context.append(d)
            conn.close()
            base["context"] = context
            base["trigger_channel"] = channel
            base["trigger_message"] = trigger_msg
            return base
        except Exception as e:
            import traceback
            traceback.print_exc()
            return {"error": str(e)}
    return with_community(path, _run)


def api_i18n(path: str) -> dict:
    """i18n/dashboard.{ko,en}.json 파일 로드."""
    from urllib.parse import parse_qs, urlparse
    q = parse_qs(urlparse(path).query)
    lang = (q.get("lang", ["ko"])[0] or "ko").lower()
    if lang not in ("ko", "en"):
        lang = "ko"
    fp = ROOT / "i18n" / f"dashboard.{lang}.json"
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}


def api_communities() -> dict:
    """각 커뮤니티의 running 상태까지 포함해서 반환.

    running 판별: 플랫폼 supervisor 등록 여부 + 로그 mtime fallback.
    """
    from src import community as _comm
    import time

    items = _comm.list_communities()
    active_id = _comm.get_community_id()
    now = time.time()

    # supervisor 에 등록된 running 목록
    try:
        from src.platform.supervisor import supervisor
        running_set = set(supervisor.list_running())
    except Exception:
        running_set = set()

    for it in items:
        # supervisor 우선, 없으면 log mtime 폴백
        if it["id"] in running_set:
            it["running"] = True
            it["last_log_age_sec"] = 0
        else:
            try:
                log_path = ROOT / "communities" / it["id"] / "logs" / "system.log"
                if log_path.exists():
                    age = now - log_path.stat().st_mtime
                    it["running"] = age < 120
                    it["last_log_age_sec"] = int(age)
                else:
                    it["running"] = False
                    it["last_log_age_sec"] = None
            except Exception:
                it["running"] = False
                it["last_log_age_sec"] = None

    return {"items": items, "active": active_id}


def api_models() -> dict:
    """사용 가능 모델 카탈로그 — 대시보드 dropdown 소스."""
    try:
        from src.core.runtime import AVAILABLE_MODELS
        return {"items": AVAILABLE_MODELS}
    except Exception as e:
        return {"error": str(e), "items": []}
