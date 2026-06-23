# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
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
import json
import time
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
    channels: Any = None  # ChannelAdapter (transport-neutral 출구; Discord 는 channel_obj/guild 사용)
    extra: dict = None  # 자유 필드


async def run_single(call: ToolCall, ctx: ToolContext) -> ToolResult:
    """하나의 tool call 실행 + 관측 1행 기록 (choke-point).

    모든 어댑터(Discord 오늘, 웹챗/플랫폼 미래)의 도구 실행이 정확히 이 함수를
    한 번 통과한다. 실행을 _run() 으로 감싸고 그 둘레에서 latency 측정 + tool_calls
    기록 (store 미주입/standalone 이면 no-op). 기록은 절대 실행을 깨지 않는다.
    """
    start = time.monotonic()
    result = await _run(call, ctx)
    latency_ms = int((time.monotonic() - start) * 1000)
    _record_tool_call(call, ctx, result, latency_ms)
    return result


async def _run(call: ToolCall, ctx: ToolContext) -> ToolResult:
    """실제 실행 로직.

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


def _record_tool_call(call: ToolCall, ctx: ToolContext,
                      result: ToolResult, latency_ms: int) -> None:
    """tool_calls 테이블에 1행 기록 (store-driven, platform-neutral).

    store 는 runtime 모듈 전역 (set_store() 로 재대입되므로 모듈을 import 해서 매번
    현재 값을 읽는다). store 미주입 (standalone/harness) → no-op. 전체를 try/except 로
    감싸 관측이 도구 실행을 절대 깨지 않게 한다 (db.log_message 훅 루프와 동일 방어).
    """
    try:
        from glimi import runtime as _rt
        store = getattr(_rt, "_store", None)
        if store is None:
            return
        try:
            args_json = json.dumps(call.args, ensure_ascii=False, default=str)
        except Exception:
            args_json = None
        if result.ok:
            preview = str(result.data)[:200] if result.data is not None else ""
        else:
            preview = (result.error or "")[:200]
        store.record_tool_call(
            agent_id=ctx.caller_agent_id,
            agent_type=ctx.caller_agent_type,
            channel=ctx.channel_name,
            tool_name=call.name,
            args_json=args_json,
            result_preview=preview,
            ok=result.ok,
            latency_ms=latency_ms,
        )
    except Exception:
        pass


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
