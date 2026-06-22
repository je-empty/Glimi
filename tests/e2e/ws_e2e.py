# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Glimi Workspace TRUE WEB E2E QA harness — drive the REAL served server over HTTP.

This is the Workspace analogue of the Community QA that drives a real *served*
instance, NOT the in-process headless runner (``tests.e2e.ws_runner``, which calls
``driver.drive_workspace`` directly and never exercises the web stack). Here we:

  1. **start the REAL server** — ``python -m workspace.run --server`` as a
     subprocess (echo for the free $0 self-test, claude_cli for the real run);
  2. **drive it ENTIRELY over HTTP** — POST /api/workspaces (round 1 runs
     synchronously inside the create call) → POST /w/{id}/auto/start (rounds 2..
     stream on a daemon thread) → poll GET /w/{id}/auto/status until done;
  3. **build the verdict from the SERVED API** — GET /w/{id}/api/snapshot +
     GET /w/{id}/chat/channels + GET /w/{id}/chat/history per channel, translate
     the served row shape (``speaker_id``/``text``) into the verdict's shape
     (``speaker``/``message``), synthesize the ``drive_result`` (NOT exposed over
     HTTP) from the coordinator's per-round messages in dm-coordinator, and reuse
     ALL of :func:`tests.e2e.ws_verdict.judge_snapshot`'s criteria;
  4. **leave the server SERVING** (``--keep-serving``) so the owner can watch the
     run externally via a tunnel — the dashboard at ``/w/{id}``.

Because the kernel store is IN-MEMORY (no SQLite, no disk), every byte of verdict
evidence must come from the HTTP endpoints while the server is up — which is also
exactly why "leave it serving" is the natural end state.

Usage::

    # FREE self-test ($0): full web round-trip on echo, server torn down after
    GLIMI_LLM_BACKEND=echo python -m tests.e2e.ws_e2e --rounds 2 --goal "에코 자가검증"

    # REAL run (COST) via the launcher — leaves the server up for a tunnel
    ./scripts/ws_e2e.sh --rounds 3 --keep-serving

Flags: --goal --rounds --backend --port --keep-serving (see ``--help``).
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "tests" / "e2e" / "results"

# Channels the verdict cares about (the authoritative inventory comes from the
# served /chat/channels, but this is the floor we always try to pull even if a
# channel happens to be empty in a given run).
KEY_CHANNELS = [
    "dm-coordinator", "dm-researcher", "dm-builder", "dm-critic",
    "group-team",
    "internal-researcher-critic", "internal-builder-researcher", "internal-owner",
]

# Same default goal/context/backlog as the headless runner so a web run and a
# headless run are comparable apples-to-apples.
DEFAULT_GOAL = "작은 오픈소스 CLI 도구의 첫 공개 런칭 기획"
DEFAULT_CONTEXT = (
    "정직한 런칭 기조. 과장 없이 실제로 동작하는 것만 보여준다. "
    "깨끗한 환경에서 5분 안에 따라할 수 있는 퀵스타트가 핵심."
)
DEFAULT_BACKLOG = [
    "퀵스타트가 깨끗한 환경에서 실제로 통과하는지 검증",
    "README 의 핵심 차별점 한 문장 확정",
    "런칭 데모(짧은 영상/gif) 시나리오",
    "런칭일과 담당까지 박은 실행 계획",
]

OWNER_NAME = "오너"


# ── tiny stdlib HTTP client (no httpx dependency) ───────────────────────────────

class HttpError(Exception):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} for {url}: {body[:200]}")
        self.status = status
        self.body = body
        self.url = url


def _http(method: str, url: str, *, body: dict | None = None,
          timeout: float = 30.0) -> dict:
    """One JSON request → parsed JSON dict. Raises HttpError on non-2xx."""
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8")
        except Exception:
            pass
        raise HttpError(e.code, raw, url) from None
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"_raw": raw}


def _get(base: str, path: str, *, timeout: float = 30.0) -> dict:
    return _http("GET", base + path, timeout=timeout)


