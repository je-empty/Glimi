"""DevQueueSupervisor — dev_requests 큐를 폴링해서 dev 매니저(세나) 응답 트리거.

System-scoped supervisor:
  - 30s 간격으로 platform.db 의 status='pending' 인 row 중 현재 community 발생분 체크.
  - 있으면 dev (세나) DM 채널로 dev agent 응답 1턴 invoke.
  - dev agent 가 dev_organize / dev_escalate / dev_clarify 중 하나 선택해서 처리.
  - 큐가 비어있으면 자연스럽게 무발화 (NO_REPLY).
"""
from __future__ import annotations

from community import community, log_writer
from community.supervisors.base import Supervisor


class DevQueueSupervisor(Supervisor):
    id = "dev.queue"
    display_name = "Dev 큐 감시 (세나)"
    kind = "system"
    interval = 30.0  # 30s 마다 폴링

    def should_exist(self) -> bool:
        return True  # 봇 수명 내내 유지 (큐 비어있어도 등록은 유지)

    def is_active(self) -> bool:
        """큐에 처리할 요청 (pending/analyzed/approved/queued/processing) 있을 때만 active.
        그 외엔 idle — UI 에서 회색 표시되어 '대기' 상태임이 명확."""
        try:
            from community.core.dev_agent import has_active_work
            return has_active_work()
        except Exception:
            return False

    async def check(self, ctx: dict) -> None:
        channels = ctx.get("channels")
        guild = ctx.get("guild")
        if channels is None and guild is None:
            return

        cid = community.get_community_id() or ""
        if not cid:
            return

        from community.core.dev_agent import (
            DEV_ID, DEV_CHANNEL,
            ensure_dev_seeded, get_pending_for_community,
        )
        pending = get_pending_for_community(cid, limit=1)
        if not pending:
            return  # 할 일 없음

        # Dev agent lazy seed
        ensure_dev_seeded()

        from community.core.channels import MGR_ID
        from community import db as _db

        # dev (세나) DM 채널 ensure — web transport (channels adapter always present).
        if channels is None:
            return
        try:
            await channels.ensure_channel(DEV_CHANNEL, participants=[DEV_ID, MGR_ID])
            _db.set_channel_participants(DEV_CHANNEL, [DEV_ID, MGR_ID])
        except Exception as e:
            log_writer.system(f"[dev.queue] {DEV_CHANNEL} 채널 ensure 실패: {e}")
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
                "그리고 너의 DM 채널에 in-character 한 줄 ack."
            )
            from community.core.runtime import runtime
            import asyncio as _asyncio
            # generate_response_force 는 sync + 내부에서 subprocess.run(claude CLI, 120s) 호출.
            # asyncio.to_thread 로 워커 스레드에서 실행 → event loop 자유.
            responses = await _asyncio.to_thread(
                runtime.generate_response_force,
                DEV_ID, DEV_CHANNEL, user_msg,
            )
            # tool 호출 dispatch (dev_organize / dev_escalate / dev_clarify) — adapter-first.
            # web 은 core.mgr_actions, 디코는 동일 core 스파인 + discord 어댑터.
            _adapter = channels
            from community.core.mgr_actions import parse_and_execute_actions
            try:
                responses = await parse_and_execute_actions(
                    DEV_CHANNEL, responses, channels=_adapter, caller_agent_id=DEV_ID,
                )
            except Exception as e:
                log_writer.system(f"[dev.queue] tool dispatch 실패: {type(e).__name__}: {e}")
            # 응답 chat 메시지를 dev (세나) DM 채널에 게시 (어댑터 경유)
            for msg in responses or []:
                if msg and msg.strip():
                    try:
                        await _adapter.send_as_agent(DEV_CHANNEL, DEV_ID, msg)
                    except Exception as e:
                        log_writer.system(f"[dev.queue] send_as_agent 실패: {e}")
            # 활동 이벤트 기록 — request_id 처리했음을 그래프에 가시화.
            try:
                from community.supervisors.events import log_event as _log_sup_event
                _log_sup_event(
                    sup_id="dev.queue", action="process_request",
                    targets=[DEV_ID],
                    summary=f"#{req['id']} 처리 (severity={req.get('severity','?')})",
                    outcome="ok",
                    details={"request_id": req["id"], "requested_by": req.get("requested_by", "")},
                )
            except Exception:
                pass
        except Exception as e:
            log_writer.system(f"[dev.queue] dev agent invoke 오류: {type(e).__name__}: {e}")
            try:
                from community.supervisors.events import log_event as _log_sup_event
                _log_sup_event(
                    sup_id="dev.queue", action="process_request",
                    targets=[DEV_ID],
                    summary=f"요청 처리 실패 — {type(e).__name__}",
                    outcome="failed",
                    details={"error": str(e)},
                )
            except Exception:
                pass
