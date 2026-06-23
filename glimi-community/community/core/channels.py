"""Canonical channel classifier — the single source of truth for what a
channel id *means* and whether a human user may post into it.

Channel ids in Glimi are plain strings whose prefix encodes their role. Today
the prefix logic is duplicated across ~8 ``channel.startswith(...)`` call-sites
(handlers, sync, dashboard). This module is the canonical helper those sites will
collapse onto (that refactor is Phase 5 — DO NOT rewrite the call-sites here, we
only add + test the helper for now).

Prefix taxonomy
---------------
- ``dm-*``              : a 1:1 conversation between the human owner and one
                         agent.                       → user-postable.
- ``group-*``          : a multi-agent group the human participates in.
                         → user-postable.
- ``mgr-*``            : manager/system channels (e.g. ``mgr-system-log``,
                         ``mgr-...``). Internal plumbing surfaced for operators.
                         → NOT user-postable.
- ``internal-dm-*``    : agent-to-agent 1:1 backchannel.   → NOT user-postable.
- ``internal-group-*`` : agent-to-agent group backchannel. → NOT user-postable.

Rule of thumb: ONLY ``dm-*`` and ``group-*`` accept human input. Everything else
is internal/system and a user message addressed to it must be rejected by the
transport layer.

Pure string logic — no I/O, no ``discord`` import, no app imports.
"""
from __future__ import annotations

from typing import Literal

ChannelKind = Literal["dm", "group", "internal-dm", "internal-group", "mgr"]


def channel_kind(channel_id: str) -> ChannelKind:
    """Classify a channel id by its prefix.

    Order matters: the ``internal-`` prefixes are checked BEFORE the bare
    ``dm-`` / ``group-`` prefixes so that ``internal-dm-...`` is never
    misclassified as a user-facing ``dm``.

    Unknown / unprefixed ids fall back to ``"group"`` — historically arbitrary
    conversation keys (e.g. ``webchat-<user>``) behave like a user-facing group
    channel, which is the safe permissive default for the chat surface. Callers
    that need stricter handling should match explicit prefixes themselves.
    """
    cid = channel_id or ""
    if cid.startswith("internal-dm-") or cid == "internal-dm":
        return "internal-dm"
    if cid.startswith("internal-group-") or cid == "internal-group":
        return "internal-group"
    if cid.startswith("mgr-") or cid == "mgr":
        return "mgr"
    if cid.startswith("dm-") or cid == "dm":
        return "dm"
    if cid.startswith("group-") or cid == "group":
        return "group"
    # Unknown prefix → treat as a user-facing group channel (permissive default
    # for the web-chat surface where channel keys are arbitrary, e.g.
    # ``webchat-<user>``).
    return "group"


# Genuine system/log ``mgr-*`` channels — NOT owner conversations. The runtime
# ``<tools>`` log lives here; the degenerate bare ``mgr`` key is treated the same.
# Everything else ``mgr-*`` (``mgr-dashboard``, ``mgr-creator``, …) is, in the
# web model, simply a DM with that manager.
SYSTEM_CHANNELS = frozenset({"mgr-system-log", "mgr"})


def is_system_channel(channel_id: str) -> bool:
    """True for non-conversation system/log channels (e.g. the runtime ``<tools>``
    log) that must stay hidden from the owner's chat surface."""
    cid = channel_id or ""
    return channel_kind(cid) == "mgr" and cid in SYSTEM_CHANNELS


def is_owner_dm(channel_id: str) -> bool:
    """An owner↔single-agent DM.

    Includes ``dm-*`` AND the manager channels (``mgr-dashboard``, ``mgr-creator``,
    …) which — in the web model — are simply DMs with those managers. The
    ``mgr-*`` split between *DM* and *system* was a Discord artifact; on the web a
    manager channel IS a 1:1 DM. Excludes the system log (``is_system_channel``)
    and agent-to-agent backchannels (``internal-*``).
    """
    cid = channel_id or ""
    k = channel_kind(cid)
    if k == "dm":
        return True
    if k == "mgr" and not is_system_channel(cid):
        return True
    return False


