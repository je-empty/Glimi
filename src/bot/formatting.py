"""
메시지 포맷팅 시스템 — 에이전트 응답 텍스트를 디스코드 네이티브 렌더링으로 변환.

**목적**: 에이전트가 `#mgr-creator` 같은 평문을 말하면 디스코드에서 클릭 가능한
channel mention (`<#channel_id>`) 으로 자동 변환해서 가독성·네비게이션 개선.

**원칙**:
- 저장/로그/DB 는 **평문** 유지 (포터빌리티·검색성·다른 UI 로 이식 시 유효).
- 디스코드 전송 순간에만 변환 (`format_for_discord`).
- 변환 실패/매칭 없음은 조용히 원문 그대로 둠 (에러 방지).

**지원 토큰:**
- `#channel-name` → `<#channel_id>` (Discord 채널 mention — 클릭 시 해당 채널로 점프)
- `@owner-name`   → `<@user_id>` (오너만 실제 mention. 에이전트는 `**name**` 볼드 폴백)
- `` `code` ``    → 그대로 (마크다운 인라인 코드, 변환 불필요)
- `**bold**`      → 그대로

**확장 방법**: 새 토큰은 `_RULES` 에 `(pattern, resolver)` 추가. resolver 는
match 객체 + guild/context 받아 치환 문자열 반환 (또는 None = 변환 안 함).

**테스트**: `pytest tests/unit/test_formatting.py` (없으면 수동 스모크로).
"""
from __future__ import annotations

import re
from typing import Optional, Callable, Any

try:
    import discord  # type: ignore
except ImportError:  # 테스트 환경
    discord = None  # type: ignore


# ── Regex 토큰 정의 ──────────────────────────────────────

# 채널: #xxx-yyy — 유니코드 word char (영문/숫자/언더스코어/한글 등) + 하이픈.
# Python 3 `\w` 는 기본 유니코드 모드라 `dm-서유나` 같은 한글 채널명도 매칭.
# 앞 경계: `\w` 가 아닌 위치만 (단어 중간에 `#` 끼어있어도 매칭 방지).
_CHANNEL_PAT = re.compile(r'(?<!\w)#([^\W\d_][\w\-]*)')

# 오너 mention: @name (한글 포함, 공백 금지)
# 현재는 비활성 — agent 시스템에서 오너 이름 대신 pet_name 을 많이 써서 오탐 위험.
# 필요해지면 활성화.
_OWNER_MENTION_ENABLED = False
_OWNER_PAT = re.compile(r'(?<!\w)@([가-힣a-zA-Z][가-힣a-zA-Z0-9_]{0,15})')

# 이미 <#id> 로 찍힌 mention — guild에서 유효한지 검증하기 위한 패턴.
# 유나가 raw ID를 직접 내보내거나(환각) 구 세션의 stale ID가 메모리/로그에서
# 전파되는 경우 Discord UI에 '알 수 없음' 으로 렌더됨. 전송 직전 걸러냄.
_RAW_CHANNEL_MENTION_PAT = re.compile(r'<#(\d+)>')

# 미치환 f-string / .format 플레이스홀더 leak 탐지.
# 예: `"{name} 안녕"` 이 substitution 없이 보내진 케이스 → 사용자에게 literal `{name}`
# 출력돼 tool/prompt 템플릿 내부가 노출됨. 전송 직전 제거 (빈 문자열로 치환).
_PLACEHOLDER_LEAK_PAT = re.compile(
    r'\{(?:name|user_name|owner_name|agent_name|speaker_name|listener_name|target|nickname|age|mbti)\}'
)


# ── 개별 변환기 ─────────────────────────────────────────

def _build_channel_map(guild: Any) -> dict[str, int]:
    """guild 내 텍스트 채널 이름 → id 매핑. guild 없으면 빈 dict."""
    if not guild:
        return {}
    result: dict[str, int] = {}
    try:
        for ch in getattr(guild, "text_channels", []):
            name = getattr(ch, "name", "")
            cid = getattr(ch, "id", None)
            if name and cid:
                result[name] = cid
    except Exception:
        pass
    return result


