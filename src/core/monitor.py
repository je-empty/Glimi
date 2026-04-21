"""
Monitor — 커뮤니티 런타임 상태를 읽기전용으로 조회하는 순수 데이터 계층.

CLI dashboard (src/tui/dashboard.py)와 Web dashboard (src/platform/dashboard/)
둘 다 이 모듈을 소비. 렌더링만 각자, 데이터 로직은 단일 소스.

서버 제어(start/stop/restart)는 wizard 소관 — 여기서는 절대 건드리지 않음.

모든 함수는:
  - 예외 없이 최선 결과 반환 (빈 리스트/None)
  - DB/파일/프로세스만 읽음
  - side effect 없음 (DB write 금지)
"""
from __future__ import annotations

import json
import os
import subprocess as _sp
from datetime import datetime
from pathlib import Path
from typing import Optional

from src import db
from src import log_writer
from src import community


# ── 프로세스 상태 ──────────────────────────────────────

def _ps_has(pattern: str) -> bool:
    try:
        r = _sp.run(["ps", "ax", "-o", "command"], capture_output=True, text=True, timeout=3)
        for line in r.stdout.split("\n"):
            if pattern in line and "grep" not in line and "monitor.py" not in line:
                return True
    except Exception:
        pass
    return False


def _bot_alive_for_current_community() -> bool:
    """현재 active 커뮤니티의 봇이 살아있는지 판정.

    `ps ax` 로 discord_bot 프로세스 전체 검사는 다른 커뮤니티 봇까지 잡아
    다른 커뮤니티 조회 시 오탐이 발생 → 현재 커뮤니티의 system.log mtime
    기준으로 판정 (log_writer가 주기적으로 씀 → 활성 봇은 mtime이 120s 이내).

    대시보드가 "Stop Server" 로 봇을 죽였을 때 log mtime 이 아직 fresh 해서
    120초간 Running 으로 남는 문제 → stop marker 파일 (.bot-stopped) 을 확인:
    marker 가 있고 log mtime 보다 newer 면 stopped. 봇이 다시 뜨면 새 log 쓰면서
    log.mtime > marker.mtime 이 돼 자동으로 alive 로 복귀.
    """
    import time as _t
    from pathlib import Path as _Path
    try:
        cid = community.get_community_id()
        if not cid:
            return False
        log_path = community.COMMUNITIES_DIR / cid / "logs" / "system.log"
        log_mtime = log_path.stat().st_mtime if log_path.exists() else 0.0

        # Stop marker: dashboard 가 봇 kill 직후 touch. log.mtime 보다 최신이면 stopped.
        stop_marker = _Path(__file__).resolve().parent.parent.parent / "dev" / ".bot-stopped"
        if stop_marker.exists():
            if stop_marker.stat().st_mtime >= log_mtime:
                return False

        if log_mtime and (_t.time() - log_mtime) < 120:
            return True
    except Exception:
        pass
    # fallback: process 기반 (log 파일이 아직 없거나 예외 시)
    return _ps_has("src.discord_bot")


def get_bot_status() -> dict:
    """Glimi 봇 / QA 러너 / 테스트 유저 봇 프로세스 상태.

    bot_alive 는 현재 active 커뮤니티 기준 — 다른 커뮤니티 봇에 오탐하지 않도록.
    """
    test_user_alive = _ps_has("tests.e2e.test_user_bot")
    test_user_thinking = False
    test_user_speaking = False
    if test_user_alive:
        try:
            import os as _os
            from src.log_writer import _get_log_dir as _ld
            d = _ld()
            test_user_thinking = _os.path.exists(_os.path.join(d, ".thinking-test-user"))
            test_user_speaking = _os.path.exists(_os.path.join(d, ".speaking-test-user"))
        except Exception:
            pass
    return {
        "bot_alive": _bot_alive_for_current_community(),
        "runner_alive": _ps_has("tests.e2e.runner"),
        "test_user_alive": test_user_alive,
        "test_user_thinking": test_user_thinking,
        "test_user_speaking": test_user_speaking,
    }


# ── 메타/오너 ──────────────────────────────────────────

def get_meta_snapshot() -> dict:
    """meta 테이블 주요 키 일괄 조회."""
    out = {
        "tutorial_phase": "",
        "yuna_greeted": "",
        "active_user_id": "",
        "user_name": "",
        "discord_owner_id": "",
    }
    try:
        conn = db.get_conn()
        for r in conn.execute("SELECT key, value FROM meta").fetchall():
            if r["key"] in out:
                out[r["key"]] = r["value"] or ""
        if out["active_user_id"]:
            u = conn.execute(
                "SELECT name FROM users WHERE id=?", (out["active_user_id"],)
            ).fetchone()
            if u:
                out["user_name"] = u["name"] or ""
        conn.close()
    except Exception:
        pass
    return out


# ── 에이전트 ───────────────────────────────────────────

EMOTION_EMOJI = {
    "기쁨": "😊", "평온": "😌", "서운함": "😢", "화남": "😠",
    "설렘": "💗", "불안": "😰", "신남": "🤩", "슬픔": "😥",
    "지침": "😩", "짜증": "😤", "외로움": "🥺", "감동": "🥹",
    "분노": "😠", "기대": "✨", "실망": "😞", "사랑": "💖",
}


