"""POST 엔드포인트 (mutations) — scan, sync, arrange, restore, trash, channel 조작, 에이전트 설정.

서버 start/stop/restart 는 플랫폼 supervisor 담당 → 여기 없음.
원본: scripts/web_dashboard.py lines 4363-4800 (api_action_*)
"""
from .context import maintenance_on, maintenance_off, require_server_stopped


def _channel_category(name: str) -> str:
    """채널 이름 → 기대 카테고리. src.bot.core._get_category_for_channel 의 사본 (의존성 회피)."""
    if name.startswith("mgr"):
        return "glimi-mgr"
    if name.startswith("internal-group-"):
        return "glimi-internal-group"
    if name.startswith("internal-dm-") or name.startswith("internal-"):
        return "glimi-internal-dm"
    if name.startswith("group-"):
        return "glimi-group"
    if name.startswith("dm-"):
        return "glimi-dm"
    return "glimi"


def _analyze_damage(scan_result: dict) -> dict:
    """scan 결과 + DB 데이터 → 손상 종류별 분류.

    DB 가 단일 진실원. 차이 종류:
      - missing_in_discord: DB 에 있는 채널이 Discord 에 없음 → 생성 필요
      - orphan_in_discord: Discord 에만 있는 glimi 채널 → 삭제 필요
      - orphan_outside: glimi 카테고리 밖에 있는 패턴 매칭 채널 → 삭제 필요
      - wrong_category: 채널이 잘못된 카테고리에 있음 → 이동 필요
      - msg_drift_db_more: DB 메시지 > Discord 메시지 (restore 필요)
      - msg_drift_discord_more: Discord 메시지 > DB 메시지 (Discord 잉여 삭제)
    """
    db_channels = {c["name"]: c for c in scan_result.get("db_channels", []) or []}
    discord_chs = {c["name"]: c for c in scan_result.get("discord_channels", []) or []}
    db_counts = scan_result.get("db_counts", {}) or {}

    missing_in_discord = sorted([n for n in db_channels if n not in discord_chs])
    orphan_in_discord = sorted([n for n in discord_chs if n not in db_channels])
    orphan_outside = list(scan_result.get("orphan_outside", []) or [])
    wrong_category = []
    msg_drift_db_more = []
    msg_drift_discord_more = []

    for name, info in discord_chs.items():
        expected_cat = _channel_category(name)
        actual_cat = info.get("category", "")
        if actual_cat and actual_cat != expected_cat:
            wrong_category.append({
                "name": name, "current": actual_cat, "expected": expected_cat,
            })

    # 메시지 카운트 비교 (양쪽 다 존재하는 채널만)
    for name in db_channels:
        if name not in discord_chs:
            continue
        d_count = discord_chs[name].get("msg_count")
        db_count = db_counts.get(name, 0)
        if d_count is None:
            continue
        if db_count > d_count:
            msg_drift_db_more.append({
                "name": name, "db": db_count, "discord": d_count, "diff": db_count - d_count,
            })
        elif d_count > db_count:
            msg_drift_discord_more.append({
                "name": name, "db": db_count, "discord": d_count, "diff": d_count - db_count,
            })

    total_issues = (
        len(missing_in_discord) + len(orphan_in_discord) + len(orphan_outside)
        + len(wrong_category) + len(msg_drift_db_more) + len(msg_drift_discord_more)
    )
    return {
        "missing_in_discord": missing_in_discord,
        "orphan_in_discord": orphan_in_discord,
        "orphan_outside": orphan_outside,
        "wrong_category": wrong_category,
        "msg_drift_db_more": msg_drift_db_more,
        "msg_drift_discord_more": msg_drift_discord_more,
        "total_issues": total_issues,
        "clean": total_issues == 0,
    }


def api_action_scan_discord(body: dict, community_id: str) -> dict:
    """Discord 채널별 메시지 카운트 조회 (read-only, 빠름)."""
    guard = require_server_stopped(community_id)
    if guard:
        return guard
    from src.core.sync import run_scan
    maintenance_on(community_id, "scan_discord")
    try:
        logs: list[str] = []
        result = run_scan(on_progress=lambda m: logs.append(m))
        # DB 측 채널 메타 + 메시지 카운트 — 손상 분석용
        try:
            from src import db as _db
            conn = _db.get_conn()
            db_counts: dict[str, int] = {}
            for row in conn.execute("SELECT channel, COUNT(*) FROM conversations GROUP BY channel").fetchall():
                db_counts[row[0]] = row[1]
            db_channels: list[dict] = []
            for row in conn.execute("SELECT channel, status FROM channels").fetchall():
                db_channels.append({
                    "name": row["channel"],
                    "status": row["status"] if "status" in row.keys() else None,
                    "msg_count": db_counts.get(row["channel"], 0),
                })
            conn.close()
            result["db_counts"] = db_counts
            result["db_channels"] = db_channels
        except Exception as e:
            result["db_counts"] = {}
            result["db_channels"] = []
            logs.append(f"DB 메타 조회 실패: {e}")

        # 손상 분석 — DB 가 단일 진실원 기준
        damage = _analyze_damage(result)
        result["damage"] = damage
        return {"ok": result.get("ok", False), "result": result, "logs": logs[-60:]}
    finally:
        maintenance_off(community_id)


