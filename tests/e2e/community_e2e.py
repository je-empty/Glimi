# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Glimi Community TRUE WEB E2E QA harness — drive the REAL served server over HTTP+WS.

This is the Community analogue of :mod:`tests.e2e.ws_e2e` (the Workspace web E2E).
Where ws_e2e drives an autonomous coordinator loop over HTTP, this drives the
human-facing product: **an autonomous OWNER agent opens the web chat and, from the
START (onboarding), chats with the manager (유나) + friend-maker (하나) + friends —
turn by turn, deciding each move itself.** It is a TRUE web E2E — it exercises the
whole web stack, not an in-process headless call:

  1. **start the REAL server** — ``python -m community.platform`` as a subprocess,
     in an ISOLATED ``GLIMI_DATA_DIR`` + ``GLIMI_COMMUNITIES_DIR`` (temp dirs, so
     it never touches the owner's real communities), with ``GLIMI_ADMIN_PASSWORD``
     set (auto-bootstraps the admin) and ``GLIMI_LLM_BACKEND`` from env (echo for
     the free $0 self-test, claude_cli for the real run). Wait for ``/healthz``;

  2. **seed a WRITABLE community** — two modes:
     - **fresh** (default, for ``--owner-agent``): owner + the default manager
       (유나) + creator/friend-maker (하나) ONLY — NO pre-seeded friends. This is
       the "from the start" state the owner agent onboards from (it greets 유나,
       asks 하나 to make a friend, then chats). Seeded by :func:`_seed_fresh`;
     - **demo mockup** (``--scripted`` legacy path): reuse
       ``scripts.seed_demo_mockup.seed("<cid>")`` (owner + 7 friend personas).
     Either way ``read_only=false`` is flipped so the WS write path is not blocked.
     Done in a child subprocess sharing the SAME isolated env BEFORE the server
     starts, so the server picks the community up at boot;

  3. **drive a QA scenario over the chat WebSocket** — log in (POST /login → session
     cookie), connect to ``/community/{cid}/chat/ws`` as the owner, then EITHER
     (default ``--owner-agent``) let an autonomous owner agent
     (:mod:`tests.e2e.community_owner_agent`) decide each turn's channel + message
     from the live snapshot and drive onboarding→friends→chat, OR (``--scripted``)
     replay the fixed ``OWNER_TURNS`` into 1-2 friend DMs. Each owner turn's reply
     is collected from the WS ``text`` frames (and reconciled against ``/chat/history``);

  4. **build the verdict from the SERVED API** — GET /chat/channels + /chat/history
     per driven DM + /api/usage, assemble the flat snapshot
     :func:`tests.e2e.community_verdict.judge_snapshot` consumes, and judge: did each
     driven DM get a non-empty friend reply, no meta leaks, no errors;

  5. **leave the server SERVING** (``--keep-serving``) so a human can WATCH the run
     live in a browser at ``/community/{cid}/chat`` (tunnel it). Mirrors ws_e2e's
     keep-serving fix exactly — BLOCK on ``proc.wait()`` so the tmux process group
     is not reaped on return (the bug that killed the watch URL).

WS send-frame (the core driving mechanism, learned from the chat.py WS handler):
    → ``{"type": "text", "channel": "dm-<agent_id>", "agent": "<agent_id>", "text": "..."}``
reply frames the server emits back:
    ← ``{"type": "typing",  "channel", "agent_id", "speaker", "on": bool}``
    ← ``{"type": "text",    "channel", "id", "agent_id", "speaker", "text"}``  (the reply)
    ← ``{"type": "error",   "channel", "error", "message"}``

Usage::

    # FREE self-test ($0): autonomous owner-agent loop on echo, torn down after
    GLIMI_LLM_BACKEND=echo python -m tests.e2e.community_e2e --owner-agent --rounds 2 --port 8232

    # REAL run (COST) — owner agent drives onboarding→friends live; tunnel to watch
    GLIMI_LLM_BACKEND=claude_cli python -m tests.e2e.community_e2e --owner-agent \
        --rounds 6 --keep-serving --host 0.0.0.0

    # Legacy scripted path (fixed owner turns into seeded friend DMs)
    GLIMI_LLM_BACKEND=echo python -m tests.e2e.community_e2e --scripted --rounds 1 --port 8231

Flags: --owner-agent/--scripted --rounds --friends --goal --backend --port --host
       --keep-serving --report --write-baseline --wall-cap (see ``--help``).

SAFETY: isolated temp dirs + a non-standard default port (8230). NEVER touches the
owner's real communities, je-empty, or any shared resource. Does not start tunnels.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

# Korean log lines must survive a non-TTY stdout (the tmux/pipe case defaults to
# ASCII → UnicodeEncodeError on the first 한글 line). Force UTF-8 on our own
# streams; the child server inherits PYTHONIOENCODING via _child_env.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "tests" / "e2e" / "results"

DEFAULT_PORT = 8230  # non-standard (8000 demo / 8100 internal / 8800 WS are taken)
ADMIN_PASSWORD = "e2e-admin-pw"   # local throwaway, isolated DB — never a real secret
COMMUNITY_ID = "qa-e2e"
OWNER_NAME = "사용자"

DEFAULT_GOAL = "오너가 AI 친구 몇 명과 DM 으로 안부·질문·후속 대화를 나눈다"
DEFAULT_CONTEXT = "친구마다 성격·말투가 다르고, 사람 친구처럼 자연스럽게 반응해야 한다."

# The realistic mini-conversation the owner sends per DM, per round. Round k sends
# OWNER_TURNS[k]; a friend reply is awaited after each. Kept short + natural.
OWNER_TURNS = [
    "오랜만이야! 요즘 어떻게 지내?",
    "나 요즘 좀 바빴어 ㅠㅠ 너는 주말에 뭐 했어?",
    "오 좋다 ㅋㅋ 다음에 같이 보자",
]


# ── tiny stdlib HTTP client (no httpx dependency) ───────────────────────────────

class HttpError(Exception):
    def __init__(self, status: int, body: str, url: str):
        super().__init__(f"HTTP {status} for {url}: {body[:200]}")
        self.status = status
        self.body = body
        self.url = url


def _http(method: str, url: str, *, body: dict | None = None,
          headers: dict | None = None, timeout: float = 30.0,
          want_headers: bool = False):
    data = None
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            resp_headers = dict(resp.getheaders())
            status = resp.status
    except urllib.error.HTTPError as e:
        raw = ""
        try:
            raw = e.read().decode("utf-8")
        except Exception:
            pass
        raise HttpError(e.code, raw, url) from None
    parsed: dict = {}
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"_raw": raw}
    if want_headers:
        return parsed, resp_headers, status
    return parsed


