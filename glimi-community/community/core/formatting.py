"""플랫폼 중립 포맷팅 가이드 — 프롬프트에 주입되는 문자열만.

Discord 의존 변환 로직 (`format_for_discord`) 은 어댑터 레이어 `src/bot/formatting.py`
에 남아있음. 여기엔 **코어 (프롬프트 빌더) 에서 쓰는 순수 함수·상수**만.

Platform decoupling 원칙: `src/core/*` 는 `src/bot/*` 를 import 하면 안 됨.
이전엔 `core/prompts/helpers.formatting_guide()` 가 `community.bot.formatting` lazy import
하던 누수가 있었음 (2026-04-22 platform_decoupling_review 에서 지적된 소프트 누수).
"""
from __future__ import annotations


# ── 에이전트 프롬프트에 주입할 가이드 ──────────────────
# persona 에게 `#mgr-*` 예시를 보이면 메타 채널 존재를 학습해 자발적으로
# 언급하는 누출이 발생 (QA 회귀). agent_type 별로 안전한 예시만 제공.

_PERSONA_EXAMPLES = "`#dm-수연`, `#group-빈이-수연-하린`"
_STAFF_EXAMPLES = "`#mgr-creator`, `#dm-이수아`, `#mgr-dashboard`"
_STAFF_LIST_EXAMPLE = "`#mgr-creator, #mgr-dashboard, #mgr-system-log`"
_PERSONA_LIST_EXAMPLE = "`#dm-수연, #group-빈이-수연`"


def get_formatting_guide(agent_type: str = "persona") -> str:
    """agent_type 별 Discord 포맷 가이드. persona 는 dm/group 예시만."""
    if agent_type == "persona":
        single_ex = _PERSONA_EXAMPLES
        list_ex = _PERSONA_LIST_EXAMPLE
        plain_ex = "`dm-수연`"
    else:
        single_ex = _STAFF_EXAMPLES
        list_ex = _STAFF_LIST_EXAMPLE
        plain_ex = "`mgr-creator` 나 `dm-이수아`"
    return f"""[Formatting rules — Discord rendering — 반드시 준수]
- 채널 언급은 **항상 `#` 접두사 필수**. 예: {single_ex}.
  평문 {plain_ex} 처럼 `#` 빼면 클릭 링크 안 되고 그냥 텍스트로 뜸.
  예외 없음 — 채널명 나올 때마다 앞에 `#` 붙이기.
- 여러 채널 나열할 때도 각각에: {list_ex} 이런 식.
- 런타임이 자동으로 `<#id>` 클릭 링크로 변환. 백틱·따옴표·대괄호 감싸지 말 것.
- 강조: `**볼드**` 는 진짜 중요한 단어에만 드물게.
- 코드/파일명만 백틱: `update_profile`, `.env`.
- `@name` 멘션 쓰지 마 — 친구들은 웹훅이라 멘션 작동 안 함. 그냥 이름 그대로.
"""


FORMATTING_GUIDE = get_formatting_guide("staff")


__all__ = ["FORMATTING_GUIDE", "get_formatting_guide"]
