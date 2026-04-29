"""DevQueueSupervisor — dev_requests 큐를 폴링해서 dev 매니저(세나) 응답 트리거.

System-scoped supervisor:
  - 30s 간격으로 status='pending' 인 row 가 있는지 체크.
  - 있으면 mgr-dev-request 채널로 dev agent 의 응답을 1턴 invoke.
  - dev agent 의 시스템 프롬프트가 "queue 가 비어있고 할 일 없으면 NO_REPLY" 룰을
    가지고 있어서, 큐가 비어있으면 자연스럽게 무발화.

봇 가동 중 dev_requests 가 들어오면 자동으로 dev agent 가 활성화됨.
"""
from __future__ import annotations

from src import db, log_writer
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

        # pending 카운트 빠르게 체크
        conn = db.get_conn()
        n = conn.execute(
            "SELECT COUNT(*) FROM dev_requests WHERE status='pending'"
        ).fetchone()[0]
        conn.close()

        if n == 0:
            return  # 할 일 없음 — dev 활성화 X

        # Dev agent lazy seed (혹시 안 됐으면)
        from src.core.dev_agent import ensure_dev_seeded, DEV_ID, DEV_CHANNEL
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
                category = await _ensure_category(guild, "glimi-mgr")
                from src.bot import MGR_ID
                ch = await ensure_unique_channel(
                    guild, DEV_CHANNEL, category, participants=[DEV_ID, MGR_ID]
                )
            except Exception as e:
                log_writer.system(f"[dev.queue] {DEV_CHANNEL} 채널 ensure 실패: {e}")
                return
            if ch is None:
                return

        # Dev agent invoke — pending 큐에서 가장 오래된 1건 대상.
        # generate_response 는 user_message 가 필요한데, 큐 상태를 자연어로 변환해서 전달.
        try:
            from src.core.dev_agent import get_pending_requests
            pending = get_pending_requests(limit=1)
            if not pending:
                return
            req = pending[0]
            user_msg = (
                f"[QUEUE TRIGGER] 새 요청 #{req['id']} 들어옴.\n"
                f"requested_by: {req['requested_by']}\n"
                f"payload_json: {req['payload_json']}\n\n"
                f"위 요청 검토하고 (1) HIGH-confidence 면 dev_dispatch_fix 호출, "
                f"(2) 모호하면 dev_escalate, (3) 페이로드 부족하면 dev_clarify."
            )
            from src.core.runtime import runtime
            from src.bot.core import send_as_agent
            responses = await runtime.generate_response_force(
                agent_id=DEV_ID,
                channel=DEV_CHANNEL,
                user_message=user_msg,
            )
            # 응답 chat 메시지를 mgr-dev-request 에 게시
            for msg in responses:
                if msg and msg.strip():
                    try:
                        await send_as_agent(ch, DEV_ID, msg)
                    except Exception as e:
                        log_writer.system(f"[dev.queue] send_as_agent 실패: {e}")
            # tool 호출 결과는 generate_response_force 안에서 dispatcher 가 처리.
        except Exception as e:
            log_writer.system(f"[dev.queue] dev agent invoke 오류: {type(e).__name__}: {e}")
