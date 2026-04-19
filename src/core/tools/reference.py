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
    """축약 버전 — 기본 주입용. 이름+한줄설명만.
    파라미터 상세·예제·안전 플래그 다 빠짐. 필요 시 에이전트가 `get_tool_details(name)`
    호출해서 on-demand 로 확장. 프롬프트 토큰 절약 + 응답 속도 향상.
    """
    tools = tools_for_agent(agent_type)
    lines = [
        "## Available Tools (brief — call `get_tool_details(name)` for params·examples)",
        "Usage: `<tools><call id=\"1\" name=\"X\">{json args}</call></tools>` at end of response.",
    ]
    by_cat: dict[str, list[ToolSpec]] = {}
    for t in tools:
        by_cat.setdefault(t.category, []).append(t)
    for cat in ("management", "query", "request"):
        if cat not in by_cat:
            continue
        lines.append(f"\n### {cat}")
        for t in by_cat[cat]:
            flag = " ⚠" if t.destructive else ""
            lines.append(f"- `{t.name}`{flag} — {t.description}")
    return "\n".join(lines)


def build_tool_details(tool_name: str) -> str:
    """특정 도구의 전체 스키마·예제·안전 플래그. get_tool_details 핸들러가 호출."""
    from .registry import TOOLS
    spec = TOOLS.get(tool_name)
    if not spec:
        return f"(unknown tool: {tool_name})"
    out = [f"### `{_format_signature(spec)}`", f"Category: {spec.category}  |  applies_to: {', '.join(sorted(spec.applies_to))}"]
    if spec.destructive:
        out.append("⚠ destructive — 신중히.")
    if spec.requires_approval:
        out.append("⚠ requires approval (보통 persona → mgr 경로).")
    out.append(f"\n{spec.description}")
    if spec.params:
        out.append("\nParams:")
        for pname, p in spec.params.items():
            opt = "(optional)" if not p.get("required") else ""
            desc = p.get("desc", "")
            out.append(f"  - `{pname}` : {p.get('type', 'any')} {opt}  {desc}")
    if spec.examples:
        out.append("\nExamples:")
        for ex in spec.examples:
            out.append(f"  {ex}")
    return "\n".join(out)