def _resolve_channel(match: re.Match, ctx: dict) -> str:
    """`#channel-name` → `<#id>` 변환. guild 에 채널 없으면 평문 `#name` 유지.

    - exact match 우선
    - 미매칭 시 case-insensitive fuzzy 시도 (에이전트 표기 흔들림 방어)
    - 최종 실패 시 볼드/브래킷 등 플랫폼-특화 마크업 절대 금지 — 평문 `#name` 그대로.
      이유: 에이전트 출력은 플랫폼 중립이어야 함. 채널이 곧 생길 수도 있고(타이밍),
      다른 메신저(Slack/Kakao 등)로 이식 시에도 `#name` 은 보편적으로 통용됨.
    """
    name = match.group(1)
    ch_map = ctx.get("_channel_map")
    if ch_map is None:
        ch_map = _build_channel_map(ctx.get("guild"))
        ctx["_channel_map"] = ch_map
    cid = ch_map.get(name)
    if cid:
        return f"<#{cid}>"
    # case-insensitive fuzzy
    name_lower = name.lower()
    for existing_name, existing_id in ch_map.items():
        if existing_name.lower() == name_lower:
            return f"<#{existing_id}>"
    # 미매칭 — 평문 `#name` 유지 (볼드/특수 마크업 금지)
    return f"#{name}"


def _resolve_owner(match: re.Match, ctx: dict) -> Optional[str]:
    if not _OWNER_MENTION_ENABLED:
        return None
    name = match.group(1)
    owner_name = ctx.get("owner_name")
    owner_id = ctx.get("owner_id")
    if owner_name and owner_id and name == owner_name:
        return f"<@{owner_id}>"
    return None  # 다른 이름은 그대로


# ── 규칙 테이블 ─────────────────────────────────────────

_RULES: list[tuple[re.Pattern, Callable[[re.Match, dict], Optional[str]]]] = [
    (_CHANNEL_PAT, _resolve_channel),
    (_OWNER_PAT, _resolve_owner),
]


# ── 공용 엔트리 ─────────────────────────────────────────

def format_for_discord(message: str,
                       guild: Any = None,
                       owner_name: str = "",
                       owner_id: Optional[int] = None) -> str:
    """에이전트 응답 텍스트를 디스코드 네이티브 렌더링으로 변환.

    Args:
        message: 에이전트 원본 응답 (예: "#mgr-creator 에서 얘기해봐")
        guild: discord.Guild (channel mention 해석용)
        owner_name, owner_id: 오너 이름/id (`@name` 변환용)

    Returns:
        포맷된 문자열 (예: "<#1234567890> 에서 얘기해봐")
    """
    if not message:
        return message

    ctx: dict = {
        "guild": guild,
        "owner_name": owner_name,
        "owner_id": owner_id,
    }

    out = message
    for pattern, resolver in _RULES:
        def _sub(m, _r=resolver, _c=ctx):
            try:
                replacement = _r(m, _c)
                if replacement is None:
                    return m.group(0)  # 매칭은 했지만 변환 안 함 — 원문 유지
                return replacement
            except Exception:
                return m.group(0)
        out = pattern.sub(_sub, out)

    # 프롬프트 템플릿 leak 방어 — 미치환 `{name}` 같은 플레이스홀더를 제거
    # (빈 문자열로 치환). 원인은 별도로 고쳐야 하지만, 사용자에게 노출되는 건 방지.
    out = _PLACEHOLDER_LEAK_PAT.sub("", out)

    # 최종 단계: `<#id>` stale/invalid 검증. guild에 실존하는 ID만 남기고
    # 나머지는 평문화해서 Discord UI의 '알 수 없음' 렌더 방지.
    if guild is not None:
        try:
            valid_ids = {str(getattr(ch, "id", "")) for ch in getattr(guild, "text_channels", [])}
            valid_ids.discard("")
            id_to_name = {str(getattr(ch, "id", "")): getattr(ch, "name", "") for ch in getattr(guild, "text_channels", [])}
            def _strip_invalid(m):
                cid = m.group(1)
                if cid in valid_ids:
                    return m.group(0)
                # Invalid/stale ID — 평문 `#name` (또는 이름 모르면 단순 '채널')
                name = id_to_name.get(cid, "")
                return f"#{name}" if name else "채널"
            out = _RAW_CHANNEL_MENTION_PAT.sub(_strip_invalid, out)
        except Exception:
            pass

    return out


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


__all__ = ["format_for_discord", "FORMATTING_GUIDE", "get_formatting_guide"]
