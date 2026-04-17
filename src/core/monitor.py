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
        out.append({
            "id": a["id"],
            "type": a.get("type", ""),
            "name": a.get("name", a["id"]),
            "status": a.get("status", ""),
            "emotion": emo,
            "emoji": EMOTION_EMOJI.get(emo, "・"),
            "intensity": a.get("emotion_intensity", 0) or 0,
            "mbti": a.get("mbti", ""),
            "age": a.get("age", 0) or 0,
            "last_active": a.get("last_active", ""),
            "thinking": log_writer.is_thinking(a["id"]),
            "speaking": log_writer.is_speaking(a["id"]),
        })
    return out


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
