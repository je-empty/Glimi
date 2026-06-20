"""Demo 커뮤니티 시연 mock — 실제 봇 없어도 '운영 중' 처럼 UI 에 보이게.

원칙:
  - 자체 UI 코드 / CSS 를 건드리지 않는다. 기존 snapshot dict 의 필드만 덮어씀.
  - 상태 rotation 은 서버 시간 기반 결정론 함수 — 각 요청마다 상태가 자연스럽게 바뀜.
  - demo 커뮤니티 (community_id == 'demo') 일 때만 동작. 다른 커뮤니티에는 영향 없음.

덮어쓰는 필드:
  - community.running = True, stopped = False, uptime 표시
  - agents[i].thinking / speaking / thinking_seconds / speaking_seconds
  - channels[i].status ('running' 으로 일부만), last_ts 를 방금 전으로
"""
from __future__ import annotations

import os
import time
from typing import Any


# 상태 rotation 주기 — N 초마다 활성 대상이 한 칸씩 밀림
# (60초로 느슨하게 — 너무 자주 바뀌면 산만)
_ROTATION_PERIOD = 60


def _capture_mode() -> bool:
    """README 그래프 움짤 캡처용 — 다수 노드를 동시에 활성화해 '동시다발' 그림을 만든다.
    평상시(라이브 데모)엔 OFF. `GLIMI_DEMO_CAPTURE=1` 일 때만 ON."""
    return os.environ.get("GLIMI_DEMO_CAPTURE", "").strip() in ("1", "true")


def _inject_capture(snap: dict[str, Any]) -> None:
    """캡처 모드 전용 — 여러 persona thinking/speaking 동시 + 여러 채널 running.
    결정론적(시간 rotation 없음)이라 프레임이 안정적. graph 에 live edge 가 풍성하게 깔림."""
    agents = snap.get("agents") or []
    personas = [a for a in agents if a.get("type") == "persona"]
    for a in agents:
        a["thinking"] = a["speaking"] = False
        a["thinking_seconds"] = a["speaking_seconds"] = 0
    # persona 를 thinking/speaking 으로 번갈아 — 색 다양성(amber ring / blue ring) 확보.
    for i, a in enumerate(personas):
        if i % 5 == 1 or i % 5 == 3:
            a["speaking"] = True
            a["speaking_seconds"] = 2 + (i % 4)
        else:
            a["thinking"] = True
            a["thinking_seconds"] = 3 + (i * 2) % 11

    # 여러 internal-/group- 채널 동시 running → 다수 edge pulse.
    channels = snap.get("channels") or []
    running_names: list[str] = []
    running_parts: list[list[str]] = []
    for c in channels:
        nm = c.get("name") or ""
        if nm.startswith(("internal-", "group-")):
            c["status"] = "running"
            from datetime import datetime, timezone
            now = time.time()
            c["last_ts"] = datetime.fromtimestamp(
                now - (int(now) % 20), tz=timezone.utc
            ).isoformat()
            running_names.append(nm)
            running_parts.append(list(c.get("participants") or []))
        elif c.get("status") == "running":
            c["status"] = "idle"

    # Supervisor — orchestrator + 각 running 채널 ChatSupervisor 다수 주입.
    sups = list(snap.get("supervisors") or [])
    persona_ids = [a["id"] for a in personas]
    for s in sups:
        if s.get("name") == "orchestrator":
            s["active"] = True
            s["intervening"] = False
            s["target_agents"] = persona_ids[:5]
    for nm, parts in list(zip(running_names, running_parts))[:4]:
        targets = [p for p in parts if p.startswith(("agent-persona-", "agent-mgr-"))]
        sups.append({
            "name": f"chat.{nm}",
            "display_name": f"Chat · {nm}",
            "icon": "💬",
            "active": True,
            "intervening": False,
            "target_agents": targets,
        })
    snap["supervisors"] = sups

# 참고: 활성중인 에이전트의 **모든** 참여 채널이 그래프에서 live 로 잡힘.
# persona 1명만 thinking 돌려도 그 persona 의 dm-/group-/internal- 여러 개가 pulse 됨.
# 그래서 "active agent" 는 1명 (thinking 전용) 으로 제한 + 추가 running 채널 mock 안 함.


def _cycle_index(n: int, period: int = _ROTATION_PERIOD) -> int:
    """현재 시간 기반 결정론 인덱스. period 초마다 한 칸씩 증가."""
    if n <= 0:
        return 0
    return int(time.time() / period) % n


