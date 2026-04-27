"""POST 엔드포인트 (mutations) — scan, sync, arrange, restore, trash, channel 조작, 에이전트 설정.

서버 start/stop/restart 는 플랫폼 supervisor 담당 → 여기 없음.
원본: scripts/web_dashboard.py lines 4363-4800 (api_action_*)
"""
from .context import maintenance_on, maintenance_off, require_server_stopped


# 메시지 동기화 제외 채널 — 존재 여부만 체크하고, DB↔Discord 메시지 카운트 drift 는 무시.
# mgr-system-log 는 봇 런타임이 로그를 webhook 으로 쏘는 채널이라 매 기동마다 메시지 누적되고
# DB 기록과 달라 매번 "drift" 로 잡힘. 유저한테 의미 없는 노이즈.
MSG_SYNC_EXCLUDED = {"mgr-system-log"}


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
    """scan 결과 → 손상 분류.

    채널 존재 여부는 **`channels` 테이블 등록** 기준 (db_channels) — conversations 메시지 0건
    이라고 orphan 판정하면 mgr-system-log 처럼 대화 없는 관리 채널이 매번 찍힘.
    메시지 drift 는 별개로 counts(Discord) vs db_counts(DB conversations) 비교.

    판정:
      discord ∌ ch & db_channels ∋ ch        → missing_in_discord
      discord ∋ ch & db_channels ∌ ch        → orphan_in_discord
      양쪽 존재 & db_count != discord_count  → msg_drift

    부가 정보 (scan 이 제공하면 함께 표시):
      - orphan_outside: glimi 카테고리 밖 패턴 매칭
      - wrong_category: 채널 카테고리 오류
    """
    counts = scan_result.get("counts", {}) or {}
    db_counts = scan_result.get("db_counts", {}) or {}
    discord_chs = {c["name"]: c for c in scan_result.get("discord_channels", []) or []}
    db_channel_list = scan_result.get("db_channels", []) or []
    db_channel_names = {c["name"] for c in db_channel_list if c.get("name")}

    # 채널 존재 기준 set
    discord_set = set(discord_chs.keys()) | set(counts.keys())
    # db 쪽은 channels 테이블 기준 — 대화 있지만 channels 등록 안 된 과거 고아도 커버 위해 db_counts 키도 합침
    db_set = set(db_channel_names) | set(db_counts.keys())

    missing_in_discord: list = [ch for ch in sorted(db_set - discord_set)]
    orphan_in_discord: list = [ch for ch in sorted(discord_set - db_set)]

    # 메시지 drift — 양쪽 모두 존재하는 채널만. MSG_SYNC_EXCLUDED 는 drift 체크 스킵.
    # Tolerance: 작은 drift 는 "split mismatch" (DB join ↔ Discord split, 1줄 vs N줄) 등 알려진
    # 비파괴 차이라 ignore. 절대 5건 이하 AND 상대 5% 이하면 clean 처리.
    TOL_ABS = 5
    TOL_REL = 0.05
    msg_drift_db_more: list = []
    msg_drift_discord_more: list = []
    minor_drifts: list = []  # tolerance 안 인 채널 (참고용 노출, clean 판정 영향 X)
    for ch in (discord_set & db_set):
        if ch in MSG_SYNC_EXCLUDED:
            continue
        db_count = db_counts.get(ch, 0)
        d_count = counts.get(ch, 0)
        diff = db_count - d_count
        if diff == 0:
            continue
        abs_diff = abs(diff)
        denom = max(db_count, d_count, 1)
        rel = abs_diff / denom
        is_significant = abs_diff > TOL_ABS or rel > TOL_REL
        entry = {"name": ch, "db": db_count, "discord": d_count, "diff": abs_diff}
        if not is_significant:
            minor_drifts.append({**entry, "signed_diff": diff})
            continue
        if diff > 0:
            msg_drift_db_more.append(entry)
        else:
            msg_drift_discord_more.append(entry)

    # 부가 정보 — scan 이 제공하면 포함 (카테고리 오류 / glimi 밖 orphan)
    orphan_outside = list(scan_result.get("orphan_outside", []) or [])
    wrong_category = []
    for name, info in discord_chs.items():
        expected_cat = _channel_category(name)
        actual_cat = info.get("category", "")
        if actual_cat and actual_cat != expected_cat:
            wrong_category.append({
                "name": name, "current": actual_cat, "expected": expected_cat,
            })

    # Sync 탭 기준 'clean': counts/db_counts diff 가 어디에도 없음
    sync_clean = not (
        missing_in_discord or orphan_in_discord
        or msg_drift_db_more or msg_drift_discord_more
    )
    total_issues = (
        len(missing_in_discord) + len(orphan_in_discord)
        + len(msg_drift_db_more) + len(msg_drift_discord_more)
        + len(orphan_outside) + len(wrong_category)
    )
    return {
        "missing_in_discord": missing_in_discord,
        "orphan_in_discord": orphan_in_discord,
        "orphan_outside": orphan_outside,
        "wrong_category": wrong_category,
        "msg_drift_db_more": msg_drift_db_more,
        "msg_drift_discord_more": msg_drift_discord_more,
        "minor_drifts": minor_drifts,  # tolerance 안. 정보용. clean 판정 영향 X.
        "total_issues": total_issues,
        # 'clean' = significant 한 issue 0건. minor drift 는 ignore (split mismatch 등 비파괴).
        "clean": sync_clean,
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
