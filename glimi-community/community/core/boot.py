# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Per-community boot seeding — the discord-free home of what ``discord_bot.py``
used to do at startup (``register_all_to_db`` / mgr seed / memory hook / initial
relationships).

Before Phase 4, ALL of this lived only in ``community.discord_bot.main`` —
so a web-driven community had achievements/memory silently inactive and no mgr
seeded. :func:`boot_community` relocates that seeding to a transport-neutral,
idempotent entry the web runtime calls per community.

Idempotency: the process serves N communities, but the achievements engine hook
and the owner-extraction memory hook are PROCESS-GLOBAL (``db.add_message_hook``)
— installing them once per process is correct (the hooks resolve the active
community from the live ``db`` path at call time). A module-level installed-set
guards both the global hooks AND per-community re-seeding so a double-call is a
no-op. The achievements ``engine.install()`` is already auto-run at
``community.achievements.__init__`` import time (kept here too, guarded, for
explicitness / import-order safety).

CALL CONVENTION: run INSIDE ``run_in_community(cid, …)`` so ``db`` resolves the
right path and ``community.set_community`` / the active-community contextvar are
pinned. :class:`community.platform.web_runtime.WebRuntime` does exactly that.

NO Discord imports (CLAUDE.md decoupling) — this is the seam the web path needs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from community import db, log_writer


# ── process-global install guards ──────────────────────────────────────────
# The two memory/achievement hooks are process-wide (db.add_message_hook). Track
# whether they were installed so a per-community boot doesn't re-register them N
# times. Per-community seeding is tracked by cid so re-boot of the same community
# is a no-op too.
_HOOKS_INSTALLED = False
_SEEDED_COMMUNITIES: set[str] = set()


def _install_global_hooks() -> None:
    """Install the process-global achievements engine + owner-extraction memory
    hook ONCE per process. Both resolve the active community at call time, so a
    single install serves every community this process drives."""
    global _HOOKS_INSTALLED
    if _HOOKS_INSTALLED:
        return
    # Achievements engine — db.log_message hook for progress tracking. Auto-run at
    # achievements/__init__ import already; call explicitly + idempotently here so
    # boot order can't leave it un-installed.
    try:
        from community.achievements import engine as _ach_engine
        _ach_engine.install()
    except Exception as e:
        log_writer.system(f"[boot] 도전과제 엔진 설치 실패 (skip): {e}")
    # Memory — owner-utterance extraction hook (owner-perspective memories).
    try:
        from community.core.memory import install_owner_extraction_hook
        install_owner_extraction_hook()
    except Exception as e:
        log_writer.system(f"[boot] 메모리 훅 설치 실패 (skip): {e}")
    _HOOKS_INSTALLED = True


def _seed_mgr() -> None:
    """Seed the manager (유나) ONLY if no agents exist yet (ported from
    ``discord_bot.py`` boot seeding). The creator (하나) is registered lazily by
    the tutorial ``channels_setup`` phase so the owner sees it 'appear' mid-flow.
    """
    if db.list_agents():
        return
    seed_path = Path(__file__).resolve().parents[2] / "assets" / "seed_agents.json"
    if not seed_path.exists():
        log_writer.system(f"[boot] 시드 파일 없음: {seed_path}")
        return
    try:
        with open(seed_path, "r", encoding="utf-8") as f:
            seeds = json.load(f)
    except Exception as e:
        log_writer.system(f"[boot] 시드 로드 실패: {type(e).__name__}: {e}")
        return
    seeded = 0
    for agent in seeds:
        if agent.get("type") == "mgr":
            db.save_agent_profile(agent)
            seeded += 1
    if seeded:
        log_writer.system(f"[boot] 시드 에이전트 {seeded}개 등록 (creator 는 튜토리얼 중 lazy 등록)")


async def boot_community(community_id: str) -> None:
    """Idempotent per-community boot seeding (transport-neutral).

    Must be called inside ``run_in_community(community_id, …)`` (the web runtime
    does). Steps (mirroring ``discord_bot.main`` minus the discord gateway):
      1. ``db.init_db()`` — schema + migrations.
      2. seed mgr from ``assets/seed_agents.json`` (only when no agents exist).
      3. ``register_all_to_db()`` — register every profile to the DB.
      4. ``setup_initial_relationships()`` — owner↔mgr/creator default rels.
      5. ``os.environ.setdefault("GLIMI_TRANSPORT", "web")`` — pin the adapter
         factory to web (never overrides an explicit transport).
      6. install the process-global memory + achievements hooks (once).

    Double-call for the same community is a no-op (guarded). ``async`` so the web
    runtime can ``await`` it in its ``start()`` (the body is sync DB work).
    """
    if community_id in _SEEDED_COMMUNITIES:
        # Still ensure the transport default + global hooks on re-entry (cheap,
        # idempotent) — but skip per-community seeding.
        os.environ.setdefault("GLIMI_TRANSPORT", "web")
        _install_global_hooks()
        return

    db.init_db()
    _seed_mgr()

    try:
        from community.core.profile import register_all_to_db, setup_initial_relationships
        register_all_to_db()
        setup_initial_relationships()
    except Exception as e:
        log_writer.system(f"[boot] 프로필/관계 등록 실패: {type(e).__name__}: {e}")

    # Pin the web transport so get_channel_adapter() resolves WebChannelAdapter.
    # setdefault — never clobber an explicit GLIMI_TRANSPORT (tests / discord).
    os.environ.setdefault("GLIMI_TRANSPORT", "web")

    _install_global_hooks()
    _SEEDED_COMMUNITIES.add(community_id)
    log_writer.system(f"[boot] community 부팅 완료: {community_id}")
