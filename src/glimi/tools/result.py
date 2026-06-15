"""
Tool 실행 결과 포맷 — 다음 턴 에이전트에게 되먹임.

포맷:
    <tool_result id="1" tool="create_room" ok="true">
    {"channel": "group-은하윤-수민", "created": true}
    </tool_result>
    <tool_result id="2" tool="update_profile" ok="false">
    {"error": "agent not found: 수민이"}
    </tool_result>

성공/실패 모두 구조화된 JSON body로.
"""
import json
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class ToolResult:
    id: str
    tool: str
    ok: bool
    data: Any  # dict | str | None
    error: Optional[str] = None  # ok=False일 때

    def to_xml(self) -> str:
        body: Any
        if self.ok:
            body = self.data if self.data is not None else {}
        else:
            body = {"error": self.error or "unknown error"}
            if self.data:
                body["details"] = self.data

        ok_str = "true" if self.ok else "false"
        try:
            body_json = json.dumps(body, ensure_ascii=False, default=str)
        except Exception:
            body_json = json.dumps({"repr": repr(body)[:500]}, ensure_ascii=False)

        return (
            f'<tool_result id="{self.id}" tool="{self.tool}" ok="{ok_str}">'
            f'{body_json}'
            f'</tool_result>'
        )


def ok(call_id: str, tool: str, data: Any = None) -> ToolResult:
    return ToolResult(id=call_id, tool=tool, ok=True, data=data)


def fail(call_id: str, tool: str, error: str, data: Any = None) -> ToolResult:
    return ToolResult(id=call_id, tool=tool, ok=False, data=data, error=error)


def format_results_block(results: list[ToolResult]) -> str:
    """여러 결과를 하나의 블록으로 묶어 user prompt에 삽입."""
    if not results:
        return ""
    lines = ["<tool_results>"]
    for r in results:
        lines.append(r.to_xml())
    lines.append("</tool_results>")
    return "\n".join(lines)
