"""도전과제 base 클래스 + 슈퍼바이저 인터페이스.

각 도전과제는 `src/achievements/catalog/<key>.py` 한 파일로 존재. 파일이 있으면 등록,
없으면 등록 안 됨. catalog/__init__.py 가 import time 에 자동 스캔.

각 파일은 다음을 export:
- `ACHIEVEMENT: Achievement` (필수) — 정의 + check 함수
- `SUPERVISOR: AchievementSupervisor` (선택) — 실시간 추적 옵저버
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Achievement:
    """도전과제 정의.

    check(user_id) → dict|None:
      반환 dict 의 키:
        "state": "locked" | "unlocked" | "done"
        "progress_data": dict (UI 표시 + 누가/언제/무엇으로 달성됐는지 기록)
        "mark_unlocked": bool — state="unlocked" 에 처음 도달 시 True
        "mark_completed": bool — state="done" 에 처음 도달 시 True
      None 반환 → 변경 없음 (idempotent).

    engine 이 매 메시지 / 명시적 recompute_all() 호출 시 모든 검사 실행.
    이미 done 인 도전과제는 skip.
    """
    key: str
    title: str
    description: str
    icon: str
    check: Callable[[str], Optional[dict]]
    # 선택: 도전과제별 메타 (작성자·도입 버전·태그 등) — UI 또는 분석용.
    meta: dict = field(default_factory=dict)

    # ── LLM-judge tier (선택) ─────────────────────────────────
    # Tier 1 (default): pure logic check 만 사용 → cheap·fast
    # Tier 2: candidate_pre_filter 로 후보 좁힌 후 LLM judge 가 의미 판정 →
    #         false-positive 방지 + 비용 적음 (Haiku batch). confession 류.
    # Tier 3: events 테이블에 명시 기록된 이벤트 (scene/supervisor) → check 가 events 우선 조회.
    candidate_pre_filter: Optional[Callable[[str], list[dict]]] = None
    """user_id → list of candidate dicts.
    각 dict 는 최소 {id, channel, speaker, speaker_name, message, timestamp} 포함.
    judge 가 yes 판정한 첫 candidate 의 id 가 trigger 가 됨.
    None 이면 Tier 2 비활성 (pure logic check 만 사용).
    """
    judge_prompt: Optional[str] = None
    """Haiku 에 전달할 시스템 프롬프트. 메시지 1건당 yes/no 판정.
    예: "다음 메시지가 캐릭터가 오너에게 마음을 직접 고백하는 발화인가? yes 또는 no 만."
    None 이면 LLM judge 비활성.
    """


class AchievementSupervisor:
    """도전과제 실시간 추적 슈퍼바이저 베이스.

    `check` 가 매 recompute 마다 DB 풀 스캔하는 비싼 도전과제는 SUPERVISOR 도 함께 정의해
    실시간 fast-path 로 진행. 슈퍼바이저는 engine 의 hook 에서 호출됨.

    Subclass 가 override 할 메서드:
      on_message(channel, speaker, message) → Optional[dict]
          새 메시지 발생 시. 도전과제 진척 발생하면 dict 반환 (Achievement.check 와 동일 shape).
      on_event(event_type, payload) → Optional[dict]
          events 테이블에 기록되는 이벤트 발생 시.
      on_tool_call(tool_name, args, result) → Optional[dict]
          도구 실행 결과 관찰 시.

    모든 메서드 default 는 None (no-op). 도전과제별로 필요한 것만 override.

    슈퍼바이저는 stateless 권장 — 진척 데이터는 DB 만 source-of-truth.
    """

    key: str = ""  # 어느 도전과제에 속하는지 표시. catalog 파일이 set.

    def on_message(self, channel: str, speaker: str, message: str) -> Optional[dict]:
        return None

    def on_event(self, event_type: str, payload: dict) -> Optional[dict]:
        return None

    def on_tool_call(self, tool_name: str, args: dict, result: dict) -> Optional[dict]:
        return None
