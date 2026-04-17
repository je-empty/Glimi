"""
Tool reference 생성 — 에이전트 system prompt에 주입될 도구 목록 텍스트.

Claude Code Tool 시스템처럼 구조화된 참조를 제공.
에이전트 타입별로 필요한 도구만 필터링.

출력 형식:
    ## Available Tools

    ### management
    - `create_room(names: list[str], topic?: str)` — 멤버들을 모아 새 톡방 생성
      예: {"names": ["은하윤"], "topic": "게임"}
    - `update_profile(name: str, field: str, value: str)` — 멤버 프로필 수정
    ...

    ### query
    - `list_channels()` — DB에 등록된 채널 목록
    ...
"""
from typing import Optional

from .registry import ToolSpec, tools_for_agent


def _format_signature(spec: ToolSpec) -> str:
    """create_room(names: list[str], topic?: str) 같은 시그니처"""
    parts = []
    for name, p in spec.params.items():
        optional_mark = "" if p.get("required", False) else "?"
        parts.append(f"{name}{optional_mark}: {p.get('type', 'any')}")
    return f"{spec.name}({', '.join(parts)})"


def _format_tool(spec: ToolSpec, verbose: bool = False) -> str:
    lines = [f"- `{_format_signature(spec)}` — {spec.description}"]

    if verbose:
        # 각 파라미터 상세 설명
        for p_name, p in spec.params.items():
            desc = p.get("desc", "")
            if desc:
                lines.append(f"    - {p_name}: {desc}")
        # 예제
        for ex in spec.examples:
            lines.append(f"    예: {ex}")
        # 안전 플래그
        flags = []
        if spec.destructive:
            flags.append("파괴적")
        if spec.requires_approval:
            flags.append("승인필요")
        if flags:
            lines.append(f"    ⚠ {', '.join(flags)}")

    return "\n".join(lines)


def build_reference(agent_type: str, verbose: bool = True) -> str:
    """
    에이전트 타입별 도구 레퍼런스 전체 텍스트.

    verbose=True면 파라미터 설명·예제·안전 플래그 포함.
    """
    tools = tools_for_agent(agent_type)
    if not tools:
        return ""

    # 카테고리별 그룹
    by_cat: dict[str, list[ToolSpec]] = {}
    for t in tools:
        by_cat.setdefault(t.category, []).append(t)

    parts = ["## Available Tools",
             "",
             "Call tools using the `<tools>` block at the END of your response:",
             "",
             "```",
             "<tools>",
             '<call id="1" name="tool_name">',
             '{"param": "value"}',
             "</call>",
             "</tools>",
             "```",
             "",
             "Rules:",
             "- Place `<tools>` block ONLY at the very end of your response",
             "- Chat text goes BEFORE the `<tools>` block",
             "- Each `<call>` needs a unique `id` and a known `name`",
             "- Args must be valid JSON object",
             "- Empty args → `{}`",
             "- Results come back as `<tool_result id=\"...\" ok=\"true|false\">...</tool_result>` in the next turn — read them to know what happened",
             ""]

    category_order = ["management", "query", "request"]
    for cat in category_order:
        if cat not in by_cat:
            continue
        parts.append(f"### {cat}")
        for t in by_cat[cat]:
            parts.append(_format_tool(t, verbose=verbose))
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def build_brief_list(agent_type: str) -> str:
    """축약 버전 — deferred tool 패턴용. 이름+한줄설명만."""
    tools = tools_for_agent(agent_type)
    lines = ["## Available Tools (brief — call `get_tool_details(name)` for params)"]
    by_cat: dict[str, list[ToolSpec]] = {}
    for t in tools:
        by_cat.setdefault(t.category, []).append(t)
    for cat, ts in by_cat.items():
        lines.append(f"\n### {cat}")
        for t in ts:
            lines.append(f"- `{t.name}` — {t.description}")
    return "\n".join(lines)
