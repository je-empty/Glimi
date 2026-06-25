# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""
에이전트 응답에서 <tools> 블록 + <call> 항목 파싱.

응답 포맷:
    (chat text...)

    <tools>
    <call id="1" name="create_room">
    {"names": ["은하윤"], "topic": "게임"}
    </call>
    <call id="2" name="update_profile">
    {"name": "은하윤", "field": "mood", "value": "활기참"}
    </call>
    </tools>

파서 동작:
    - <tools>...</tools> 블록 찾기 (없으면 빈 리스트)
    - 그 안의 <call> 항목들 추출
    - id/name 속성 + JSON body 파싱
    - chat_text = <tools> 블록 이전의 전체 텍스트
"""
import json
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict
    raw: str = ""  # 원본 블록 (디버그용)


@dataclass
class ParsedResponse:
    chat: str  # <tools> 블록 이전 텍스트 (trailing 공백 제거)
    tool_calls: list[ToolCall]
    errors: list[str]  # 파싱 에러 메시지 (에이전트 피드백용)


_TOOLS_BLOCK = re.compile(r'<tools>(.*?)</tools>', re.DOTALL | re.IGNORECASE)
# 로컬 모델이 <tools> 블록을 마크다운 코드펜스로 감싸는 케이스 — 펜스만 벗겨냄
_FENCE_WRAPPED_TOOLS = re.compile(
    r'```[a-zA-Z]*\s*(<tools>.*?</tools>)\s*```', re.DOTALL | re.IGNORECASE
)

# 모델 control/special token 누출 (특히 gemma 계열 로컬 모델) — 채팅에 절대 노출 금지.
# 예: <channel|>, <|channel|>, <start_of_turn>, <end_of_turn>, <eos>, <unused42>,
#     <|im_start|>, <pad>. 일반 사용자 텍스트의 부등호(<, >, <3 등)는 건드리지 않도록
#     "토큰처럼 생긴" 패턴만 한정.
_CONTROL_TOKEN = re.compile(
    r'<\|?(?:'
    r'channel|start_of_turn|end_of_turn|eos|bos|pad|sep|mask|cls|unk'
    r'|unused\d*|im_start|im_end|tool_call|message|assistant|user|system'
    r')\b[^>]*\|?>',
    re.IGNORECASE,
)
# 파이프로 감싼 control token 일반형 (<|...|>) — 내용 짧은 것만 (오인 최소화)
_PIPE_TOKEN = re.compile(r'<\|[^>\n]{0,40}?\|>')
# HTML 태그 누출 — 로컬 모델이 <br>, <p>, <b> 등 HTML 을 채팅에 뱉는 케이스.
# 알려진 인라인/블록 태그만 한정 (일반 부등호·코드 보존). 채팅엔 HTML 불필요.
_HTML_TAG = re.compile(
    r'</?(?:br|p|div|span|b|i|u|em|strong|ul|ol|li|h[1-6]|hr|a|code|pre)\b[^>]*/?>',
    re.IGNORECASE,
)


def strip_control_tokens(text: str) -> str:
    """모델 special/control token + HTML 태그 누출 제거. 일반 텍스트는 보존."""
    if not text or "<" not in text:
        return text
    text = _CONTROL_TOKEN.sub("", text)
    text = _PIPE_TOKEN.sub("", text)
    text = _HTML_TAG.sub("", text)
    return text
_CALL_BLOCK = re.compile(
    r'<call\s+([^>]*)>\s*(.*?)\s*</call>',
    re.DOTALL | re.IGNORECASE
)
_ATTR = re.compile(r'(\w+)\s*=\s*"([^"]*)"')


def _parse_attrs(attr_str: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in _ATTR.finditer(attr_str)}


def parse_response(text: str) -> ParsedResponse:
    """
    에이전트 응답 전문을 받아 chat + tool_calls 분리.

    <tools> 블록이 없으면 tool_calls=[], chat=전체.
    <tools> 블록이 있지만 내용 파싱 실패 시 errors에 추가.
    """
    errors: list[str] = []
    if not text:
        return ParsedResponse(chat="", tool_calls=[], errors=errors)

    text = _FENCE_WRAPPED_TOOLS.sub(r'\1', text)
    m = _TOOLS_BLOCK.search(text)
    if not m:
        return ParsedResponse(chat=strip_control_tokens(text).strip(), tool_calls=[], errors=errors)

    # chat = <tools> 이전
    chat = strip_control_tokens(text[:m.start()]).rstrip()
    tools_body = m.group(1)

    tool_calls: list[ToolCall] = []
    for c in _CALL_BLOCK.finditer(tools_body):
        attrs = _parse_attrs(c.group(1))
        body = c.group(2).strip()
        name = attrs.get("name", "")
        call_id = attrs.get("id", "")

        if not name:
            errors.append(f"<call> without name attribute: {body[:60]}")
            continue

        # JSON 파싱 — 빈 body는 {} 로 처리 (params=[] 도구용).
        # 방어: LLM 이 JSON 뒤에 코멘트/설명을 붙이는 실수 ("Extra data" 에러) 흔함.
        # JSONDecoder.raw_decode 로 유효한 JSON 부분만 추출 후 나머지 drop.
        try:
            if body:
                try:
                    args = json.loads(body)
                except json.JSONDecodeError as _e:
                    # 앞에서부터 유효한 JSON object 만 잘라서 재시도
                    try:
                        decoder = json.JSONDecoder()
                        args, _end = decoder.raw_decode(body.lstrip())
                        leftover = body.lstrip()[_end:].strip()
                        if leftover:
                            errors.append(
                                f"call '{name}' trailing text after JSON discarded: {leftover[:40]}"
                            )
                    except Exception:
                        raise _e
            else:
                args = {}
            if not isinstance(args, dict):
                errors.append(f"call '{name}' args not object: {body[:60]}")
                continue
        except json.JSONDecodeError as e:
            errors.append(f"call '{name}' JSON parse failed: {e.msg}")
            continue

        tool_calls.append(ToolCall(id=call_id, name=name, args=args, raw=c.group(0)))

    return ParsedResponse(chat=chat, tool_calls=tool_calls, errors=errors)


def strip_tool_blocks(text: str) -> str:
    """<tools>...</tools> 완전 제거한 chat 텍스트. 채널 전송용 안전장치."""
    if not text:
        return ""
    text = _FENCE_WRAPPED_TOOLS.sub(r'\1', text)
    return _TOOLS_BLOCK.sub("", text).strip()
