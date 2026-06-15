"""
Glimi Tool System — Claude Code tool_use 패턴의 프롬프트 레벨 구현.

구성:
    registry: 모든 도구 선언 (ToolSpec)
    parser:   에이전트 응답에서 <tools>/<call> 파싱
    validator: 인자 타입/필수 필드 검증
    reference: 에이전트 프롬프트에 주입할 도구 레퍼런스
    result:    실행 결과를 <tool_result>로 포맷
    dispatcher: handler 등록 + 실행 루틴
"""
from .registry import ToolSpec, TOOLS, get_tool, tools_for_agent, set_handler
from .parser import ToolCall, ParsedResponse, parse_response, strip_tool_blocks, strip_control_tokens
from .validator import ValidationError, validate_args, check_permission
from .reference import build_reference, build_brief_list
from .result import ToolResult, ok, fail, format_results_block
from .dispatcher import ToolContext, run_single, run_tools

__all__ = [
    "ToolSpec", "TOOLS", "get_tool", "tools_for_agent", "set_handler",
    "ToolCall", "ParsedResponse", "parse_response", "strip_tool_blocks", "strip_control_tokens",
    "ValidationError", "validate_args", "check_permission",
    "build_reference", "build_brief_list",
    "ToolResult", "ok", "fail", "format_results_block",
    "ToolContext", "run_single", "run_tools",
]
