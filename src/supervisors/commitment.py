"""CommitmentSupervisor — 에이전트 commitment ('갈게', '할게', '부탁할게') 추적.

문제:
  유나가 internal-dm-서유나-윤하나 에서 "하나야 ~~ 부탁해" 요청 →
  하나가 "ㅋㅋ 알겠어, mgr-creator 가서 빈이한테 물어볼게" 약속 →
  내부 대화 끝남. 이후 trigger 없으면 하나가 mgr-creator 에 가서 발화 안 함.
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

from src import community as _community, db, log_writer
from src.supervisors.base import Supervisor


# Commitment 발화 감지 — "(channel) 가볼게" 류 패턴.
# Group 1: 채널 (mgr-creator 등). Group 2: 약속 동사 (가볼게/할게/물어볼게/부탁할게/등).
_COMMIT_PATTERNS = [
    # 채널명 #mgr-creator 가볼게 / mgr-creator 에 가볼게
    _re.compile(r"#?(mgr-[a-z\-가-힣]+|dm-[\w가-힣]+|group-[\w가-힣\-]+)\s*(?:에|로)?\s*가\s*(?:볼게|봐야|볼래|볼)|"
                r"#?(mgr-[a-z\-가-힣]+|dm-[\w가-힣]+|group-[\w가-힣\-]+)\s*에서\s*(?:할|물어|가)",
                _re.IGNORECASE),
]

# 채널명 명시 없이 단순 "갈게/물어볼게/할게" — context 로 추측 (internal-dm 안에서)
_GENERIC_COMMIT = _re.compile(
    r"(빈이한테|오너한테|.*한테)?\s*(?:물어볼게|갈게|가볼게|가서|할게|해볼게|보낼게|만들게)",
)

# Channel hints — 내부 commitment 만 있을 때 디폴트 target 결정용
_DEFAULT_TARGET_BY_AGENT_TYPE = {
    "creator": "mgr-creator",  # 하나는 mgr-creator 가 본거지
    "mgr": "mgr-dashboard",
}

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
        guild = ctx.get("guild")
        if guild is None:
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

            # 5 분 안 지났으면 skip
            try:
                from src.core.timeutil import parse_aware
                ts_dt = parse_aware(commit_ts)
                elapsed = now - ts_dt.timestamp()
            except Exception:
                continue
            if elapsed < NUDGE_AFTER_SEC:
                continue

            # target_ch 에 해당 agent 발화 있었는지 (commit_ts 이후)
            if self._agent_spoke_after(agent_id, target_ch, commit_ts):
                continue  # 약속 이행됨

            # invoke_agent 로 nudge
            await self._nudge_agent(guild, agent_id, agent_name, target_ch, commit_msg)
            self._last_nudge[key] = now

    # ── helpers ───────────────────────────────────────────────

    def _scan_recent_commitments(self) -> list[dict]:
        """최근 1시간 내 internal-dm/internal-group 에서 commitment 발화 추출.
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
                "AND c.timestamp >= datetime('now', '-1 hour') "
                "ORDER BY c.id DESC LIMIT 100"
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
                target = _DEFAULT_TARGET_BY_AGENT_TYPE.get(d["agent_type"])
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

    async def _nudge_agent(self, guild, agent_id: str, agent_name: str,
                            target_channel: str, commit_msg: str) -> None:
        """invoke_agent 로 강제 nudge — 해당 agent 가 target_channel 에서 약속 이행 발화."""
        try:
            from src.bot.mgr_system import yuna_force_agent
            import json as _json
            # invoke_agent payload 형식: {name, target, instruction}
            instruction = (
                f"방금 internal-dm 에서 한 약속 이행 차례 — '{commit_msg[:120]}'. "
                f"#{target_channel} 가서 약속한 작업 시작. 빈이가 기다리고 있어."
            )
            payload = _json.dumps({
                "name": agent_name,
                "target": target_channel,
                "instruction": instruction,
            }, ensure_ascii=False)
            # yuna_force_agent 가 expect 하는 channel 객체 — mgr-dashboard 가 제일 안전
            mgr_ch = next((c for c in guild.text_channels if c.name == "mgr-dashboard"), None)
            await yuna_force_agent(mgr_ch, payload, guild)
            log_writer.system(
                f"[commitment] {agent_name} → #{target_channel} nudge 발송 (commit: {commit_msg[:80]})"
            )
        except Exception as e:
            log_writer.system(f"[commitment] nudge 실패 ({agent_name} → #{target_channel}): {e}")
