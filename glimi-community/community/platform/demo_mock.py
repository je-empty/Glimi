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


def _chan_label(name: str) -> str:
    """채널 id → 짧은 표시 라벨 (대화 supervisor 카드용)."""
    n = name or ""
    if n.startswith("internal-"):
        return n[len("internal-"):].replace("-", "·")
    if n.startswith("group-"):
        return n[len("group-"):] + " 단톡"
    if n.startswith("dm-"):
        return n[len("dm-"):]
    return n


def _demo_supervisors(snap: dict[str, Any], running_channel: str | None = None) -> list[dict]:
    """데모용 풍부한 supervisor 세트 — 실제 타입(오케스트레이터·약속 이행·이벤트·대화)을
    반영하되 last_action / intervening / target 으로 '살아 운영 중' 처럼 보이게.
    런타임이 안 떠 있어도 결정론적으로 구성(시간 기반 rotation 으로 live 느낌)."""
    agents = snap.get("agents") or []
    pids = [a["id"] for a in agents if a.get("type") == "persona"]
    pname = {a["id"]: a.get("name", "") for a in agents}
    channels = snap.get("channels") or []
    now = int(time.time())
    n1 = pname.get(pids[0], "친구") if pids else "친구"
    n2 = pname.get(pids[1], "친구") if len(pids) > 1 else "친구"

    sups: list[dict] = [
        {
            "name": "orchestrator", "kind": "system",
            "display_name": "오케스트레이터", "icon": "🧭",
            "active": True, "intervening": False,
            "target_agents": pids[:4],
            "last_action": f"{n1} 화제가 잔잔하게 도는 중 — 누가 받아칠지 신호를 보냄",
            "seconds_since_action": now % 40 + 3,
        },
        {
            "name": "commitment", "kind": "system",
            "display_name": "약속 이행 추적", "icon": "🤝",
            "active": True, "intervening": (now // 23) % 3 == 0,
            "target_agents": pids[1:3],
            "last_action": f"{n2}가 말한 '주말에 같이 가자' 약속을 기억해 둠 — 리마인드 타이밍 계산 중",
            "seconds_since_action": now % 55 + 5,
        },
        {
            "name": "events", "kind": "system",
            "display_name": "이벤트 관찰", "icon": "📅",
            "active": False, "intervening": False,
            "target_agents": [],
            "last_action": "다가오는 생일·기념일 없음 — 조건 충족 시 깜짝 이벤트 트리거 대기",
            "seconds_since_action": now % 600 + 120,
        },
    ]

    # 채널별 '대화' 감시자 — group / internal / dm 골고루, running 채널은 개입(intervening).
    chat_chs = [c for c in channels
                if (c.get("name") or "").startswith(("group-", "internal-", "dm-"))]
    chat_chs.sort(key=lambda c: 0 if c.get("name") == running_channel else 1)
    actions = [
        "방금 오간 메시지 톤 분석 — 분위기 따뜻, 개입 불필요",
        "대화가 끊길 기미 — 화제를 이어줄 한 명을 호출할지 검토",
        "한 명이 지친 기색 — 위로 흐름으로 부드럽게 유도",
        "잔잔한 일상 — 그냥 지켜보는 중",
    ]
    for i, c in enumerate(chat_chs[:4]):
        nm = c.get("name") or ""
        parts = [p for p in (c.get("participants") or [])
                 if p.startswith(("agent-persona-", "agent-mgr-"))]
        is_running = (nm == running_channel)
        sups.append({
            "name": f"chat.{nm}", "kind": "chat",
            "display_name": f"대화 · {_chan_label(nm)}", "icon": "💬",
            "active": is_running or i < 2,
            "intervening": is_running,
            "target_agents": parts[:3],
            "last_action": actions[i % len(actions)],
            "seconds_since_action": (now + i * 7) % 50 + 2,
        })
    return sups


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

    # Supervisor — 풍부한 데모 세트 (오케스트레이터·약속 이행·이벤트·대화 다수).
    snap["supervisors"] = _demo_supervisors(
        snap, running_names[0] if running_names else None)

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

    # ── Supervisor 주입 — 풍부한 데모 세트 (실제 타입 반영: 오케스트레이터·약속 이행·이벤트·대화) ──
    # running 채널이 있으면 그 채널의 '대화' 감시자를 개입(intervening) 상태로 표시.
    snap["supervisors"] = _demo_supervisors(snap, running_channel_name)

    return snap
