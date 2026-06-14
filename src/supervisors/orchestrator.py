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
from datetime import datetime, timedelta, timezone

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

        # Quiet hours (01:00~07:59 KST) — 새벽 자동 페어링 차단.
        from src.core.scoping import is_quiet_hour, quiet_hour_label
        if is_quiet_hour():
            log_writer.system(
                f"[sup:orchestrator] pairing skip — quiet hour ({quiet_hour_label()})"
            )
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

        # ① group-* 채널 revive — 페르소나가 오너 부재 시에도 group-* 에서 자발 대화.
        # 기존: orchestrator 가 internal-dm 만 점화 → group-* 는 오너 떠나면 영원 침묵.
        # 수정: 오래 idle 한 group-* 채널에서 페르소나끼리 먼저 수다 시작.
        revived = await self._revive_idle_group(guild)
        if revived:
            self._last_started_at = _time.time()
            return

        # ② 페어 후보 스캔 (internal-dm)
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
        try:
            from src.supervisors.events import log_event as _log_sup_event
            _log_sup_event(
                sup_id="orchestrator", action="pair_start",
                targets=[a_id, b_id],
                summary=f"{a_name} ↔ {b_name} 대화 시작 ({reason})",
                outcome="ok",
                details={"reason": reason},
            )
        except Exception:
            pass
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
        # UTC-aware now — DB 타임스탬프는 UTC-aware ISO 포맷. naive 와 섞으면 TypeError.
        now = datetime.now(timezone.utc)
        mature_ids: set[str] = set()
        for p in personas:
            try:
                created = datetime.fromisoformat(p["created_at"]) if p["created_at"] else None
                # 레거시 naive 타임스탬프 방어 — UTC 로 취급.
                if created and created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
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

        # 최근 internal-* / group-* / dm-* 대화 시각 — 페어 freshness 계산.
        # 기존: internal-* 만. 수정: group-*, dm-* 도 포함해야 "최근 dm-A 에서 말 많이 나눔"
        # 페어가 internal-dm 자동 개설 쿨다운에 들어감. 없으면 금방 다시 꺼냄.
        last_chat: dict[tuple[str, str], datetime] = {}
        rows = conn.execute(
            "SELECT channel, MAX(timestamp) as ts FROM conversations "
            "WHERE channel LIKE 'internal-%' OR channel LIKE 'group-%' OR channel LIKE 'dm-%' "
            "GROUP BY channel"
        ).fetchall()
        for r in rows:
            ch = r["channel"]
            try:
                ts = datetime.fromisoformat(r["ts"]) if r["ts"] else None
                if ts and ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
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

    async def _revive_idle_group(self, guild) -> bool:
        """오래 idle 한 group-* 채널에서 페르소나들끼리 자발적 대화 재개.

        조건:
          - 채널에 페르소나 2+ 참여 (오너 제외)
          - 마지막 메시지가 min_group_idle 이상 전
          - 채널 status != 'running'
        반환: revive 했으면 True, 아니면 False.
        """
        try:
            conn = db.get_conn()
            # 모든 group-* 채널 + 참여자
            rows = conn.execute(
                "SELECT channel, participants, status FROM channels "
                "WHERE channel LIKE 'group-%' AND channel NOT LIKE 'group-' || '' "
            ).fetchall()
            now = datetime.now(timezone.utc)
            candidates: list[tuple[float, str, list]] = []
            for r in rows:
                ch = r["channel"]
                # internal- 접두사 방어 (SQL 조건이 group-% 라서 internal-group-% 포함됨)
                if ch.startswith("internal-"):
                    continue
                if r["status"] == "running":
                    continue
                try:
                    import json as _json
                    parts = _json.loads(r["participants"] or "[]")
                except Exception:
                    parts = []
                if not isinstance(parts, list):
                    continue
                # 페르소나만 추리기
                personas = [pid for pid in parts if pid and pid.startswith("agent-persona-")]
                if len(personas) < 2:
                    continue
                last = conn.execute(
                    "SELECT MAX(timestamp) as ts FROM conversations WHERE channel=?", (ch,)
                ).fetchone()
                ts_raw = last["ts"] if last else None
                hours_since = 999.0
                if ts_raw:
                    try:
                        ts = datetime.fromisoformat(ts_raw)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        hours_since = (now - ts).total_seconds() / 3600.0
                    except Exception:
                        pass
                if hours_since < 1.0:
                    continue  # 1시간 이내 대화 있으면 스킵
                candidates.append((hours_since, ch, personas))
            conn.close()
            if not candidates:
                return False
            candidates.sort(reverse=True)
            hours_since, ch_name, personas = candidates[0]
            # 최대 3명까지 (그룹 규모 제한)
            if len(personas) > 3:
                personas = random.sample(personas, 3)
            from src.bot.conversation_bridge import start_conversation
            from src.bot.core import send_as_agent

            ch = discord.utils.get(guild.text_channels, name=ch_name)
            if not ch:
                return False

            async def _send(agent_id: str, message: str):
                await send_as_agent(ch, agent_id, message)

            names = []
            for pid in personas:
                a = db.get_agent(pid)
                names.append(a["name"] if a else pid)
            log_writer.system(
                f"[sup:orchestrator] ▶ group revive: #{ch_name} ({' · '.join(names)}, idle {hours_since:.1f}h)"
            )
            try:
                from src.supervisors.events import log_event as _log_sup_event
                _log_sup_event(
                    sup_id="orchestrator", action="group_revive",
                    targets=list(personas),
                    summary=f"#{ch_name} 그룹 부활 ({', '.join(names)}, idle {hours_since:.1f}h)",
                    outcome="ok",
                    details={"channel": ch_name, "idle_hours": round(hours_since, 1)},
                )
            except Exception:
                pass
            ctx_text = f"오너 없을 때 자연스럽게 모여서 수다. 공통 관심사로 가볍게. (idle {hours_since:.1f}h)"
            asyncio.create_task(start_conversation(ch_name, personas, _send, context=ctx_text))
            return True
        except Exception as e:
            log_writer.system(f"[sup:orchestrator] group revive 오류: {type(e).__name__}: {e}")
            return False

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
        from src.bot.conversation_bridge import start_conversation
        from src.bot import internal_dm_channel_name
        ch_name = internal_dm_channel_name(a_name, b_name)
        try:
            # 채널 생성 (Discord + DB) — ensure_unique_channel 로 중복 생성 방지
            from src.bot.core import _get_category_for_channel, _ensure_category
            from src.core.sync import ensure_unique_channel
            cat = await _ensure_category(guild, _get_category_for_channel(ch_name))
            ch, created = await ensure_unique_channel(guild, ch_name, cat)
            if created:
                log_writer.system(f"[sup:orchestrator] 채널 생성: {ch_name}")
            db.set_channel_participants(ch_name, [a_id, b_id])
            # 첫 internal 대화면 관계 레코드도 자동 생성 — 없으면 다음 스캔에서도 계속
            # "모르는 사이" 로 분류되어 skip → rapport 쌓이지 못하는 루프. 여기서 기본
            # 관계 (친구, intimacy=30) 로 등록해 이후 orchestrator 가 정상 pick 가능.
            if not db.get_relationship(a_id, b_id):
                try:
                    db.add_relationship(a_id, b_id, "친구", intimacy=30, dynamics="처음 대화 시작")
                except Exception:
                    pass
            from src.bot.core import send_as_agent
            async def _send(agent_id: str, message: str):
                await send_as_agent(ch, agent_id, message)

            # 풍성한 context — 짧은 대화·작별 echo 회귀 fix.
            # 두 에이전트의 직업/관심사 + 관계 dynamics + intimacy + 최근 dm 활동 요약을 묶어 seed.
            context_text = self._build_rich_context(a_id, b_id, a_name, b_name, reason)
            # 페르소나끼리 internal-dm 은 16턴까지 허용 (default 8 은 너무 일찍 wrap-up)
            asyncio.create_task(
                start_conversation(ch_name, [a_id, b_id], _send,
                                    context=context_text, max_turns=16)
            )
            log_writer.system(
                f"[sup:orchestrator] ▶ 대화 시작: #{ch_name} ({a_name} ↔ {b_name})"
            )
        except Exception as e:
            log_writer.system(
                f"[sup:orchestrator] 채널/대화 시작 실패: {type(e).__name__}: {e}"
            )

    def _build_rich_context(self, a_id: str, b_id: str, a_name: str, b_name: str, reason: str) -> str:
        """internal-dm 시작 시 두 페르소나 간 자연스러운 시작 토픽 seed.

        포함:
          - 각자 직업·관심사 (profile)
          - 관계 (type/intimacy/dynamics)
          - 최근 각자의 dm 에서 언급한 화제 1줄씩 (자연스러운 referent)
        seed 가 있으면 페르소나가 첫 턴에 "OO 어떻게 됐어?" 식으로 specific 시작 가능.
        """
        try:
            from src.core.profile import load_profile
            pa = load_profile(a_id) or {}
            pb = load_profile(b_id) or {}
            a_occ = (pa.get("daily_life") or {}).get("occupation", "") if pa else ""
            b_occ = (pb.get("daily_life") or {}).get("occupation", "") if pb else ""
            a_interests = ", ".join((pa.get("personality") or {}).get("likes", [])[:3])
            b_interests = ", ".join((pb.get("personality") or {}).get("likes", [])[:3])

            # 관계
            rel = db.get_relationship(a_id, b_id) or db.get_relationship(b_id, a_id) or {}
            rel_type = rel.get("type", "친구")
            intimacy = rel.get("intimacy_score", 30)
            dynamics = rel.get("dynamics", "")

            # 각자의 dm 채널에서 마지막 발화 1줄 — 최근 화제 referent
            def _last_dm_topic(name: str) -> str:
                try:
                    conn = db.get_conn()
                    row = conn.execute(
                        "SELECT message FROM conversations WHERE channel=? "
                        "ORDER BY id DESC LIMIT 1",
                        (f"dm-{name}",),
                    ).fetchone()
                    conn.close()
                    if row and row["message"]:
                        return row["message"][:60]
                except Exception:
                    pass
                return ""

            a_topic = _last_dm_topic(a_name)
            b_topic = _last_dm_topic(b_name)

            parts = [
                f"{a_name} ↔ {b_name} internal-dm — {rel_type} 사이 (친밀도 {intimacy}/100).",
            ]
            if dynamics:
                parts.append(f"관계 분위기: {dynamics}.")
            if a_occ or b_occ or a_interests or b_interests:
                parts.append(
                    f"{a_name}: {a_occ or '?'} | 관심: {a_interests or '?'}. "
                    f"{b_name}: {b_occ or '?'} | 관심: {b_interests or '?'}."
                )
            if a_topic:
                parts.append(f"{a_name} 최근 빈이랑 한 얘기: \"{a_topic}\"")
            if b_topic:
                parts.append(f"{b_name} 최근 빈이랑 한 얘기: \"{b_topic}\"")
            parts.append(
                "이걸 referent 로 자연스럽게 말 걸어. "
                "근황·공통 관심사·서로 안부 깊게 — 8턴 이상 충분히 풀어. "
                "한 줄 작별 echo 로 일찍 끝내지 말 것."
            )
            parts.append(f"({reason})")
            return " ".join(parts)
        except Exception as e:
            log_writer.system(f"[sup:orchestrator] context build 실패 (fallback): {e}")
            return f"요즘 어떻게 지냈는지 가볍게 근황 나눔. ({reason})"
