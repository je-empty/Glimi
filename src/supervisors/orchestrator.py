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
        # 봇 기동 직후 바로 orchestrator 가 페어 선정하지 않도록 현재 시각으로 초기화.
        # 기존엔 0.0 으로 두어서 재기동 후 첫 check (15s 후) 에 즉시 대화 시작 →
        # persona 가 오너에게 인사할 틈도 없이 내부 대화 투입되는 회귀.
        import time as _time
        self._last_started_at: float = _time.time()
        self._min_gap_between_starts: float = 90.0    # 자동 시작 간 최소 간격
        self._min_idle_per_pair_hours: float = 0.5    # 페어별 최소 idle
        # 신규 persona 유예 — 생성 후 이 시간 동안은 orchestrator 후보에서 제외.
        # 이유: 갓 만들어진 친구가 오너와 첫 대면/인사 끝내기 전에 다른 persona 와
        # 내부 대화 시작하면 유저 몰입 깨짐.
        self._new_persona_grace_minutes: float = 30.0

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

        # 이미 running internal 채널 너무 많으면 추가 시작 자제
        # (5 로 상향 — 친구 N명 있을 때 여러 페어 동시 진행 허용)
        running_count = self._count_running_internal()
        if running_count >= 5:
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
            # created_at 도 가져와 신규 persona 유예 판정 — 갓 만들어진 친구는 스킵.
            personas = conn.execute(
                "SELECT id, name, created_at FROM agents WHERE type='persona' AND status='active'"
            ).fetchall()
        except Exception:
            conn.close()
            return None
        if len(personas) < 2:
            conn.close()
            return None

        # 신규 persona 필터 — 생성 후 grace 기간 안이면 후보에서 제거.
        now = datetime.utcnow()
        mature_ids: set[str] = set()
        for p in personas:
            try:
                created = datetime.fromisoformat(p["created_at"]) if p["created_at"] else None
            except Exception:
                created = None
            if created is None:
                mature_ids.add(p["id"])
                continue
            age_min = (now - created).total_seconds() / 60.0
            if age_min >= self._new_persona_grace_minutes:
                mature_ids.add(p["id"])

        # 페어별 친밀도
        rel_rows = conn.execute(
            "SELECT agent_a, agent_b, intimacy_score FROM relationships"
        ).fetchall()
        intimacy: dict[tuple[str, str], int] = {}
        for r in rel_rows:
            key = tuple(sorted([r["agent_a"], r["agent_b"]]))
            intimacy[key] = int(r["intimacy_score"] or 0)

        # 최근 internal-dm/group 대화 시각
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

        # 모든 페어 후보 점수화.
        # 제외 조건:
        #   - 둘 중 하나라도 신규 persona (grace 기간 안) → skip
        #   - 서로 관계 레코드도 없고 internal 대화 이력도 없음 → skip
        # 첫 대면은 persona 본인이 "쟤랑 얘기하고 싶다" 결정했을 때 자연스럽게 일어나야 함.
        candidates: list[tuple[float, str, str, str]] = []  # (score, a, b, reason)
        id_list = [p["id"] for p in personas]
        for i in range(len(id_list)):
            for j in range(i + 1, len(id_list)):
                a_id, b_id = id_list[i], id_list[j]
                if a_id not in mature_ids or b_id not in mature_ids:
                    continue
                key = tuple(sorted([a_id, b_id]))
                last = last_chat.get(key)
                has_rel = key in intimacy
                if not last and not has_rel:
                    continue  # 서로 전혀 모르는 사이 — orchestrator 는 skip
                score = intimacy.get(key, 0) / 100.0   # 0~1 (unknown 은 0)
                if last:
                    hours_since = (now - last).total_seconds() / 3600.0
                    if hours_since < self._min_idle_per_pair_hours:
                        continue  # 너무 최근 대화
                    score += min(hours_since / 24.0, 1.0) * 0.5   # 오래 안 봤을수록 +
                    reason = f"idle {hours_since:.1f}h, intimacy {intimacy.get(key,0)}"
                else:
                    # 관계 레코드는 있지만 아직 대화 없음 — 가벼운 가점만
                    score += 0.1
                    reason = f"관계 있음(첫 대화), intimacy {intimacy.get(key,0)}"
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
        from src.bot import internal_dm_channel_name
        ch_name = internal_dm_channel_name(a_name, b_name)
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
            # 첫 internal 대화면 관계 레코드도 자동 생성 — 없으면 다음 스캔에서도 계속
            # "모르는 사이" 로 분류되어 skip → rapport 쌓이지 못하는 루프. 여기서 기본
            # 관계 (친구, intimacy=30) 로 등록해 이후 orchestrator 가 정상 pick 가능.
            if not db.get_relationship(a_id, b_id):
                try:
                    db.add_relationship(a_id, b_id, "친구", intimacy=30, dynamics="처음 대화 시작")
                except Exception:
                    pass
            # start_conversation 시그니처: (channel_name, participants, send_fn, context, max_turns)
            # send_fn 은 (agent_id, message) → await send_as_agent 호출
            from src.bot.core import send_as_agent
            async def _send(agent_id: str, message: str):
                await send_as_agent(ch, agent_id, message)
            context_text = f"요즘 어떻게 지냈는지 가볍게 근황 나눔. ({reason})"
            asyncio.create_task(start_conversation(ch_name, [a_id, b_id], _send, context=context_text))
            log_writer.system(
                f"[sup:orchestrator] ▶ 대화 시작: #{ch_name} ({a_name} ↔ {b_name})"
            )
        except Exception as e:
            log_writer.system(
                f"[sup:orchestrator] 채널/대화 시작 실패: {type(e).__name__}: {e}"
            )
