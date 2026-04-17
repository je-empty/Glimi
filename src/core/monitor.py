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

    # 기본값 (runtime.py와 동기화)
    type_defaults = {
        "persona": "claude-sonnet-4-6",
        "mgr": "claude-sonnet-4-6",
        "creator": "claude-sonnet-4-6",
    }
    default = type_defaults.get(agent_type, "claude-sonnet-4-6")
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
    """최근 대화. speaker는 에이전트/유저 이름으로 해석."""
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
                "ORDER BY c.timestamp DESC LIMIT ?",
                (channel, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT c.id, c.speaker, c.channel, c.message, c.timestamp, "
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

    # test-user-bot 가상 에이전트 — DB에 없지만 상세뷰 제공
    if agent_id == "test-user-bot":
        return _get_test_user_detail()

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
        "model": model_info["model"],
        "provider": model_info["provider"],
        "model_override": model_info["override"],
    }


def _get_test_user_detail() -> dict:
    """QA test-user-bot의 가상 상세 정보."""
    import os as _os
    alive = _ps_has("tests.e2e.test_user_bot")

    # 환경변수에서 페르소나 정보
    name = _os.environ.get("QA_USER_NAME", "심재빈")
    nickname = _os.environ.get("QA_USER_NICKNAME", "빈이")
    age = _os.environ.get("QA_USER_AGE", "26")
    mbti = "ENTP"
    background = "QA 자동 테스트용 가상 유저 — 프로젝트를 전혀 모르는 신규 유저로 온보딩 시나리오를 재현함. Claude Haiku 모델로 실시간 응답 생성."

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
        "thinking": False,
        "speaking": alive,
        "thinking_seconds": 0,
        "speaking_seconds": 0,
        "last_active": "",
        "relationships": [],
        "memories_by_channel": {},
        "thinking_logs": thinking_logs,
        "primary_channel": "mgr-dashboard",
        "primary_chat": primary_chat,
        "model": "claude-haiku-4-5-20251001",
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
      - onboarding: 신규 오너 가입 시나리오
      - auto_conversation: 에이전트간 자동 대화 세션 (채널 status='running')
    향후 추가 가능: birthday, conflict, party 등.
    """
    from datetime import datetime
    from pathlib import Path as _P
    scenes: list[dict] = []

    # ── 1. Onboarding ──────────────────────────────────
    try:
        phase = db.get_meta("onboarding_phase") or ""
        greeted = db.get_meta("yuna_greeted") or ""
    except Exception:
        phase = ""
        greeted = ""

    status = "not_started"
    if phase == "complete":
        status = "completed"
    elif greeted or phase:
        status = "active"

    # 완료 시간 — .onboarding-complete 플래그 파일의 mtime
    completed_at = None
    started_at = None
    try:
        log_dir = _P(community.get_log_dir())
        complete_flag = log_dir / ".onboarding-complete"
        if complete_flag.exists():
            completed_at = datetime.fromtimestamp(complete_flag.stat().st_mtime).isoformat()
        # 시작 시간: yuna_greeted=1 된 시점을 추정 — 유나 첫 메시지 timestamp
        if greeted:
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

    phase_desc_map = {
        "": "프로필 수집 단계",
        "channels_setup": "시스템 채널 셋업 중",
        "channels_done": "최종 완료 대기",
        "complete": "완료됨",
    }
    scenes.append({
        "id": "onboarding",
        "name": "Onboarding",
        "icon": "🌱",
        "description": "신규 오너 가입 — 프로필 수집 → 시스템 채널 → 크리에이터 소개 → 완료",
        "status": status,
        "phase": phase,
        "phase_desc": phase_desc_map.get(phase, phase),
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
        "recent_messages": get_recent_messages(limit=30),
        "total_messages": get_total_message_count(),
        "community_id": community.get_community_id(),
        "community_meta": get_community_meta(),
    }
