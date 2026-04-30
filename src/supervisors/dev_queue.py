"""DevQueueSupervisor — dev_requests 큐를 폴링해서 dev 매니저(세나) 응답 트리거.

System-scoped supervisor:
  - 30s 간격으로 platform.db 의 status='pending' 인 row 중 현재 community 발생분 체크.
  - 있으면 mgr-dev-request 채널로 dev agent 응답 1턴 invoke.
  - dev agent 가 dev_organize / dev_escalate / dev_clarify 중 하나 선택해서 처리.
  - 큐가 비어있으면 자연스럽게 무발화 (NO_REPLY).
"""
from __future__ import annotations

from src import community, log_writer
from src.supervisors.base import Supervisor


class DevQueueSupervisor(Supervisor):
    id = "dev.queue"
    display_name = "Dev 큐 감시 (세나)"
    kind = "system"
    interval = 30.0  # 30s 마다 폴링

    def should_exist(self) -> bool:
        return True  # 봇 수명 내내 유지

    async def check(self, ctx: dict) -> None:
        guild = ctx.get("guild")
        if guild is None:
            return

        cid = community.get_community_id() or ""
        if not cid:
            return

        from src.core.dev_agent import (
            DEV_ID, DEV_CHANNEL,
            ensure_dev_seeded, get_pending_for_community,
        )
        pending = get_pending_for_community(cid, limit=1)
        if not pending:
            return  # 할 일 없음

        # Dev agent lazy seed
        ensure_dev_seeded()

        # mgr-dev-request 채널 ensure
        ch = None
        for c in guild.text_channels:
            if c.name == DEV_CHANNEL:
                ch = c
                break
        if ch is None:
            try:
                from src.core.sync import ensure_unique_channel
                from src.bot.core import _ensure_category
                from src.bot import MGR_ID
                from src import db as _db
                category = await _ensure_category(guild, "glimi-mgr")
                # ensure_unique_channel 은 (channel, created) 튜플 반환
                result = await ensure_unique_channel(guild, DEV_CHANNEL, category)
                ch = result[0] if isinstance(result, tuple) else result
                # DB 참여자 등록 (세나 + 유나)
                _db.set_channel_participants(DEV_CHANNEL, [DEV_ID, MGR_ID])
            except Exception as e:
                log_writer.system(f"[dev.queue] {DEV_CHANNEL} 채널 ensure 실패: {e}")
                return
            if ch is None:
                return

        # Dev agent invoke — pending 큐에서 가장 오래된 1건 대상.
        try:
            req = pending[0]
            user_msg = (
                f"[QUEUE TRIGGER] 새 요청 #{req['id']} 들어옴.\n"
                f"requested_by: {req['requested_by']}\n"
                f"severity: {req.get('severity','?')}\n"
                f"payload_json: {req['payload_json']}\n\n"
                "위 요청 검토하고 다음 중 정확히 하나를 호출:\n"
                "  - dev_organize (가장 흔함, 작업 brief 정리해서 admin 검토 대기로)\n"
                "  - dev_escalate (정리도 어려운 모호한 케이스, admin 직접 판단)\n"
                "  - dev_clarify (보고서 정보 부족, 추가 질문)\n"
                "그리고 mgr-dev-request 에 in-character 한 줄 ack."
            )
            from src.core.runtime import runtime
            from src.bot.core import send_as_agent
            from src.bot.mgr_system import parse_and_execute_actions
            responses = await runtime.generate_response_force(
                agent_id=DEV_ID,
                channel=DEV_CHANNEL,
                user_message=user_msg,
            )
            # tool 호출 dispatch (dev_organize / dev_escalate / dev_clarify) — 응답 텍스트와
            # 별개로 runtime 이 stash 한 tool_calls 를 ToolContext 로 실행.
            try:
                responses = await parse_and_execute_actions(
                    ch, responses, guild, caller_agent_id=DEV_ID,
                )
            except Exception as e:
                log_writer.system(f"[dev.queue] tool dispatch 실패: {type(e).__name__}: {e}")
            # 응답 chat 메시지를 mgr-dev-request 에 게시
            for msg in responses or []:
                if msg and msg.strip():
                    try:
                        await send_as_agent(ch, DEV_ID, msg)
                    except Exception as e:
                        log_writer.system(f"[dev.queue] send_as_agent 실패: {e}")
        except Exception as e:
            log_writer.system(f"[dev.queue] dev agent invoke 오류: {type(e).__name__}: {e}")