def _get_agent_model(agent_id: str, agent_type: str) -> dict:
    """에이전트 사용 모델 정보 조회.

    우선순위:
    1. agent_config 테이블에 model override 있으면 그것 (로컬 모델 스왑 대비)
    2. runtime.AGENT_MODELS에 타입 기본값
    3. 기본 "claude-sonnet-4-6"
    """
    # per-agent override 체크
    override_model = None
    try:
        conn = db.get_conn()
        row = conn.execute(
            "SELECT config_json FROM agent_config WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        conn.close()
        if row:
            import json as _json
            cfg = _json.loads(row["config_json"] or "{}")
            override_model = cfg.get("model")
    except Exception:
        pass

    # 기본값 — runtime.AGENT_MODELS 가 single source of truth.
    # 이전엔 type_defaults 가 별도 하드코딩돼 runtime 바꿔도 대시보드엔 반영 X (QA 회귀).
    try:
        from src.core.runtime import AGENT_MODELS as _AM
        default = _AM.get(agent_type, "claude-sonnet-4-6")
    except Exception:
        default = "claude-sonnet-4-6"
    model = override_model or default

    # provider 분류 (UI에서 색상 구분용)
    if model.startswith("claude-"):
        provider = "claude"
    elif model.startswith("gpt-") or model.startswith("openai"):
        provider = "openai"
    elif "llama" in model.lower() or "ollama" in model.lower():
        provider = "local"
    elif "/" in model or "local" in model.lower():
        provider = "local"
    else:
        provider = "other"

    return {"model": model, "provider": provider, "override": bool(override_model)}


def get_agents() -> list[dict]:
    """모든 에이전트 (mgr → creator → persona 순) + thinking/speaking 플래그."""
    try:
        agents = db.list_agents()
    except Exception:
        return []
    agents.sort(key=lambda a: (
        0 if a.get("type") == "mgr" else 1 if a.get("type") == "creator" else 2,
        a.get("id", ""),
    ))
    out = []
    for a in agents:
        emo = a.get("current_emotion") or "평온"
        aid = a["id"]
        atype = a.get("type", "")
        is_t = log_writer.is_thinking(aid)
        is_s = log_writer.is_speaking(aid)
        model_info = _get_agent_model(aid, atype)
        out.append({
            "id": aid,
            "type": atype,
            "name": a.get("name", aid),
            "status": a.get("status", ""),
            "emotion": emo,
            "emoji": EMOTION_EMOJI.get(emo, "・"),
            "intensity": a.get("emotion_intensity", 0) or 0,
            "mbti": a.get("mbti", ""),
            "age": a.get("age", 0) or 0,
            "last_active": a.get("last_active", ""),
            "thinking": is_t,
            "speaking": is_s,
            "thinking_seconds": log_writer.thinking_seconds(aid) if is_t else 0,
            "speaking_seconds": log_writer.speaking_seconds(aid) if is_s else 0,
            "model": model_info["model"],
            "provider": model_info["provider"],
            "model_override": model_info["override"],
        })
    return out


def get_agent_thinking_logs(agent_id: str, n: int = 5) -> list[str]:
    """system.log에서 특정 에이전트 관련 최근 로그 라인 (확장 카드용)."""
    lines = get_recent_system_logs(tail_lines=80)
    filtered = [l for l in lines if f"[{agent_id}]" in l]
    return filtered[-n:]


def get_agent_recent_chat(agent_id: str, channel_hint: str = "", limit: int = 3) -> list[dict]:
    """특정 에이전트가 주로 말하는 채널의 최근 메시지."""
    if not channel_hint:
        # 에이전트 타입으로 기본 채널 추정
        try:
            a = db.get_agent(agent_id)
            if a and a.get("type") == "mgr":
                channel_hint = "mgr-dashboard"
            elif a:
                channel_hint = f"dm-{a['name']}"
        except Exception:
            return []
    try:
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT c.speaker, c.message, c.timestamp, a.name as agent_name, u.name as user_name "
            "FROM conversations c "
            "LEFT JOIN agents a ON a.id = c.speaker "
            "LEFT JOIN users u ON u.id = c.speaker "
            "WHERE c.channel = ? "
            "ORDER BY c.timestamp DESC LIMIT ?",
            (channel_hint, limit),
        ).fetchall()
        conn.close()
    except Exception:
        return []
    return [
        {
            "speaker": r["agent_name"] or r["user_name"] or r["speaker"],
            "is_user": bool(r["user_name"]),
            "message": r["message"] or "",
            "timestamp": r["timestamp"] or "",
        }
        for r in reversed(rows)
    ]


# ── 채널 ───────────────────────────────────────────────

def get_channels() -> list[dict]:
    """DB 등록된 모든 채널 + 최근 활동 + 참여자 수."""
    try:
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT c.channel, c.participants, c.status, "
            "       COUNT(conv.id) as msg_count, MAX(conv.timestamp) as last_ts "
            "FROM channels c "
            "LEFT JOIN conversations conv ON conv.channel = c.channel "
            "GROUP BY c.channel "
            "ORDER BY COALESCE(MAX(conv.timestamp), c.created_at) DESC"
        ).fetchall()
        conn.close()
    except Exception:
        return []

    def _prefix_kind(name: str) -> str:
        if name.startswith("mgr-"):
            return "mgr"
        if name.startswith("internal-dm-"):
            return "internal-dm"
        if name.startswith("internal-group-"):
            return "internal-group"
        if name.startswith("dm-"):
            return "dm"
        if name.startswith("group-"):
            return "group"
        return "other"

    out = []
    for r in rows:
        try:
            parts = json.loads(r["participants"]) if r["participants"] else []
        except Exception:
            parts = []
        out.append({
            "name": r["channel"],
            "participants": parts,
            "participant_count": len(parts),
            "status": r["status"] or "idle",
            "msg_count": r["msg_count"] or 0,
            "last_ts": r["last_ts"] or "",
            "kind": _prefix_kind(r["channel"]),
            "internal": r["channel"].startswith("internal-"),
        })
    return out


# ── 대화 ───────────────────────────────────────────────