def api_action_run_sync(body: dict, community_id: str) -> dict:
    """full sync 실행. body.channels (list) 로 특정 채널만 지정 가능."""
    guard = require_server_stopped(community_id)
    if guard:
        return guard
    from src.core.sync import run_sync
    selected = body.get("channels")
    channels_filter = set(selected) if isinstance(selected, list) and selected else None

    maintenance_on(community_id, "run_sync")
    try:
        logs: list[str] = []
        result = run_sync(on_progress=lambda m: logs.append(m), channels_filter=channels_filter)
        return {
            "ok": True,
            "result": result,
            "logs": logs[-40:],
            "channels_filter": sorted(list(channels_filter)) if channels_filter else None,
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": "exception", "message": str(e)}
    finally:
        maintenance_off(community_id)


def api_action_arrange_channels(body: dict, community_id: str) -> dict:
    """카테고리 + 채널 내부 순서 정렬."""
    guard = require_server_stopped(community_id)
    if guard:
        return guard
    from src.core.sync import run_arrange
    maintenance_on(community_id, "arrange_channels")
    try:
        logs: list[str] = []
        result = run_arrange(on_progress=lambda m: logs.append(m))
        return {"ok": result.get("ok", False), "result": result, "logs": logs[-40:]}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": "exception", "message": str(e)}
    finally:
        maintenance_off(community_id)


def api_action_restore(body: dict, community_id: str) -> dict:
    """DB 메시지를 Discord 에 재전송."""
    guard = require_server_stopped(community_id)
    if guard:
        return guard
    from src.core.sync import run_restore
    maintenance_on(community_id, "restore")
    try:
        logs: list[str] = []
        try:
            result = run_restore(on_progress=lambda m: logs.append(m))
        except TypeError:
            result = run_restore()
        return {"ok": True, "result": result, "logs": logs[-20:]}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": "exception", "message": str(e)}
    finally:
        maintenance_off(community_id)


def api_action_channel_clear(body: dict, community_id: str) -> dict:
    """채널의 DB 메시지만 삭제 (Discord 유지)."""
    from src import db
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
    from src import db
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
    from src import db
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
    from src import db
    try:
        return {"ok": True, "items": db.trash_list()}
    except Exception as e:
        return {"error": "exception", "message": str(e)}


def api_action_trash_restore(body: dict, community_id: str) -> dict:
    from src import db
    trash_id = body.get("trash_id")
    if trash_id is None:
        return {"error": "missing_trash_id"}
    try:
        return {"ok": True, "result": db.trash_restore(int(trash_id))}
    except Exception as e:
        return {"error": "exception", "message": str(e)}


def api_action_trash_empty(body: dict, community_id: str) -> dict:
    from src import db
    try:
        db.trash_empty()
        return {"ok": True}
    except Exception as e:
        return {"error": "exception", "message": str(e)}


def api_action_set_agent_model(body: dict, community_id: str) -> dict:
    """에이전트 model override 설정/해제. 페르소나만 허용.

    POST body: {"agent_id": "agent-persona-001", "model": "claude-haiku-4-5"}
               {"agent_id": "...", "model": ""}  → override 해제
    """
    from src import db as _db
    aid = (body.get("agent_id") or "").strip()
    model = (body.get("model") or "").strip()
    if not aid:
        return {"ok": False, "error": "agent_id required"}
    try:
        agent = _db.get_agent(aid)
        if not agent:
            return {"ok": False, "error": "agent not found"}
        if agent.get("type") != "persona":
            return {"ok": False, "error": f"model override not allowed for type={agent.get('type')} (persona only)"}
    except Exception as e:
        return {"ok": False, "error": f"agent lookup failed: {e}"}
    try:
        from src.core.runtime import AVAILABLE_MODELS
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
