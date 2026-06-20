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
from community import db
from community.achievements.definitions import ACHIEVEMENTS, SUPERVISORS, get_by_key


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

            # Tier 2 (LLM judge): pre_filter 로 후보 좁힌 후 Haiku batch 판정.
            # check 가 None 반환해도 judge 가 yes 하면 done 처리.
            result = None
            if ach.candidate_pre_filter and ach.judge_prompt:
                try:
                    candidates = ach.candidate_pre_filter(user_id) or []
                except Exception as e:
                    print(f"[achievements] {ach.key} pre_filter 실패: {e}")
                    candidates = []
                if candidates:
                    from community.achievements.judge import batch_classify
                    verdicts = batch_classify(ach.key, candidates, ach.judge_prompt)
                    # 첫 양성 → trigger
                    for cand, ok in zip(candidates, verdicts):
                        if ok:
                            result = {
                                "state": "done",
                                "mark_completed": True,
                                "mark_unlocked": True,
                                "progress_data": {
                                    "agent": cand.get("speaker"),
                                    "agent_name": cand.get("speaker_name") or cand.get("speaker"),
                                    "channel": cand.get("channel"),
                                    "message": (cand.get("message") or "")[:120],
                                    "timestamp": cand.get("timestamp"),
                                    "source": "llm_judge",
                                },
                            }
                            break

            # Tier 1/3 fallback — 기존 check (events 우선, 그 다음 logic)
            if result is None:
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
    """대시보드 렌더용 — 전 과제 + 진척도 + 요약.

    title/description 은 현재 커뮤니티 언어를 따른다. en 커뮤니티면
    catalog_i18n_en.ACHIEVEMENTS_EN 맵으로 치환 (키 없으면 한국어 fallback).
    이 함수는 with_community 컨텍스트 안에서 호출되므로 get_language() 가
    올바른 커뮤니티를 반영한다.
    """
    user_id = user_id or _active_user_id()
    if not user_id:
        return {"user_id": None, "items": [], "done": 0, "total": len(ACHIEVEMENTS)}

    # 커뮤니티 언어에 따른 title/description override 맵 선택
    en_map: dict = {}
    try:
        from community.community import get_language
        if get_language() == "en":
            from community.achievements.catalog_i18n_en import ACHIEVEMENTS_EN
            en_map = ACHIEVEMENTS_EN
    except Exception as e:
        print(f"[achievements] i18n 맵 로드 실패: {e}")

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
        tr = en_map.get(ach.key) or {}
        items.append({
            "key": ach.key,
            "title": tr.get("title") or ach.title,
            "description": tr.get("description") or ach.description,
            "icon": ach.icon,
            "state": row["state"] if row else "locked",
            "progress": row.get("progress_data") if row else None,
            "unlocked_at": row.get("unlocked_at") if row else None,
            "completed_at": row.get("completed_at") if row else None,
        })
    done = sum(1 for i in items if i["state"] == "done")
    return {"user_id": user_id, "items": items, "done": done, "total": len(ACHIEVEMENTS)}
