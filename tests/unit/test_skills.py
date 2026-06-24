"""Skills 시스템 회귀 가드.

배경: skills 프레임워크(71f63e2)가 build_system_prompt 에 와이어링돼 있었는데
74a81ac("Cytoscape graph + dashboard polish") 가 그 호출을 *실수로* 같이 지워서,
이후 스킬이 어떤 에이전트에도 주입되지 않는 회귀가 조용히 발생했다 — 테스트가
없어서 아무도 못 잡음. 이 파일이 그 가드다.

검증:
- 코어(glimi/skills) + 커뮤니티(community/skills) 두 위치 모두에서 로드되는가
- applies-to 필터링 (persona 전용 스킬이 mgr 에 새지 않는가)
- build_system_prompt 출력에 스킬 섹션이 실제로 append 되는가  ← 회귀 지점
"""
import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in ("glimi-core", "glimi-community", "glimi-workspace", ""):
    _d = os.path.join(_REPO, _p) if _p else _REPO
    if _d not in sys.path:
        sys.path.insert(0, _d)


def test_skills_load_from_core_and_community():
    """코어 기본 스킬 + 커뮤니티 도메인 스킬이 한 검색경로로 합쳐 로드된다."""
    from community.core.skills import get_all_skills, invalidate_cache
    invalidate_cache()
    names = {s["name"] for s in get_all_skills()}
    # 코어(glimi/skills) — 범용 행동
    assert "emotional-expression" in names
    assert "memory-recall" in names
    assert "ambient-awareness" in names
    assert "conversation-join" in names
    # 커뮤니티(community/skills) — 도메인 정책
    assert "meta-question-handling" in names


def test_applies_to_filtering():
    """persona 전용 스킬은 mgr 프롬프트에 새면 안 된다 (메타 누출 방지)."""
    from community.core.skills import build_skills_section
    persona = build_skills_section("persona")
    mgr = build_skills_section("mgr")
    # meta-question-handling = applies-to: persona
    assert "meta-question-handling" in persona
    assert "meta-question-handling" not in mgr
    # ambient-awareness = applies-to: all → 둘 다
    assert "ambient-awareness" in persona
    assert "ambient-awareness" in mgr


def test_skills_appended_to_system_prompt(monkeypatch):
    """회귀 가드: build_system_prompt 출력에 Shared Skills 섹션이 반드시 붙는다.

    74a81ac 처럼 append 호출이 사라지면 이 테스트가 깨진다.
    """
    from community.core import prompts
    from community.core import profile as profile_mod

    # 실제 커뮤니티/에이전트 없이도 돌도록 profile 로더와 빌더를 스텁.
    monkeypatch.setattr(
        profile_mod, "load_profile",
        lambda aid: {"type": "persona", "name": "테스트", "id": aid},
    )
    monkeypatch.setattr(
        prompts, "_get_builder",
        lambda module, name: (lambda profile, **kw: "BASE_PROMPT_BODY"),
    )

    out = prompts.build_system_prompt("agent-persona-test")
    assert "BASE_PROMPT_BODY" in out           # 빌더 본문 유지
    assert "=== Shared Skills ===" in out       # ← 스킬 섹션이 붙었다 (회귀 지점)
    assert "meta-question-handling" in out      # persona 매칭 스킬 실제 주입


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
