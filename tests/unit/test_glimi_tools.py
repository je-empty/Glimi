"""glimi/tools/* 커널 단위 테스트 — LLM·백엔드 없이 순수/모킹 로직만.

대상:
  - parser.parse_response / strip_control_tokens
  - validator.validate_args / check_permission
  - dispatcher.run_single (asyncio.run + mock handler)
  - registry.ToolSpec lookup

실행:
    PYTHONPATH=<worktree> python -m pytest tests/unit/test_glimi_tools.py -q
"""
import asyncio

from glimi.tools import registry
from glimi.tools.registry import ToolSpec, get_tool, tools_for_agent, set_handler
from glimi.tools.parser import parse_response, strip_control_tokens, ToolCall
from glimi.tools.validator import validate_args, check_permission, ValidationError
from glimi.tools.dispatcher import run_single, ToolContext


def _spec(**kw) -> ToolSpec:
    base = dict(
        name="t",
        description="d",
        params={},
        category="management",
        applies_to=frozenset({"mgr"}),
    )
    base.update(kw)
    return ToolSpec(**base)


# ────────────────────────────────────────────────────
# parser.parse_response
# ────────────────────────────────────────────────────

def test_parse_no_tools_block_is_all_chat():
    r = parse_response("그냥 평범한 대화 텍스트")
    assert r.chat == "그냥 평범한 대화 텍스트"
    assert r.tool_calls == []
    assert r.errors == []


def test_parse_empty_text():
    r = parse_response("")
    assert r.chat == ""
    assert r.tool_calls == []
    assert r.errors == []


def test_parse_single_call_splits_chat_and_tool():
    text = (
        "안녕 반가워!\n\n"
        '<tools>\n'
        '<call id="1" name="create_room">\n'
        '{"names": ["은하윤"], "topic": "게임"}\n'
        '</call>\n'
        '</tools>'
    )
    r = parse_response(text)
    assert r.chat == "안녕 반가워!"
    assert len(r.tool_calls) == 1
    call = r.tool_calls[0]
    assert isinstance(call, ToolCall)
    assert call.id == "1"
    assert call.name == "create_room"
    assert call.args == {"names": ["은하윤"], "topic": "게임"}
    assert r.errors == []


def test_parse_multiple_calls_in_order():
    text = (
        "chat\n<tools>\n"
        '<call id="1" name="a">{"x": 1}</call>\n'
        '<call id="2" name="b">{}</call>\n'
        "</tools>"
    )
    r = parse_response(text)
    assert [c.name for c in r.tool_calls] == ["a", "b"]
    assert [c.id for c in r.tool_calls] == ["1", "2"]
    # 빈 body 는 {} 로 처리
    assert r.tool_calls[1].args == {}


def test_parse_empty_body_is_empty_dict():
    text = '<tools>\n<call id="1" name="finish_tutorial"></call>\n</tools>'
    r = parse_response(text)
    assert r.tool_calls[0].args == {}
    assert r.errors == []


def test_parse_call_without_name_is_error_not_call():
    text = '<tools>\n<call id="1">{"x": 1}</call>\n</tools>'
    r = parse_response(text)
    assert r.tool_calls == []
    assert any("without name" in e for e in r.errors)


def test_parse_malformed_json_records_error():
    text = '<tools>\n<call id="1" name="a">{not valid json at all}</call>\n</tools>'
    r = parse_response(text)
    assert r.tool_calls == []
    assert any("a" in e for e in r.errors)


def test_parse_trailing_text_after_json_is_salvaged():
    # LLM 이 유효 JSON 뒤에 설명을 붙인 케이스 — 앞의 JSON 만 살리고 경고
    text = '<tools>\n<call id="1" name="a">{"x": 1} 그리고 추가 설명</call>\n</tools>'
    r = parse_response(text)
    assert len(r.tool_calls) == 1
    assert r.tool_calls[0].args == {"x": 1}
    assert any("trailing" in e for e in r.errors)


def test_parse_args_not_object_is_error():
    text = '<tools>\n<call id="1" name="a">[1, 2, 3]</call>\n</tools>'
    r = parse_response(text)
    assert r.tool_calls == []
    assert any("not object" in e for e in r.errors)


def test_parse_fence_wrapped_tools_block():
    text = (
        "chat\n```xml\n"
        '<tools>\n<call id="1" name="a">{"x": 1}</call>\n</tools>\n'
        "```"
    )
    r = parse_response(text)
    assert len(r.tool_calls) == 1
    assert r.tool_calls[0].name == "a"


