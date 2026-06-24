"""CommitmentSupervisor — 에이전트 commitment ('갈게', '할게', '부탁할게') 추적.

문제:
  유나가 internal-dm-서유나-윤하나 에서 "하나야 ~~ 부탁해" 요청 →
  하나가 "ㅋㅋ 알겠어, 내 DM 가서 빈이한테 물어볼게" 약속 →
  내부 대화 끝남. 이후 trigger 없으면 하나가 자기 DM 채널에 가서 발화 안 함.
  결과: 약속 묵음 + 빈이 무한 대기.

해결:
  internal-dm/internal-group 에서 commitment 패턴 (X 가볼게 / 할게 / 부탁할게) 발화 후
  N (5) 분 안에 X 채널에서 해당 agent 발화가 없으면 invoke_agent 로 강제 nudge.

스코프:
  system supervisor — 60s 마다 internal-dm/internal-group 채널의 최근 메시지 검사.
  pending commitment 추적 (in-memory) + 최근 nudge 시각 (중복 nudge 방지).
"""
from __future__ import annotations

import re as _re
import time as _time
from typing import Optional

from community import community as _community, db, log_writer
from community.supervisors.base import Supervisor


# Commitment 발화 감지 — "(channel) 가볼게" 류 패턴.
# Group 1: 채널 (dm-윤하나 등; 레거시 mgr-* 도 매칭). Group 2: 약속 동사 (가볼게/할게/등).
_COMMIT_PATTERNS = [
    # 채널명 #dm-윤하나 가볼게 / dm-윤하나 에 가볼게 (레거시 mgr-* 도 매칭)
    _re.compile(r"#?(mgr-[a-z\-가-힣]+|dm-[\w가-힣]+|group-[\w가-힣\-]+)\s*(?:에|로)?\s*가\s*(?:볼게|봐야|볼래|볼)|"
                r"#?(mgr-[a-z\-가-힣]+|dm-[\w가-힣]+|group-[\w가-힣\-]+)\s*에서\s*(?:할|물어|가)",
                _re.IGNORECASE),
]

# 채널명 명시 없이 단순 "갈게/물어볼게/할게" — context 로 추측 (internal-dm 안에서)
# 우리 root 의 promise_re 풍부한 패턴 통합 — mgr 가 same-turn 약속만 하고 도구 호출
# 없는 회귀에서 잡힌 사례 다수 추가 (확인해볼게/체크할게/살펴볼게 등).
_GENERIC_COMMIT = _re.compile(
    r"(빈이한테|오너한테|.*한테)?\s*"
    r"(?:물어볼게|물어볼래|갈게|가볼게|가볼래|가서|할게|해볼게|해볼래|"
    r"보낼게|만들게|만들어볼게|확인해볼게|확인할게|찾아볼게|알아볼게|"
    r"전달할게|체크할게|살펴볼게|시킬게|요청할게|알려줄게|"
    r"적용할게|반영할게|넣어둘게|넣어볼게)",
)

# Channel hints — 내부 commitment 만 있을 때 디폴트 target 결정용.
# 스태프(유나/하나/세나) DM 채널 키는 id 기반 정본 (dm-<agent-id>) — 표시 이름은
# 로케일 종속이라 채널 키에 새기지 않는다(i18n). resolver 가 legacy dm-<이름> 폴백 처리.
def _default_target_for_type(agent_type: str) -> Optional[str]:
    """agent_type (mgr/creator/dev) → 그 스태프의 owner↔manager DM 채널 키 (dm-<id>)."""
    from community.core.channels import mgr_channel, creator_channel, dev_channel
    return {
        "mgr": mgr_channel, "creator": creator_channel, "dev": dev_channel,
    }.get(agent_type, lambda: None)()


def _mgr_dm_channel_name() -> str:
    """mgr (유나) 의 owner↔mgr DM 채널 키 — yuna_force_agent 호출 컨텍스트용 (id 기반)."""
    from community.core.channels import mgr_channel
    return mgr_channel()

NUDGE_AFTER_SEC = 5 * 60      # 5 분 안에 안 가면 nudge
RENUDGE_COOLDOWN_SEC = 15 * 60  # 같은 (agent, target) 쌍 15 분에 1회만 nudge


