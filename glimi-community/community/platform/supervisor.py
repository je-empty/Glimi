"""커뮤니티 봇 subprocess supervisor.

각 커뮤니티 봇 = `python -m community.discord_bot` + `GLIMI_COMMUNITY={id}` env.
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

from community.community import COMMUNITIES_DIR, PROJECT_ROOT


# ── 외부 기동 봇 감지 (QA runner 등 platform 바깥에서 spawn 된 봇) ───────────
# 봇 subprocess 는 기동 시 `dev/.bot-{cid}.pid` 에 pid 를 기록. QA runner 같은 외부
# 경로로 띄운 봇도 같은 파일 씀. status/list_running 이 자기 _handles 만 보면 이런
# 봇을 '정지됨' 으로 잘못 표시 — PID 파일 fallback 으로 감지.
_EXTERNAL_PID_DIR = PROJECT_ROOT / "dev"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError, OSError):
        return False


def _read_external_bot_pid(community_id: str) -> Optional[int]:
    """dev/.bot-{cid}.pid 존재 + alive 면 pid 반환, 아니면 None."""
    pid_file = _EXTERNAL_PID_DIR / f".bot-{community_id}.pid"
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text().strip())
    except (ValueError, OSError):
        return None
    if not _pid_alive(pid):
        return None
    return pid


def _scan_external_bot_cids() -> dict[str, int]:
    """dev/.bot-*.pid 스캔 — alive pid 만 반환. {cid: pid}."""
    out: dict[str, int] = {}
    if not _EXTERNAL_PID_DIR.exists():
        return out
    for p in _EXTERNAL_PID_DIR.glob(".bot-*.pid"):
        name = p.name  # .bot-qa.pid
        if not name.startswith(".bot-") or not name.endswith(".pid"):
            continue
        cid = name[len(".bot-"):-len(".pid")]
        # ".bot.pid" (without dash/cid) — legacy default. skip.
        if not cid:
            continue
        try:
            pid = int(p.read_text().strip())
        except (ValueError, OSError):
            continue
        if _pid_alive(pid):
            out[cid] = pid
    return out


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
            # Windows 기본 stdout codepage (cp949) 가 한글/em-dash 인코딩 못 해서
            # 봇 startup print() 가 즉시 UnicodeEncodeError 로 죽는 회귀 fix.
            # PYTHONIOENCODING=utf-8 로 강제 → log 파일에 UTF-8 그대로 기록.
            env["PYTHONIOENCODING"] = "utf-8"
            env["PYTHONUTF8"] = "1"

            # append mode + line buffered
            log_fh = open(log_path, "ab", buffering=0)
            log_fh.write(f"\n===== supervisor spawn {community_id} @ {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} =====\n".encode())

            # Process group 분리 — OS 별로 다른 flag 사용.
            # POSIX: start_new_session=True (setsid). Windows: CREATE_NEW_PROCESS_GROUP + CREATE_NO_WINDOW.
            # CREATE_NEW_PROCESS_GROUP 만으로는 console attach 유지 → 봇 종료 시 console event 가
            # 부모 platform 에 전파되어 같이 종료되는 회귀. CREATE_NO_WINDOW 로 봇을 console-detached 로
            # 띄워야 부모 cmd 와 완전 분리. stdin=DEVNULL 로 fd inherit 도 차단.
            popen_kwargs: dict = {}
            if sys.platform == "win32":
                popen_kwargs["creationflags"] = (
                    subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
                )
                popen_kwargs["stdin"] = subprocess.DEVNULL
            else:
                popen_kwargs["start_new_session"] = True

            proc = subprocess.Popen(
                [sys.executable, "-m", "community.discord_bot"],
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                **popen_kwargs,
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
        """SIGTERM → wait → 안 죽으면 SIGKILL. 실행 중 아니었으면 False.

        POSIX: os.killpg 로 process group 단위 정리.
        Windows: proc.terminate() / proc.kill() — CREATE_NEW_PROCESS_GROUP 으로 분리됨.
        """
        with self._lock:
            handle = self._handles.get(community_id)
            if not handle or handle.process.poll() is not None:
                self._handles.pop(community_id, None)
                return False
            proc = handle.process

        # SIGTERM 단계
        try:
            if sys.platform == "win32":
                proc.terminate()
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            # SIGKILL 단계
            try:
                if sys.platform == "win32":
                    proc.kill()
                else:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
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
        if handle:
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
                "external": False,
            }
        # Fallback: platform 외부에서 기동된 봇 (QA runner, 수동 실행 등).
        ext_pid = _read_external_bot_pid(community_id)
        if ext_pid:
            return {
                "running": True,
                "pid": ext_pid,
                "started_at": None,
                "uptime_sec": None,
                "exit_code": None,
                "log_path": None,
                "external": True,
            }
        return {"running": False, "pid": None, "started_at": None, "uptime_sec": None}

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
        # Fallback: PID 파일로 외부 기동 봇 추가 감지 (_handles 없는 경우만)
        for cid in _scan_external_bot_cids().keys():
            if cid not in out:
                out.append(cid)
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
