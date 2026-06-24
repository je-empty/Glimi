"""여러 도전과제에서 재사용되는 헬퍼.

언더스코어 prefix 라 catalog loader 가 스킵 (도전과제로 등록되지 않음).
"""
from __future__ import annotations

import re as _re
from typing import Optional

from community import db


# 매니저(서유나/윤하나) 만 참여하는 internal-* 채널 이름 식별.
# persona 자율 사교 도전과제 (peek_internal / agent_auto_chat) 에서 매니저간 대화는 제외.
MANAGER_NAMES = ("윤하나", "서유나", "유나", "하나")

# 버튜버 페르소나 식별용 background 키워드 — oshikatsu / hakooshi 공통.
VTUBER_KEYWORDS = ("버튜버", "VTuber", "vtuber", "V튜버", "브이튜버")


def get_persona_universes() -> dict[str, str]:
    """모든 active persona 의 universe 매핑 (없으면 미포함). universe_collector / new_universe 공유."""
    import json as _json
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT a.id, a.name, c.config_json FROM agents a "
        "LEFT JOIN agent_config c ON a.id = c.agent_id "
        "WHERE a.type='persona' AND a.status='active'"
    ).fetchall()
    conn.close()
    out: dict[str, str] = {}
    for r in rows:
        u = None
        if r["config_json"]:
            try:
                u = (_json.loads(r["config_json"]) or {}).get("universe")
            except Exception:
                u = None
        if u:
            out[r["name"]] = u
    return out


def get_vtuber_personas() -> list[dict]:
    """background 에 VTuber 키워드 포함된 active persona 목록 (id, name)."""
    pat = " OR ".join(f"background LIKE '%{kw}%'" for kw in VTUBER_KEYWORDS)
    conn = db.get_conn()
    rows = conn.execute(
        f"SELECT id, name FROM agents WHERE type='persona' AND status='active' AND ({pat})"
    ).fetchall()
    conn.close()
    return [{"id": r["id"], "name": r["name"]} for r in rows]


def is_manager_only_channel(ch_name: str) -> bool:
    if not ch_name:
        return False
    for prefix in ("internal-dm-", "internal-group-"):
        if ch_name.startswith(prefix):
            rest = ch_name[len(prefix):]
            parts = rest.split("-")
            return all(p in MANAGER_NAMES for p in parts if p)
    return False


def manager_owner_dm_channels() -> list[str]:
    """오너↔매니저 1:1 DM 채널 (dm-<유나/하나/세나>) + 레거시 mgr-* 채널.

    매니저(유나/하나/세나)도 페르소나처럼 dm-<이름> 채널을 쓴다. DB 의 mgr/creator/dev
    에이전트 이름에서 도출. 레거시 커뮤니티(구 mgr-dashboard/mgr-creator) 도 함께 반환해
    achievement 검사가 back-compat 유지."""
    chans: list[str] = []
    try:
        for a in db.list_agents():
            if a.get("type") in ("mgr", "creator", "dev"):
                chans.append(f"dm-{a['name']}")
    except Exception:
        pass
    # 레거시 back-compat (구 커뮤니티 채널명)
    chans.extend(["mgr-dashboard", "mgr-creator"])
    # 중복 제거 (순서 유지)
    seen: set[str] = set()
    out: list[str] = []
    for c in chans:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def check_event_count(event_types: list[str], threshold: int) -> Optional[dict]:
    """events 테이블의 특정 type 카운트 ≥ threshold 면 done."""
    conn = db.get_conn()
    placeholders = ",".join("?" * len(event_types))
    try:
        cnt = conn.execute(
            f"SELECT COUNT(*) AS c FROM events WHERE event_type IN ({placeholders})",
            event_types,
        ).fetchone()["c"]
    except Exception:
        cnt = 0
    finally:
        conn.close()
    if cnt >= threshold:
        return {"state": "done", "mark_completed": True, "mark_unlocked": True,
                "progress_data": {"count": cnt, "threshold": threshold}}
    if cnt > 0:
        return {"state": "unlocked", "mark_unlocked": True,
                "progress_data": {"count": cnt, "need": threshold}}
    return None


# 사랑 도전과제 — 채널 필터·메타박살 제외만 다른 두 케이스 (mgr_love, persona_love) 통합.
_LOVE_USER_PAT = _re.compile(
    r"(사랑해|좋아해|사귀자|연인|데이트.*하자|결혼.*하자|결혼생활|마음에\s*들어|반했)",
    _re.IGNORECASE,
)
_LOVE_AGENT_PAT = _re.compile(
    r"(나도\s*사랑|나도\s*좋아|사랑이.*맞|좋긴\s*하지|싫다고는\s*못|"
    r"심장.*쫄깃|얼굴.*빨개|부끄럽.*인정|좋은\s*거\s*맞아)",
    _re.IGNORECASE,
)


def check_love_exchange(user_id: str, channel_filter: str,
                        exclude_meta_breached: bool = False) -> Optional[dict]:
    """오너 사랑 고백 → 같은 채널 직후 10 발화 안 에이전트의 사랑형 응답 매칭."""
    conn = db.get_conn()
    extra = ""
    if exclude_meta_breached:
        extra = " AND speaker NOT IN (SELECT id FROM agents WHERE meta_breached_at IS NOT NULL)"
    rows = conn.execute(
        f"SELECT id, channel, speaker, message FROM conversations "
        f"WHERE channel LIKE ?{extra} ORDER BY id ASC",
        (channel_filter,),
    ).fetchall()
    conn.close()
    by_ch: dict[str, list] = {}
    for r in rows:
        by_ch.setdefault(r["channel"], []).append(r)
    for ch, msgs in by_ch.items():
        for i, m in enumerate(msgs):
            if m["speaker"] != user_id:
                continue
            if not _LOVE_USER_PAT.search(m["message"] or ""):
                continue
            for j in range(i + 1, min(i + 11, len(msgs))):
                nxt = msgs[j]
                if nxt["speaker"] == user_id:
                    continue
                if _LOVE_AGENT_PAT.search(nxt["message"] or ""):
                    # 에이전트 이름도 progress_data 에 명시 — UI 가 ID 변환 안 해도 됨.
                    agent_name = ""
                    try:
                        agent = db.get_agent(nxt["speaker"])
                        agent_name = (agent or {}).get("name", "") or ""
                    except Exception:
                        pass
                    return {
                        "state": "done", "mark_completed": True, "mark_unlocked": True,
                        "progress_data": {
                            "channel": ch,
                            "agent": nxt["speaker"],
                            "agent_name": agent_name,
                            "owner_msg": (m["message"] or "")[:60],
                            "agent_msg": (nxt["message"] or "")[:60],
                        },
                    }
    return None