def get_recent_messages(limit: int = 30, channel: Optional[str] = None) -> list[dict]:
    """최근 대화. 시간순 ASC (오래된→최신). speaker는 에이전트/유저 이름으로 해석.

    정렬:
      SQL 에선 `timestamp DESC, id DESC` 로 상위 N 건 추출 (같은 초 타임스탬프
      ties 는 id DESC 로 깔끔히 정렬) → 최신 N 건을 확보.
      이후 Python 에서 reverse 해서 ASC(오래된→최신) 로 반환 — 채팅 UI 가 위에서
      아래로 시간순 읽기에 자연스럽고, slice(-N) 이 최신 N 건을 가져오는 JS 관용 사용.
    """
    try:
        conn = db.get_conn()
        if channel:
            rows = conn.execute(
                "SELECT c.id, c.speaker, c.channel, c.message, c.timestamp, "
                "       a.name as agent_name, u.name as user_name "
                "FROM conversations c "
                "LEFT JOIN agents a ON a.id = c.speaker "
                "LEFT JOIN users u ON u.id = c.speaker "
                "WHERE c.channel = ? "
                "ORDER BY c.timestamp DESC, c.id DESC LIMIT ?",
                (channel, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT c.id, c.speaker, c.channel, c.message, c.timestamp, "
                "       a.name as agent_name, u.name as user_name "
                "FROM conversations c "
                "LEFT JOIN agents a ON a.id = c.speaker "
                "LEFT JOIN users u ON u.id = c.speaker "
                "ORDER BY c.timestamp DESC, c.id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        # (기존 output 루프에서 reversed(rows) 로 ASC 변환 — 여기선 그대로 둠)
        total = conn.execute("SELECT COUNT(*) as c FROM conversations").fetchone()["c"]
        conn.close()
    except Exception:
        return []

    out = []
    for r in reversed(rows):
        who = r["agent_name"] or r["user_name"] or r["speaker"]
        out.append({
            "id": r["id"],
            "speaker_id": r["speaker"],
            "speaker": who,
            "is_user": bool(r["user_name"]),
            "channel": r["channel"],
            "message": r["message"] or "",
            "timestamp": r["timestamp"] or "",
        })
    # total 접근은 별도 조회로
    return out


def get_total_message_count() -> int:
    try:
        conn = db.get_conn()
        c = conn.execute("SELECT COUNT(*) as c FROM conversations").fetchone()["c"]
        conn.close()
        return c
    except Exception:
        return 0


# ── 이벤트 ─────────────────────────────────────────────

def get_events(limit: int = 20) -> list[dict]:
    try:
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT event_type, participants, description, created_at "
            "FROM events ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        conn.close()
    except Exception:
        return []
    return [
        {
            "type": r["event_type"] or "",
            "participants": r["participants"] or "",
            "description": r["description"] or "",
            "timestamp": r["created_at"] or "",
        }
        for r in rows
    ]


# ── 관계 ───────────────────────────────────────────────

def get_relationships() -> list[dict]:
    try:
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT * FROM relationships ORDER BY intimacy_score DESC"
        ).fetchall()
        conn.close()
    except Exception:
        return []
    return [dict(r) for r in rows]


# ── 시스템 로그 ────────────────────────────────────────

def get_recent_system_logs(tail_lines: int = 100) -> list[str]:
    """community logs/system.log 마지막 N줄."""
    try:
        log_dir = Path(community.get_log_dir())
    except Exception:
        return []
    path = log_dir / "system.log"
    if not path.exists():
        return []
    try:
        with open(path, "rb") as f:
            data = f.read()
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        return lines[-tail_lines:]
    except Exception:
        return []


# ── 유틸 ───────────────────────────────────────────────

def human_ago(iso_ts: str) -> str:
    if not iso_ts:
        return ""
    try:
        dt = datetime.fromisoformat(iso_ts)
    except Exception:
        return ""
    # 타임존 정규화:
    #  - aware datetime (신규 UTC 데이터 or SQLite CURRENT_TIMESTAMP 에 +00 추가된 경우) → 그대로 UTC 비교
    #  - naive (레거시 datetime.now() KST 또는 SQLite CURRENT_TIMESTAMP 둘 다 naive) → 기존 관례상 KST 로 가정
    from datetime import timezone, timedelta
    KST = timezone(timedelta(hours=9))
    if dt.tzinfo is None:
        # 레거시 호환: naive 는 KST 로 간주 후 UTC 변환
        dt = dt.replace(tzinfo=KST)
    dt_utc = dt.astimezone(timezone.utc)
    now_utc = datetime.now(timezone.utc)
    secs = (now_utc - dt_utc).total_seconds()
    if secs < 0:
        return "방금"
    if secs < 60:
        return f"{int(secs)}초 전"
    if secs < 3600:
        return f"{int(secs/60)}분 전"
    if secs < 86400:
        return f"{int(secs/3600)}시간 전"
    return f"{int(secs/86400)}일 전"


# ── 상세 뷰 ────────────────────────────────────────────

def _get_agent_gender(agent, profile) -> str:
    """성별 추출 — agents 테이블에 컬럼이 있으면 거기서, 없으면 profile.gender,
    그것도 없으면 relationship_to_owner.type 키워드로 휴리스틱 추론.

    DB 마이그레이션 전까지는 휴리스틱이 fallback. 정확도는 낮음.
    """
    # 1. agents 테이블 gender 컬럼 (마이그레이션 후)
    try:
        keys = agent.keys() if hasattr(agent, "keys") else []
        if "gender" in keys:
            g = agent["gender"]
            if g:
                return str(g)
    except Exception:
        pass
    # 2. profile.gender (JSON)
    if profile and profile.get("gender"):
        return str(profile["gender"])
    # 3. relationship_to_owner.type 키워드 휴리스틱
    rel = (profile or {}).get("relationship_to_owner") or {}
    rtype = (rel.get("type") or "").strip()
    if rtype:
        female_kw = ["여자친구", "여친", "와이프", "아내", "여사친", "여자", "girlfriend", "wife"]
        male_kw = ["남자친구", "남친", "남편", "남사친", "남자", "boyfriend", "husband"]
        for k in female_kw:
            if k in rtype:
                return "여성"
        for k in male_kw:
            if k in rtype:
                return "남성"
    return ""


def get_agent_detail(agent_id: str) -> dict:
    """에이전트 전체 상세: 프로필 + 관계 + 메모리 + 추론 로그 + 주 채널 채팅."""
    from src.core.profile import load_profile

    # test-user-bot 가상 에이전트 — DB에 없지만 상세뷰 제공
    if agent_id == "test-user-bot":
        return _get_test_user_detail()

    # sup:NAME 형식 — supervisor 가상 에이전트 상세뷰
    if agent_id.startswith("sup:"):
        return _get_supervisor_detail(agent_id[4:])

    try:
        agent = db.get_agent(agent_id)
    except Exception:
        agent = None
    if not agent:
        return {"error": "agent not found"}

    profile = load_profile(agent_id) or {}
    emo = agent.get("current_emotion") or "평온"
    is_t = log_writer.is_thinking(agent_id)
    is_s = log_writer.is_speaking(agent_id)
    model_info = _get_agent_model(agent_id, agent.get("type", "persona"))

    # 관계 (relationships 테이블)
    rels = []
    try:
        for r in db.get_all_relationships(agent_id):
            other_id = r["agent_b"] if r["agent_a"] == agent_id else r["agent_a"]
            other = db.get_agent(other_id)
            rels.append({
                "other_id": other_id,
                "other_name": (other or {}).get("name") or other_id,
                "type": r.get("type", ""),
                "intimacy": r.get("intimacy_score", 0),
                "dynamics": r.get("dynamics", "") or "",
            })
    except Exception:
        pass

    # 메모리 — 채널별로 묶음 (5 레이어 시스템: L1/L2/L3 + is_pinned + importance + entities)
    memories_by_channel: dict[str, list[dict]] = {}
    pinned_memories: list[dict] = []
    try:
        import json as _json
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT * FROM memories WHERE agent_id = ? "
            "ORDER BY channel, level DESC, id DESC",
            (agent_id,),
        ).fetchall()
        for m in rows:
            ch = m["channel"] or "general"
            keys = m.keys()
            def _jparse(v):
                if not v:
                    return []
                try:
                    x = _json.loads(v)
                    return x if isinstance(x, list) else []
                except Exception:
                    return []
            entry = {
                "id": m["id"],
                "level": m["level"],
                "content": m["content"],
                "created_at": m["created_at"] or "",
                "mem_type": m["mem_type"] if "mem_type" in keys else None,
                "importance": m["importance"] if "importance" in keys else 5,
                "is_pinned": bool(m["is_pinned"]) if "is_pinned" in keys else False,
                "related_entities": _jparse(m["related_entities"]) if "related_entities" in keys else [],
                "knows": _jparse(m["knows"]) if "knows" in keys else [],
            }
            memories_by_channel.setdefault(ch, []).append(entry)
            if entry["is_pinned"]:
                pinned_memories.append({**entry, "channel": ch})

        # 관계 변곡점 — 양방향
        rel_hist_rows = conn.execute(
            "SELECT * FROM relationship_history WHERE agent_a=? OR agent_b=? "
            "ORDER BY created_at DESC LIMIT 30",
            (agent_id, agent_id),
        ).fetchall()

        # agent_facts — 현재 유효한 것만
        fact_rows = conn.execute(
            "SELECT * FROM agent_facts WHERE agent_id=? AND valid_to IS NULL "
            "ORDER BY importance DESC, created_at DESC LIMIT 100",
            (agent_id,),
        ).fetchall()
        conn.close()

        relationship_history = [dict(r) for r in rel_hist_rows]
        facts = [dict(r) for r in fact_rows]
    except Exception as e:
        relationship_history = []
        facts = []
        print(f"[Monitor] memory detail 로드 실패: {e}")

    # 주 채널 이름
    atype = agent.get("type", "persona")
    if atype == "mgr":
        primary = "mgr-dashboard"
    elif atype == "creator":
        primary = "mgr-creator"
    else:
        primary = f"dm-{agent.get('name', '')}"

    # 추론 로그 (agent_id 태그 필터)
    sys_lines = get_recent_system_logs(tail_lines=300)
    thinking_logs = [l for l in sys_lines if f"[{agent_id}]" in l][-30:]

    # 주 채널 채팅
    primary_chat = get_recent_messages(limit=30, channel=primary)

    return {
        "id": agent_id,
        "name": agent.get("name", agent_id),
        "type": atype,
        "status": agent.get("status", ""),
        "emotion": emo,
        "emoji": EMOTION_EMOJI.get(emo, "・"),
        "intensity": agent.get("emotion_intensity", 0) or 0,
        "mbti": agent.get("mbti", "") or (profile.get("mbti", "") if profile else ""),
        "age": agent.get("age", 0) or 0,
        "birth_year": agent.get("birth_year", 0) or 0,
        "gender": _get_agent_gender(agent, profile),
        "enneagram": profile.get("enneagram", "") if profile else "",
        "traits": (profile.get("personality", {}) or {}).get("traits", []) if profile else [],
        "background": profile.get("background", "") if profile else "",
        "relationship_to_owner": profile.get("relationship_to_owner", {}) if profile else {},
        "thinking": is_t,
        "speaking": is_s,
        "thinking_seconds": log_writer.thinking_seconds(agent_id) if is_t else 0,
        "speaking_seconds": log_writer.speaking_seconds(agent_id) if is_s else 0,
        "last_active": agent.get("last_active", ""),
        "relationships": rels,
        "memories_by_channel": memories_by_channel,
        "pinned_memories": pinned_memories,
        "agent_facts": facts,
        "relationship_history": relationship_history,
        "thinking_logs": thinking_logs,
        "primary_channel": primary,
        "primary_chat": primary_chat,
        "model": model_info["model"],
        "provider": model_info["provider"],
        "model_override": model_info["override"],
    }


