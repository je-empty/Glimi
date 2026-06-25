"""POST 엔드포인트 (mutations) — trash, channel 조작, 에이전트 설정.

서버 start/stop/restart 는 플랫폼 supervisor 담당 → 여기 없음.
"""
from .context import maintenance_on, maintenance_off, require_server_stopped


def api_action_channel_clear(body: dict, community_id: str) -> dict:
    """채널의 DB 메시지만 삭제 (Discord 유지)."""
    from community import db
    channel = (body.get("channel") or "").strip()
    if not channel:
        return {"error": "missing_channel"}
    try:
        result = db.delete_channel_data(channel)
        return {"ok": True, "deleted": result}
    except Exception as e:
        return {"error": "exception", "message": str(e)}


def api_action_channel_delete(body: dict, community_id: str) -> dict:
    """채널 DB + Discord 양쪽 삭제."""
    from community import db
    channel = (body.get("channel") or "").strip()
    if not channel:
        return {"error": "missing_channel"}

    try:
        db_result = db.delete_channel_data(channel)
    except Exception as e:
        return {"error": "db_delete_failed", "message": str(e)}

    try:
        conn = db.get_conn()
        conn.execute("DELETE FROM channels WHERE channel = ?", (channel,))
        conn.commit()
        conn.close()
    except Exception:
        pass

    return {
        "ok": True,
        "db": db_result,
        "note": "Discord 채널은 남아있음 — 봇 실행 중이면 다음 sync 때 자동 정리됨",
    }


def api_action_trash_message(body: dict, community_id: str) -> dict:
    from community import db
    channel = (body.get("channel") or "").strip()
    message_id = body.get("message_id")
    if not channel:
        return {"error": "missing_channel"}
    try:
        ids = [int(message_id)] if message_id else None
        db.trash_messages(channel, message_ids=ids)
        return {"ok": True}
    except Exception as e:
        return {"error": "exception", "message": str(e)}


def api_action_trash_list(body: dict, community_id: str) -> dict:
    from community import db
    try:
        return {"ok": True, "items": db.trash_list()}
    except Exception as e:
        return {"error": "exception", "message": str(e)}


def api_action_trash_restore(body: dict, community_id: str) -> dict:
    from community import db
    trash_id = body.get("trash_id")
    if trash_id is None:
        return {"error": "missing_trash_id"}
    try:
        return {"ok": True, "result": db.trash_restore(int(trash_id))}
    except Exception as e:
        return {"error": "exception", "message": str(e)}


def api_action_trash_empty(body: dict, community_id: str) -> dict:
    from community import db
    try:
        db.trash_empty()
        return {"ok": True}
    except Exception as e:
        return {"error": "exception", "message": str(e)}


def api_action_set_agent_model(body: dict, community_id: str) -> dict:
    """에이전트 model override 설정/해제 — 실시간 (재시작 불필요, 다음 턴 반영).

    POST body: {"agent_id": "agent-persona-001", "model": "claude-haiku-4-5"}
               {"agent_id": "...", "model": ""}  → override 해제 (type 기본값)
    persona / mgr / creator / dev 모두 허용. _resolve_agent_model 이 DB override 우선 사용.
    """
    from community import db as _db
    _SWITCHABLE = {"persona", "mgr", "creator", "dev"}
    aid = (body.get("agent_id") or "").strip()
    model = (body.get("model") or "").strip()
    if not aid:
        return {"ok": False, "error": "agent_id required"}
    try:
        agent = _db.get_agent(aid)
        if not agent:
            return {"ok": False, "error": "agent not found"}
        if agent.get("type") not in _SWITCHABLE:
            return {"ok": False, "error": f"model override not allowed for type={agent.get('type')}"}
    except Exception as e:
        return {"ok": False, "error": f"agent lookup failed: {e}"}
    try:
        from community.core.runtime import AVAILABLE_MODELS
        valid_ids = {m["id"] for m in AVAILABLE_MODELS}
    except Exception:
        valid_ids = set()
    if model and valid_ids and model not in valid_ids:
        return {"ok": False, "error": f"unknown model: {model}"}
    try:
        ok = _db.set_agent_model_override(aid, model)
        if not ok:
            return {"ok": False, "error": "set override failed"}
        return {"ok": True, "agent_id": aid, "model": model or "(default)"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
