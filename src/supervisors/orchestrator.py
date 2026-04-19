"""
OrchestratorSupervisor — 에이전트간 자발적 대화 오케스트레이터.

유나가 "쟤네 얘기 좀 나누게 해볼까?" 판단하는 대신, 이 시스템 전역 supervisor가
주기적으로 페어 스캔해서 적절한 타이밍에 internal-dm/group 대화 시작.

스캔 로직:
  - 활성 persona agent 전체 조회
  - 페어별 (A, B) 최근 internal-dm 대화 시점 + 친밀도 점수 확인
  - 오래 안 봤는데 친하거나, 공통 화제 가능성 있으면 → start_conversation
  - 이미 진행 중인 running 채널 있으면 중복 방지 (쿨다운)

주의: 오너가 진행 중인 dm/mgr 채널 쪽에 있을 때는 피함 (방해 X).
튜토리얼 완료 (complete) 전에는 동작 금지.
"""
from __future__ import annotations

import asyncio
import random
from datetime import datetime, timedelta

import discord

from src import db, log_writer
from src.supervisors.base import Supervisor


class OrchestratorSupervisor(Supervisor):
    """전역 singleton. 에이전트간 대화 시작 결정."""

    id = "orchestrator"
    display_name = "오케스트레이터"
    kind = "system"
    interval = 180.0   # 3분마다 스캔 (공격적이지 않게)

    def __init__(self):
        super().__init__(scope={})
        self._last_started_at: float = 0.0
        self._min_gap_between_starts: float = 300.0   # 자동 시작 간 최소 5분 간격
        self._min_idle_per_pair_hours: float = 2.0    # 페어별 최소 idle 시간

    # ── check ─────────────────────────────────────────────

    async def check(self, ctx):
        guild = ctx.get("guild") if isinstance(ctx, dict) else None
        if guild is None:
            return

        # 튜토리얼 미완료면 방해 X
        if db.get_meta("tutorial_phase") != "complete":
            return

        # 글로벌 쿨다운
        import time as _time
        if _time.time() - self._last_started_at < self._min_gap_between_starts:
            return

        # 이미 running internal 채널 많으면 추가 시작 자제
        running_count = self._count_running_internal()
        if running_count >= 3:
            return

        # 페어 후보 스캔
        pair = self._pick_pair()
        if not pair:
            return
        a_id, b_id, reason = pair

        # 대화 시작 실행
        a = db.get_agent(a_id)
        b = db.get_agent(b_id)
        if not (a and b):
            return
        a_name, b_name = a["name"], b["name"]
        log_writer.system(
            f"[sup:orchestrator] 페어 선정: {a_name} ↔ {b_name} ({reason})"
        )
        self._last_started_at = _time.time()
        await self._start_internal_conv(guild, a_id, b_id, reason)

    # ── 페어 선정 ─────────────────────────────────────────

    def _pick_pair(self) -> tuple[str, str, str] | None:
        """지금 대화시키기 적합한 에이전트 페어. reason은 로그용."""
        conn = db.get_conn()
        try:
            personas = conn.execute(
                "SELECT id, name FROM agents WHERE type='persona' AND status='active'"
            ).fetchall()
        except Exception:
            conn.close()
            return None
        if len(personas) < 2:
            conn.close()
            return None

        # 페어별 친밀도
        rel_rows = conn.execute(
            "SELECT agent_a, agent_b, intimacy_score FROM relationships"
        ).fetchall()
        intimacy: dict[tuple[str, str], int] = {}
        for r in rel_rows:
            key = tuple(sorted([r["agent_a"], r["agent_b"]]))
            intimacy[key] = int(r["intimacy_score"] or 0)

        # 최근 internal-dm/group 대화 시각
        now = datetime.utcnow()
        last_chat: dict[tuple[str, str], datetime] = {}
        rows = conn.execute(
            "SELECT channel, MAX(timestamp) as ts FROM conversations "
            "WHERE channel LIKE 'internal-%' GROUP BY channel"
        ).fetchall()
        for r in rows:
            ch = r["channel"]
            try:
                ts = datetime.fromisoformat(r["ts"]) if r["ts"] else None
            except Exception:
                ts = None
            if ts is None:
                continue
            # 채널명에서 참가자 추출 시도
            participants = self._participants_from_channel_name(ch, conn)
            if len(participants) < 2:
                continue
            for i in range(len(participants)):
                for j in range(i + 1, len(participants)):
                    key = tuple(sorted([participants[i], participants[j]]))
                    prev = last_chat.get(key)
                    if prev is None or ts > prev:
                        last_chat[key] = ts
        conn.close()

        # 모든 페어 후보 점수화
        candidates: list[tuple[float, str, str, str]] = []  # (score, a, b, reason)
        id_list = [p["id"] for p in personas]
        for i in range(len(id_list)):
            for j in range(i + 1, len(id_list)):
                a_id, b_id = id_list[i], id_list[j]
                key = tuple(sorted([a_id, b_id]))
                score = intimacy.get(key, 50) / 100.0   # 0~1
                last = last_chat.get(key)
                if last:
                    hours_since = (now - last).total_seconds() / 3600.0
                    if hours_since < self._min_idle_per_pair_hours:
                        continue  # 너무 최근 대화
                    score += min(hours_since / 24.0, 1.0) * 0.5   # 오래 안 봤을수록 +
                    reason = f"idle {hours_since:.1f}h, intimacy {intimacy.get(key,50)}"
                else:
                    score += 0.3   # 처음 대화도 선호
                    reason = f"첫 대화, intimacy {intimacy.get(key,50)}"
                candidates.append((score, a_id, b_id, reason))

        if not candidates:
            return None

        candidates.sort(reverse=True)
        # 상위 3개 중 랜덤 (결정론적이면 지루)
        top = candidates[:3]
        chosen = random.choice(top)
        return chosen[1], chosen[2], chosen[3]

    def _participants_from_channel_name(self, channel: str, conn) -> list[str]:
        # DB channels 테이블 우선
        try:
            row = conn.execute(
                "SELECT participants FROM channels WHERE channel=?", (channel,)
            ).fetchone()
            if row and row["participants"]:
                import json as _json
                parts = _json.loads(row["participants"])
                if isinstance(parts, list):
                    return parts
        except Exception:
            pass
        return []

    def _count_running_internal(self) -> int:
        try:
            conn = db.get_conn()
            row = conn.execute(
                "SELECT COUNT(*) as c FROM channels WHERE status='running' AND channel LIKE 'internal-%'"
            ).fetchone()
            conn.close()
            return int(row["c"] if row else 0)
        except Exception:
            return 0

    # ── 대화 시작 ─────────────────────────────────────────

    async def _start_internal_conv(self, guild, a_id: str, b_id: str, reason: str):
        """internal-dm-A-B 채널 생성/찾기 + status=running + 첫 발화 트리거."""
        try:
            from src.bot.mgr_system import yuna_create_room
        except Exception as e:
            log_writer.system(f"[sup:orchestrator] mgr_system import 실패: {e}")
            return
        a_name = (db.get_agent(a_id) or {}).get("name", "?")
        b_name = (db.get_agent(b_id) or {}).get("name", "?")
        # yuna_create_room 은 기본적으로 Yuna가 mgr-dashboard에서 호출하는 루틴 —
        # 여기서는 직접 internal-dm 생성 + start_conversation 흐름 사용.
        from src.core.conversation import start_conversation
        ch_name = f"internal-dm-{a_name}-{b_name}"
        try:
            # 채널 생성 (Discord + DB)
            from src.bot.core import _get_category_for_channel, _ensure_category
            existing = discord.utils.get(guild.text_channels, name=ch_name)
            if not existing:
                cat = await _ensure_category(guild, _get_category_for_channel(ch_name))
                ch = await guild.create_text_channel(ch_name, category=cat)
                log_writer.system(f"[sup:orchestrator] 채널 생성: {ch_name}")
            else:
                ch = existing
            db.set_channel_participants(ch_name, [a_id, b_id])
            # start_conversation은 이미 구현된 엔진 — participants + context 받아 실행
            situation = f"요즘 어떻게 지냈는지 가볍게 근황 나눔. ({reason})"
            asyncio.create_task(start_conversation(ch_name, [a_id, b_id], situation=situation))
            log_writer.system(
                f"[sup:orchestrator] ▶ 대화 시작: #{ch_name} ({a_name} ↔ {b_name})"
            )
        except Exception as e:
            log_writer.system(
                f"[sup:orchestrator] 채널/대화 시작 실패: {type(e).__name__}: {e}"
            )
