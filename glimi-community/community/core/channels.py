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


# ── Agent identity + manager-channel keys ───────────────────────────────────
# 스태프(mgr/creator/dev) DM 채널의 **정본 키는 에이전트 id 기반** `dm-<agent-id>` 다.
# 표시 이름(유나/서유나/Yuna 등)은 로케일별로 바뀌므로 채널 키에 절대 새기지 않는다
# (i18n). UI 는 채널의 agent id 에서 표시 이름을 렌더 타임에 resolve 한다.
#
# 페르소나(유저가 만든 친구) 채널은 이름 기반 `dm-<이름>` 유지 — 친구 이름은
# 로케일 종속이 아니고, 유저가 직접 붙인 고유 식별자라 그대로 쓴다.
#
# 하위호환: 기존 커뮤니티(라이브 qa)는 name-based `dm-서유나` mgr 채널을 가질 수 있다.
# resolver(mgr_channel/creator_channel/dev_channel) 는 `dm-<id>` 를 우선하되, 그게
# 아직 없고 legacy `dm-<이름>` 채널이 DB 에 있으면 그걸 채택한다(코드 폴백 — 라이브 DB
# 는 건드리지 않음). 새 커뮤니티는 처음부터 `dm-<id>` 로 시드/부팅된다.
MGR_ID = "agent-mgr-001"
CREATOR_ID = "agent-creator-001"
DEV_ID = "agent-dev-001"

# Canonical id-based channel keys (the single source of truth). These are the
# defaults the seed/boot create and every web call-site posts into.
MGR_CHANNEL = f"dm-{MGR_ID}"        # mgr (유나)     owner↔mgr DM
CREATOR_CHANNEL = f"dm-{CREATOR_ID}"  # creator (하나) owner↔creator DM
DEV_CHANNEL = f"dm-{DEV_ID}"        # dev (세나)     triage DM

# Deprecated name-based aliases (the old seed default names). Kept ONLY so the
# legacy-fallback resolver below + any old caller still referencing a display
# name can recognize a pre-id-based channel. DO NOT post into these directly.
_LEGACY_MGR_CHANNEL = "dm-서유나"
_LEGACY_CREATOR_CHANNEL = "dm-윤하나"
_LEGACY_DEV_CHANNEL = "dm-한세나"


def _channel_exists(channel_key: str) -> bool:
    """True iff a channel with this exact key is registered in the active
    community DB. Best-effort (returns False on any error / no community pinned)."""
    if not channel_key:
        return False
    try:
        from community import db
        conn = db.get_conn()
        try:
            row = conn.execute(
                "SELECT 1 FROM channels WHERE channel = ? LIMIT 1", (channel_key,)
            ).fetchone()
            return row is not None
        finally:
            conn.close()
    except Exception:
        return False


def _legacy_name_channel(agent_id: str) -> str:
    """The legacy `dm-<display-name>` key for a staff agent id, from the DB agent
    name (community may have renamed the manager). Empty string if unknown."""
    try:
        from community import db
        row = db.get_agent(agent_id)
        name = (row or {}).get("name")
        if name:
            return f"dm-{_norm_name_for_channel(name)}"
    except Exception:
        pass
    return ""


def _staff_channel(agent_id: str, *, default_legacy: str = "") -> str:
    """Resolve a staff (mgr/creator/dev) DM channel key, id-based-preferred.

    Precedence (web-first, i18n-safe):
      1. ``dm-<agent-id>`` — the canonical key. Used if it already exists, OR if
         no legacy name-based channel exists either (fresh community → adopt the
         canonical key so ``ensure_channel`` creates it id-based).
      2. legacy ``dm-<display-name>`` — ONLY if the canonical key is absent AND a
         name-based channel already exists in the DB (an existing community that
         predates the id-based convention). Adopting it avoids a split-brain DM.

    Never mutates the DB — pure resolution. A one-time migration (rename legacy →
    id-based) is advisable for existing communities but is intentionally NOT done
    here (see module docstring / report)."""
    canonical = f"dm-{agent_id}"
    if _channel_exists(canonical):
        return canonical
    legacy = _legacy_name_channel(agent_id) or default_legacy
    if legacy and legacy != canonical and _channel_exists(legacy):
        return legacy
    return canonical


def mgr_channel() -> str:
    """The owner↔manager(유나) DM channel key. ``dm-agent-mgr-001`` canonically,
    falling back to a legacy ``dm-<name>`` channel if one already exists."""
    return _staff_channel(MGR_ID, default_legacy=_LEGACY_MGR_CHANNEL)


def creator_channel() -> str:
    """The owner↔creator(하나) DM channel key (id-based-preferred)."""
    return _staff_channel(CREATOR_ID, default_legacy=_LEGACY_CREATOR_CHANNEL)


def dev_channel() -> str:
    """The owner↔dev(세나) DM channel key (id-based-preferred)."""
    return _staff_channel(DEV_ID, default_legacy=_LEGACY_DEV_CHANNEL)


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
