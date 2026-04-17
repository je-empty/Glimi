"""
Monitor — 커뮤니티 런타임 상태를 읽기전용으로 조회하는 순수 데이터 계층.

CLI dashboard (src/tui/dashboard.py)와 Web dashboard (scripts/web_dashboard.py)
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


def get_bot_status() -> dict:
    """Glimi 봇 / QA 러너 / 테스트 유저 봇 프로세스 상태."""
    return {
        "bot_alive": _ps_has("src.discord_bot"),
        "runner_alive": _ps_has("tests.e2e.runner"),
        "test_user_alive": _ps_has("tests.e2e.test_user_bot"),
    }


# ── 메타/오너 ──────────────────────────────────────────

def get_meta_snapshot() -> dict:
    """meta 테이블 주요 키 일괄 조회."""
    out = {
        "onboarding_phase": "",
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
        is_t = log_writer.is_thinking(aid)
        is_s = log_writer.is_speaking(aid)
        out.append({
            "id": aid,
            "type": a.get("type", ""),
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
    """최근 대화. speaker는 에이전트/유저 이름으로 해석."""
    try:
        conn = db.get_conn()
        if channel:
            rows = conn.execute(
                "SELECT c.speaker, c.channel, c.message, c.timestamp, "
                "       a.name as agent_name, u.name as user_name "
                "FROM conversations c "
                "LEFT JOIN agents a ON a.id = c.speaker "
                "LEFT JOIN users u ON u.id = c.speaker "
                "WHERE c.channel = ? "
                "ORDER BY c.timestamp DESC LIMIT ?",
                (channel, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT c.speaker, c.channel, c.message, c.timestamp, "
                "       a.name as agent_name, u.name as user_name "
                "FROM conversations c "
                "LEFT JOIN agents a ON a.id = c.speaker "
                "LEFT JOIN users u ON u.id = c.speaker "
                "ORDER BY c.timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        total = conn.execute("SELECT COUNT(*) as c FROM conversations").fetchone()["c"]
        conn.close()
    except Exception:
        return []

    out = []
    for r in reversed(rows):
        who = r["agent_name"] or r["user_name"] or r["speaker"]
        out.append({
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
    secs = (datetime.now() - dt).total_seconds()
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

def get_agent_detail(agent_id: str) -> dict:
    """에이전트 전체 상세: 프로필 + 관계 + 메모리 + 추론 로그 + 주 채널 채팅."""
    from src.core.profile import load_profile

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

    # 메모리 — 채널별로 묶음
    memories_by_channel: dict[str, list[dict]] = {}
    try:
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT * FROM memories WHERE agent_id = ? "
            "ORDER BY channel, level DESC, id DESC",
            (agent_id,),
        ).fetchall()
        conn.close()
        for m in rows:
            ch = m["channel"] or "general"
            memories_by_channel.setdefault(ch, []).append({
                "level": m["level"],
                "content": m["content"],
                "created_at": m["created_at"] or "",
                "mem_type": m["mem_type"] if "mem_type" in m.keys() else None,
            })
    except Exception:
        pass

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
        "thinking_logs": thinking_logs,
        "primary_channel": primary,
        "primary_chat": primary_chat,
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
    """프로세스/PID/디스크/로그 크기 등 시스템 헬스."""
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
    }


def ROOT_DIR():
    from pathlib import Path as _P
    return _P(__file__).resolve().parent.parent.parent


def get_dev_state() -> dict:
    """dev/pending.json + dev/result.json 상태."""
    import json as _json
    root = ROOT_DIR()
    out = {"pending": None, "result": None, "active": False}
    try:
        out["active"] = log_writer.is_dev_active()
    except Exception:
        pass
    p = root / "dev" / "pending.json"
    r = root / "dev" / "result.json"
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
    """~/.claude/ 혹은 프로젝트 내부 usage 파일 읽기. 없으면 빈값."""
    import json as _json
    from pathlib import Path as _P
    # 후보 파일들
    candidates = [
        _P.home() / ".claude" / "usage.json",
        ROOT_DIR() / "dev" / "usage.json",
    ]
    for p in candidates:
        try:
            if p.exists():
                return _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
    # CLI 호출 건수를 system.log에서 카운트 (폴백)
    lines = get_recent_system_logs(tail_lines=5000)
    sonnet = sum(1 for l in lines if "claude-sonnet" in l.lower())
    haiku = sum(1 for l in lines if "claude-haiku" in l.lower())
    opus = sum(1 for l in lines if "claude-opus" in l.lower())
    return {
        "source": "log-derived",
        "sonnet_calls": sonnet,
        "haiku_calls": haiku,
        "opus_calls": opus,
        "total": sonnet + haiku + opus,
    }


# ── 통합 스냅샷 ────────────────────────────────────────

def snapshot() -> dict:
    """웹 대시보드/CLI가 한 번에 가져갈 수 있는 전체 상태 dict."""
    return {
        "bot": get_bot_status(),
        "meta": get_meta_snapshot(),
        "agents": get_agents(),
        "channels": get_channels(),
        "events": get_events(),
        "recent_messages": get_recent_messages(limit=30),
        "total_messages": get_total_message_count(),
        "community_id": community.get_community_id(),
    }
