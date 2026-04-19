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
    name = match.group(1)
    ch_map = ctx.get("_channel_map")
    if ch_map is None:
        ch_map = _build_channel_map(ctx.get("guild"))
        ctx["_channel_map"] = ch_map
    cid = ch_map.get(name)
    if cid:
        return f"<#{cid}>"
    # 매칭 실패 — 볼드로라도 강조 (평문보다 눈에 띔)
    return f"**#{name}**"


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
                # Invalid/stale ID — 채널명을 모르니 평문 폴백
                name = id_to_name.get(cid, "")
                return f"**#{name}**" if name else "**(채널)**"
            out = _RAW_CHANNEL_MENTION_PAT.sub(_strip_invalid, out)
        except Exception:
            pass

    return out


# ── 에이전트 프롬프트에 주입할 가이드 ──────────────────

FORMATTING_GUIDE = """\
[Formatting rules — Discord rendering]
- Other channels: write as plain `#channel-name` (e.g. `#mgr-creator`).
  The runtime auto-converts to clickable Discord channel links. Don't use ``` backticks ```, don't quote, don't wrap in brackets.
- Emphasis: use `**bold**` for important words. Use sparingly.
- Code / commands / filenames: wrap in single backticks like ``update_profile`` or ``.env``.
- Don't use `@mention` for other members — they're webhooks (mentions don't work).
  Just write their name as-is.
"""


__all__ = ["format_for_discord", "FORMATTING_GUIDE"]