def _get_supervisor_detail(sup_name: str) -> dict:
    """Supervisor를 에이전트 상세 모달 포맷으로 반환."""
    sups = get_supervisors()
    sup = next((s for s in sups if s["name"] == sup_name), None)
    if not sup:
        return {"error": f"supervisor not found: {sup_name}"}

    # 추론 로그 = supervisor의 recent_logs
    thinking_logs = sup["recent_logs"]
    # primary_chat — 감시 대상 에이전트들의 최근 메시지 (있으면)
    primary_chat = []
    for aid in (sup["target_agents"] or [])[:3]:
        try:
            a = db.get_agent(aid)
            if not a:
                continue
            atype = a.get("type", "persona")
            ch = "mgr-dashboard" if atype == "mgr" else ("mgr-creator" if atype == "creator" else f"dm-{a['name']}")
            msgs = get_recent_messages(limit=5, channel=ch)
            primary_chat.extend(msgs)
        except Exception:
            continue
    primary_chat = primary_chat[-10:]

    status_emoji = "🔥" if sup["intervening"] else ("💭" if sup["active"] else "💤")
    emotion = "개입 중" if sup["intervening"] else ("감시 중" if sup["active"] else "대기")

    # 친화 표시명 매핑 (class_name 대신) — UI에 깔끔하게 보이도록
    display_name_map = {
        "tutorial": "Tutorial",
        "channel-conv": "Channel Conversation",
    }
    friendly_name = display_name_map.get(sup_name, sup_name)

    return {
        "id": f"sup:{sup_name}",
        "name": f"{sup['icon']} {friendly_name}",
        "type": "supervisor",
        "status": "active" if sup["active"] else "inactive",
        "emotion": emotion,
        "emoji": status_emoji,
        "intensity": 10 if sup["intervening"] else (5 if sup["active"] else 0),
        "mbti": "",
        "age": 0,
        "enneagram": "",
        "traits": ["백그라운드 감시", "비동기 실행", f"{sup['interval_sec']}초 주기"],
        "background": sup["description"],
        "relationship_to_owner": {},
        "thinking": sup["intervening"],
        "speaking": False,
        "thinking_seconds": sup["seconds_since_action"] or 0,
        "speaking_seconds": 0,
        "last_active": sup["last_action"] or "",
        "relationships": [
            {
                "other_id": aid,
                "other_name": (db.get_agent(aid) or {}).get("name", aid),
                "type": "감시 대상",
                "intimacy": 100 if sup["intervening"] else (60 if sup["active"] else 20),
                "dynamics": "intervention" if sup["intervening"] else "observing",
            }
            for aid in (sup["target_agents"] or [])
        ],
        "memories_by_channel": {},
        "thinking_logs": thinking_logs,
        "primary_channel": "(다수 채널 감시)",
        "primary_chat": primary_chat,
        # supervisor는 내부적으로 Haiku 기반 judge + SONNET 기반 inject 혼용
        "model": "claude-haiku-4-5 · claude-sonnet-4-6",
        "provider": "claude",
        "model_override": False,
        "synthetic": True,
        "is_supervisor": True,
    }


