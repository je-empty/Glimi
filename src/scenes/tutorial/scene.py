"""
TutorialScene — 싱글톤 인스턴스.

- phase 저장은 legacy meta 키 `tutorial_phase` + `yuna_greeted` 를 그대로 사용
  (기존 코드 호환). scene 인터페이스로는 정규화된 phase id를 노출.

Phase 매핑:
  yuna_greeted=None, tutorial_phase=""        → "greet"
  yuna_greeted=1,    tutorial_phase=""        → "collect_profile"
  tutorial_phase="channels_setup"             → "channels_setup"
  tutorial_phase="channels_done"              → "channels_done"
  tutorial_phase="complete"                   → "complete"
"""
from __future__ import annotations

from src.scenes.base import Scene, Phase, register_scene
from src.scenes.tutorial.prompts import (
    build_mgr_fragment,
    build_creator_fragment,
)


class TutorialScene(Scene):
    id = "tutorial"
    description = "오너 첫 접속 → 프로필 수집 → 시스템 채널/크리에이터 세팅 → 첫 친구 생성"
    phases = [
        Phase("greet", "유나 첫 인사 전"),
        Phase("collect_profile", "프로필 수집 진행 중"),
        Phase("channels_setup", "Phase 2 트리거 (채널 생성 중)"),
        Phase("channels_done", "채널 생성 완료, 크리에이터가 오너와 대화 중"),
        Phase("complete", "튜토리얼 완료"),
    ]

    # ── 레거시 DB 키와 매핑 ─────────────────────────────

    def current_phase(self) -> str:
        from src import db
        raw = (db.get_meta("tutorial_phase") or "").strip()
        if raw == "complete":
            return "complete"
        if raw in ("channels_setup", "channels_done"):
            return raw
        greeted = db.get_meta("yuna_greeted")
        return "collect_profile" if greeted else "greet"

    def set_phase(self, phase_id: str):
        from src import db
        if phase_id in ("channels_setup", "channels_done", "complete"):
            db.set_meta("tutorial_phase", phase_id)
        elif phase_id == "collect_profile":
            db.set_meta("tutorial_phase", "")
            db.set_meta("yuna_greeted", "1")
        elif phase_id == "greet":
            db.set_meta("tutorial_phase", "")
        else:
            raise ValueError(f"unknown tutorial phase: {phase_id}")
        # supervisor pool 재동기화 (씬 활성/비활성 변화 감지)
        try:
            import asyncio as _aio
            from src.supervisors.base import pool as _pool
            loop = _aio.get_event_loop()
            if loop.is_running():
                loop.create_task(_pool.sync())
        except Exception:
            pass

    def is_active(self) -> bool:
        return self.current_phase() != "complete"

    def is_complete(self) -> bool:
        return self.current_phase() == "complete"

    # ── 프롬프트 ────────────────────────────────────────

    def build_agent_prompt_fragment(
        self, agent_type: str, phase: str, ctx: dict
    ) -> str:
        if agent_type == "mgr":
            return build_mgr_fragment(phase, ctx)
        if agent_type == "creator":
            return build_creator_fragment(phase, ctx)
        return ""

    # ── 슈퍼바이저 (lazy import로 순환 회피) ────────────

    def supervisors(self) -> list:
        """이 씬이 가질 supervisor들 (복수). pool이 활성화 시 등록."""
        from src.scenes.tutorial.supervisor import TutorialFlowSupervisor
        return [TutorialFlowSupervisor(self)]

    # 구버전 호환 (단일 반환)
    def supervisor(self):
        sups = self.supervisors()
        return sups[0] if sups else None


scene = TutorialScene()
register_scene(scene)