class CommitmentSupervisor(Supervisor):
    id = "commitment.tracker"
    display_name = "약속 이행 추적"
    kind = "system"
    interval = 60.0  # 1 분 폴링

    def __init__(self, scope=None):
        super().__init__(scope)
        # (agent_id, target_channel) → last_nudge_ts. 중복 nudge 방지.
        self._last_nudge: dict[tuple, float] = {}
        # 직전 처리 시각 (메시지 cursor) — 매 tick 새 메시지만 검사
        self._last_scan_msg_id: int = 0

    def is_active(self) -> bool:
        """현재 추적 중인 commitment 있을 때만 active (UI 표시용).
        간단 추정: 최근 nudge 가 30분 안에 있었으면 active."""
        if not self._last_nudge:
            return False
        now = _time.time()
        return any((now - ts) < 30 * 60 for ts in self._last_nudge.values())

    async def check(self, ctx: dict) -> None:
        channels = ctx.get("channels")
        guild = ctx.get("guild")
        if channels is None and guild is None:
            return

        commitments = self._scan_recent_commitments()
        if not commitments:
            return

        # 각 commitment 의 target_channel 에서 해당 agent 발화 있었는지 확인
        for cm in commitments:
            agent_id = cm["agent_id"]
            agent_name = cm["agent_name"]
            target_ch = cm["target_channel"]
            commit_msg = cm["commit_msg"]
            commit_ts = cm["commit_ts"]

            # cooldown 체크
            now = _time.time()
            key = (agent_id, target_ch)
            last = self._last_nudge.get(key, 0.0)
            if now - last < RENUDGE_COOLDOWN_SEC:
                continue

            # 5 분 안 지났으면 skip.
            # commit_ts 포맷: "YYYY-MM-DD HH:MM:SS" (DB CURRENT_TIMESTAMP, naive UTC)
            # 또는 ISO+tz. 둘 다 처리.
            elapsed = self._elapsed_since(commit_ts, now)
            if elapsed is None:
                log_writer.system(f"[commitment] ts parse 실패 — skip ({commit_ts!r})")
                continue
            if elapsed < NUDGE_AFTER_SEC:
                continue

            # target_ch 에 해당 agent 발화 있었는지 (commit_ts 이후)
            if self._agent_spoke_after(agent_id, target_ch, commit_ts):
                continue  # 약속 이행됨

            # invoke_agent 로 nudge
            await self._nudge_agent(channels, guild, agent_id, agent_name, target_ch, commit_msg)
            self._last_nudge[key] = now

    # ── helpers ───────────────────────────────────────────────

    @staticmethod
    def _elapsed_since(ts: str, now_posix: float) -> Optional[float]:
        """DB timestamp (UTC naive 'YYYY-MM-DD HH:MM:SS' 또는 ISO with tz) → 경과초.
        실패 시 None."""
        if not ts:
            return None
        from datetime import datetime as _dt, timezone as _tz
        s = ts.strip().replace("T", " ")
        # tz 정보가 있으면 fromisoformat 으로 그대로 처리
        try:
            if "+" in s or s.endswith("Z") or "-" in s[10:]:
                iso = ts.replace("Z", "+00:00")
                dt = _dt.fromisoformat(iso)
                return now_posix - dt.timestamp()
        except Exception:
            pass
        # naive — UTC 로 가정 (SQLite CURRENT_TIMESTAMP 기본)
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                dt = _dt.strptime(s, fmt).replace(tzinfo=_tz.utc)
                return now_posix - dt.timestamp()
            except ValueError:
                continue
        return None

    def _scan_recent_commitments(self) -> list[dict]:
        """최근 12시간 내 internal-dm/internal-group 에서 commitment 발화 추출.
        12h 윈도우는 봇 재시작·overnight 이후에도 미처리 stall 회복하기 위함.
        Cooldown (15min) 이 중복 nudge 차단.
        반환: [{agent_id, agent_name, target_channel, commit_msg, commit_ts}, ...]
        """
        out = []
        try:
            conn = db.get_conn()
            rows = conn.execute(
                "SELECT c.id, c.channel, c.speaker, c.message, c.timestamp, "
                "  a.name as agent_name, a.type as agent_type "
                "FROM conversations c JOIN agents a ON a.id = c.speaker "
                "WHERE (c.channel LIKE 'internal-dm-%' OR c.channel LIKE 'internal-group-%') "
                "AND c.timestamp >= datetime('now', '-12 hours') "
                "ORDER BY c.id DESC LIMIT 200"
            ).fetchall()
            conn.close()
        except Exception as e:
            log_writer.system(f"[commitment] scan 실패: {e}")
            return out

        for r in rows:
            d = dict(r)
            msg = (d["message"] or "").strip()
            if not msg:
                continue
            # 1) 채널 명시 패턴
            target = None
            for pat in _COMMIT_PATTERNS:
                m = pat.search(msg)
                if m:
                    target = next((g for g in m.groups() if g), None)
                    break
            # 2) generic + agent type 디폴트
            if not target and _GENERIC_COMMIT.search(msg):
                target = _default_target_for_type(d["agent_type"])
            if not target:
                continue
            out.append({
                "agent_id": d["speaker"],
                "agent_name": d["agent_name"] or d["speaker"],
                "target_channel": target,
                "commit_msg": msg[:200],
                "commit_ts": d["timestamp"],
                "msg_id": d["id"],
            })
        # 같은 agent 의 최신 commitment 만 유지 (오래된 게 미해소면 그것도 OK 지만 latest 우선)
        seen = set()
        deduped = []
        for c in out:  # already DESC by id
            k = (c["agent_id"], c["target_channel"])
            if k in seen:
                continue
            seen.add(k)
            deduped.append(c)
        return deduped

    def _agent_spoke_after(self, agent_id: str, channel: str, since_ts: str) -> bool:
        try:
            conn = db.get_conn()
            row = conn.execute(
                "SELECT 1 FROM conversations WHERE speaker=? AND channel=? AND timestamp > ? LIMIT 1",
                (agent_id, channel, since_ts),
            ).fetchone()
            conn.close()
            return row is not None
        except Exception:
            return False

    async def _nudge_agent(self, channels, guild, agent_id: str, agent_name: str,
                            target_channel: str, commit_msg: str) -> None:
        """invoke_agent 로 강제 nudge — 해당 agent 가 target_channel 에서 약속 이행 발화.

        Phase 3.4: yuna_force_agent 새 시그니처 (channel_name, args_str, ctx) +
        adapter-first. args_str 는 "이름 채널 지시" 공백 구분 (split(None,2)).
        """
        from community.supervisors.events import log_event as _log_sup_event
        try:
            instruction = (
                f"방금 internal-dm 에서 한 약속 이행 차례 — '{commit_msg[:120]}'. "
                f"#{target_channel} 가서 약속한 작업 시작. 빈이가 기다리고 있어."
            )
            args_str = f"{agent_name} {target_channel} {instruction}"
            _mgr_dm = _mgr_dm_channel_name()

            if channels is not None:
                # adapter-first (web). BEFORE community.bot import.
                from community.core.mgr_actions import yuna_force_agent, MGR_ID
                from glimi.tools.dispatcher import ToolContext
                ctx = ToolContext(caller_agent_id=MGR_ID, caller_agent_type="mgr",
                                  channel_name=_mgr_dm, channels=channels)
                await yuna_force_agent(_mgr_dm, args_str, ctx)
            else:
                # guild-fallback (Discord — Phase-6-doomed).
                from community.bot.mgr_system import core_mgr_actions
                from community.adapters.discord.channels import get_discord_adapter
                from community.core.mgr_actions import MGR_ID
                from glimi.tools.dispatcher import ToolContext
                ctx = ToolContext(caller_agent_id=MGR_ID, caller_agent_type="mgr",
                                  channel_name=_mgr_dm, channels=get_discord_adapter())
                await core_mgr_actions.yuna_force_agent(_mgr_dm, args_str, ctx)
            log_writer.system(
                f"[commitment] {agent_name} → #{target_channel} nudge 발송 (commit: {commit_msg[:80]})"
            )
            _log_sup_event(
                sup_id="commitment.tracker",
                action="nudge",
                targets=[agent_id],
                summary=f"{agent_name} → #{target_channel} 약속 이행 강제 발화",
                outcome="ok",
                details={"target_channel": target_channel, "commit_msg": commit_msg[:200]},
            )
        except Exception as e:
            log_writer.system(f"[commitment] nudge 실패 ({agent_name} → #{target_channel}): {e}")
            _log_sup_event(
                sup_id="commitment.tracker",
                action="nudge",
                targets=[agent_id],
                summary=f"{agent_name} → #{target_channel} nudge 시도 실패",
                outcome="failed",
                details={"target_channel": target_channel, "error": str(e)},
            )