def _get_test_user_detail() -> dict:
    """QA test-user-bot의 가상 상세 정보."""
    import os as _os
    alive = _ps_has("tests.e2e.test_user_bot")
    # 실제 활동 상태 — test_user_bot이 .thinking-test-user / .speaking-test-user 토글
    log_dir = community.get_log_dir() if hasattr(community, "get_log_dir") else None
    is_thinking = False
    is_speaking = False
    if alive:
        try:
            from src.log_writer import _get_log_dir as _ld
            d = _ld()
            is_thinking = _os.path.exists(_os.path.join(d, ".thinking-test-user"))
            is_speaking = _os.path.exists(_os.path.join(d, ".speaking-test-user"))
        except Exception:
            pass

    # 환경변수에서 페르소나 정보
    name = _os.environ.get("QA_USER_NAME", "심재빈")
    nickname = _os.environ.get("QA_USER_NICKNAME", "빈이")
    age = _os.environ.get("QA_USER_AGE", "26")
    mbti = "ENTP"
    background = "QA 자동 테스트용 가상 유저 — 프로젝트를 전혀 모르는 신규 유저로 튜토리얼 시나리오를 재현함. Claude Haiku 모델로 실시간 응답 생성."

    # 이 agent가 남긴 메시지 (test-user가 DB에 speaker='test-user'로 log)
    primary_chat = get_recent_messages(limit=20)
    primary_chat = [m for m in primary_chat if m.get("is_user") and "심재빈" in (m.get("speaker") or "")][-15:]

    # 로그에서 test-user 관련 라인
    sys_lines = get_recent_system_logs(tail_lines=200)
    thinking_logs = [l for l in sys_lines if "test-user" in l.lower() or "TestUser" in l][-20:]

    return {
        "id": "test-user-bot",
        "name": f"{name} (QA)",
        "type": "persona",
        "status": "active" if alive else "inactive",
        "emotion": "신남" if alive else "평온",
        "emoji": "🤩" if alive else "😌",
        "intensity": 7 if alive else 0,
        "mbti": mbti,
        "age": int(age) if str(age).isdigit() else 26,
        "enneagram": "",
        "traits": ["ENTP", "QA 자동화", "메타 질문 challenger", "카톡 스타일"],
        "background": background,
        "relationship_to_owner": {},
        "thinking": is_thinking,
        "speaking": is_speaking,
        "thinking_seconds": 0,
        "speaking_seconds": 0,
        "last_active": "",
        "relationships": [],
        "memories_by_channel": {},
        "thinking_logs": thinking_logs,
        "primary_channel": "mgr-dashboard",
        "primary_chat": primary_chat,
        "model": "claude-haiku-4-5",
        "provider": "claude",
        "model_override": True,
        "synthetic": True,
    }


def get_channel_detail(channel_name: str) -> dict:
    """채널 상세: 참여자 + 전체 메시지."""
    try:
        participants = db.get_channel_participants(channel_name) or []
    except Exception:
        participants = []
    # 참여자 이름 resolve
    part_info = []
    for pid in participants:
        try:
            a = db.get_agent(pid)
            if a:
                part_info.append({"id": pid, "name": a.get("name", pid), "type": a.get("type", "")})
            else:
                part_info.append({"id": pid, "name": pid, "type": ""})
        except Exception:
            part_info.append({"id": pid, "name": pid, "type": ""})

    messages = get_recent_messages(limit=500, channel=channel_name)
    return {
        "name": channel_name,
        "participants": part_info,
        "messages": messages,
        "message_count": len(messages),
    }


# ── Health / Usage ──────────────────────────────────────

def get_health() -> dict:
    """프로세스/PID/디스크/로그 크기 + Glimi 프로세스 리소스 + 시스템 리소스."""
    from pathlib import Path as _P
    import shutil

    status = get_bot_status()

    # PID 파일
    pid_file = str(ROOT_DIR() / "dev" / ".bot.pid")
    pid: Optional[str] = None
    try:
        if os.path.exists(pid_file):
            with open(pid_file) as f:
                pid = f.read().strip()
    except Exception:
        pass

    # 로그 크기
    log_size = 0
    try:
        log_dir = _P(community.get_log_dir())
        sys_log = log_dir / "system.log"
        if sys_log.exists():
            log_size = sys_log.stat().st_size
    except Exception:
        pass

    # DB 크기
    db_size = 0
    try:
        db_path = _P(community.get_community_dir()) / "community.db"
        if db_path.exists():
            db_size = db_path.stat().st_size
    except Exception:
        pass

    # 디스크 여유
    disk_total, disk_used, disk_free = 0, 0, 0
    try:
        t, u, f = shutil.disk_usage(str(_P(community.get_community_dir())))
        disk_total, disk_used, disk_free = t, u, f
    except Exception:
        pass

    # 시스템 CPU/메모리 (psutil 있으면 세부)
    sys_cpu_pct = 0.0
    sys_mem_total, sys_mem_used, sys_mem_pct = 0, 0, 0.0
    sys_load = [0, 0, 0]
    glimi_cpu_pct = 0.0
    glimi_mem_bytes = 0
    glimi_proc_count = 0
    try:
        import psutil  # type: ignore
        sys_cpu_pct = psutil.cpu_percent(interval=0.1)
        vm = psutil.virtual_memory()
        sys_mem_total = vm.total
        sys_mem_used = vm.used
        sys_mem_pct = vm.percent
        try:
            sys_load = list(os.getloadavg())
        except Exception:
            pass

        # Glimi 관련 프로세스 합산 (src.discord_bot, tests.e2e.runner, test_user_bot)
        patterns = ("src.discord_bot", "tests.e2e.runner", "tests.e2e.test_user_bot", "src.tools.dev_runner")
        for proc in psutil.process_iter(["pid", "cmdline", "cpu_percent", "memory_info"]):
            try:
                cmd = " ".join(proc.info.get("cmdline") or [])
                if any(p in cmd for p in patterns):
                    glimi_proc_count += 1
                    try:
                        glimi_cpu_pct += proc.cpu_percent(interval=0) or 0.0
                    except Exception:
                        pass
                    try:
                        glimi_mem_bytes += proc.info.get("memory_info").rss if proc.info.get("memory_info") else 0
                    except Exception:
                        pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except ImportError:
        pass
    except Exception:
        pass

    # GPU 정보 (plat 별 best-effort)
    gpu_info = _get_gpu_info()

    return {
        "bot_alive": status["bot_alive"],
        "runner_alive": status["runner_alive"],
        "test_user_alive": status["test_user_alive"],
        "pid": pid,
        "dev_active": log_writer.is_dev_active() if hasattr(log_writer, "is_dev_active") else False,
        "log_size_bytes": log_size,
        "db_size_bytes": db_size,
        "disk_total_bytes": disk_total,
        "disk_used_bytes": disk_used,
        "disk_free_bytes": disk_free,
        # 시스템 리소스
        "sys_cpu_pct": round(sys_cpu_pct, 1),
        "sys_mem_total_bytes": sys_mem_total,
        "sys_mem_used_bytes": sys_mem_used,
        "sys_mem_pct": round(sys_mem_pct, 1),
        "sys_load_1m": round(sys_load[0], 2) if sys_load else 0,
        "sys_load_5m": round(sys_load[1], 2) if len(sys_load) > 1 else 0,
        "sys_load_15m": round(sys_load[2], 2) if len(sys_load) > 2 else 0,
        # Glimi 프로세스 합산
        "glimi_cpu_pct": round(glimi_cpu_pct, 1),
        "glimi_mem_bytes": glimi_mem_bytes,
        "glimi_proc_count": glimi_proc_count,
        # GPU
        "gpu": gpu_info,
    }