def _post(base: str, path: str, *, body: dict | None = None,
          timeout: float = 30.0) -> dict:
    return _http("POST", base + path, body=body or {}, timeout=timeout)


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ── server lifecycle ────────────────────────────────────────────────────────────

def _launch_server(host: str, port: int, backend: str, data_dir: Path,
                   log_fh) -> subprocess.Popen:
    """Spawn the REAL workspace server as a subprocess.

    The backend is captured by the server AT IMPORT (server.py:_USER_BACKEND), so
    GLIMI_LLM_BACKEND MUST be in the child env before it starts — exactly what we
    do here. GLIMI_DEMO_ONLY is deliberately left UNSET so create works.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([
        str(PROJECT_ROOT / "glimi-core"),
        str(PROJECT_ROOT / "glimi-community"),
        str(PROJECT_ROOT / "glimi-workspace"),
        str(PROJECT_ROOT),
        env.get("PYTHONPATH", ""),
    ]).rstrip(os.pathsep)
    env["GLIMI_LLM_BACKEND"] = backend
    env["GLIMI_DATA_DIR"] = str(data_dir)
    env["GLIMI_NO_BROWSER"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    env.pop("GLIMI_DEMO_ONLY", None)  # must allow create
    env.setdefault("GLIMI_LANG", "en")

    py = str(PROJECT_ROOT / ".venv" / "bin" / "python")
    if not Path(py).exists():
        py = sys.executable
    cmd = [py, "-u", "-m", "workspace.run", "--server",
           "--host", host, "--port", str(port)]
    print(f"[ws_e2e] launch: {' '.join(cmd)} (backend={backend})")
    proc = subprocess.Popen(
        cmd, cwd=str(PROJECT_ROOT), env=env,
        stdout=log_fh, stderr=subprocess.STDOUT,
    )
    return proc


def _wait_ready(base: str, proc: subprocess.Popen, timeout: float = 40.0) -> None:
    """Block until GET / returns 200 (the home page), or raise on timeout/crash."""
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"server process exited early (code {proc.returncode}) — see log")
        try:
            req = urllib.request.Request(base + "/", method="GET")
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                if resp.status == 200:
                    return
        except Exception as e:  # noqa: BLE001 — connection refused while booting
            last_err = e
        time.sleep(0.5)
    raise TimeoutError(f"server not ready within {timeout}s ({last_err})")


def _stop_server(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=10)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# ── served-data harvesting → verdict snapshot ───────────────────────────────────

def _harvest_channel(base: str, ws_id: str, channel: str,
                     timeout: float = 30.0) -> list[dict]:
    """Pull a channel's FULL message list over HTTP, paging via before_id, and
    translate each served row into the verdict's expected shape.

    Served row: {id, speaker_id, display_name, is_user, text, timestamp, ...}.
    Verdict row: {speaker, message, id, timestamp, is_user}.
    limit caps at 200 per call → page backward with the smallest id of the window.
    """
    out: list[dict] = []
    before_id = 0
    seen: set[int] = set()
    while True:
        path = f"/w/{ws_id}/chat/history?channel={channel}&limit=200"
        if before_id:
            path += f"&before_id={before_id}"
        try:
            resp = _get(base, path, timeout=timeout)
        except HttpError:
            break
        rows = resp.get("messages") or []
        if not rows:
            break
        page = []
        for r in rows:
            rid = r.get("id")
            if rid in seen:
                continue
            seen.add(rid)
            page.append({
                "speaker": r.get("speaker_id") or "",
                "message": r.get("text") or "",
                "id": rid,
                "timestamp": r.get("timestamp") or "",
                "is_user": bool(r.get("is_user")),
            })
        if not page:
            break
        out = page + out  # older page goes in front (rows are ASC)
        ids = [r["id"] for r in page if r.get("id") is not None]
        if len(rows) < 200 or not ids:
            break
        before_id = min(ids)  # page backward
    out.sort(key=lambda m: (m.get("id") or 0))
    return out


def _synthesize_drive_result(channels: dict, owner_id: str,
                             rounds_run: int, reason: str | None) -> dict:
    """Reconstruct the driver's internal drive_result from served channels.

    /auto/start returns only {ok,running,max_rounds}; the full
    {deliverables,last_deliverable,done,stopped_reason} dict is internal. We
    recover it: the coordinator's gated synthesis messages in dm-coordinator ARE
    the per-round deliverables (last = last_deliverable); done = reason=="done";
    stopped_reason + rounds come from /auto/status.
    """
    coord_msgs = [m.get("message", "") for m in channels.get("dm-coordinator", [])
                  if m.get("speaker") == "coordinator"]
    deliverables = [c for c in coord_msgs if (c or "").strip()]
    return {
        "rounds": int(rounds_run),
        "deliverables": deliverables,
        "done": (reason == "done"),
        "stopped_reason": reason,
        "last_deliverable": deliverables[-1] if deliverables else "",
    }


def _build_snapshot(base: str, ws_id: str, *, backend: str, goal: str,
                    rounds_requested: int, status: dict, snapshot_payload: dict,
                    usage: dict, channel_names: list[str],
                    elapsed: float, error: str | None) -> dict:
    """Assemble the flat snapshot dict that ws_verdict.judge_snapshot consumes,
    entirely from the SERVED endpoints."""
    # owner_id: prefer the snapshot's owner_ids[0]; else infer from is_user rows.
    owner_ids = snapshot_payload.get("owner_ids") or []
    owner_id = owner_ids[0] if owner_ids else "owner"

    channels: dict[str, list[dict]] = {}
    pull = list(dict.fromkeys(list(channel_names) + KEY_CHANNELS))
    for ch in pull:
        msgs = _harvest_channel(base, ws_id, ch)
        if msgs:
            channels[ch] = msgs
            if owner_id == "owner":
                for m in msgs:  # refine owner_id from the served is_user flag
                    if m.get("is_user") and m.get("speaker"):
                        owner_id = m["speaker"]
                        break

    reason = status.get("reason")
    rounds_run = int(status.get("rounds_run") or 0)
    drive_result = _synthesize_drive_result(channels, owner_id, rounds_run, reason)

    return {
        "run_id": f"ws-e2e-{ws_id}",
        "backend": backend,
        "goal": goal,
        "owner_id": owner_id,
        "owner_name": snapshot_payload.get("owner_name") or OWNER_NAME,
        "channels": channels,
        "relationships": snapshot_payload.get("relationships") or [],
        "agents": snapshot_payload.get("agents") or [],
        # Round 1 ran inside create; auto drives the rest. Use the verifiable
        # coordinator-deliverable count as the round floor (more honest than
        # blindly trusting max_rounds when an LLM finished early).
        "rounds_requested": max(rounds_requested,
                                len(drive_result["deliverables"])),
        "drive_result": drive_result,
        # Raw usage rows are in-memory-only (unreachable over HTTP) → []; the
        # verdict's budget check then no-ops on rows and relies on stopped_reason.
        # The /api/usage aggregate is folded into metrics for observability.
        "usage": [],
        "usage_aggregate": usage,
        "elapsed_seconds": round(elapsed, 1),
        "error": error,
    }


# ── the run ──────────────────────────────────────────────────────────────────

def run(*, goal: str, context: str, backlog: list, rounds: int, backend: str,
        host: str, port: int, keep_serving: bool, poll_interval: float,
        wall_clock_cap: float) -> dict:
    """Full web E2E: start server → create over HTTP → auto-run → poll →
    harvest served data → judge → write artifacts. Returns the verdict dict."""
    from tests.e2e import ws_verdict

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"ws-e2e-{ts}"
    base = f"http://127.0.0.1:{port}" if host in ("0.0.0.0", "") else f"http://{host}:{port}"
    data_dir = RESULTS_DIR / "ws-e2e-data" / ts
    data_dir.mkdir(parents=True, exist_ok=True)
    server_log = RESULTS_DIR / f"{run_id}-server.log"

    print("=" * 64)
    print("  Glimi Workspace — TRUE WEB E2E (real server, HTTP-driven)")
    print("=" * 64)
    print(f"  run_id   : {run_id}")
    print(f"  backend  : {backend}")
    print(f"  rounds   : {rounds}")
    print(f"  goal     : {goal}")
    print(f"  bind     : {host}:{port}   (probe {base})")
    print(f"  keep     : {keep_serving}")
    print("=" * 64 + "\n")

    start = time.time()
    error: str | None = None
    ws_id = ""
    status: dict = {}
    snapshot_payload: dict = {}
    usage: dict = {}
    channel_names: list[str] = []

    log_fh = open(server_log, "w", encoding="utf-8")
    proc = _launch_server(host, port, backend, data_dir, log_fh)
    try:
        # (a) wait for the home page.
        _wait_ready(base, proc, timeout=40.0)
        print(f"[ws_e2e] server ready at {base}")

        # (b) create the workspace over HTTP — round 1 runs SYNCHRONOUSLY inside
        # this call (instant on echo, MINUTES on claude_cli → long timeout).
        print("[ws_e2e] POST /api/workspaces (round 1 runs synchronously) ...")
        card = _post(base, "/api/workspaces",
                     body={"name": OWNER_NAME, "goal": goal}, timeout=900.0)
        ws_id = str(card.get("id") or "")
        if not ws_id:
            raise RuntimeError(f"create returned no id: {card}")
        print(f"[ws_e2e] created workspace id={ws_id} (agents={card.get('agents')}, "
              f"channels={card.get('channels')})")

        # (c) enable the autonomous loop (rounds 2.. on a daemon thread).
        auto = _post(base, f"/w/{ws_id}/auto/start",
                     body={"context": context, "backlog": backlog,
                           "max_rounds": rounds}, timeout=60.0)
        print(f"[ws_e2e] auto/start → {auto}")

        # (d) poll status until running==false or the wall-clock cap trips.
        deadline = time.time() + wall_clock_cap
        last_rounds = -1
        while True:
            status = _get(base, f"/w/{ws_id}/auto/status", timeout=30.0)
            rr = status.get("rounds_run")
            if rr != last_rounds:
                print(f"[ws_e2e] status: running={status.get('running')} "
                      f"rounds_run={rr} reason={status.get('reason')}")
                last_rounds = rr
            if not status.get("running"):
                break
            if time.time() > deadline:
                print(f"[ws_e2e] WALL-CLOCK CAP {wall_clock_cap}s hit — stopping run")
                try:
                    _post(base, f"/w/{ws_id}/auto/stop", timeout=30.0)
                except Exception:
                    pass
                error = f"wall_clock_cap {wall_clock_cap}s exceeded"
                status = _get(base, f"/w/{ws_id}/auto/status", timeout=30.0)
                break
            time.sleep(poll_interval)
        print(f"[ws_e2e] auto-run done: reason={status.get('reason')} "
              f"rounds_run={status.get('rounds_run')}")

        # (e) harvest the SERVED data for the verdict.
        snapshot_payload = _get(base, f"/w/{ws_id}/api/snapshot", timeout=60.0)
        try:
            chans = _get(base, f"/w/{ws_id}/chat/channels", timeout=30.0)
            channel_names = [c.get("channel") for c in chans.get("channels", [])
                             if c.get("channel")]
        except Exception:
            channel_names = []
        try:
            usage = _get(base, f"/w/{ws_id}/api/usage", timeout=30.0)
        except Exception:
            usage = {}

    except Exception as exc:  # capture; never crash the harness
        import traceback
        error = f"{type(exc).__name__}: {exc}"
        print(traceback.format_exc())
    finally:
        # Flush the server's own log so it's readable even while serving.
        try:
            log_fh.flush()
        except Exception:
            pass

    elapsed = time.time() - start

    # (f) assemble + judge.
    snap = _build_snapshot(
        base, ws_id, backend=backend, goal=goal, rounds_requested=rounds,
        status=status, snapshot_payload=snapshot_payload, usage=usage,
        channel_names=channel_names, elapsed=elapsed, error=error,
    ) if ws_id else {
        "backend": backend, "goal": goal, "channels": {}, "error": error,
        "drive_result": {}, "usage": [], "elapsed_seconds": round(elapsed, 1),
        "owner_id": "owner", "rounds_requested": rounds,
    }

    # Persist the assembled snapshot (so a failure is debuggable + the verdict
    # path mirrors the headless ws-store-*.json artifact).
    store_path = RESULTS_DIR / f"ws-e2e-store-{ts}.json"
    store_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2),
                          encoding="utf-8")

    verdict = ws_verdict.judge_snapshot(snap, run_id=run_id)
    verdict["ws_id"] = ws_id
    verdict["base_url"] = base
    verdict["served"] = True
    verdict["error"] = error
    verdict["usage_aggregate"] = snap.get("usage_aggregate", {})
    verdict["server_pid"] = proc.pid
    verdict["server_log"] = str(server_log)
    verdict["store_snapshot"] = str(store_path)
    verdict["keep_serving"] = keep_serving

    out_path = RESULTS_DIR / f"{run_id}.json"
    out_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    print("\n" + "=" * 64)
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    print("=" * 64)
    status_s = verdict.get("status", "?")
    emoji = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(status_s, "?")
    print(f"\n{emoji} {status_s}")
    print(f"[ws_e2e] verdict: {out_path}")
    print(f"[ws_e2e] served snapshot: {store_path}")
    print(f"[ws_e2e] server log: {server_log}")

    if keep_serving and ws_id and proc.poll() is None:
        print("\n" + "─" * 64)
        print(f"  SERVER LEFT RUNNING for external watching (tunnel this):")
        print(f"    PID  : {proc.pid}")
        print(f"    bind : {host}:{port}")
        print(f"    watch: {base}/w/{ws_id}   (dashboard / chat replay)")
        print(f"    home : {base}/")
        print(f"  stop it:  kill {proc.pid}")
        print("─" * 64)
        # Detach: do NOT close the log fh / kill the server.
    else:
        _stop_server(proc)
        try:
            log_fh.close()
        except Exception:
            pass
        print("[ws_e2e] server torn down.")

    return verdict


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Glimi Workspace TRUE WEB E2E QA (drives the real served server over HTTP)")
    ap.add_argument("--goal", default=DEFAULT_GOAL, help="owner's project goal to drive")
    ap.add_argument("--context", default=None,
                    help="owner context/brief (default keeps the tuned launch brief for the default goal)")
    ap.add_argument("--rounds", type=int, default=3,
                    help="auto max_rounds for /auto/start (clamped 1..10 server-side; default 3)")
    ap.add_argument("--backend", default=None,
                    help="LLM backend (else env GLIMI_LLM_BACKEND → echo). echo=$0 self-test, claude_cli=real")
    ap.add_argument("--port", type=int, default=0,
                    help="server port (default: a free ephemeral port)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind host (use 0.0.0.0 with --keep-serving to expose for a tunnel)")
    ap.add_argument("--keep-serving", action="store_true",
                    help="leave the server running after the run (for external watching via a tunnel)")
    ap.add_argument("--poll-interval", type=float, default=3.0,
                    help="seconds between /auto/status polls (default 3)")
    ap.add_argument("--cap", type=float, default=1800.0,
                    help="wall-clock cap in seconds for the auto-run poll loop (default 1800)")
    args = ap.parse_args(argv)

    backend = (args.backend or os.environ.get("GLIMI_LLM_BACKEND") or "echo").strip() or "echo"
    port = args.port or _free_port()

    # Default goal keeps its tuned context/backlog; a custom goal drives from the
    # goal (+ optional --context) alone — same policy as the headless runner.
    if args.goal == DEFAULT_GOAL:
        context = args.context if args.context is not None else DEFAULT_CONTEXT
        backlog = list(DEFAULT_BACKLOG)
    else:
        context = args.context or ""
        backlog = []

    verdict = run(
        goal=args.goal, context=context, backlog=backlog,
        rounds=max(1, min(args.rounds, 10)), backend=backend,
        host=args.host, port=port, keep_serving=args.keep_serving,
        poll_interval=max(0.5, args.poll_interval), wall_clock_cap=max(30.0, args.cap),
    )
    status = verdict.get("status", "?")
    return 0 if status in ("PASS", "WARN") else 1


if __name__ == "__main__":
    sys.exit(main())
