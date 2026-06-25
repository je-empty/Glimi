"""Per-community WebRuntime lifecycle manager (web-first).

Each active community runs an in-process ``WebRuntime`` that boots the community,
registers the supervisor pool, fires the manager's proactive greeting, and ticks
the pool on an interval. This owns their lifecycle across the platform lifespan
AND the dashboard start/stop/restart controls.

(Formerly launched a Discord bot subprocess per community via
``python -m community.discord_bot``; the in-process web runtime replaced it when
the project went web-first, so there is no longer a subprocess to manage.)
"""
import time
from dataclasses import dataclass

from community.community import COMMUNITIES_DIR


@dataclass
class RuntimeHandle:
    community_id: str
    runtime: object  # WebRuntime — kept opaque to avoid an import cycle.
    started_at: float


class Supervisor:
    """Owns the live ``WebRuntime`` per community. Lifecycle methods are async (a
    WebRuntime boots + tears down on the event loop); status reads are sync."""

    def __init__(self) -> None:
        self._handles: dict[str, RuntimeHandle] = {}

    # ── lifecycle (async — runs on the event loop) ─────────────────────
    async def start_async(self, community_id: str) -> RuntimeHandle:
        """Boot the community's WebRuntime. Idempotent — returns the existing
        handle if it is already running."""
        existing = self._handles.get(community_id)
        if existing is not None:
            return existing
        cdir = COMMUNITIES_DIR / community_id
        if not cdir.exists():
            raise FileNotFoundError(f"community dir 없음: {cdir}")
        from .web_runtime import WebRuntime
        rt = WebRuntime(community_id)
        await rt.start()
        handle = RuntimeHandle(community_id, rt, time.time())
        self._handles[community_id] = handle
        return handle

    async def stop_async(self, community_id: str) -> bool:
        """Tear down the community's WebRuntime. False if it was not running."""
        handle = self._handles.pop(community_id, None)
        if handle is None:
            return False
        try:
            await handle.runtime.stop()
        except Exception:
            pass
        return True

    async def restart_async(self, community_id: str) -> RuntimeHandle:
        await self.stop_async(community_id)
        return await self.start_async(community_id)

    async def shutdown_all_async(self) -> None:
        for cid in list(self._handles.keys()):
            try:
                await self.stop_async(cid)
            except Exception as e:
                print(f"[supervisor] stop {cid} failed: {e}")

    # ── status (sync — registry reads) ─────────────────────────────────
    def status(self, community_id: str) -> dict:
        handle = self._handles.get(community_id)
        if handle is not None:
            return {
                "running": True,
                "pid": None,
                "started_at": handle.started_at,
                "uptime_sec": time.time() - handle.started_at,
                "exit_code": None,
            }
        return {"running": False, "pid": None, "started_at": None, "uptime_sec": None}

    def list_running(self) -> list[str]:
        return list(self._handles.keys())

    def shutdown_all(self, timeout: float = 10.0) -> None:
        """Best-effort SYNC teardown for signal/atexit handlers (no running event
        loop). Cancels each runtime's background tasks directly; the process is
        exiting, so the OS reclaims the rest."""
        for cid in list(self._handles.keys()):
            handle = self._handles.pop(cid, None)
            if handle is None:
                continue
            try:
                for t in getattr(handle.runtime, "_tasks", []) or []:
                    t.cancel()
            except Exception:
                pass

    def tail_log(self, community_id: str, lines: int = 200) -> str:
        log_path = COMMUNITIES_DIR / community_id / "logs" / "system.log"
        if not log_path.exists():
            return ""
        try:
            content = log_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"(log read failed: {e})"
        return "\n".join(content.splitlines()[-lines:])


# 싱글톤 인스턴스
supervisor = Supervisor()
