"""
Supervisor 패키지 — 중앙 아키텍처.

API:
  from community.supervisors import pool, Supervisor
  pool.register(MySupervisor())
  await pool.tick(guild=guild)          # Discord
  await pool.tick(channels=adapter)     # web

씬 supervisor는 `src/scenes/<scene_id>/supervisor.py` 에 위치.
channel/system supervisor는 이 패키지 내부 (chat.py, orchestrator.py 등).
"""
from community.supervisors.base import (  # noqa: F401
    Supervisor,
    SupervisorPool,
    SupervisorKind,
    pool,
)

__all__ = ["Supervisor", "SupervisorPool", "SupervisorKind", "pool"]
