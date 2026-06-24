# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""WebRuntime — the per-community autonomous driver for the web transport.

This is the web-native replacement for what the Discord bot's ``on_ready`` +
``@tasks.loop`` background tasks did: seed the community, register the supervisor
pool, fire 유나's PROACTIVE first greeting, and tick the pool on an interval so
agent-to-agent conversations / scene supervisors run WITHOUT a Discord gateway.

One instance per community (the platform serves N communities in one process).
``start()`` is idempotent-friendly; ``stop()`` cancels its tasks.

NO Discord imports (CLAUDE.md decoupling) — every outbound message goes through
:class:`community.adapters.web.channels.WebChannelAdapter` via the adapter factory.

SCOPING: the platform pins process-global state (DB path, active community) under
a threading lock (``run_in_community``). Each tick / greeting re-pins this
community right before touching the kernel so a concurrent community's state can't
leak in. The kernel's tool-stash is keyed by the active-community contextvar, so
``set_active_community(cid)`` is set on the loop thread each tick.
"""
from __future__ import annotations

import asyncio
from typing import Optional

from community import db, log_writer
from community.core.channels import MGR_ID, mgr_channel


_TICK_SECONDS = 5.0


class WebRuntime:
    """Drives onboarding + supervisors for ONE community over the web transport."""

    def __init__(self, community_id: str):
        self.cid = community_id
        self._tasks: list[asyncio.Task] = []
        self._stopped = False

    # ── scope helper ────────────────────────────────────────────
    def _scope(self, fn):
        """Run ``fn`` with this community pinned (DB path + active community).
        Synchronous — kernel/DB calls inside must be sync. For async work, pin
        first (this), then await OUTSIDE the lock (the lock is a threading.Lock)."""
        from community.platform.community_ctx import run_in_community
        return run_in_community(self.cid, fn)

    def _pin(self) -> None:
        """Pin process-global community state + the kernel active-community
        contextvar on the CURRENT (loop) thread. The contextvar is task-local, so
        it must be set on the loop, not only inside an executor thread."""
        from community.core.runtime import set_active_community
        self._scope(lambda: None)        # DB path + community.set_community + env
        set_active_community(self.cid)    # kernel contextvar on the loop thread

    def _adapter(self):
        from community.core.channel_adapter import get_channel_adapter
        return get_channel_adapter()

    # ── lifecycle ───────────────────────────────────────────────

    async def start(self) -> None:
        """Boot the community, register supervisors, fire the proactive greeting,
        and start the tick loop. Safe to call once per community."""
        from community.core.boot import boot_community
        from community.supervisors import runner

        self._pin()
        await boot_community(self.cid)

        # Register the system supervisors + initial pool sync (transport-neutral).
        try:
            runner.start_supervisors()
        except Exception as e:
            log_writer.system(f"[web-runtime:{self.cid}] start_supervisors 오류: {e}")

        # 유나 greets FIRST — proactively, before any owner message. Run it as a
        # BACKGROUND task, NOT inline: the greeting is a (potentially slow, 30-90s on
        # claude_cli) LLM generation, and ``start()`` is awaited inside the server's
        # lifespan startup. Blocking on it would stall the whole app from becoming
        # ready (``/healthz`` never answers → the client times out and tears the
        # server down mid-generation → the greeting's ``run_in_executor`` is
        # cancelled, surfacing as a ``CancelledError`` that crashes startup). Firing
        # it in the tick-loop set lets the server go ready immediately; the greeting
        # lands a few seconds later (idempotent via the ``yuna_greeted`` flag).
        self._tasks = [
            asyncio.create_task(self._greet_safely()),
            asyncio.create_task(self._tick_loop()),
        ]
        log_writer.system(f"[web-runtime:{self.cid}] started")

    async def _greet_safely(self) -> None:
        """Background wrapper for the proactive greeting — never lets a slow/failed
        generation propagate (incl. ``CancelledError`` on shutdown) into the loop."""
        try:
            await self._fire_onboarding_greeting_if_needed()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log_writer.system(
                f"[web-runtime:{self.cid}] greeting 오류: {type(e).__name__}: {e}")

    async def stop(self) -> None:
        """Cancel all background tasks for this community."""
        self._stopped = True
        for t in self._tasks:
            t.cancel()
        for t in self._tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
        self._tasks = []
        log_writer.system(f"[web-runtime:{self.cid}] stopped")

    # ── tick loop (replaces tasks.py supervisor_tick) ───────────

    async def _tick_loop(self) -> None:
        """Every ~5s: pin this community on the loop thread, then tick the pool
        with the web ChannelAdapter (no guild). Each supervisor's own interval is
        checked inside pool.tick, so most ticks are cheap."""
        from community.supervisors.base import pool
        while not self._stopped:
            try:
                self._pin()
                await pool.tick(channels=self._adapter())
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log_writer.system(
                    f"[web-runtime:{self.cid}] tick 오류: {type(e).__name__}: {e}"
                )
            try:
                await asyncio.sleep(_TICK_SECONDS)
            except asyncio.CancelledError:
                raise

    # ── proactive onboarding greeting ──────────────────────────

    def _mgr_channel_name(self) -> str:
        """The owner↔manager DM channel key — id-based canonical (``dm-agent-mgr-001``),
        with a legacy ``dm-<name>`` fallback for pre-existing communities. The
        display name (유나/서유나/…) is localized so it is NEVER baked into the key
        (i18n) — the UI resolves it from the channel's agent id at render time."""
        return mgr_channel()

    def _greeting_already_done(self) -> bool:
        """True iff 유나 has already greeted (meta flag set). Pin first."""
        try:
            return bool(db.get_meta("yuna_greeted"))
        except Exception:
            return False

    def _build_greeting(self) -> tuple[str, str]:
        """Resolve owner fields + the manager DM channel, build the greeting prompt
        (ported from bot/tasks._check_owner_profile). Returns (channel_name, prompt).
        Must run pinned (sync DB reads)."""
        from community.core.profile import load_profile
        from community.community import get_language
        from community.scenes.tutorial.greeting import build_yuna_greeting_prompt

        ch_name = self._mgr_channel_name()

        conn = db.get_conn()
        user = conn.execute("SELECT * FROM users LIMIT 1").fetchone()
        conn.close()
        user = dict(user) if user else {}

        import json as _json
        name = user.get("name", "친구")
        age = user.get("age", "?")
        pers = user.get("personality")
        if isinstance(pers, str):
            try:
                pers = _json.loads(pers)
            except Exception:
                pers = {}
        pers = pers or {}
        gender = pers.get("gender", "")
        nickname = pers.get("nickname", "")

        mgr_profile = load_profile(MGR_ID)
        p_name = mgr_profile["name"] if mgr_profile else "유나"

        missing = []
        if not user.get("mbti"):
            missing.append("MBTI")
        if not user.get("background"):
            missing.append("직업/하는 일")
        if not user.get("enneagram"):
            missing.append("에니어그램(모르면 패스)")

        owner_age = int(age) if str(age).isdigit() else None
        yuna_age = 18
        older = bool(owner_age and owner_age > yuna_age)

        prompt = build_yuna_greeting_prompt(
            name=name, age=age, gender=gender, nickname=nickname,
            missing=missing, p_name=p_name, yuna_age=yuna_age,
            older=older, lang=get_language(),
        )
        return ch_name, prompt

    async def _fire_onboarding_greeting_if_needed(self) -> bool:
        """PROACTIVE 유나 first greeting — fires ONCE, before any owner message.

        Idempotency: the ``yuna_greeted`` meta flag is set BEFORE generation so a
        crash/restart mid-generation does not re-greet (mirrors bot/tasks). The mgr
        channel is ensured to exist, then 유나's greeting is generated and sent via
        the web ChannelAdapter so it persists in the manager DM + broadcasts.

        Returns True if a greeting was fired this call.
        """
        self._pin()
        if self._greeting_already_done():
            return False

        # Activate the manager + creator (mgr/creator activate first; personas after
        # tutorial). Build the greeting while pinned.
        from community.core.runtime import runtime as _rt
        try:
            self._scope(lambda: _rt.activate_agent(MGR_ID))
        except Exception:
            pass

        ch_name, prompt = self._scope(self._build_greeting)

        channels = self._adapter()
        # Ensure the manager DM exists so history/broadcast land on a real channel.
        try:
            await channels.ensure_channel(ch_name, participants=[MGR_ID])
        except Exception as e:
            log_writer.system(f"[web-runtime:{self.cid}] mgr 채널 보장 실패: {e}")

        # Set the flag BEFORE generation (idempotent against crash/restart).
        try:
            self._scope(lambda: db.set_meta("yuna_greeted", "1"))
        except Exception:
            pass

        # Generate the greeting (blocking kernel call → executor, pinned inside).
        loop = asyncio.get_event_loop()

        def _gen():
            from community.platform.community_ctx import run_in_community
            from community.core.runtime import set_active_community

            def _call():
                # Pin the kernel contextvar in THIS worker thread — run_in_community
                # is idempotent on the module global and may skip applying it here,
                # leaving the stash/contextvar unset (same hazard as chat._run_turn).
                set_active_community(self.cid)
                return _rt.generate_response(
                    MGR_ID, ch_name, prompt, log_user_message=False
                )
            return run_in_community(self.cid, _call)

        try:
            responses = await loop.run_in_executor(None, _gen)
        except Exception as e:
            log_writer.system(
                f"[web-runtime:{self.cid}] 유나 greeting 생성 실패: {type(e).__name__}: {e}"
            )
            responses = []

        sent = 0
        for resp in responses or []:
            resp = (resp or "").strip()
            if not resp:
                continue
            # Pin the loop thread (broadcast + persist resolve the active community).
            self._pin()
            await channels.send_as_agent(ch_name, MGR_ID, resp)
            sent += 1
            await asyncio.sleep(0.3)

        log_writer.system(
            f"[web-runtime:{self.cid}] 유나 첫 인사 완료 — {sent}건 ({ch_name})"
        )
        return True