def is_user_postable(channel_id: str) -> bool:
    """True iff a human user is allowed to post into this channel.

    Owner DMs (``dm-*`` and the manager channels ``mgr-dashboard`` / ``mgr-creator``
    / other non-system ``mgr-*``) and ``group-*`` accept human input. The system
    log (``mgr-system-log``), bare ``mgr``, and ``internal-*`` backchannels reject
    it.
    """
    return is_owner_dm(channel_id) or channel_kind(channel_id) == "group"


# ── Agent identity + manager-channel name defaults ──────────────────────────
# 매니저(유나/하나/세나) 채널도 페르소나와 동일하게 dm-<이름>. 아래 값은 seed_agents.json
# 기본 이름 기준 default — 웹/시드-기본 커뮤니티에선 이 default 가 곧 실제값.
# (구 Discord 어댑터는 startup 시 _build_channel_maps() 가 커뮤니티별 실제 이름으로 자기
#  모듈 globals 를 덮어썼다 — 그 가변 사본은 community/bot 에 남고 Phase 6 에서 함께 삭제.)
MGR_CHANNEL = "dm-서유나"       # mgr (유나) owner↔mgr DM
CREATOR_CHANNEL = "dm-윤하나"    # creator (하나) owner↔creator DM
DEV_CHANNEL = "dm-한세나"        # dev manager (세나) triage DM
MGR_ID = "agent-mgr-001"
CREATOR_ID = "agent-creator-001"
DEV_ID = "agent-dev-001"


# ── internal-dm 채널명 정렬 컨벤션 ───────────────────────────────────────────
# Yuna(mgr) 먼저 → Hana(creator) → 그 외 입력 순서. 모든 internal-dm 생성 경로가 경유.

def _agent_name_priority(name: str) -> int:
    """sort 키 — 작을수록 채널명에서 앞에 온다."""
    PRIORITY = {"서유나": 0, "Yuna": 0, "윤하나": 1, "Hana": 1, "한세나": 2, "Sena": 2}
    return PRIORITY.get(name, 9)


def _norm_name_for_channel(name: str) -> str:
    """페르소나/유저 이름을 채널명 부품으로 변환.
    공백→하이픈, 영숫자/한글/하이픈/언더스코어 외 제거, 연속 하이픈→단일."""
    import re as _re
    s = _re.sub(r"\s+", "-", (name or "").strip())
    s = _re.sub(r"[^\w\-가-힣ㄱ-ㅎㅏ-ㅣ]", "", s)
    s = _re.sub(r"-+", "-", s).strip("-")
    return s


def internal_dm_channel_name(a_name: str, b_name: str) -> str:
    """두 에이전트 이름으로 internal-dm 채널명 생성. 유나 우선 → 하나 → 그 외."""
    if not a_name or not b_name:
        return f"internal-dm-{_norm_name_for_channel(a_name) or '?'}-{_norm_name_for_channel(b_name) or '?'}"
    pa, pb = _agent_name_priority(a_name), _agent_name_priority(b_name)
    first, second = (a_name, b_name) if pa <= pb else (b_name, a_name)
    return f"internal-dm-{_norm_name_for_channel(first)}-{_norm_name_for_channel(second)}"


# ── 채널명 정규화 + 카테고리 순서 (Phase 1.4 salvage from community.core.sync) ──
# sync.py 는 top-level `import discord` 라 web python 에서 import 불가. 아래 두 심볼은
# discord-free 라 여기(core.channels)로 옮겨 web 경로(scene/achievement)가 sync 의
# discord 의존 없이 쓰게 한다. sync.py 는 자체 caller 호환을 위해 re-export 유지.

def normalize_channel_name(name: str) -> str:
    """채널명 정규화 — 공백 → dash, 양 끝 trim. Discord 가 자동 변환하는 것과 일치시켜
    DB·runtime cache 와 어긋나는 회귀 방지."""
    import re as _re
    if not name:
        return name
    return _re.sub(r"\s+", "-", name.strip())


# 카테고리 순서 (구 Discord 카테고리 정렬용 — web 에선 no-op 이지만 scene 코드가 참조)
CATEGORY_ORDER = ["glimi-mgr", "glimi-dm", "glimi-group", "glimi-internal-dm", "glimi-internal-group"]
