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


# 상태 rotation 주기 — N 초마다 활성 대상이 한 칸씩 밀림
# (60초로 느슨하게 — 너무 자주 바뀌면 산만)
_ROTATION_PERIOD = 60

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
    # 별도 running 채널 mock 하지 않음 — 활성 persona 가 속한 채널들이 이미
    # 그래프에서 자연스럽게 pulse 됨 (partyLive 판정). 추가하면 중복/과도.
    # 대신 기존 DB 의 stale running 상태는 초기화해서 사용자가 통제권 유지.
    channels = snap.get("channels") or []
    if isinstance(channels, list) and channels:
        for c in channels:
            if c.get("status") == "running":
                c["status"] = "idle"

    return snap
