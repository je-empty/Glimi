"""Dev batch run orchestrator — tmux session + bot lifecycle + dispatch.

When admin clicks "Run all approved" on /admin/dev-requests, the platform calls
`start_dev_run()` which:

  1. Stops ALL community bot subprocesses (so Claude Code can edit code without races)
  2. Creates a dev_runs row
  3. Spawns a tmux session `Glimi-Claude-Code-Dev` running this module's CLI entrypoint
  4. Returns immediately — UI polls /api/admin/dev-requests/live_output for progress

The tmux session executes `python -m community.core.dev_runner --run-id N --requests 1,2,3 ...`,
which calls `dev_dispatch.run_batch(...)` with output piped to a log file (so the web
UI can tail it). When run_batch returns, the runner restarts the previously-running bots.

Platform stays up the whole time so admin can watch the dashboard live.
"""
from __future__ import annotations

import argparse
import asyncio
import json as _json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TMUX_SESSION = "Glimi-Claude-Code-Dev"
DEV_RUNS_DIR = PROJECT_ROOT / "data" / "dev_runs"


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _log_path_for(run_id: int) -> Path:
    DEV_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return DEV_RUNS_DIR / f"run-{run_id}-{_ts()}.log"


def _stop_all_bots() -> list[str]:
    """모든 community bot subprocess 정지. 정지된 community id list 반환.

    참고: dev_runner 는 tmux 세션 안에서 별도 Python 프로세스로 돌기 때문에
    플랫폼 프로세스의 in-memory `Supervisor` instance 에 접근 불가. 대신 platform API
    /api/communities/{id}/stop 을 호출해서 제대로 정지시킴.
    """
    import urllib.request
    import urllib.error
    base = os.environ.get("GLIMI_PLATFORM_URL", "http://127.0.0.1:8000")
    cookie = os.environ.get("GLIMI_DEV_RUN_COOKIE", "")
    try:
        req = urllib.request.Request(f"{base}/api/communities", method="GET")
        if cookie:
            req.add_header("Cookie", cookie)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = _json.loads(resp.read())
    except Exception as e:
        print(f"[dev_runner] failed to list communities: {e}", flush=True)
        return []

    stopped = []
    items = data.get("items", []) if isinstance(data, dict) else data
    for item in items:
        cid = item.get("id")
        running = item.get("status", {}).get("running") if isinstance(item.get("status"), dict) else item.get("running")
        if not cid or not running:
            continue
        try:
            req = urllib.request.Request(
                f"{base}/api/communities/{cid}/stop", method="POST",
                data=b"",
            )
            if cookie:
                req.add_header("Cookie", cookie)
            with urllib.request.urlopen(req, timeout=15) as r:
                _ = r.read()
            stopped.append(cid)
            print(f"[dev_runner] stopped bot: {cid}", flush=True)
        except Exception as e:
            print(f"[dev_runner] stop {cid} failed: {e}", flush=True)
    return stopped


def _restart_bots(community_ids: list[str]) -> None:
    import urllib.request
    base = os.environ.get("GLIMI_PLATFORM_URL", "http://127.0.0.1:8000")
    cookie = os.environ.get("GLIMI_DEV_RUN_COOKIE", "")
    for cid in community_ids:
        try:
            req = urllib.request.Request(
                f"{base}/api/communities/{cid}/start", method="POST", data=b"",
            )
            if cookie:
                req.add_header("Cookie", cookie)
            with urllib.request.urlopen(req, timeout=30) as r:
                _ = r.read()
            print(f"[dev_runner] restarted bot for {cid}", flush=True)
        except Exception as e:
            print(f"[dev_runner] restart {cid} failed: {e}", flush=True)


# ── tmux session helper ────────────────────────────────────

def _tmux_session_exists(name: str = TMUX_SESSION) -> bool:
    p = subprocess.run(["tmux", "has-session", "-t", name],
                       capture_output=True, text=True)
    return p.returncode == 0


