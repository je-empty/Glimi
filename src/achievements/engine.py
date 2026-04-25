"""
도전과제 엔진 — 메시지 로깅 시 훅을 걸어 진척도 재계산 + DB upsert.

성능 고려:
  - 매 메시지마다 모든 achievement check 를 돌리면 낭비. 따라서:
    1) 이미 done 상태인 건 스킵
    2) 일부 check 는 "channel 변화" 에만 관심 — 현재는 단순히 모두 돌림 (7개 정도라 미미)
    3) 훅 실행 중 예외는 조용히 무시 (로깅만)
"""
from __future__ import annotations

import json
from src import db
from src.achievements.definitions import ACHIEVEMENTS, SUPERVISORS, get_by_key


_installed = False


def _active_user_id() -> str | None:
    """현재 활성 오너의 user_id 를 meta.active_user_id 또는 users 첫 행에서 조회."""
    conn = db.get_conn()
    row = conn.execute("SELECT value FROM meta WHERE key='active_user_id'").fetchone()
    uid = row["value"] if row else None
    if not uid:
        row = conn.execute("SELECT id FROM users LIMIT 1").fetchone()
        uid = row["id"] if row else None
    conn.close()
    return uid


def recompute_all(user_id: str | None = None) -> dict:
    """전 도전과제 재계산. 새로 done 된 것 (key) 리스트 반환 → 축하 ping 등에 활용."""
    user_id = user_id or _active_user_id()
    if not user_id:
        return {"newly_done": [], "newly_unlocked": [], "user_id": None}

    newly_done: list[str] = []
    newly_unlocked: list[str] = []

    for ach in ACHIEVEMENTS:
        try:
            prev = db.get_achievement(user_id, ach.key)
            prev_state = prev["state"] if prev else "locked"
            if prev_state == "done":
                continue  # 이미 완료 — 재평가 불필요

            result = ach.check(user_id)
            if not result:
                continue

            new_state = result.get("state", prev_state)
            mark_unlocked = bool(result.get("mark_unlocked"))
            mark_completed = bool(result.get("mark_completed"))
            progress = result.get("progress_data")

            if new_state == prev_state and not mark_unlocked and not mark_completed:
                # 진척 data 변화만 있으면 저장, 상태 플래그 없이
                if progress is not None and (
                    prev is None or prev.get("progress_data") != json.dumps(progress, ensure_ascii=False)
                ):
                    db.upsert_achievement(user_id, ach.key, state=new_state, progress_data=progress)
                continue

            db.upsert_achievement(
                user_id, ach.key,
                state=new_state,
                progress_data=progress,
                mark_unlocked=mark_unlocked,
                mark_completed=mark_completed,
            )

            if mark_completed and prev_state != "done":
                newly_done.append(ach.key)
            elif mark_unlocked and prev_state == "locked":
                newly_unlocked.append(ach.key)
        except Exception as e:
            print(f"[achievements] {ach.key} check 실패: {e}")

    return {"newly_done": newly_done, "newly_unlocked": newly_unlocked, "user_id": user_id}


def _apply_supervisor_result(user_id: str, ach_key: str, result: dict) -> bool:
    """슈퍼바이저가 반환한 진척 dict 를 DB 에 upsert. newly_completed 면 True."""
    if not result:
        return False
    prev = db.get_achievement(user_id, ach_key)
    prev_state = prev["state"] if prev else "locked"
    if prev_state == "done":
        return False
    new_state = result.get("state", prev_state)
    mark_unlocked = bool(result.get("mark_unlocked"))
    mark_completed = bool(result.get("mark_completed"))
    progress = result.get("progress_data")
    db.upsert_achievement(
        user_id, ach_key,
        state=new_state, progress_data=progress,
        mark_unlocked=mark_unlocked, mark_completed=mark_completed,
    )
    return mark_completed and prev_state != "done"


def _on_message(channel: str, speaker: str, message: str):
    """log_message 훅. (1) 슈퍼바이저 fast-path → (2) recompute_all 안전망."""
    user_id = _active_user_id()
    # 1. 슈퍼바이저 fast-path — 정의된 도전과제만 즉시 갱신
    for sup in SUPERVISORS:
        try:
            res = sup.on_message(channel, speaker, message)
            if res and user_id and sup.key:
                _apply_supervisor_result(user_id, sup.key, res)
        except Exception as e:
            print(f"[achievements/supervisor:{sup.key}] {e}")
    # 2. 전체 recompute — supervisor 없는 도전과제 안전망
    try:
        recompute_all()
    except Exception as e:
        print(f"[achievements hook] {e}")


def install():
    """db.log_message 에 훅 등록. 중복 방지."""
    global _installed
    if _installed:
        return
    db.add_message_hook(_on_message)
    _installed = True


def dashboard_summary(user_id: str | None = None) -> dict:
    """대시보드 렌더용 — 전 과제 + 진척도 + 요약."""
    user_id = user_id or _active_user_id()
    if not user_id:
        return {"user_id": None, "items": [], "done": 0, "total": len(ACHIEVEMENTS)}

    # DB 에 없는 정의도 locked 상태로 포함시키기 위해 merge
    saved = {a["key"]: a for a in db.list_achievements(user_id)}
    items = []
    for ach in ACHIEVEMENTS:
        row = saved.get(ach.key)
        if row and row.get("progress_data"):
            try:
                row["progress_data"] = json.loads(row["progress_data"])
            except Exception:
                row["progress_data"] = None
        items.append({
            "key": ach.key,
            "title": ach.title,
            "description": ach.description,
            "icon": ach.icon,
            "state": row["state"] if row else "locked",
            "progress": row.get("progress_data") if row else None,
            "unlocked_at": row.get("unlocked_at") if row else None,
            "completed_at": row.get("completed_at") if row else None,
        })
    done = sum(1 for i in items if i["state"] == "done")
    return {"user_id": user_id, "items": items, "done": done, "total": len(ACHIEVEMENTS)}