def _get(base: str, path: str, *, cookie: str = "", timeout: float = 30.0) -> dict:
    headers = {"Cookie": cookie} if cookie else None
    return _http("GET", base + path, headers=headers, timeout=timeout)


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


# ── server + seed lifecycle ─────────────────────────────────────────────────────

def _child_env(backend: str, data_dir: Path, comm_dir: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([
        str(PROJECT_ROOT / "glimi-core"),
        str(PROJECT_ROOT / "glimi-community"),
        str(PROJECT_ROOT / "glimi-workspace"),
        str(PROJECT_ROOT),
        env.get("PYTHONPATH", ""),
    ]).rstrip(os.pathsep)
    env["GLIMI_LLM_BACKEND"] = backend
    env["GLIMI_DATA_DIR"] = str(data_dir)            # isolates platform.db + secret + demo marker
    env["GLIMI_COMMUNITIES_DIR"] = str(comm_dir)     # isolates communities/ + registry.toml
    env["GLIMI_ADMIN_PASSWORD"] = ADMIN_PASSWORD     # auto-bootstrap admin (non-interactive)
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"  # 한글 로그가 ASCII stdout 에서 안 깨지게
    env.setdefault("GLIMI_LANG", "ko")
    return env


_SEED_SNIPPET = """
import sys
from scripts.seed_demo_mockup import seed
from community.platform.demo_seed import _write_registry_block
from community.community import _ensure_registry
cid = sys.argv[1]
seed(cid)                                  # owner + 9 friend personas + DM scripts
_ensure_registry(cid)                      # ensure a [community.<cid>] block exists
# Flip read_only=false so the chat WS write path is NOT blocked (seed marks demos
# read_only; an E2E that posts owner messages needs a writable community).
_write_registry_block(cid, "QA E2E", "owner<->friends web E2E", language="ko", read_only=False)
print("[seed] '%s' seeded writable (read_only=false)" % cid)
"""


# FRESH seed (the "from the start" state for the owner agent): owner + the default
# manager (유나) + creator/friend-maker (하나) + their DM channels — NO friend
# personas. The owner agent onboards from here (greets 유나, asks 하나 for a friend,
# then chats). Mirrors scripts.seed_demo_mockup's DB shape (init_db, users, agents,
# dm-<agent_id> channels) but omits the persona block. read_only=false so the WS
# write path is open.
_FRESH_SEED_SNIPPET = """
import sys
from datetime import datetime
from community import community, db
from community.platform.demo_seed import _write_registry_block
from community.community import _ensure_registry

cid = sys.argv[1]
community.set_community(cid)
cdir = community.get_community_dir()
cdir.mkdir(parents=True, exist_ok=True)
for suffix in ("", "-shm", "-wal"):
    p = cdir / ("community.db" + suffix)
    if p.exists():
        p.unlink()
(cdir / "logs").mkdir(parents=True, exist_ok=True)
(cdir / "logs" / "system.log").write_text("[seed] fresh (mgr+creator only)\\n")
envf = cdir / ".env"
if not envf.exists():
    envf.write_text("DISCORD_BOT_TOKEN=fresh-no-token\\n")

db.init_db()
conn = db.get_conn()
conn.execute(
    "INSERT INTO users (id, name, age, mbti, personality) VALUES (?,?,?,?,?)",
    ("owner", "사용자", 29, "INTJ", '{"gender":"남자","nickname":"사용자"}'),
)
conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('active_user_id','owner')")

def _agent(aid, atype, name, age, gender, mbti, bg):
    conn.execute(
        "INSERT INTO agents (id,type,name,status,current_emotion,emotion_intensity,"
        "birth_year,age,gender,mbti,background,profile_image_filename,version,created_at)"
        " VALUES (?,?,?,'active','평온',5,?,?,?,?,?,?,1,?)",
        (aid, atype, name, 2026 - age, age, gender, mbti, bg, aid + ".png",
         datetime.now().isoformat()),
    )

_agent("agent-mgr-001", "mgr", "유나", 24, "여자", "ENFJ",
       "Glimi 커뮤니티 매니저. 친근하고 정리 잘하는 누나 같은 존재.")
_agent("agent-creator-001", "creator", "하나", 22, "여자", "INFP",
       "신규 멤버 튜토리얼 + 친구 디자이너. 다정하고 창의적.")

def _channel(name, parts):
    conn.execute(
        "INSERT INTO channels (channel,participants,status,max_turns,created_at)"
        " VALUES (?,?,?,?,?)",
        (name, __import__("json").dumps(parts, ensure_ascii=False), "idle", 0,
         datetime.now().isoformat()),
    )

_channel("dm-agent-mgr-001", ["agent-mgr-001"])
_channel("dm-agent-creator-001", ["agent-creator-001"])
conn.commit()
conn.close()

_ensure_registry(cid)
_write_registry_block(cid, "QA E2E (fresh)",
                      "owner onboards manager+creator from scratch (web E2E)",
                      language="ko", read_only=False)
print("[seed] '%s' seeded FRESH (owner + 유나 + 하나, read_only=false)" % cid)
"""


def _seed_community(env: dict, cid: str, log_fh, *, fresh: bool = False) -> None:
    """Seed a writable community in a child subprocess sharing the isolated env.

    Runs BEFORE the server starts so the community + registry block exist at boot.

    - ``fresh=True`` (owner-agent default): owner + manager (유나) + creator (하나)
      ONLY — the "from the start" state the owner agent onboards from.
    - ``fresh=False`` (scripted legacy): the rich demo mockup (7 friend personas).

    Either way read_only=false is flipped (the demo seeder marks demos read_only,
    which would block the WS write path)."""
    py = _python()
    snippet = _FRESH_SEED_SNIPPET if fresh else _SEED_SNIPPET
    label = "fresh (mgr+creator only)" if fresh else "demo mockup (7 friends)"
    cmd = [py, "-c", snippet, cid]
    print(f"[community_e2e] seed: {cid} — {label} (writable) ...")
    res = subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    log_fh.write(res.stdout or "")
    log_fh.flush()
    if res.returncode != 0:
        raise RuntimeError(f"seed failed (code {res.returncode}):\n{res.stdout[-2000:]}")


def _python() -> str:
    py = str(PROJECT_ROOT / ".venv" / "bin" / "python")
    return py if Path(py).exists() else sys.executable


def _launch_server(host: str, port: int, env: dict, log_fh) -> subprocess.Popen:
    cmd = [_python(), "-u", "-m", "community.platform",
           "--host", host, "--port", str(port)]
    print(f"[community_e2e] launch: {' '.join(cmd)} (backend={env.get('GLIMI_LLM_BACKEND')})")
    return subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), env=env,
                            stdout=log_fh, stderr=subprocess.STDOUT)


