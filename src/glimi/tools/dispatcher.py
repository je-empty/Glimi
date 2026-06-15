"""
Tool Dispatcher — parsed ToolCall을 받아 실제 핸들러 실행 후 ToolResult 반환.

Context:
    caller_agent_id: 호출한 에이전트 ID
    caller_agent_type: "mgr" | "creator" | "persona"
    channel_name: 실행 컨텍스트 채널
    channel_obj: discord.TextChannel (optional)
    guild: discord.Guild (optional)

Flow:
    parsed = parse_response(agent_output)
    ctx = ToolContext(...)
    results = await run_tools(parsed.tool_calls, ctx)
    # results를 format_results_block(results)로 감싸 다음 턴 prompt에 주입
"""
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .registry import ToolSpec, get_tool
from .validator import ValidationError, validate_args, check_permission
from .parser import ToolCall
from .result import ToolResult, ok, fail


@dataclass
class ToolContext:
    caller_agent_id: str
    caller_agent_type: str  # "mgr" | "creator" | "persona"
    channel_name: str
    channel_obj: Any = None  # discord.TextChannel
    guild: Any = None  # discord.Guild
    extra: dict = None  # 자유 필드


async def run_single(call: ToolCall, ctx: ToolContext) -> ToolResult:
    """하나의 tool call 실행.

    1. 스펙 존재 확인
    2. 권한 확인 (agent_type이 applies_to에 있는지)
    3. 인자 검증
    4. 핸들러 호출 (없으면 'not implemented')
    5. 결과 → ToolResult
    """
    spec = get_tool(call.name)
    if spec is None:
        return fail(
            call.id, call.name,
            f"unknown tool '{call.name}'. check spelling or use list_tools()"
        )

    allowed, reason = check_permission(spec, ctx.caller_agent_type)
    if not allowed:
        return fail(call.id, call.name, reason)

    try:
        args = validate_args(spec, call.args)
    except ValidationError as e:
        return fail(call.id, call.name, e.msg)

    handler = spec.handler
    if handler is None:
        return fail(
            call.id, call.name,
            f"tool '{call.name}' has no handler registered (internal error)"
        )

    try:
        # 핸들러는 (args, ctx) → ToolResult-data 또는 dict 반환
        result_data = await handler(args, ctx) if _is_coro_callable(handler) else handler(args, ctx)
        if isinstance(result_data, ToolResult):
            # 핸들러가 직접 ToolResult 반환한 경우 (id 자동 주입)
            if not result_data.id:
                result_data.id = call.id
            if not result_data.tool:
                result_data.tool = call.name
            return result_data
        return ok(call.id, call.name, result_data)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return fail(call.id, call.name, f"{type(e).__name__}: {str(e)[:200]}")


def _is_coro_callable(fn: Callable) -> bool:
    """fn이 async 함수인지"""
    import asyncio
    return asyncio.iscoroutinefunction(fn)


async def run_tools(calls: list[ToolCall], ctx: ToolContext) -> list[ToolResult]:
    """여러 tool call을 순차 실행. 순차 실행이 안전 (DB/discord 동시성)."""
    results: list[ToolResult] = []
    for call in calls:
        r = await run_single(call, ctx)
        results.append(r)
    return results