def _get_gpu_info() -> dict:
    """GPU 정보 수집 (플랫폼별 best-effort).

    macOS (Apple Silicon): unified memory → VRAM == RAM. GPU 이름만.
    macOS (Intel+dGPU): system_profiler로 VRAM
    Linux NVIDIA: nvidia-smi
    """
    import platform
    import subprocess as _sp
    out = {
        "name": "",
        "platform": platform.system(),
        "unified_memory": False,
        "vram_total_bytes": 0,
        "vram_used_bytes": 0,  # 측정 어려움 — 0이면 미지원
        "utilization_pct": 0,  # 측정 어려움
        "supported": False,
    }
    sys = platform.system()
    try:
        if sys == "Darwin":
            # system_profiler로 GPU 이름 / VRAM
            r = _sp.run(
                ["system_profiler", "SPDisplaysDataType", "-json"],
                capture_output=True, text=True, timeout=4,
            )
            if r.returncode == 0:
                import json as _json
                data = _json.loads(r.stdout or "{}")
                gpus = data.get("SPDisplaysDataType", [])
                if gpus:
                    g = gpus[0]
                    out["name"] = g.get("_name") or g.get("sppci_model", "")
                    # Apple Silicon: spdisplays_vram이 "shared" or N MB
                    vram = g.get("spdisplays_vram_shared") or g.get("spdisplays_vram")
                    if vram:
                        if "shared" in str(vram).lower() or "apple" in out["name"].lower():
                            out["unified_memory"] = True
                        elif "mb" in str(vram).lower():
                            try:
                                out["vram_total_bytes"] = int(str(vram).split()[0].replace(",", "")) * 1024 * 1024
                            except Exception:
                                pass
                        elif "gb" in str(vram).lower():
                            try:
                                out["vram_total_bytes"] = int(float(str(vram).split()[0].replace(",", "")) * 1024 * 1024 * 1024)
                            except Exception:
                                pass
                    else:
                        out["unified_memory"] = True  # Apple Silicon 기본
                    # Core count
                    cores = g.get("sppci_cores")
                    if cores:
                        out["cores"] = cores
                    out["supported"] = True
        elif sys == "Linux":
            # nvidia-smi 시도
            r = _sp.run(
                ["nvidia-smi", "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3,
            )
            if r.returncode == 0:
                parts = [p.strip() for p in r.stdout.strip().split(",")]
                if len(parts) >= 4:
                    out["name"] = parts[0]
                    out["vram_total_bytes"] = int(parts[1]) * 1024 * 1024
                    out["vram_used_bytes"] = int(parts[2]) * 1024 * 1024
                    out["utilization_pct"] = int(parts[3])
                    out["supported"] = True
    except Exception:
        pass
    return out


def ROOT_DIR():
    from pathlib import Path as _P
    return _P(__file__).resolve().parent.parent.parent


def get_dev_state() -> dict:
    """커뮤니티별 dev/pending.json + dev/result.json 상태."""
    import json as _json
    from src import community as _community
    out = {"pending": None, "result": None, "active": False}
    try:
        out["active"] = log_writer.is_dev_active()
    except Exception:
        pass
    dev_dir = _community.get_community_dir() / "dev"
    p = dev_dir / "pending.json"
    r = dev_dir / "result.json"
    try:
        if p.exists():
            out["pending"] = _json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        pass
    try:
        if r.exists():
            out["result"] = _json.loads(r.read_text(encoding="utf-8"))
    except Exception:
        pass
    return out


def get_usage_stats() -> dict:
    """Claude 계정 사용량 — ~/.claude/telemetry/ 의 tengu_exit 이벤트 파싱.

    tengu_exit 이벤트의 additional_metadata에:
      last_session_cost (USD)
      last_session_total_input_tokens
      last_session_total_output_tokens
      last_session_total_cache_creation_input_tokens
      last_session_total_cache_read_input_tokens
      last_session_api_duration (ms)
    """
    import json as _json
    import glob as _glob
    from pathlib import Path as _P
    from datetime import datetime, timezone, timedelta

    telem_dir = _P.home() / ".claude" / "telemetry"
    if not telem_dir.exists():
        # 폴백: 로그 기반
        lines = get_recent_system_logs(tail_lines=5000)
        return {
            "source": "log-derived",
            "cost_total_usd": 0,
            "sonnet_calls": sum(1 for l in lines if "claude-sonnet" in l.lower()),
            "haiku_calls": sum(1 for l in lines if "claude-haiku" in l.lower()),
            "opus_calls": sum(1 for l in lines if "claude-opus" in l.lower()),
        }

    total_cost = 0.0
    total_in = 0
    total_out = 0
    total_cache_w = 0
    total_cache_r = 0
    total_api_ms = 0
    sessions = 0
    by_day: dict[str, dict] = {}
    by_model: dict[str, int] = {}
    subscription_type = None

    now = datetime.now(timezone.utc)
    day_today = now.strftime("%Y-%m-%d")
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d")

    cost_today = 0.0
    cost_week = 0.0
    cost_month = 0.0

    for fp in _glob.glob(str(telem_dir / "*.json")):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = _json.loads(line)
                        ed = ev.get("event_data", {})
                        name = ed.get("event_name", "")
                        model = ed.get("model", "") or ""
                        ts = ed.get("client_timestamp", "")
                        if name == "tengu_exit":
                            meta = ed.get("additional_metadata", "{}")
                            if isinstance(meta, str):
                                meta = _json.loads(meta)
                            cost = meta.get("last_session_cost") or 0
                            if not cost:
                                continue
                            total_cost += cost
                            total_in += meta.get("last_session_total_input_tokens", 0) or 0
                            total_out += meta.get("last_session_total_output_tokens", 0) or 0
                            total_cache_w += meta.get("last_session_total_cache_creation_input_tokens", 0) or 0
                            total_cache_r += meta.get("last_session_total_cache_read_input_tokens", 0) or 0
                            total_api_ms += meta.get("last_session_api_duration", 0) or 0
                            sessions += 1
                            day = ts[:10] if ts else "?"
                            d = by_day.setdefault(day, {"cost": 0, "sessions": 0})
                            d["cost"] += cost
                            d["sessions"] += 1
                            if day == day_today:
                                cost_today += cost
                            if day >= week_ago:
                                cost_week += cost
                            if day >= month_ago:
                                cost_month += cost
                        elif name == "tengu_startup_manual_model_config":
                            meta = ed.get("additional_metadata", "{}")
                            if isinstance(meta, str):
                                meta = _json.loads(meta)
                            st = meta.get("subscriptionType")
                            if st:
                                subscription_type = st
                        if model:
                            by_model[model] = by_model.get(model, 0) + 1
                    except Exception:
                        continue
        except Exception:
            continue

    # 최근 7일 일별 cost
    recent_days = []
    for i in range(7):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        info = by_day.get(d, {"cost": 0, "sessions": 0})
        recent_days.append({"date": d, "cost": round(info["cost"], 4), "sessions": info["sessions"]})

    return {
        "source": "telemetry",
        "subscription_type": subscription_type or "unknown",
        "cost_total_usd": round(total_cost, 4),
        "cost_today_usd": round(cost_today, 4),
        "cost_week_usd": round(cost_week, 4),
        "cost_month_usd": round(cost_month, 4),
        "sessions_total": sessions,
        "tokens_input": total_in,
        "tokens_output": total_out,
        "tokens_cache_write": total_cache_w,
        "tokens_cache_read": total_cache_r,
        "api_duration_ms": total_api_ms,
        "recent_days": recent_days,
        "by_model": by_model,
    }


def get_scenes() -> list[dict]:
    """커뮤니티의 모든 씬(시나리오) 상태 — active/completed/not_started.

    씬 = 시간 제한적 커뮤니티 이벤트. 현재:
      - tutorial: 신규 오너 가입 시나리오
      - auto_conversation: 에이전트간 자동 대화 세션 (채널 status='running')
    향후 추가 가능: birthday, conflict, party 등.
    """
    from datetime import datetime
    from pathlib import Path as _P
    scenes: list[dict] = []

    # ── 1. Tutorial — scene 객체에서 직접 읽음 (single source of truth) ──
    try:
        from src.scenes.tutorial.scene import scene as _tut_scene
        cur_phase = _tut_scene.current_phase()
        # phase id → description (Phase 객체에서 가져옴)
        phase_desc = next(
            (p.description for p in _tut_scene.phases if p.id == cur_phase),
            cur_phase,
        )
        is_complete = _tut_scene.is_complete()
        is_active = _tut_scene.is_active()
    except Exception:
        cur_phase = ""
        phase_desc = ""
        is_complete = False
        is_active = False

    status = "completed" if is_complete else ("active" if is_active else "not_started")
    # greet 단계 (greeted=False) 도 not_started 가 아닌 active — 씬 자체는 시작됨
    if cur_phase == "greet":
        status = "active"

    # 완료 시간 — .tutorial-complete 플래그 파일의 mtime
    completed_at = None
    started_at = None
    try:
        log_dir = _P(community.get_log_dir())
        complete_flag = log_dir / ".tutorial-complete"
        if complete_flag.exists():
            completed_at = datetime.fromtimestamp(complete_flag.stat().st_mtime).isoformat()
        # 시작 시간: 유나의 첫 mgr-dashboard 메시지 timestamp
        try:
            conn = db.get_conn()
            row = conn.execute(
                "SELECT MIN(timestamp) as ts FROM conversations WHERE channel='mgr-dashboard'"
            ).fetchone()
            conn.close()
            if row and row["ts"]:
                started_at = row["ts"]
        except Exception:
            pass
    except Exception:
        pass

    scene_description = ""
    try:
        scene_description = _tut_scene.description or ""
    except Exception:
        scene_description = "신규 오너 — 첫 인사부터 친구 생성까지"

    scenes.append({
        "id": "tutorial",
        "name": "Tutorial",
        "icon": "🌱",
        "description": scene_description,
        "status": status,
        "phase": cur_phase,
        "phase_desc": phase_desc,
        "started_at": started_at,
        "completed_at": completed_at,
    })

    # ── 2. Auto Conversations (에이전트간 대화 세션) ──
    try:
        conn = db.get_conn()
        running = conn.execute(
            "SELECT channel, current_turn, max_turns, created_at FROM channels "
            "WHERE status = 'running'"
        ).fetchall()
        conn.close()
        for r in running:
            scenes.append({
                "id": f"conversation:{r['channel']}",
                "name": f"Conversation",
                "icon": "💬",
                "description": f"#{r['channel']} 에이전트 자동 대화 ({r['current_turn']}/{r['max_turns']} 턴)",
                "status": "active",
                "phase": f"{r['current_turn']}/{r['max_turns']}",
                "phase_desc": f"턴 진행 중",
                "started_at": r["created_at"],
                "completed_at": None,
                "target_channel": r["channel"],
            })
    except Exception:
        pass

    return scenes


def get_supervisors() -> list[dict]:
    """감시자(supervisor) 목록과 상태.

    데이터 소스:
      1) In-process: SupervisorPool 이 있으면 직접 읽음 (봇 프로세스 내부 관측)
      2) Cross-process: 비어있으면 `communities/{id}/logs/.supervisors.json` 에서 로드
         (대시보드 처럼 별도 프로세스에서 봇의 pool 상태를 볼 수 있게)
    """
    import re as _re
    import json as _json
    import os as _os

    class _SupShim:
        """JSON 에서 로드했거나 정적 enumerate 한 supervisor 의 경량 shim.
        _active 로 실제 동작 중 여부 표시 (봇 오프라인 시 False)."""
        def __init__(self, data: dict, _active: bool = True):
            self.id = data.get("id", "?")
            self.kind = data.get("kind", "system")
            self.display_name = data.get("display_name", self.id)
            self.scope = data.get("scope", {}) or {}
            self.interval = data.get("interval", 0)
            self._active = _active

    live_sups: list = []
    try:
        from src.supervisors.base import pool
        live_sups = list(pool.all())
    except Exception:
        live_sups = []

    snapshot_loaded = False
    if not live_sups:
        # fallback: file-based snapshot (봇 프로세스가 최근에 저장한 것)
        try:
            from src import db as _db
            snap_path = _os.path.join(
                _os.path.dirname(_db._get_db_path()), "logs", ".supervisors.json"
            )
            if _os.path.exists(snap_path):
                with open(snap_path, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                items = data.get("items", [])
                live_sups = [_SupShim(it) for it in items if it.get("active", True)]
                if live_sups:
                    snapshot_loaded = True
        except Exception:
            pass

    if not snapshot_loaded and not live_sups:
        # 오프라인 또는 최초 기동 전: 코드베이스에서 "존재 가능한" supervisor 을
        # 정적으로 enumerate 해서 대시보드에 offline 상태로 표시.
        try:
            expected: list[_SupShim] = []
            # 1) system 싱글톤 — 항상 후보 (봇 오프라인이면 inactive)
            expected.append(_SupShim({
                "id": "orchestrator",
                "kind": "system",
                "display_name": "오케스트레이터",
                "scope": {},
            }, _active=False))
            # 2) scene-scoped — 정의된 씬마다 1 개
            try:
                from src import scenes as _scenes_pkg
                import pkgutil as _pkgutil, importlib as _importlib
                for _, modname, ispkg in _pkgutil.iter_modules(_scenes_pkg.__path__):
                    if not ispkg or modname == "__pycache__":
                        continue
                    try:
                        sub = _importlib.import_module(f"src.scenes.{modname}")
                        sc = getattr(sub, "scene", None)
                        if sc is None:
                            continue
                        # scene.supervisors() 는 인스턴스 생성 필요 → 메타만 추출
                        sup_modname = f"src.scenes.{modname}.supervisor"
                        try:
                            sup_mod = _importlib.import_module(sup_modname)
                            # 클래스명 Convention: {Scope}FlowSupervisor 또는 비슷
                            for _attr in dir(sup_mod):
                                cls = getattr(sup_mod, _attr)
                                if (
                                    isinstance(cls, type) and _attr.endswith("Supervisor")
                                    and _attr != "Supervisor"
                                ):
                                    expected.append(_SupShim({
                                        "id": getattr(cls, "id", f"{modname}.flow"),
                                        "kind": getattr(cls, "kind", "scene"),
                                        "display_name": getattr(cls, "display_name", f"{modname} · 흐름"),
                                        "scope": {"scene_id": modname},
                                    }, _active=False))
                                    break
                        except Exception:
                            pass
                    except Exception:
                        continue
            except Exception:
                pass
            # 중복 제거 (id 기준)
            seen = set()
            dedup: list[_SupShim] = []
            for s in expected:
                if s.id in seen:
                    continue
                seen.add(s.id)
                dedup.append(s)
            live_sups = dedup
        except Exception:
            live_sups = []

    # 아이콘 매핑 (id prefix 기준)
    ICON_BY_PREFIX = {
        "tutorial": "🌱",
        "chat": "💬",
        "orchestrator": "🎼",
        "health": "❤️",
    }

    def _icon(sup_id: str) -> str:
        for prefix, icon in ICON_BY_PREFIX.items():
            if sup_id.startswith(prefix):
                return icon
        return "◆"

    # channel-scoped supervisor의 target 계산 — 해당 채널 참가자
    def _channel_targets(channel_name: str) -> list[str]:
        try:
            import json as _json
            conn = db.get_conn()
            row = conn.execute(
                "SELECT participants FROM channels WHERE channel=?", (channel_name,)
            ).fetchone()
            conn.close()
            if row and row["participants"]:
                return _json.loads(row["participants"])
        except Exception:
            pass
        return []

    def _scene_targets(scope: dict) -> list[str]:
        sid = scope.get("scene_id", "")
        if sid == "tutorial":
            return ["agent-mgr-001", "agent-creator-001"]
        return []

    def _system_targets() -> list[str]:
        return []   # system supervisor는 target 없음 (전역)

    all_logs = get_recent_system_logs(tail_lines=500)
    out = []
    for sup in live_sups:
        name = sup.id
        # target 결정
        if sup.kind == "channel":
            ch = sup.scope.get("channel", "")
            targets = _channel_targets(ch) if ch else []
        elif sup.kind == "scene":
            targets = _scene_targets(sup.scope)
        else:
            targets = _system_targets()

        # 로그 추출 (id + 레거시 name 둘 다 매칭)
        sup_logs = [
            l for l in all_logs
            if f"[sup:{name}]" in l or f"[supervisor] 활성화: {name}" in l
        ]
        sup_logs = sup_logs[-15:]

        # 최근 액션 시각
        last_action = None
        seconds_since = None
        for l in reversed(sup_logs):
            m = _re.match(r'\[(\d\d):(\d\d):(\d\d)\]', l)
            if m:
                last_action = m.group(0).strip("[]")
                try:
                    from datetime import datetime, timedelta
                    now = datetime.now()
                    today_action = now.replace(
                        hour=int(m.group(1)), minute=int(m.group(2)),
                        second=int(m.group(3)), microsecond=0
                    )
                    if today_action > now:
                        today_action -= timedelta(days=1)
                    seconds_since = (now - today_action).total_seconds()
                except Exception:
                    pass
                break

        intervening = False
        if sup_logs and seconds_since is not None and seconds_since < 10:
            last_log = sup_logs[-1].lower()
            if any(kw in last_log for kw in ("재촉", "강제 지시", "트리거", "inject", "nudge")):
                intervening = True

        out.append({
            "name": name,
            "class_name": type(sup).__name__,
            "kind": sup.kind,
            "scope": sup.scope,
            "icon": _icon(name),
            "description": sup.display_name or name,
            "interval_sec": sup.interval,
            # live(봇 프로세스 pool): True / snapshot fallback: True /
            # offline enumerate: False (shim._active 참조)
            "active": getattr(sup, "_active", True),
            "target_agents": targets,
            "recent_logs": sup_logs,
            "last_action": last_action,
            "seconds_since_action": seconds_since,
            "intervening": intervening,
        })

    return out


def get_community_meta() -> dict:
    """registry.toml의 이 커뮤니티 정보 (name, description, language)."""
    try:
        from src.community import COMMUNITIES_DIR, REGISTRY_PATH
        import tomllib
        cid = community.get_community_id()
        if REGISTRY_PATH.exists():
            with open(REGISTRY_PATH, "rb") as f:
                reg = tomllib.load(f)
            info = reg.get("community", {}).get(cid, {}) or reg.get("communities", {}).get(cid, {})
            return {
                "id": cid,
                "name": info.get("name", cid),
                "description": info.get("description", ""),
                "language": info.get("language", "ko"),
            }
    except Exception:
        pass
    return {"id": community.get_community_id(), "name": "", "description": "", "language": ""}


# ── 통합 스냅샷 ────────────────────────────────────────

def snapshot() -> dict:
    """웹 대시보드/CLI가 한 번에 가져갈 수 있는 전체 상태 dict."""
    return {
        "bot": get_bot_status(),
        "meta": get_meta_snapshot(),
        "agents": get_agents(),
        "channels": get_channels(),
        "events": get_events(),
        "scenes": get_scenes(),
        "supervisors": get_supervisors(),
        "recent_messages": get_recent_messages(limit=30),
        "total_messages": get_total_message_count(),
        "community_id": community.get_community_id(),
        "community_meta": get_community_meta(),
    }