def spawn_tmux_run(run_id: int, request_ids: list[int], log_path: Path) -> dict:
    """tmux 세션 띄우고 거기서 dev_runner 실행. 즉시 반환 (백그라운드 실행).

    Pre-condition: 호출자가 이미 community bot 들을 정지시킨 상태여야 함.
    """
    if _tmux_session_exists():
        return {"ok": False, "error": f"tmux session {TMUX_SESSION} already running"}

    py = sys.executable or "python3"
    request_csv = ",".join(str(r) for r in request_ids)
    cmd = (
        f'cd {PROJECT_ROOT}; '
        f'PYTHONUNBUFFERED=1 {py} -u -m community.core.dev_runner '
        f'--run-id {run_id} --requests "{request_csv}" --log-path "{log_path}" '
        f'2>&1 | tee -a "{log_path}"'
    )
    proc = subprocess.run(
        ["tmux", "new-session", "-d", "-s", TMUX_SESSION, cmd],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return {"ok": False, "error": f"tmux spawn failed: {proc.stderr[:200]}"}
    return {"ok": True, "session": TMUX_SESSION, "log_path": str(log_path)}


def kill_tmux_session() -> bool:
    if not _tmux_session_exists():
        return True
    p = subprocess.run(["tmux", "kill-session", "-t", TMUX_SESSION],
                       capture_output=True, text=True)
    return p.returncode == 0


# ── Entry: invoked by tmux session ─────────────────────────

async def _run_inside_tmux(run_id: int, request_ids: list[int], log_path: str) -> int:
    """tmux 안에서 실행되는 메인 흐름 — bot 정지 + dispatch + bot 재가동."""
    # bot 정지는 호출자(admin run endpoint) 가 이미 했어야 함.
    # 안전하게 다시 한 번 확인 + 정지 + 재가동 대상 기록.
    print(f"[dev_runner] run #{run_id} starting — {len(request_ids)} requests", flush=True)
    print(f"[dev_runner] log: {log_path}", flush=True)

    stopped = _stop_all_bots()
    if stopped:
        print(f"[dev_runner] stopped community bots: {stopped}", flush=True)

    try:
        from community.core import dev_dispatch, dev_agent
        run = dev_agent.get_run(run_id)
        if not run:
            print(f"[dev_runner] ❌ run #{run_id} not found", flush=True)
            return 2
        branch_name = run["branch_name"]

        result = await dev_dispatch.run_batch(
            run_id=run_id,
            branch_name=branch_name,
            request_ids=request_ids,
            log_path=log_path,
        )
        if result.get("ok"):
            print(f"[dev_runner] ✓ run #{run_id} done — "
                  f"completed={result.get('completed')}, failed={result.get('failed')}, "
                  f"PR={result.get('pr_url') or 'none'}", flush=True)
        else:
            print(f"[dev_runner] ❌ run #{run_id} failed: {result.get('error')}", flush=True)
    finally:
        if stopped:
            print(f"[dev_runner] restarting bots: {stopped}", flush=True)
            _restart_bots(stopped)
        print(f"[dev_runner] tmux session exiting", flush=True)
    return 0


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", type=int, required=True)
    p.add_argument("--requests", type=str, required=True,
                   help="comma-separated request ids")
    p.add_argument("--log-path", type=str, required=True)
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    request_ids = [int(x) for x in args.requests.split(",") if x.strip()]
    return asyncio.run(_run_inside_tmux(args.run_id, request_ids, args.log_path))


# ── public API for admin endpoint ──────────────────────────

def start_dev_run(request_ids: list[int], started_by: str) -> dict:
    """admin endpoint 가 호출 — bot 정지는 안 하고 (tmux 안에서 함) dev_runs row 만 만들고
    tmux 세션 spawn.

    반환: {ok, run_id, branch, log_path} 또는 {ok=False, error}.
    """
    if _tmux_session_exists():
        return {"ok": False, "error": "Another dev run is already in progress"}

    from community.core import dev_agent, dev_dispatch
    if not request_ids:
        return {"ok": False, "error": "no request_ids provided"}

    branch_name = dev_dispatch._make_branch_name()
    log_path = _log_path_for(0)  # run_id 모르니까 임시. 아래에서 갱신

    # run row 생성
    run_id = dev_agent.create_run(branch_name, request_ids, started_by, str(log_path))

    # log_path 를 run_id 반영해서 갱신
    real_log = DEV_RUNS_DIR / f"run-{run_id}-{_ts()}.log"
    real_log.parent.mkdir(parents=True, exist_ok=True)
    dev_agent.update_run_status(run_id, "starting", log_path=str(real_log))

    # queue 마킹
    dev_agent.mark_queued_batch(request_ids, run_id, branch_name)

    # tmux spawn
    spawn = spawn_tmux_run(run_id, request_ids, real_log)
    if not spawn.get("ok"):
        dev_agent.update_run_status(run_id, "failed", error=spawn.get("error", "tmux spawn"))
        return {"ok": False, "error": spawn.get("error", "tmux spawn failed"), "run_id": run_id}

    return {
        "ok": True,
        "run_id": run_id,
        "branch": branch_name,
        "log_path": str(real_log),
        "session": TMUX_SESSION,
    }


def tail_log(log_path: str, since_byte: int = 0, max_bytes: int = 32_000) -> dict:
    """admin UI 가 폴링하는 helper — log 파일을 since_byte 부터 읽어서 새 chunk 반환.

    반환: {bytes_read: int, next_byte: int, content: str, finished: bool}.
    finished: tmux 세션이 죽었으면 True.
    """
    p = Path(log_path)
    if not p.exists():
        return {"bytes_read": 0, "next_byte": 0, "content": "", "finished": False}
    try:
        size = p.stat().st_size
    except OSError:
        return {"bytes_read": 0, "next_byte": since_byte, "content": "", "finished": False}
    if since_byte >= size:
        finished = not _tmux_session_exists()
        return {"bytes_read": 0, "next_byte": size, "content": "", "finished": finished}
    end = min(size, since_byte + max_bytes)
    with open(p, "rb") as f:
        f.seek(since_byte)
        chunk = f.read(end - since_byte)
    try:
        text = chunk.decode("utf-8", errors="replace")
    except Exception:
        text = ""
    finished = (end >= size) and (not _tmux_session_exists())
    return {
        "bytes_read": end - since_byte,
        "next_byte": end,
        "content": text,
        "finished": finished,
    }


__all__ = [
    "TMUX_SESSION", "DEV_RUNS_DIR",
    "start_dev_run", "spawn_tmux_run", "kill_tmux_session", "tail_log",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