def test_parse_strips_control_tokens_from_chat():
    text = "안녕<end_of_turn> 반가워<|im_end|>"
    r = parse_response(text)
    assert "<end_of_turn>" not in r.chat
    assert "<|im_end|>" not in r.chat
    assert "안녕" in r.chat and "반가워" in r.chat


# ────────────────────────────────────────────────────
# parser.strip_control_tokens
# ────────────────────────────────────────────────────

def test_strip_control_tokens_removes_special_tokens():
    assert strip_control_tokens("<start_of_turn>hi<end_of_turn>") == "hi"
    assert strip_control_tokens("a<|im_start|>b<|im_end|>c") == "abc"


def test_strip_control_tokens_removes_html_tags():
    assert strip_control_tokens("hello<br>world") == "helloworld"
    assert strip_control_tokens("<p>text</p>") == "text"


def test_strip_control_tokens_preserves_plain_angle_brackets():
    # 일반 부등호/이모티콘은 보존 (< 가 없으면 early-return, 있어도 토큰 패턴만 제거)
    assert strip_control_tokens("3 < 5 and x > y") == "3 < 5 and x > y"
    assert strip_control_tokens("<3 사랑해") == "<3 사랑해"


def test_strip_control_tokens_noop_without_angle():
    assert strip_control_tokens("plain text") == "plain text"
    assert strip_control_tokens("") == ""


# ────────────────────────────────────────────────────
# validator.validate_args
# ────────────────────────────────────────────────────

def test_validate_passes_matching_types():
    spec = _spec(params={
        "s": {"type": "str", "required": True},
        "n": {"type": "int", "required": True},
        "b": {"type": "bool", "required": True},
        "ls": {"type": "list[str]", "required": True},
    })
    out = validate_args(spec, {"s": "x", "n": 3, "b": True, "ls": ["a", "b"]})
    assert out == {"s": "x", "n": 3, "b": True, "ls": ["a", "b"]}


def test_validate_coerces_number_to_str():
    spec = _spec(params={"s": {"type": "str", "required": True}})
    assert validate_args(spec, {"s": 25}) == {"s": "25"}
    assert validate_args(spec, {"s": 1.5}) == {"s": "1.5"}
    assert validate_args(spec, {"s": True}) == {"s": "True"}


def test_validate_coerces_str_to_single_element_list():
    spec = _spec(params={"ls": {"type": "list[str]", "required": True}})
    assert validate_args(spec, {"ls": "solo"}) == {"ls": ["solo"]}


def test_validate_int_rejects_bool():
    # bool 은 int 의 서브타입이지만 별도 취급 — int 필드에 bool 거부
    spec = _spec(params={"n": {"type": "int", "required": True}})
    try:
        validate_args(spec, {"n": True})
        assert False, "expected ValidationError"
    except ValidationError as e:
        assert "int" in e.msg


def test_validate_missing_required_raises():
    spec = _spec(name="mytool", params={"s": {"type": "str", "required": True}})
    try:
        validate_args(spec, {})
        assert False, "expected ValidationError"
    except ValidationError as e:
        assert e.tool == "mytool"
        assert "missing required" in e.msg and "s" in e.msg


def test_validate_optional_field_absent_ok():
    spec = _spec(params={"s": {"type": "str", "required": False}})
    assert validate_args(spec, {}) == {}


def test_validate_drops_unknown_fields():
    spec = _spec(params={"s": {"type": "str", "required": True}})
    assert validate_args(spec, {"s": "x", "extra": "y", "more": 1}) == {"s": "x"}


def test_validate_non_dict_args_raises():
    spec = _spec()
    try:
        validate_args(spec, ["not", "a", "dict"])
        assert False, "expected ValidationError"
    except ValidationError as e:
        assert "object" in e.msg


# ────────────────────────────────────────────────────
# validator.check_permission
# ────────────────────────────────────────────────────

def test_check_permission_allowed():
    spec = _spec(applies_to=frozenset({"mgr", "creator"}))
    allowed, reason = check_permission(spec, "mgr")
    assert allowed is True
    assert reason == ""


def test_check_permission_denied():
    spec = _spec(name="mgronly", applies_to=frozenset({"mgr"}))
    allowed, reason = check_permission(spec, "persona")
    assert allowed is False
    assert "persona" in reason and "mgronly" in reason


# ────────────────────────────────────────────────────
# registry — ToolSpec lookup
# ────────────────────────────────────────────────────

