"""
Scene base classes — self-contained 이벤트/미션/온보딩 모듈 단위.

각 Scene은:
- id (unique), description, phase 목록 정의
- `build_agent_prompt_fragment(agent_type, phase, ctx)` — 활성 phase별 시스템 프롬프트 조각
- `supervisor()` — SceneSupervisor 인스턴스 (None 가능)
- `tools()` — scene 활성 시 dispatcher에 등록할 도구 목록
- `on_phase_enter/exit` — 라이프사이클 훅 (채널 생성, 최초 인사 등)

DB에 phase 저장: key = `scene:{id}:phase`, value = phase_id 또는 "complete".
빈 값은 아직 시작 전 (greet 대기 상태).

기존 hardcoded 코드(온보딩)를 점진적으로 여기로 옮긴다. 레거시 meta 키
(`onboarding_phase` 등)는 호환성 유지 위해 scene 내부에서 둘 다 읽고/쓴다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class Phase:
    id: str
    description: str = ""


class Scene:
    """씬 베이스 클래스 — 서브클래스가 메타/동작 오버라이드."""

    id: str = ""
    description: str = ""
    phases: list[Phase] = []

    # ── 상태 조회 (DB meta 기반) ──────────────────────

    def _meta_key(self) -> str:
        return f"scene:{self.id}:phase"

    def current_phase(self) -> str:
        """현재 phase id. 빈 문자열이면 아직 시작 전."""
        from src import db
        return db.get_meta(self._meta_key()) or ""

    def set_phase(self, phase_id: str):
        from src import db
        db.set_meta(self._meta_key(), phase_id)

    def is_active(self) -> bool:
        """씬이 진행 중인지 — 시작됐고 완료 안 된 상태."""
        p = self.current_phase()
        return bool(p) and p != "complete"

    def is_complete(self) -> bool:
        return self.current_phase() == "complete"

    def phase_index(self, phase_id: str) -> int:
        for i, p in enumerate(self.phases):
            if p.id == phase_id:
                return i
        return -1

    # ── 서브클래스 오버라이드 ─────────────────────────

    def build_agent_prompt_fragment(
        self, agent_type: str, phase: str, ctx: dict
    ) -> str:
        """에이전트 타입 + phase 조합별 system prompt 조각 반환.
        빈 문자열이면 프롬프트에 추가 안 함."""
        return ""

    def supervisor(self):
        """이 씬의 SceneSupervisor 인스턴스 (또는 None)."""
        return None

    def tools(self) -> list:
        """씬 활성 시 등록할 ToolSpec 목록."""
        return []

    async def on_phase_enter(self, phase: str, ctx: dict):
        pass

    async def on_phase_exit(self, phase: str, ctx: dict):
        pass


class SceneSupervisor:
    """씬의 phase 전이/진행 상태를 감시. 기존 Supervisor와 동일 인터페이스."""

    name: str = "scene-supervisor"
    interval: float = 30

    def __init__(self, scene: Scene):
        self.scene = scene

    def should_run(self) -> bool:
        return self.scene.is_active() or self.scene.current_phase() == ""

    def is_done(self) -> bool:
        return self.scene.is_complete()

    async def check(self, guild):
        pass


# ── 레지스트리 ─────────────────────────────────────────

_REGISTRY: dict[str, Scene] = {}


def register_scene(scene: Scene):
    """import 시 auto-register 되도록 scene 모듈에서 호출."""
    if not scene.id:
        raise ValueError("Scene.id is required")
    _REGISTRY[scene.id] = scene


def get_scene(scene_id: str) -> Optional[Scene]:
    return _REGISTRY.get(scene_id)


def all_scenes() -> list[Scene]:
    return list(_REGISTRY.values())


def active_scenes() -> list[Scene]:
    return [s for s in _REGISTRY.values() if s.is_active()]


def build_prompt_fragments(agent_type: str, ctx: dict) -> str:
    """활성 모든 씬의 프롬프트 조각을 합쳐서 반환.
    시작 전 씬도 (current_phase == "") 조각을 내보낼 수 있도록 한다
    (예: 온보딩 최초 진입 시 yuna_greeted 체크용)."""
    parts = []
    for scene in _REGISTRY.values():
        phase = scene.current_phase()
        frag = scene.build_agent_prompt_fragment(agent_type, phase, ctx)
        if frag and frag.strip():
            parts.append(frag.strip())
    return "\n\n".join(parts)