def inject(snap: dict[str, Any]) -> dict[str, Any]:
    """snapshot dict 을 in-place 로 수정해서 '운영 중' 으로 보이게."""
    if not isinstance(snap, dict):
        return snap

    # ── 커뮤니티 running 표시 ──
    meta = snap.get("meta") or {}
    meta["running"] = True
    meta["stopped"] = False
    meta.setdefault("uptime_seconds", int(time.time()) % (3600 * 24))
    snap["meta"] = meta

    # ── bot_alive = True — 오프라인 안내 배너 / hero offline 표시 제거 ──
    bot = dict(snap.get("bot") or {})
    bot["bot_alive"] = True
    snap["bot"] = bot

    # ── 캡처 모드 — 다수 노드 동시 활성 (README 그래프 움짤용) ──
    if _capture_mode():
        _inject_capture(snap)
        return snap

    # ── 에이전트 thinking rotation — persona 1명만 ──
    # 활성 에이전트의 모든 참여 채널이 graph 에서 live 로 잡히므로 1명만 해도 이미
    # 여러 edge 가 pulse 됨. 그래서 persona 1명 + thinking 만 (speaking 생략) 으로 최소화.
    # mgr/creator 는 너무 많은 채널에 속해있어서 활성화하면 edge 폭탄 — 제외.
    agents = snap.get("agents") or []
    if isinstance(agents, list) and agents:
        pool = [a for a in agents if a.get("type") == "persona"]
        if not pool:
            pool = [a for a in agents if a.get("type") in ("persona", "mgr")]

        # 모든 에이전트 상태 초기화 (mock 일관성)
        for a in agents:
            a["thinking"] = False
            a["speaking"] = False
            a["thinking_seconds"] = 0
            a["speaking_seconds"] = 0

        n = len(pool)
        if n > 0:
            thinking_idx = _cycle_index(n)
            t = pool[thinking_idx]
            t["thinking"] = True
            t["thinking_seconds"] = int(time.time()) % 12 + 3  # 3~14초

    # ── 채널 '활성' 표시 rotation ──
    # 기존 DB stale running 초기화 후, internal-* 중 1개만 rotation 으로 running.
    # 이 running 채널에 대해 ChatSupervisor 주입 → 실제 운영처럼 감시자가 붙은 모습.
    channels = snap.get("channels") or []
    running_channel_name: str | None = None
    running_channel_participants: list[str] = []
    if isinstance(channels, list) and channels:
        for c in channels:
            if c.get("status") == "running":
                c["status"] = "idle"

        internal_candidates = [
            i for i, c in enumerate(channels)
            if (c.get("name") or "").startswith("internal-")
        ]
        if internal_candidates:
            idx = internal_candidates[_cycle_index(len(internal_candidates))]
            c = channels[idx]
            c["status"] = "running"
            running_channel_name = c.get("name")
            running_channel_participants = list(c.get("participants") or [])
            # last_ts 를 최근으로 — last_ago 는 api_snapshot 이 재계산
            from datetime import datetime, timezone
            now = time.time()
            c["last_ts"] = datetime.fromtimestamp(
                now - (int(now) % 30), tz=timezone.utc
            ).isoformat()

    # ── Supervisor 주입 — 실제 동작처럼 채팅방별 ChatSupervisor + 전역 Orchestrator ──
    # 기존 supervisors 배열 유지하되 running 채널 에 대응하는 chat.* 항목 추가.
    sups = list(snap.get("supervisors") or [])
    # tutorial 완료 상태면 tutorial.flow 는 inactive 그대로 (건드리지 않음)
    # orchestrator 는 항상 active 표시 (항상 돌아가는 전역 supervisor)
    for s in sups:
        if s.get("name") == "orchestrator":
            s["active"] = True
            s["intervening"] = False
            # 타겟: 가장 친밀도 높은 persona 페어가 자연스러움.
            # target_agents 빈 배열이면 그래프에 안 그려지니 persona 몇 명을 target 으로.
            persona_ids = [a["id"] for a in (snap.get("agents") or []) if a.get("type") == "persona"]
            s["target_agents"] = persona_ids[:3]  # 상위 3명만

    # running 채널이 있으면 해당 채널 전용 ChatSupervisor 주입
    if running_channel_name and running_channel_participants:
        persona_targets = [
            pid for pid in running_channel_participants
            if pid.startswith("agent-persona-") or pid.startswith("agent-mgr-")
        ]
        sups.append({
            "name": f"chat.{running_channel_name}",
            "display_name": f"Chat · {running_channel_name}",
            "icon": "💬",
            "active": True,
            "intervening": False,
            "target_agents": persona_targets,
        })

    snap["supervisors"] = sups

    return snap
