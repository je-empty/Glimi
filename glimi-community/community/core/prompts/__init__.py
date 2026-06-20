"""프롬프트 모듈 — agent_type × language 별 system prompt 빌더.

구조:
    src/core/prompts/
    ├── __init__.py          ← 이 파일: build_system_prompt + get_builder dispatch
    ├── helpers.py           ← 공통 헬퍼 (tools reference / formatting / speech / pet name / ...)
    ├── en/                  ← 정본 (순수 영어)
    │   ├── common.py        ← build_common_prompt + core_identity_rules
    │   ├── persona.py
    │   ├── mgr.py
    │   ├── creator.py
    │   ├── persona_events.py
    │   ├── mgr_notifications.py
    │   ├── commands/
    │   └── external/        ← supervisor judge 등 영어 전용
    └── ko/                  ← 한국 문화 특화 override (존댓말 / 호칭 / 해례)
        └── ...              ← 없는 모듈은 en fallback

tutorial 전용 프롬프트는 src/scenes/tutorial/ 안에 있음 — 씬 종속이라 분리.

언어 dispatch:
    community.get_language() → 'ko' 면 ko/ 먼저 찾고 없으면 en/ 폴백.
    en 만 쓰는 시스템 (LLM judge 등) 은 직접 en import.
"""
from __future__ import annotations

import importlib
from typing import Callable


def _resolve_lang() -> str:
    """현재 커뮤니티 언어. 오류 시 'en'."""
    try:
        from community.community import get_language
        return get_language() or "en"
    except Exception:
        return "en"


def _get_builder(module: str, name: str) -> Callable:
    """lang 기반 dispatch — ko/{module} 에 name 있으면 그거, 없으면 en/{module}.name.

    module: 'common' | 'persona' | 'mgr' | 'creator' | 'persona_events' | 'mgr_notifications' | ...
    name:   함수명 (예: 'build_persona_prompt')
    """
    lang = _resolve_lang()
    if lang != "en":
        try:
            m = importlib.import_module(f"community.core.prompts.{lang}.{module}")
            fn = getattr(m, name, None)
            if fn is not None:
                return fn
        except ImportError:
            pass  # ko 모듈 없음 — en fallback
    en_module = importlib.import_module(f"community.core.prompts.en.{module}")
    return getattr(en_module, name)


def build_system_prompt(agent_id: str, include_profile_image_template: bool = False) -> str:
    """에이전트용 system prompt 생성 — 커뮤니티 언어에 맞춰 빌더 선택."""
    from community.core.profile import load_profile

    profile = load_profile(agent_id)
    if not profile:
        return ""

    agent_type = profile.get("type", "persona")

    if agent_type == "persona":
        builder = _get_builder("persona", "build_persona_prompt")
        base = builder(profile)
    elif agent_type == "mgr":
        builder = _get_builder("mgr", "build_mgr_prompt")
        base = builder(profile, include_profile_image_template=include_profile_image_template)
    elif agent_type == "creator":
        builder = _get_builder("creator", "build_creator_prompt")
        base = builder(profile)
    elif agent_type == "dev":
        builder = _get_builder("dev", "build_dev_prompt")
        base = builder(profile)
    else:
        return ""

    # 공용 스킬 섹션 append — 코어 기본 행동(glimi/skills) + 커뮤니티 도메인(community/skills),
    # applies-to 로 agent_type 필터링. 71f63e2 도입 → 74a81ac(대시보드 커밋)에서 실수로
    # 빠진 회귀를 복원. build_skills_section 이 빈 문자열이면 no-op.
    try:
        from community.core.skills import build_skills_section
        skills_text = build_skills_section(agent_type)
        if skills_text:
            base = base + "\n\n" + skills_text
    except Exception as e:
        print(f"[Prompt] skills 로드 실패 (무시): {e}")

    return base


__all__ = ["build_system_prompt", "_get_builder"]
