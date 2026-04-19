"""
Scene 레지스트리 + 자동 로드.

import src.scenes  해 두면 등록된 모든 씬이 메모리에 올라오고
`base.active_scenes()` / `base.build_prompt_fragments()` 등으로 조회 가능.
"""
from src.scenes.base import (  # noqa: F401
    Scene,
    Phase,
    SceneSupervisor,
    register_scene,
    get_scene,
    all_scenes,
    active_scenes,
    build_prompt_fragments,
)

# 각 씬 모듈을 import하면 module-level register_scene(...)이 실행되어 레지스트리 등록됨
from src.scenes import tutorial  # noqa: F401

__all__ = [
    "Scene",
    "Phase",
    "SceneSupervisor",
    "register_scene",
    "get_scene",
    "all_scenes",
    "active_scenes",
    "build_prompt_fragments",
]
