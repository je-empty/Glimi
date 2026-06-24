"""
Skills 로더 — 에이전트별 공용 행동 패턴 주입

개념 (Claude Code의 Skill 시스템에서 차용):
- 각 스킬은 skills/<name>/SKILL.md 파일
- frontmatter(YAML)로 메타데이터, 본문은 에이전트 프롬프트에 주입될 텍스트
- applies-to 필드로 대상 에이전트 타입 필터링

검색 경로 (코어 → 앱 순, 같은 name 이면 앱이 override):
- **코어 기본 행동** = `glimi` 패키지의 `glimi/skills/` (ambient-awareness, emotional-expression 등 범용)
- **커뮤니티 도메인** = 이 패키지의 `community/skills/` (meta-question-handling 등 — 중립 커널에 못 넣는 정책)
  → "코어가 기본 스킬을 ship 하고 커뮤니티가 확장/override" (core extension 모델)

Frontmatter 스키마:
---
name: 스킬 이름
description: 한 줄 설명
applies-to: all | persona | mgr | creator | "persona,mgr"  # 공백 없이 쉼표로
when-to-use: 언제 발동하는지 자연어
priority: 1  # 정렬 우선순위 (낮을수록 먼저)
---
<본문 — 에이전트 프롬프트에 들어갈 행동 지침>

로더 동작:
- 봇 시작 시 1회 스캔 (캐시)
- build_skills_section(agent_type)으로 타입별 매치된 스킬 본문 합쳐서 반환
- 파일 수정 시 invalidate_cache()로 재스캔
"""
from pathlib import Path
from typing import Optional

_SKILLS_CACHE: Optional[list[dict]] = None


def _skills_dirs() -> list[Path]:
    """스킬 검색 경로 — 코어(glimi 패키지) 먼저, 그다음 이 커뮤니티 앱.

    같은 name 의 스킬이 양쪽에 있으면 뒤(커뮤니티)가 코어를 override 한다.
    """
    dirs: list[Path] = []
    try:
        import glimi
        dirs.append(Path(glimi.__file__).resolve().parent / "skills")   # glimi-core/glimi/skills
    except Exception:
        pass
    dirs.append(Path(__file__).resolve().parent.parent / "skills")      # glimi-community/community/skills
    return dirs


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    """간단한 YAML-like frontmatter 파서 (의존성 없이).

    ---
    key: value
    ---
    body...

    복잡한 YAML(리스트, 중첩) 지원 안 함. 단순 key: value만.
    """
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm_text = text[3:end].strip()
    body = text[end + 4:].lstrip("\n")

    meta = {}
    for line in fm_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip()] = val.strip().strip('"\'')
    return meta, body


def _scan_skills() -> list[dict]:
    """검색 경로 전체 스캔 (코어 → 커뮤니티, name 충돌 시 커뮤니티 우선)."""
    by_name: dict[str, dict] = {}

    for skills_dir in _skills_dirs():
        if not skills_dir.exists():
            continue
        for skill_file in sorted(skills_dir.rglob("SKILL.md")):
            try:
                text = skill_file.read_text(encoding="utf-8")
                meta, body = _parse_frontmatter(text)
                name = meta.get("name", skill_file.parent.name)
                by_name[name] = {
                    "path": str(skill_file),
                    "name": name,
                    "description": meta.get("description", ""),
                    "applies_to": meta.get("applies-to", "all"),
                    "when_to_use": meta.get("when-to-use", ""),
                    "priority": int(meta.get("priority", "10") or "10"),
                    "body": body.strip(),
                }
            except Exception as e:
                print(f"[Skills] 로드 실패 {skill_file}: {e}")

    skills = list(by_name.values())
    skills.sort(key=lambda s: s["priority"])
    return skills


def get_all_skills() -> list[dict]:
    """모든 스킬 반환 (캐시됨)."""
    global _SKILLS_CACHE
    if _SKILLS_CACHE is None:
        _SKILLS_CACHE = _scan_skills()
    return _SKILLS_CACHE


def invalidate_cache():
    """스킬 수정 후 재스캔 강제."""
    global _SKILLS_CACHE
    _SKILLS_CACHE = None


def _matches(skill: dict, agent_type: str) -> bool:
    """applies-to 매칭 — 'all' / 단일 / 쉼표 구분."""
    applies = skill.get("applies_to", "all").lower()
    if applies == "all" or not applies:
        return True
    targets = [t.strip() for t in applies.split(",")]
    return agent_type in targets


def build_skills_section(agent_type: str) -> str:
    """agent_type에 해당하는 스킬 본문들을 시스템 프롬프트 섹션으로 합침.

    Returns:
        system prompt에 append할 텍스트. 매치 없으면 빈 문자열.
    """
    skills = [s for s in get_all_skills() if _matches(s, agent_type)]
    if not skills:
        return ""

    parts = ["=== Shared Skills ==="]
    parts.append("(Below are shared behavior patterns — apply when the situation matches.)")
    for s in skills:
        parts.append(f"\n### {s['name']}")
        if s["when_to_use"]:
            parts.append(f"When: {s['when_to_use']}")
        parts.append(s["body"])
    return "\n".join(parts)
