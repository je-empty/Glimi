# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""creator 가 채널에 띄운 sample 프로필 이미지 추적.

목적: `set_profile_image` 호출 시 LLM 이 직전 preview 와 다른 sample 파일명을 넘기는
환각 케이스 방어. preview 시 (caller, channel) → sample_file 기록, set_profile_image 는
이를 참조해 mismatch 면 preview 한 파일로 교정.

휘발성 in-memory dict — 재시작 시 잊혀짐 (튜토리얼 후 set_profile_image 까지 보통 1-2 분
이내라 영속 저장 불필요).

플랫폼 중립 (discord-free). 구 위치 community/bot/profile_preview.py 는 re-export shim.
"""
from __future__ import annotations

import time
import threading

# 검증 유효 기간 — preview 후 이 시간을 넘겨 호출되면 무시 (LLM 이 재선택했다고 간주).
PREVIEW_TTL_SEC = 600  # 10분

_lock = threading.Lock()
_state: dict[tuple[str, str], tuple[str, float]] = {}


def record_preview(caller_agent_id: str, channel_name: str, sample_file: str) -> None:
    """creator 가 sample 이미지를 채널에 띄운 시점 기록."""
    if not (caller_agent_id and channel_name and sample_file):
        return
    base = _strip_full_suffix(sample_file)
    with _lock:
        _state[(caller_agent_id, channel_name)] = (base, time.time())


def get_recent_preview(caller_agent_id: str, channel_name: str) -> str:
    """마지막 preview sample 파일명 (base, -full 제거된 형태). 없거나 만료면 빈 문자열."""
    if not (caller_agent_id and channel_name):
        return ""
    with _lock:
        entry = _state.get((caller_agent_id, channel_name))
    if not entry:
        return ""
    base, ts = entry
    if time.time() - ts > PREVIEW_TTL_SEC:
        return ""
    return base


def clear_preview(caller_agent_id: str, channel_name: str) -> None:
    """set_profile_image 적용 후 호출 — 같은 preview 가 다음 생성에 잘못 적용되는 거 방지."""
    with _lock:
        _state.pop((caller_agent_id, channel_name), None)


def _strip_full_suffix(name: str) -> str:
    """`agent-persona-f-19-infp-shy-dreamy-full.png` → `agent-persona-f-19-infp-shy-dreamy.png`.

    set_profile_image 인자는 base `.png` 를 받기 때문에 비교를 위해 `-full` suffix 제거.
    """
    if "-full." in name:
        return name.replace("-full.", ".")
    return name
