"""
Project Glimi — Supervisor 모듈 shim.

실제 registrar 로직은 transport-neutral `community/supervisors/runner.py` 로
이전됨 (Phase 4.3). 이 파일은 기존 디스코드 호출부
(`from community.bot.supervisors import start_supervisors / notify_idle / _run_checks`)
가 계속 동작하도록 re-export 만 한다.

runner 는 ChannelAdapter(get_channel_adapter) 경유라 guild 없이도 동작 — 웹/디스코드 공용.
"""
from community.supervisors.runner import (  # noqa: F401
    start_supervisors,
    notify_idle,
    _run_checks,
    _notify_idle_tasks,
)
