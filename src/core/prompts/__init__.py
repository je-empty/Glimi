"""프롬프트 모듈 — agent_type 별 system prompt 빌더.

구조:
    src/core/prompts/
    ├── __init__.py          ← 이 파일: build_system_prompt dispatch
    ├── helpers.py           ← 공통 헬퍼 (도구 레퍼런스/포맷 가이드/말투/별칭/채널 요약/샘플 카탈로그)
    └── en/                  ← 정본 (모든 프롬프트)
        ├── common.py        ← build_common_prompt + core_identity_rules
        ├── persona.py       ← build_persona_prompt
        ├── mgr.py           ← build_mgr_prompt
        └── creator.py       ← build_creator_prompt

향후 `ko/` 오버라이드 추가 시: community.get_language() 기반으로 선택,
미구현 빌더는 en fallback.
"""
from __future__ import annotations

from src.core.prompts import en


def build_system_prompt(agent_id: str, include_profile_image_template: bool = False) -> str:
    """에이전트용 system prompt 생성."""
    # lazy import — profile.py 와의 순환 회피
    from src.core.profile import load_profile

    profile = load_profile(agent_id)
    if not profile:
        return ""

    agent_type = profile.get("type", "persona")

    if agent_type == "persona":
        return en.build_persona_prompt(profile)
    elif agent_type == "mgr":
        return en.build_mgr_prompt(profile, include_profile_image_template=include_profile_image_template)
    elif agent_type == "creator":
        return en.build_creator_prompt(profile)
    return ""


__all__ = ["build_system_prompt"]