def _wait_ready(base: str, proc: subprocess.Popen, timeout: float = 45.0) -> None:
    """Block until GET /healthz returns 200, or raise on timeout/crash."""
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(
                f"server process exited early (code {proc.returncode}) — see log")
        try:
            req = urllib.request.Request(base + "/healthz", method="GET")
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


def _login(base: str) -> str:
    """POST /login (form) as admin → the session cookie string for WS + reads.

    urllib follows the 303 redirect; we capture the Set-Cookie off the FIRST
    response, so we issue a manual no-redirect request to read the header."""
    import http.cookiejar

    from urllib.parse import urlencode

    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    body = urlencode({"username": "admin", "password": ADMIN_PASSWORD, "next": "/"}).encode()
    req = urllib.request.Request(base + "/login", data=body, method="POST",
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    opener.open(req, timeout=20.0)
    cookies = {c.name: c.value for c in jar}
    if "glimi_session" not in cookies:
        raise RuntimeError(f"login produced no session cookie (got {list(cookies)})")
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


# ── owner-agent driving (the DEFAULT drive) ────────────────────────────────────

# Human labels for the manager / creator rooms so the owner agent picks a room by
# who's in it, not by an opaque id. Friend DMs get a "<name> (친구) DM" label built
# from the served channel list.
_MGR_CHANNEL = "dm-agent-mgr-001"
_CREATOR_CHANNEL = "dm-agent-creator-001"


def _owner_snapshot(base: str, cid: str, cookie: str, *, round_idx: int,
                    backend: str, recent: dict[str, list[dict]]) -> dict:
    """Assemble the live community snapshot the owner agent decides from.

    Pulls the served channel list (so the owner sees rooms that appeared as the
    session progressed — e.g. a friend 하나 just created), labels manager/creator/
    friend rooms in human terms, and carries the in-memory recent transcript per
    channel (observed live over the WS) so the owner reacts to what was just said."""
    labels: dict[str, str] = {}
    postable: list[str] = []
    friend_channels: list[str] = []
    friend_names: list[str] = []
    mgr_ch = _MGR_CHANNEL
    creator_ch = _CREATOR_CHANNEL
    try:
        chans = _get(base, f"/community/{cid}/chat/channels", cookie=cookie)
        for c in chans.get("channels", []):
            ch = c.get("channel") or ""
            if not ch or c.get("kind") != "dm":
                continue
            name = c.get("name") or ch
            atype = c.get("agent_type") or ""
            if atype == "mgr" or ch == _MGR_CHANNEL:
                mgr_ch = ch
                labels[ch] = f"{name}(매니저) DM"
            elif atype == "creator" or ch == _CREATOR_CHANNEL:
                creator_ch = ch
                labels[ch] = f"{name}(친구 만들어주는 사람) DM"
            else:
                friend_channels.append(ch)
                friend_names.append(name)
                labels[ch] = f"{name}(친구) DM"
            if c.get("postable"):
                postable.append(ch)
    except Exception:
        pass
    # Always allow the manager/creator DMs (they exist from the fresh seed even if
    # the channel list call hiccuped).
    for ch in (mgr_ch, creator_ch):
        if ch not in postable:
            postable.append(ch)
        labels.setdefault(ch, ch)

    # Build the per-channel recent transcript view (most recent last, capped).
    channels_view: dict[str, list[dict]] = {}
    for ch in set(list(recent.keys()) + postable):
        channels_view[ch] = (recent.get(ch) or [])[-6:]

    return {
        "round": round_idx,
        "backend": backend,
        "channels": channels_view,
        "labels": labels,
        "postable_channels": postable,
        "mgr_channel": mgr_ch,
        "creator_channel": creator_ch,
        "friend_channels": friend_channels,
        "friend_names": friend_names,
    }


async def _drive_owner_agent(base: str, base_ws: str, cid: str, cookie: str,
                             rounds: int, reply_timeout: float, backend: str,
                             log) -> dict:
    """Autonomous owner-agent drive: each round the owner agent decides the channel
    + message from the live snapshot, the harness sends the owner frame over the WS,
    awaits the friend/manager reply, feeds it back into the snapshot, and repeats.

    Returns ``{channel: [reply_texts]}`` (observed live) for the same downstream
    use as the scripted path. Streams every owner turn + reply to the log so a
    watcher sees the autonomous onboarding→friends→chat session unfold."""
    import websockets

    from tests.e2e.community_owner_agent import OwnerDriver

    driver = OwnerDriver(backend=backend)
    # Per-channel recent transcript (the owner's working memory of the session).
    recent: dict[str, list[dict]] = {}
    observed: dict[str, list[str]] = {}

    ws_url = f"{base_ws}/community/{cid}/chat/ws"
    async with websockets.connect(
        ws_url, additional_headers={"Cookie": cookie}, open_timeout=20,
        max_size=4 * 1024 * 1024,
    ) as ws:
        for rnd in range(rounds):
            snap = _owner_snapshot(base, cid, cookie, round_idx=rnd,
                                   backend=backend, recent=recent)
            turn = driver.next_turn(snap)
            ch = turn["channel"]
            text = turn["text"]
            agent_id = ch[len("dm-"):] if ch.startswith("dm-") else ch
            label = snap["labels"].get(ch, ch)
            note = turn.get("note", "")
            log(f"[owner-agent] R{rnd + 1} → {label} ({ch}): {text!r}"
                + (f"   ⟪{note}⟫" if note else ""))

            # Record the owner's own turn into the working memory (the WS does NOT
            # echo it back, so we add it here for the next snapshot).
            recent.setdefault(ch, []).append(
                {"speaker": "사용자", "text": text, "is_user": True})

            await ws.send(json.dumps({
                "type": "text", "channel": ch, "agent": agent_id, "text": text,
            }))
            reply = await _await_reply(ws, ch, reply_timeout, log)
            if reply:
                observed.setdefault(ch, []).append(reply)
                recent.setdefault(ch, []).append(
                    {"speaker": agent_id, "text": reply, "is_user": False})

    # Stash the owner side for the verdict (turns + token usage).
    observed["_owner_turns"] = driver.turns           # type: ignore[assignment]
    observed["_owner_usage"] = driver.usage           # type: ignore[assignment]
    return observed


# ── WS driving (scripted legacy path) ──────────────────────────────────────────

async def _drive_ws(base_ws: str, cid: str, cookie: str, friends: list[str],
                    rounds: int, reply_timeout: float, log) -> dict:
    """Connect to the chat WS as the owner, send the mini-conversation into each
    friend DM, collect each reply. Returns {channel: [reply_texts]} (observed live).

    Frame contract (from chat.py WS handler):
      send  {type:'text', channel:'dm-<id>', agent:'<id>', text:'...'}
      recv  {type:'typing'|'text'|'error', channel, ...}  — a 'text' from a
            non-owner speaker on that channel is the friend's reply.
    """
    import websockets

    ws_url = f"{base_ws}/community/{cid}/chat/ws"
    observed: dict[str, list[str]] = {ch: [] for ch in friends}
    # websockets passes cookies via extra headers (the server reads the cookie jar).
    async with websockets.connect(
        ws_url, additional_headers={"Cookie": cookie}, open_timeout=20,
        max_size=4 * 1024 * 1024,
    ) as ws:
        for rnd in range(rounds):
            turn = OWNER_TURNS[min(rnd, len(OWNER_TURNS) - 1)]
            for ch in friends:
                agent_id = ch[len("dm-"):]
                log(f"[community_e2e] → {ch}: {turn!r}")
                await ws.send(json.dumps({
                    "type": "text", "channel": ch, "agent": agent_id, "text": turn,
                }))
                # Drain frames until a non-owner 'text' on THIS channel (the reply),
                # or the per-reply timeout. typing/pong frames are skipped.
                got = await _await_reply(ws, ch, reply_timeout, log)
                if got:
                    observed[ch].append(got)
    return observed


async def _await_reply(ws, channel: str, reply_timeout: float, log) -> str:
    """Await frames until a friend 'text' reply on ``channel`` arrives or we time out."""
    import websockets

    deadline = time.time() + reply_timeout
    reply = ""
    while time.time() < deadline:
        remaining = max(0.1, deadline - time.time())
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        except asyncio.TimeoutError:
            break
        except websockets.ConnectionClosed:
            break
        try:
            frame = json.loads(raw)
        except Exception:
            continue
        ftype = frame.get("type")
        ch = frame.get("channel")
        if ftype == "error" and ch == channel:
            log(f"[community_e2e] ← {channel} ERROR: {frame.get('error')} "
                f"{frame.get('message', '')}")
            break
        if ftype == "text" and ch == channel and frame.get("text"):
            # A 'text' frame on this DM from the agent = the friend reply (the
            # owner turn is logged by the kernel but not echoed as a WS frame).
            reply = frame.get("text") or ""
            log(f"[community_e2e] ← {channel}: {reply[:80]!r}")
            # Echo emits one line; a real backend may stream multiple. Take the
            # first non-empty reply frame as the reply (history harvest captures
            # the full set for the verdict).
            break
    return reply


# ── served-data harvesting → verdict snapshot ───────────────────────────────────

def _harvest_channel(base: str, cid: str, channel: str, cookie: str,
                     timeout: float = 30.0) -> list[dict]:
    """Pull a channel's full message list over HTTP, paging via before_id, and
    translate each served row into the verdict's expected shape.

    Served row: {id, speaker_id, display_name, is_user, text, timestamp, ...}.
    Verdict row: {speaker, message, id, timestamp, is_user}."""
    from urllib.parse import quote

    out: list[dict] = []
    before_id = 0
    seen: set = set()
    ch_q = quote(channel, safe="")  # 한글 채널명(group-친구들 등)이 URL 에서 안 깨지게
    while True:
        path = f"/community/{cid}/chat/history?channel={ch_q}&limit=200"
        if before_id:
            path += f"&before_id={before_id}"
        try:
            resp = _get(base, path, cookie=cookie, timeout=timeout)
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
        out = page + out
        ids = [r["id"] for r in page if r.get("id") is not None]
        if len(rows) < 200 or not ids:
            break
        before_id = min(ids)
    out.sort(key=lambda m: (m.get("id") or 0))
    return out


def _build_snapshot(base: str, cid: str, cookie: str, *, backend: str, goal: str,
                    context: str, driven: list[str], elapsed: float,
                    error: str | None, drive_mode: str = "scripted",
                    owner_turns: list | None = None,
                    owner_usage: dict | None = None) -> dict:
    """Assemble the flat snapshot community_verdict.judge_snapshot consumes, from the
    SERVED endpoints. owner_id is inferred from the served is_user rows.

    ``drive_mode`` ("owner-agent" | "scripted") + ``owner_turns`` (the owner agent's
    chosen turns) + ``owner_usage`` (owner-side token usage) are carried so the
    verdict can judge the WHOLE session (owner + friends), not just the replies."""
    channels: dict[str, list[dict]] = {}
    # Pull every postable channel (so meta/error scans see the whole space) + the
    # driven DMs (always).
    pull = list(driven)
    try:
        chans = _get(base, f"/community/{cid}/chat/channels", cookie=cookie)
        for c in chans.get("channels", []):
            ch = c.get("channel")
            if ch and ch not in pull:
                pull.append(ch)
    except Exception:
        pass

    owner_id = "owner"
    for ch in pull:
        msgs = _harvest_channel(base, cid, ch, cookie)
        if msgs:
            channels[ch] = msgs
            for m in msgs:
                if m.get("is_user") and m.get("speaker"):
                    owner_id = m["speaker"]
                    break

    try:
        usage = _get(base, f"/api/usage?community={cid}", cookie=cookie)
    except Exception:
        usage = {}

    return {
        "run_id": f"community-e2e-{cid}",
        "backend": backend,
        "goal": goal,
        "context": context,
        "owner_id": owner_id,
        "owner_name": OWNER_NAME,
        "driven_channels": driven,
        "channels": channels,
        "usage": [],
        "usage_aggregate": usage,
        "elapsed_seconds": round(elapsed, 1),
        "error": error,
        "drive_mode": drive_mode,
        "owner_turns": owner_turns or [],
        "owner_usage": owner_usage or {},
    }


# ── the run ──────────────────────────────────────────────────────────────────

def run(*, goal: str, context: str, rounds: int, num_friends: int, backend: str,
        host: str, port: int, keep_serving: bool, reply_timeout: float,
        wall_clock_cap: float, report: bool = False,
        write_baseline: bool = False, owner_agent: bool = True,
        watch_pause: float = 0.0, qa: bool = False) -> dict:
    """Full web E2E: seed → start server → log in → drive (owner-agent | scripted)
    → harvest → judge → write artifacts. Returns the verdict dict. Mirrors ws_e2e.run.

    ``owner_agent=True`` (default): a fresh community (owner + 유나 + 하나) is seeded
    and an autonomous owner agent drives onboarding→friends→chat over the WS.
    ``owner_agent=False``: the demo mockup is seeded and the fixed ``OWNER_TURNS``
    are replayed into ``num_friends`` friend DMs."""
    from tests.e2e import community_verdict

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_id = f"community-e2e-{ts}"
    base = (f"http://127.0.0.1:{port}" if host in ("0.0.0.0", "")
            else f"http://{host}:{port}")
    base_ws = base.replace("http://", "ws://", 1)
    server_log = RESULTS_DIR / f"{run_id}-server.log"

    # Isolated temp dirs (auto-cleaned unless --keep-serving — the live server
    # still needs them). NEVER the owner's real data/communities.
    tmp_root = Path(tempfile.mkdtemp(prefix=f"glimi-community-e2e-{ts}-"))
    data_dir = tmp_root / "data"
    comm_dir = tmp_root / "communities"
    data_dir.mkdir(parents=True, exist_ok=True)
    comm_dir.mkdir(parents=True, exist_ok=True)
    env = _child_env(backend, data_dir, comm_dir)

    drive_mode = "owner-agent" if owner_agent else "scripted"
    print("=" * 64)
    print("  Glimi Community — TRUE WEB E2E (real server, WS-driven)")
    print("=" * 64)
    print(f"  run_id   : {run_id}")
    print(f"  backend  : {backend}")
    print(f"  drive    : {drive_mode}")
    print(f"  rounds   : {rounds}   friends: {num_friends}")
    print(f"  bind     : {host}:{port}   (probe {base})")
    print(f"  temp     : {tmp_root}")
    print(f"  keep     : {keep_serving}")
    print("=" * 64 + "\n")

    start = time.time()
    error: str | None = None
    driven: list[str] = []
    owner_turns: list = []
    owner_usage: dict = {}
    log_fh = open(server_log, "w", encoding="utf-8")

    # (a) seed a writable community BEFORE the server boots (shared isolated env).
    #     owner-agent → FRESH (owner + 유나 + 하나); scripted → demo mockup.
    proc = None
    try:
        _seed_community(env, COMMUNITY_ID, log_fh, fresh=owner_agent)

        # (b) launch + wait for /healthz.
        proc = _launch_server(host, port, env, log_fh)
        _wait_ready(base, proc, timeout=45.0)
        print(f"[community_e2e] server ready at {base}")

        # (c) log in (admin can access any community).
        cookie = _login(base)
        print("[community_e2e] logged in (session cookie acquired)")

        # (c.5) optional live-watch pause: the fresh community (owner + 유나 + 하나,
        #       no friends yet) is now served but NOT yet driven. Hold here so a
        #       watcher can open the chat page and catch the owner agent from turn 0.
        if watch_pause > 0:
            print("=" * 64)
            print(f"  ⏸  LIVE-WATCH PAUSE — {watch_pause:.0f}s before the owner starts.")
            print(f"     Open the chat now:  {base}/community/{COMMUNITY_ID}/chat")
            print("     (fresh community: 유나 매니저 + 하나 창작자, 친구 아직 없음.")
            print("      the owner agent's first message lands when this pause ends.)")
            print("=" * 64, flush=True)
            time.sleep(watch_pause)
            print("[community_e2e] watch pause over — owner agent driving now.\n", flush=True)

        if owner_agent:
            # ── OWNER-AGENT DRIVE (default) — autonomous owner onboards from the
            #    start (greet 유나 → ask 하나 for a friend → chat), deciding each turn.
            print("[community_e2e] drive mode: AUTONOMOUS OWNER AGENT "
                  "(onboarding → friends → chat)")

            async def _drive_with_cap():
                return await asyncio.wait_for(
                    _drive_owner_agent(base, base_ws, COMMUNITY_ID, cookie, rounds,
                                       reply_timeout, backend, log=print),
                    timeout=wall_clock_cap,
                )
            try:
                observed = asyncio.run(_drive_with_cap())
            except asyncio.TimeoutError:
                error = f"wall_clock_cap {wall_clock_cap}s exceeded"
                print(f"[community_e2e] WALL-CLOCK CAP {wall_clock_cap}s hit — stopping drive")
                observed = {}
            owner_turns = observed.pop("_owner_turns", [])  # type: ignore[assignment]
            owner_usage = observed.pop("_owner_usage", {})  # type: ignore[assignment]
            # The owner agent decides its own channels — the driven set is whatever
            # it actually posted into (so the verdict judges those DMs).
            driven = [ch for ch in observed.keys()] or \
                [t.get("channel") for t in owner_turns if t.get("channel")]
            driven = sorted(set(driven))
            n_obs = sum(len(v) for v in observed.values())
            print(f"[community_e2e] owner-agent drive done — {len(owner_turns)} owner "
                  f"turn(s), {n_obs} live reply frame(s), channels: {driven}")
        else:
            # ── SCRIPTED DRIVE (legacy) — fixed owner turns into seeded friend DMs.
            chans = _get(base, f"/community/{COMMUNITY_ID}/chat/channels", cookie=cookie)
            dm_channels = [c["channel"] for c in chans.get("channels", [])
                           if c.get("kind") == "dm" and c.get("channel", "").startswith("dm-")]
            # Prefer persona friends over mgr/creator for a more representative run.
            personas = [c for c in dm_channels if "persona" in c]
            ordered = personas + [c for c in dm_channels if c not in personas]
            driven = ordered[:max(1, num_friends)]
            if not driven:
                raise RuntimeError(f"no friend DM channels found (channels={dm_channels})")
            print(f"[community_e2e] driving {len(driven)} friend DM(s): {driven}")

            async def _drive_with_cap():
                return await asyncio.wait_for(
                    _drive_ws(base_ws, COMMUNITY_ID, cookie, driven, rounds,
                              reply_timeout, log=print),
                    timeout=wall_clock_cap,
                )
            try:
                observed = asyncio.run(_drive_with_cap())
                n_obs = sum(len(v) for v in observed.values())
                print(f"[community_e2e] WS drive done — {n_obs} live reply frame(s) observed")
            except asyncio.TimeoutError:
                error = f"wall_clock_cap {wall_clock_cap}s exceeded"
                print(f"[community_e2e] WALL-CLOCK CAP {wall_clock_cap}s hit — stopping drive")

        # (f) harvest the SERVED data for the verdict.
        snap = _build_snapshot(
            base, COMMUNITY_ID, cookie, backend=backend, goal=goal, context=context,
            driven=driven, elapsed=time.time() - start, error=error,
            drive_mode=drive_mode, owner_turns=owner_turns, owner_usage=owner_usage)
    except Exception as exc:  # capture; never crash the harness
        import traceback
        error = f"{type(exc).__name__}: {exc}"
        print(traceback.format_exc())
        snap = {
            "run_id": run_id, "backend": backend, "goal": goal, "context": context,
            "owner_id": "owner", "owner_name": OWNER_NAME,
            "driven_channels": driven, "channels": {}, "usage": [],
            "usage_aggregate": {}, "elapsed_seconds": round(time.time() - start, 1),
            "error": error, "drive_mode": drive_mode,
            "owner_turns": owner_turns, "owner_usage": owner_usage,
        }
    finally:
        try:
            log_fh.flush()
        except Exception:
            pass

    # (g) persist the assembled snapshot + judge.
    store_path = RESULTS_DIR / f"community-e2e-store-{ts}.json"
    store_path.write_text(json.dumps(snap, ensure_ascii=False, indent=2),
                          encoding="utf-8")

    verdict = community_verdict.judge_snapshot(snap, run_id=run_id)
    verdict["community_id"] = COMMUNITY_ID
    verdict["base_url"] = base
    verdict["served"] = True
    verdict["error"] = error
    verdict["usage_aggregate"] = snap.get("usage_aggregate", {})
    verdict["server_pid"] = proc.pid if proc else None
    verdict["server_log"] = str(server_log)
    verdict["store_snapshot"] = str(store_path)
    verdict["keep_serving"] = keep_serving
    verdict["temp_dir"] = str(tmp_root)
    verdict["drive_mode"] = drive_mode
    if owner_agent:
        # Owner-side summary so the verdict reflects the AUTONOMOUS session, not just
        # the friends' replies: how many turns the owner produced, what it said
        # (channel + text + private reason), and the owner-side token spend.
        verdict["owner_turns_count"] = len(owner_turns)
        verdict["owner_turns"] = owner_turns
        verdict["owner_usage"] = owner_usage

    out_path = RESULTS_DIR / f"{run_id}.json"
    out_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    # (h) portfolio report (Markdown + metrics JSON), reusing the SAME snapshot.
    if report or write_baseline:
        try:
            from tests.e2e import community_report
            out = community_report.generate_from_snapshot(
                snap, run_id=run_id, write_baseline=write_baseline)
            verdict["report_md"] = out["report_paths"]["md"]
            verdict["report_json"] = out["report_paths"]["json"]
            q = out["quality"]
            qs = (f"{q.get('overall')}/10 ({'pass' if q.get('pass') else 'fail'})"
                  if q.get("status") == "scored" else f"{q.get('status')}")
            print(f"[community_e2e] 리포트 — quality: {qs}")
            print(f"[community_e2e] 리포트(MD): {out['report_paths']['md']}")
            if out["report_paths"].get("baseline"):
                print(f"[community_e2e] 베이스라인 갱신: {out['report_paths']['baseline']}")
        except Exception as exc:
            import traceback
            print(f"[community_e2e] 리포트 실패 (verdict 는 완료): {exc}")
            print(traceback.format_exc())

    # (i) QA generation: multi-dimension quality assessment + git-anchored history.
    #     Turns this run into a "generation" (overall 0-100 score across onboarding /
    #     friend-creation / conversation-quality / no-hallucination / no-leaks /
    #     responsiveness), persisted to SQLite + a committable git-SHA-stamped JSON.
    if qa:
        try:
            from tests.e2e import qa_quality, qa_history
            assessment = qa_quality.assess(snap)
            gen = qa_history.record_generation(
                assessment, run_id=run_id, owner_name=OWNER_NAME, goal=goal,
                report_md=verdict.get("report_md", ""))
            verdict["qa"] = {
                "overall_score": assessment["overall_score"],
                "passed": assessment["passed"],
                "failing": assessment["failing"],
                "generation_no": gen["generation_no"],
                "generation_file": gen["_path"],
                "git_sha": gen["git"]["sha"],
            }
            ov = assessment["overall_score"]
            print("\n" + "─" * 64)
            print(f"  QA GENERATION #{gen['generation_no']}  ·  git {gen['git']['sha']}"
                  + ("*" if gen['git']['dirty'] else "")
                  + f"  ·  {'✅ PASS' if assessment['passed'] else '❌ FAIL'} "
                  + f"(overall {ov}/100, gate {assessment['min_overall']})")
            for dim in assessment["dimensions"]:
                if dim["skipped"]:
                    mark, sc = "·", "skip"
                else:
                    mark = "✅" if dim["passed"] else "❌"
                    sc = f"{dim['score']}/10"
                print(f"    {mark} {dim['label']:8s} {sc:>6s}  (w{dim['weight']})  {dim['detail'][:70]}")
            print(f"  generation: {gen['_path']}")
            print("─" * 64)
        except Exception as exc:
            import traceback
            print(f"[community_e2e] QA 평가 실패 (verdict 는 완료): {exc}")
            print(traceback.format_exc())

    print("\n" + "=" * 64)
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    print("=" * 64)
    status_s = verdict.get("status", "?")
    emoji = {"PASS": "✅", "WARN": "⚠️", "FAIL": "❌"}.get(status_s, "?")
    print(f"\n{emoji} {status_s}")
    print(f"[community_e2e] verdict: {out_path}")
    print(f"[community_e2e] served snapshot: {store_path}")
    print(f"[community_e2e] server log: {server_log}")

    if keep_serving and proc and proc.poll() is None:
        print("\n" + "─" * 64)
        print("  SERVER LEFT RUNNING for external watching (tunnel this):")
        print(f"    PID  : {proc.pid}")
        print(f"    bind : {host}:{port}")
        print(f"    watch: {base}/community/{COMMUNITY_ID}/chat   (live web chat)")
        print(f"    login: admin / {ADMIN_PASSWORD}")
        print(f"    home : {base}/")
        print(f"  stop it:  kill {proc.pid}   (temp dir {tmp_root} stays while serving)")
        print("─" * 64)
        # BLOCK so the child server stays up — if we returned, the parent would exit
        # and the tmux session would reap the server's process group (the ws_e2e bug
        # the proc.wait() block fixes). The verdict JSON is already written above.
        try:
            proc.wait()
        except KeyboardInterrupt:
            _stop_server(proc)
        _cleanup(tmp_root)
    else:
        if proc:
            _stop_server(proc)
        try:
            log_fh.close()
        except Exception:
            pass
        _cleanup(tmp_root)
        print("[community_e2e] server torn down + temp dir cleaned.")

    return verdict


def _cleanup(tmp_root: Path) -> None:
    try:
        shutil.rmtree(tmp_root, ignore_errors=True)
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Glimi Community TRUE WEB E2E QA (drives the real served server over HTTP+WS)")
    ap.add_argument("--goal", default=DEFAULT_GOAL, help="the chat scenario being driven (for the report/judge)")
    ap.add_argument("--context", default=None, help="extra context for the judge")
    drive = ap.add_mutually_exclusive_group()
    drive.add_argument("--owner-agent", dest="owner_agent", action="store_true", default=True,
                       help="DEFAULT: an autonomous owner agent drives onboarding→friends→chat "
                            "from a FRESH community (owner + 유나 + 하나)")
    drive.add_argument("--scripted", dest="owner_agent", action="store_false",
                       help="legacy: replay fixed OWNER_TURNS into seeded friend DMs (demo mockup)")
    ap.add_argument("--rounds", type=int, default=2,
                    help="owner-agent: number of autonomous owner turns (default 2). "
                         "scripted: owner turns per friend DM (clamped 1..3)")
    ap.add_argument("--friends", type=int, default=2,
                    help="scripted mode: how many friend DMs to drive (default 2; ignored by --owner-agent)")
    ap.add_argument("--backend", default=None,
                    help="LLM backend (else env GLIMI_LLM_BACKEND → echo). echo=$0 self-test, claude_cli=real")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT,
                    help=f"server port (default {DEFAULT_PORT}; non-standard to avoid live services)")
    ap.add_argument("--host", default="127.0.0.1",
                    help="bind host (use 0.0.0.0 with --keep-serving to expose for a tunnel)")
    ap.add_argument("--keep-serving", action="store_true",
                    help="leave the server running after the run (for external watching via a tunnel)")
    ap.add_argument("--watch-pause", type=float, default=0.0, metavar="SECONDS",
                    help="after the server is up + logged in, pause this many seconds BEFORE "
                         "the owner starts driving — so a live watcher can open the chat page "
                         "first and see the owner agent from its very first message (turn 0)")
    ap.add_argument("--reply-timeout", type=float, default=120.0,
                    help="seconds to wait for each friend reply frame (default 120; claude is slower)")
    ap.add_argument("--wall-cap", "--cap", dest="cap", type=float, default=None,
                    help="wall-clock cap (s) for the whole WS drive "
                         "(default: env GLIMI_COMMUNITY_E2E_WALL_CAP or 1800)")
    ap.add_argument("--report", action="store_true",
                    help="emit a portfolio report (Markdown + metrics JSON); quality judge runs only on a real backend")
    ap.add_argument("--qa", action="store_true",
                    help="record a QA GENERATION: multi-dimension quality assessment (0-100) "
                         "→ SQLite history + git-SHA-stamped JSON under tests/e2e/qa_generations/")
    ap.add_argument("--write-baseline", action="store_true",
                    help="(re)write tests/e2e/community-baseline.json from this run (implies --report)")
    args = ap.parse_args(argv)

    backend = (args.backend or os.environ.get("GLIMI_LLM_BACKEND") or "echo").strip() or "echo"
    port = args.port or _free_port()

    DEFAULT_WALL_CAP = 1800.0
    if args.cap is not None:
        wall_cap = args.cap
    else:
        try:
            wall_cap = float(os.environ.get("GLIMI_COMMUNITY_E2E_WALL_CAP", "")
                             or DEFAULT_WALL_CAP)
        except ValueError:
            wall_cap = DEFAULT_WALL_CAP

    context = args.context if args.context is not None else DEFAULT_CONTEXT

    # scripted mode replays OWNER_TURNS (3 entries) so it clamps to 1..3; the owner
    # agent decides its own messages each round so it can run as many as requested.
    rounds = max(1, args.rounds) if args.owner_agent else max(1, min(args.rounds, 3))

    verdict = run(
        goal=args.goal, context=context, rounds=rounds,
        num_friends=max(1, args.friends), backend=backend, host=args.host,
        port=port, keep_serving=args.keep_serving,
        reply_timeout=max(5.0, args.reply_timeout),
        wall_clock_cap=max(30.0, wall_cap),
        report=args.report, write_baseline=args.write_baseline,
        owner_agent=args.owner_agent, watch_pause=max(0.0, args.watch_pause),
        qa=args.qa,
    )
    return 0 if verdict.get("status") in ("PASS", "WARN") else 1


if __name__ == "__main__":
    sys.exit(main())
