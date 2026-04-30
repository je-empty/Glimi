"""
Supervisor 시스템 — 중앙 아키텍처.

정의: 백그라운드 감시자. 관찰 → 감지 → 개입. Reactive 안전망.

3 kinds:
  - scene    : 씬 1개에 붙음. 씬 시작~완료 사이 존재.
  - channel  : 특정 채널 1개당 인스턴스. running~idle 사이 존재.
  - system   : 전역 싱글톤. 봇 수명 내내.

SupervisorPool 이 lifecycle 관리:
  - sync()  — 상태 변화 감지 시 자동 인스턴스 생성/제거
  - tick()  — 주기 check() 호출. try/except 격리.
"""
from __future__ import annotations

import asyncio
from typing import Optional, Literal

SupervisorKind = Literal["scene", "channel", "system"]


class Supervisor:
    """모든 감시자의 베이스. 서브클래스는 `check()` 구현 + 메타 설정."""

    # ── 메타 (서브클래스가 오버라이드) ────────────────────
    id: str = ""                         # 전역 unique
    display_name: str = ""               # UI 표시
    kind: SupervisorKind = "system"      # scene | channel | system
    interval: float = 30.0               # tick 주기 (초)

    # scope 메타 (sync 시 동적 생성/제거에 사용)
    #   scene    → {"scene_id": "tutorial"}
    #   channel  → {"channel": "internal-dm-유나-하나"}
    #   system   → {}
    scope: dict

    def __init__(self, scope: Optional[dict] = None):
        self.scope = scope or {}
        self._last_tick: float = 0.0

    # ── 서브클래스 구현 필수 ───────────────────────────────

    async def check(self, ctx: dict) -> None:
        """주기 감시 로직. pool.tick() 이 interval 간격으로 호출."""
        return None

    def should_exist(self) -> bool:
        """False 반환 시 pool이 이 인스턴스를 제거한다.
        scene-scoped: scene.is_active() 결과
        channel-scoped: 채널 status == 'running'
        system: 항상 True"""
        return True

    def is_active(self) -> bool:
        """현재 실제로 'active' 인지 (pool 등록 여부 ≠ active 여부).
        기본 True. 큐 기반 system supervisor (예: DevQueueSupervisor) 는 큐 비어있을 때
        False 반환해서 UI 가 'idle' 로 표시. should_exist 와는 다름 — should_exist 는
        등록 자체 여부, is_active 는 표시용 활성 여부.
        """
        return True

    # ── 유틸 ───────────────────────────────────────────────

    def __repr__(self) -> str:
        return f"<Supervisor id={self.id!r} kind={self.kind}>"