def test_get_tool_known_and_unknown():
    assert get_tool("create_room").name == "create_room"
    assert get_tool("definitely_not_a_tool") is None


def test_tools_for_agent_filters_by_applies_to():
    persona_tools = {t.name for t in tools_for_agent("persona")}
    mgr_tools = {t.name for t in tools_for_agent("mgr")}
    # persona 전용 도구는 persona 에만, mgr 전용은 mgr 에만
    assert "get_my_songs" in persona_tools
    assert "get_my_songs" not in mgr_tools
    assert "create_room" in mgr_tools
    assert "create_room" not in persona_tools


def test_set_handler_unknown_tool_is_noop():
    # 미등록 도구에 핸들러 주입은 조용히 skip (런타임 안전)
    set_handler("definitely_not_a_tool", lambda a, c: None)
    assert get_tool("definitely_not_a_tool") is None


# ────────────────────────────────────────────────────
# dispatcher.run_single (asyncio.run + mock handler)
# ────────────────────────────────────────────────────

def _ctx(agent_type="mgr"):
    return ToolContext(
        caller_agent_id="agent-1",
        caller_agent_type=agent_type,
        channel_name="mgr-creator",
    )


def test_run_single_unknown_tool_fails():
    r = asyncio.run(run_single(ToolCall(id="1", name="no_such", args={}), _ctx()))
    assert r.ok is False
    assert "unknown tool" in r.error
    assert r.id == "1" and r.tool == "no_such"


def test_run_single_permission_denied_fails():
    # get_my_songs 는 persona 전용 — mgr 가 호출하면 거부
    r = asyncio.run(run_single(ToolCall(id="2", name="get_my_songs", args={}), _ctx("mgr")))
    assert r.ok is False
    assert "not available to mgr" in r.error


def test_run_single_missing_handler_fails():
    # list_channels 는 등록돼 있지만 테스트 환경에선 핸들러 미주입
    spec = get_tool("list_channels")
    assert spec is not None and spec.handler is None
    r = asyncio.run(run_single(ToolCall(id="3", name="list_channels", args={}), _ctx()))
    assert r.ok is False
    assert "no handler" in r.error


def test_run_single_validation_error_fails():
    # set_topic 은 target/value 필수 — 누락 시 검증 실패
    r = asyncio.run(run_single(ToolCall(id="4", name="set_topic", args={}), _ctx()))
    assert r.ok is False
    assert "missing required" in r.error


def test_run_single_sync_handler_returns_ok():
    spec = ToolSpec(
        name="__test_sync__", description="d",
        params={"x": {"type": "str", "required": True}},
        category="management", applies_to=frozenset({"mgr"}),
    )
    spec.handler = lambda args, ctx: {"echo": args["x"]}
    registry.TOOLS["__test_sync__"] = spec
    try:
        r = asyncio.run(run_single(ToolCall(id="5", name="__test_sync__", args={"x": "hi"}), _ctx()))
        assert r.ok is True
        assert r.data == {"echo": "hi"}
        assert r.id == "5" and r.tool == "__test_sync__"
    finally:
        registry.TOOLS.pop("__test_sync__", None)


def test_run_single_async_handler_returns_ok():
    async def handler(args, ctx):
        return {"got": args["x"]}

    spec = ToolSpec(
        name="__test_async__", description="d",
        params={"x": {"type": "str", "required": True}},
        category="management", applies_to=frozenset({"mgr"}),
    )
    spec.handler = handler
    registry.TOOLS["__test_async__"] = spec
    try:
        r = asyncio.run(run_single(ToolCall(id="6", name="__test_async__", args={"x": "yo"}), _ctx()))
        assert r.ok is True
        assert r.data == {"got": "yo"}
    finally:
        registry.TOOLS.pop("__test_async__", None)


def test_run_single_handler_exception_becomes_fail():
    def boom(args, ctx):
        raise RuntimeError("kaboom")

    spec = ToolSpec(
        name="__test_boom__", description="d", params={},
        category="management", applies_to=frozenset({"mgr"}),
    )
    spec.handler = boom
    registry.TOOLS["__test_boom__"] = spec
    try:
        r = asyncio.run(run_single(ToolCall(id="7", name="__test_boom__", args={}), _ctx()))
        assert r.ok is False
        assert "RuntimeError" in r.error and "kaboom" in r.error
    finally:
        registry.TOOLS.pop("__test_boom__", None)
