"""커뮤니티 봇 subprocess supervisor.

각 커뮤니티 봇 = `python -m src.discord_bot` + `GLIMI_COMMUNITY={id}` env.
현재 구조상 1 subprocess = 1 community 고정 (전역 state 이유). 이 클래스는 N 개를 동시 관리.

legacy run.sh 의 auto-restart / exit-code-42 dev-runner 로직은 여기로 이관 가능 — 지금은 MVP 로 단순 start/stop 만.
"""
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.community import COMMUNITIES_DIR, PROJECT_ROOT


@dataclass
class BotHandle:
    community_id: str
    process: subprocess.Popen
    started_at: float
    log_path: Path


@dataclass
class Supervisor:
    _handles: dict[str, BotHandle] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # ── 수명주기 ───────────────────────────────────────────

    def start(self, community_id: str) -> BotHandle:
        """봇 subprocess 기동. 이미 실행 중이면 기존 핸들 반환."""
        with self._lock:
            existing = self._handles.get(community_id)
            if existing and existing.process.poll() is None:
                return existing
            # stale 제거
            if existing:
                self._handles.pop(community_id, None)

            cdir = COMMUNITIES_DIR / community_id
            if not cdir.exists():
                raise FileNotFoundError(f"community dir 없음: {cdir}")
            log_dir = cdir / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "bot.log"

            env = os.environ.copy()
            env["GLIMI_COMMUNITY"] = community_id
            # 플랫폼 안에서 띄우므로 대시보드 자동 기동은 안 함
            env["GLIMI_NO_DASHBOARD"] = "1"

            # append mode + line buffered
            log_fh = open(log_path, "ab", buffering=0)
            log_fh.write(f"\n===== supervisor spawn {community_id} @ {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} =====\n".encode())

            proc = subprocess.Popen(
                [sys.executable, "-m", "src.discord_bot"],
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # 자체 process group → kill 시 깨끗
            )
            handle = BotHandle(
                community_id=community_id,
                process=proc,
                started_at=time.time(),
                log_path=log_path,
            )
            self._handles[community_id] = handle
            return handle

    def stop(self, community_id: str, timeout: float = 10.0) -> bool:
        """SIGTERM → wait → 안 죽으면 SIGKILL. 실행 중 아니었으면 False."""
        with self._lock:
            handle = self._handles.get(community_id)
            if not handle or handle.process.poll() is not None:
                self._handles.pop(community_id, None)
                return False
            proc = handle.process

        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=3.0)

        with self._lock:
            self._handles.pop(community_id, None)
        return True

    def restart(self, community_id: str) -> BotHandle:
        self.stop(community_id)
        return self.start(community_id)

    # ── 상태 조회 ───────────────────────────────────────────

    def status(self, community_id: str) -> dict:
        with self._lock:
            handle = self._handles.get(community_id)
        if not handle:
            return {"running": False, "pid": None, "started_at": None, "uptime_sec": None}
        rc = handle.process.poll()
        running = rc is None
        if not running:
            with self._lock:
                self._handles.pop(community_id, None)
        return {
            "running": running,
            "pid": handle.process.pid if running else None,
            "started_at": handle.started_at,
            "uptime_sec": (time.time() - handle.started_at) if running else None,
            "exit_code": rc,
            "log_path": str(handle.log_path),
        }

    def list_running(self) -> list[str]:
        out = []
        with self._lock:
            stale = []
            for cid, h in self._handles.items():
                if h.process.poll() is None:
                    out.append(cid)
                else:
                    stale.append(cid)
            for cid in stale:
                self._handles.pop(cid, None)
        return out

    def shutdown_all(self, timeout: float = 10.0) -> None:
        """플랫폼 종료 시 모든 봇 정리."""
        for cid in list(self._handles.keys()):
            try:
                self.stop(cid, timeout=timeout)
            except Exception as e:
                print(f"[supervisor] stop {cid} failed: {e}")

    def tail_log(self, community_id: str, lines: int = 200) -> str:
        with self._lock:
            handle = self._handles.get(community_id)
        if handle:
            log_path = handle.log_path
        else:
            log_path = COMMUNITIES_DIR / community_id / "logs" / "bot.log"
        if not log_path.exists():
            return ""
        # 간이 tail — 큰 파일이면 seek 로 최적화 가능
        try:
            content = log_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            return f"(log read failed: {e})"
        return "\n".join(content.splitlines()[-lines:])


# 싱글톤 인스턴스
supervisor = Supervisor()
