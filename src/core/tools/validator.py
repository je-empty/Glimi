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
