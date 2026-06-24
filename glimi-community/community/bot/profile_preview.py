# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""DEPRECATED 위치 — 로직은 community.core.profile_preview 로 이동(discord-free).

이 파일은 Discord 어댑터 코드(`community/bot/`)의 기존 import 를 깨지 않기 위한 re-export
shim. 신규 코드(웹/코어)는 `community.core.profile_preview` 를 직접 import 할 것.
"""
from community.core.profile_preview import (  # noqa: F401
    PREVIEW_TTL_SEC,
    record_preview,
    get_recent_preview,
    clear_preview,
    _strip_full_suffix,
)
