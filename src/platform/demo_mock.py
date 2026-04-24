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

import time
from typing import Any


# 동시에 활성화할 에이전트 수 (너무 과하지 않게)
_ACTIVE_AGENT_COUNT = 2

# 상태 rotation 주기 — N 초마다 활성 에이전트 셋이 한 칸씩 밀림
_ROTATION_PERIOD = 30

# 동시에 활성화할 채널 수
_ACTIVE_CHANNEL_COUNT = 2


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

    # ── 에이전트 thinking / speaking rotation ──
    # persona·mgr·creator 섞어서 후보로. 동시 _ACTIVE_AGENT_COUNT 명만 활성.
    # 한 명은 thinking, 다음 slot 은 speaking — 30초마다 밀림.
    agents = snap.get("agents") or []
    if isinstance(agents, list) and agents:
        # thinking 후보 풀: persona / mgr 우선 (creator 는 덜 활동적인 이미지)
        pool = [a for a in agents if a.get("type") in ("persona", "mgr")]
        if not pool:
            pool = agents[:]
        n = len(pool)
        thinking_idx = _cycle_index(n)
        speaking_idx = (thinking_idx + 1) % n if n > 1 else -1

        # 모든 에이전트 상태 초기화 (mock 일관성)
        for a in agents:
            a["thinking"] = False
            a["speaking"] = False
            a["thinking_seconds"] = 0
            a["speaking_seconds"] = 0

        # rotation 에 따라 활성화
        if n > 0:
            t = pool[thinking_idx]
            t["thinking"] = True
            t["thinking_seconds"] = int(time.time()) % 12 + 3  # 3~14초
        if speaking_idx >= 0:
            s = pool[speaking_idx]
            s["speaking"] = True
            s["speaking_seconds"] = int(time.time()) % 8 + 2  # 2~9초

    # ── 채널 '활성' 표시 rotation ──
    # internal-* / group-* / dm-* 중에서 일부만 status=running + last_ts 방금전.
    # 채널 dict 의 이름 필드는 `name` (api_snapshot 이 이 key 로 반환).
    channels = snap.get("channels") or []
    if isinstance(channels, list) and channels:
        # 기존 running 표시 초기화 (demo 는 우리가 통제)
        for c in channels:
            if c.get("status") == "running":
                c["status"] = "idle"

        candidates = [
            i for i, c in enumerate(channels)
            if (c.get("name") or "").startswith(("internal-", "group-", "dm-"))
        ]
        if candidates:
            k = min(_ACTIVE_CHANNEL_COUNT, len(candidates))
            base = _cycle_index(len(candidates))
            active_set = {candidates[(base + offset) % len(candidates)] for offset in range(k)}
            now = time.time()
            from datetime import datetime, timezone
            for idx in active_set:
                c = channels[idx]
                c["status"] = "running"
                c["last_ts"] = datetime.fromtimestamp(
                    now - (int(now) % 30), tz=timezone.utc
                ).isoformat()
                if not c.get("msg_count"):
                    c["msg_count"] = 3

    return snap
