# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""
Tool call 인자 검증 — spec에 맞춰 타입/필수 필드 체크.

의도적으로 가벼움: Pydantic 의존 없이 dict schema만으로 충분.
로컬 모델 스왑 시에도 그대로 작동.
"""
from typing import Any

from .registry import ToolSpec


class ValidationError(Exception):
    def __init__(self, tool: str, msg: str):
        self.tool = tool
        self.msg = msg
        super().__init__(f"[{tool}] {msg}")


_TYPE_CHECKERS = {
    "str": lambda v: isinstance(v, str),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "bool": lambda v: isinstance(v, bool),
    "list[str]": lambda v: isinstance(v, list) and all(isinstance(x, str) for x in v),
    "list": lambda v: isinstance(v, list),
    "dict": lambda v: isinstance(v, dict),
    "any": lambda v: True,
}


def validate_args(spec: ToolSpec, args: dict) -> dict[str, Any]:
    """
    spec.params에 따라 args 검증.

    Returns: 정규화된 args (여분 필드 제거됨)
    Raises: ValidationError
    """
    if not isinstance(args, dict):
        raise ValidationError(spec.name, "args must be object")

    normalized: dict[str, Any] = {}

    # 필수 필드 체크
    for param_name, param_spec in spec.params.items():
        required = param_spec.get("required", False)
        param_type = param_spec.get("type", "any")
        if param_name not in args:
            if required:
                raise ValidationError(
                    spec.name,
                    f"missing required field '{param_name}' ({param_type})"
                )
            continue

        value = args[param_name]
        checker = _TYPE_CHECKERS.get(param_type, _TYPE_CHECKERS["any"])
        if not checker(value):
            # LLM 이 str 파라미터에 int/float/bool 을 넣는 경우가 빈번 (예: age=25, value=1).
            # 엄격히 reject 하면 프로필 수정 같은 기본 플로우가 실패 → 자동 str 변환.
            # list[str] 에 대해서도 단일 str 은 [str] 로 승격해서 호출자 의도 보존.
            coerced = None
            if param_type == "str" and isinstance(value, (int, float, bool)):
                coerced = str(value)
            elif param_type == "str" and isinstance(value, (dict, list)):
                # LLM 이 JSON 문자열 대신 raw object 로 보내는 케이스 (예: create_agent_profile
                # 의 args 는 JSON 문자열 기대지만 dict 로 들어옴). json.dumps 로 직렬화.
                import json as _json
                try:
                    coerced = _json.dumps(value, ensure_ascii=False)
                except Exception:
                    pass
            elif param_type == "list[str]" and isinstance(value, str):
                coerced = [value]
            if coerced is not None:
                normalized[param_name] = coerced
                continue
            raise ValidationError(
                spec.name,
                f"field '{param_name}' expects {param_type}, got {type(value).__name__}"
            )
        normalized[param_name] = value

    # 스펙에 없는 필드는 경고만 (무시)
    # 에이전트가 추가 필드를 던지면 조용히 drop
    return normalized


def check_permission(spec: ToolSpec, agent_type: str) -> tuple[bool, str]:
    """
    이 도구를 해당 에이전트 타입이 호출 가능한가?
    Returns: (allowed, reason_if_denied)
    """
    if agent_type not in spec.applies_to:
        return False, f"tool '{spec.name}' not available to {agent_type} (applies_to: {sorted(spec.applies_to)})"
    return True, ""