class SupervisorPool:
    """싱글톤 풀. 봇 수명 내내 유지."""

    def __init__(self):
        self._instances: dict[str, Supervisor] = {}
        self._tick_task: Optional[asyncio.Task] = None
        self._tick_interval: float = 5.0  # 5초마다 tick check (각 supervisor의 interval은 내부에서 체크)
        self._sync_lock = asyncio.Lock()

    # ── CRUD ───────────────────────────────────────────────

    def register(self, sup: Supervisor) -> Supervisor:
        if not sup.id:
            raise ValueError("Supervisor.id is required")
        self._instances[sup.id] = sup
        self._dump_snapshot()
        return sup

    def unregister(self, sup_id: str) -> Optional[Supervisor]:
        removed = self._instances.pop(sup_id, None)
        if removed is not None:
            self._dump_snapshot()
        return removed

    def _dump_snapshot(self):
        """supervisor 상태를 `communities/{id}/logs/.supervisors.json` 에 기록.
        대시보드(별도 프로세스) 가 읽어서 UI에 반영하기 위함. 실패해도 무시."""
        try:
            import json as _json, os as _os, time as _time
            from src import db as _db, community as _comm
            cid = _comm.get_community_id()
            logs_dir = _os.path.dirname(_db._get_db_path()) + "/logs"
            _os.makedirs(logs_dir, exist_ok=True)
            data = {
                "community_id": cid,
                "updated_at": _time.time(),
                "items": [
                    {
                        "id": s.id,
                        "kind": s.kind,
                        "display_name": getattr(s, "display_name", s.id),
                        "scope": dict(getattr(s, "scope", {}) or {}),
                        "active": getattr(s, "should_exist", lambda: True)(),
                    }
                    for s in self._instances.values()
                ],
            }
            tmp = _os.path.join(logs_dir, ".supervisors.json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                _json.dump(data, f, ensure_ascii=False)
            _os.replace(tmp, _os.path.join(logs_dir, ".supervisors.json"))
        except Exception as e:
            try:
                print(f"[pool] snapshot write fail: {e}")
            except Exception:
                pass

    def get(self, sup_id: str) -> Optional[Supervisor]:
        return self._instances.get(sup_id)

    def all(self) -> list[Supervisor]:
        return list(self._instances.values())

    def by_kind(self, kind: SupervisorKind) -> list[Supervisor]:
        return [s for s in self._instances.values() if s.kind == kind]

    # ── 동기화 (lifecycle trigger) ─────────────────────────

    async def sync(self):
        """scene/channel 상태 기반으로 인스턴스 자동 생성·제거.
        호출 시점: 봇 ready, channel status change, scene phase change, tick loop 내부."""
        async with self._sync_lock:
            await self._sync_scene_supervisors()
            await self._sync_channel_supervisors()
            # system은 bot ready 때 1회만 등록, sync 에선 건드리지 않음.

    async def _sync_scene_supervisors(self):
        """각 씬의 supervisors() 리스트와 현재 등록 상태 비교.
        활성 씬: 누락된 supervisor는 등록. 비활성 씬: 등록된 supervisor는 제거."""
        try:
            from src.scenes import all_scenes
        except Exception:
            return

        wanted_ids: set[str] = set()
        for scene in all_scenes():
            if not scene.is_active():
                continue
            try:
                scene_sups = scene.supervisors() if hasattr(scene, "supervisors") else []
            except Exception:
                scene_sups = []
            # 하위호환: `supervisor()` 단일 반환 API 지원
            if not scene_sups and hasattr(scene, "supervisor"):
                try:
                    single = scene.supervisor()
                    scene_sups = [single] if single else []
                except Exception:
                    pass
            for sup in scene_sups:
                if not sup or sup.kind != "scene":
                    continue
                if sup.id not in self._instances:
                    self.register(sup)
                wanted_ids.add(sup.id)

        # wanted에 없는 scene-scoped supervisor는 제거
        for sup_id, sup in list(self._instances.items()):
            if sup.kind == "scene" and sup_id not in wanted_ids:
                self.unregister(sup_id)

    async def _sync_channel_supervisors(self):
        """running internal-* 채널 각각에 ChatSupervisor 인스턴스 보장."""
        try:
            from src import db
            conn = db.get_conn()
            rows = conn.execute(
                "SELECT channel FROM channels WHERE status='running' AND channel LIKE 'internal-%'"
            ).fetchall()
            conn.close()
            running = {r["channel"] for r in rows}
        except Exception:
            running = set()

        try:
            from src.supervisors.chat import ChatSupervisor
        except Exception:
            return

        wanted_ids: set[str] = set()
        for ch_name in running:
            sup_id = ChatSupervisor.id_for(ch_name)
            wanted_ids.add(sup_id)
            if sup_id not in self._instances:
                self.register(ChatSupervisor(channel_name=ch_name))

        for sup_id, sup in list(self._instances.items()):
            if sup.kind == "channel" and sup_id not in wanted_ids:
                self.unregister(sup_id)

    def register_system_supervisors(self):
        """봇 ready 때 1회 호출. 전역 싱글톤 supervisor들 등록."""
        try:
            from src.supervisors.orchestrator import OrchestratorSupervisor
            self.register(OrchestratorSupervisor())
        except Exception as e:
            import logging
            logging.getLogger("glimi.supervisor").warning(
                f"OrchestratorSupervisor 등록 실패: {e}"
            )
        try:
            from src.supervisors.dev_queue import DevQueueSupervisor
            self.register(DevQueueSupervisor())
        except Exception as e:
            import logging
            logging.getLogger("glimi.supervisor").warning(
                f"DevQueueSupervisor 등록 실패: {e}"
            )
        try:
            from src.supervisors.commitment import CommitmentSupervisor
            self.register(CommitmentSupervisor())
        except Exception as e:
            import logging
            logging.getLogger("glimi.supervisor").warning(
                f"CommitmentSupervisor 등록 실패: {e}"
            )

    # ── Tick ───────────────────────────────────────────────

    async def tick(self, guild):
        """각 supervisor를 자기 interval 지났으면 check().
        매 ~5초마다 호출 권장 (bot tasks 에서). 각 check는 try/except 격리."""
        from src.community import is_maintenance_mode
        if is_maintenance_mode():
            return
        import time as _time
        from src import log_writer
        ctx = {"guild": guild}
        await self.sync()  # tick마다 안전하게 재동기화
        now = _time.time()
        for sup in list(self._instances.values()):
            if not sup.should_exist():
                self.unregister(sup.id)
                log_writer.system(f"[sup:{sup.id}] 종료 조건 충족 — pool에서 제거")
                continue
            if now - sup._last_tick < sup.interval:
                continue
            sup._last_tick = now
            try:
                await sup.check(ctx)
            except Exception as e:
                log_writer.system(f"[sup:{sup.id}] check 오류: {type(e).__name__}: {e}")


# ── 싱글톤 ──────────────────────────────────────────────

pool = SupervisorPool()
