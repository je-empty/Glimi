#!/usr/bin/env python3
"""
Glimi Web Dashboard — 서버 상태 실시간 관찰 (read-only).

CLI dashboard(src/tui/dashboard.py)와 동일한 데이터 소스(src.core.monitor)를 공유.
서버 제어(start/stop/restart) 기능은 여기 없음 — 그건 wizard 소관.

실행:
  GLIMI_COMMUNITY=qa python3 scripts/web_dashboard.py
  python3 scripts/web_dashboard.py qa           # CLI 인자로 커뮤니티 지정
  python3 scripts/web_dashboard.py dev --port 8765

접속:
  http://127.0.0.1:8765
  http://127.0.0.1:8765/?community=qa   (쿼리스트링으로도 가능 — live 전환)
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import socketserver
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_PORT = 8765


HTML = r"""<!doctype html>
<html lang="ko"><head>
<meta charset="utf-8">
<title>◈ Glimi Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {
    --bg: #0a0a0f;
    --bg-2: #10101a;
    --panel: #141420;
    --panel-2: #1a1a28;
    --border: #242438;
    --border-soft: #1e1e2e;
    --text: #e4e4ec;
    --text-dim: #9696a8;
    --text-faint: #5a5a6a;
    --accent: #7cb7ff;
    --accent-2: #a78bfa;
    --ok: #6ee7a8;
    --warn: #fbbf24;
    --err: #f87171;
    --cmd: #c084fc;
    --mgr: #60a5fa;
    --creator: #fbbf24;
    --persona: #a78bfa;
    --user: #fb923c;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; overflow: hidden; }
  body {
    background: radial-gradient(ellipse at top, #14142a 0%, #0a0a0f 60%);
    color: var(--text);
    font: 13px/1.55 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Pretendard", "Noto Sans KR", sans-serif;
    font-feature-settings: "ss01", "cv01";
  }
  .mono { font-family: "SF Mono", "JetBrains Mono", ui-monospace, Menlo, monospace; font-size: 12px; }

  /* ── 레이아웃 ── */
  .app { display: grid; grid-template-rows: auto 1fr; height: 100vh; }

  header {
    padding: 12px 20px;
    background: linear-gradient(180deg, rgba(22,22,36,0.95), rgba(18,18,30,0.85));
    backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 18px;
  }
  header .brand { font-size: 16px; font-weight: 600; letter-spacing: 0.3px; color: var(--accent); }
  header .brand .dot { color: var(--accent-2); }
  header .community { font-size: 12px; color: var(--text-dim); padding: 3px 10px; background: var(--panel); border-radius: 12px; border: 1px solid var(--border-soft); }
  header .pills { display: flex; gap: 8px; flex: 1; }
  header select { background: var(--panel); color: var(--text); border: 1px solid var(--border); border-radius: 10px; padding: 4px 8px; font-size: 12px; }
  .pill { font-size: 11px; padding: 4px 12px; border-radius: 999px; background: var(--panel); color: var(--text-dim); border: 1px solid var(--border-soft); display: inline-flex; align-items: center; gap: 6px; }
  .pill::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--text-faint); }
  .pill.on::before { background: var(--ok); box-shadow: 0 0 8px var(--ok); }
  .pill.on { color: var(--ok); border-color: rgba(110,231,168,0.3); background: rgba(110,231,168,0.08); }
  .pill.off::before { background: var(--err); }
  .pill.off { color: var(--err); border-color: rgba(248,113,113,0.3); background: rgba(248,113,113,0.08); }
  .pill.neutral { color: var(--text-dim); }

  .grid {
    display: grid;
    grid-template-columns: 320px 1fr 380px;
    grid-template-rows: 1fr;
    gap: 14px;
    padding: 14px;
    min-height: 0;
    overflow: hidden;
  }
  .col { display: flex; flex-direction: column; gap: 12px; min-height: 0; overflow: hidden; }

  /* ── Card ── */
  .card {
    background: var(--panel);
    border: 1px solid var(--border-soft);
    border-radius: 14px;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }
  .card h3 {
    padding: 10px 14px;
    font-size: 11px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1.2px;
    color: var(--text-dim);
    background: linear-gradient(180deg, rgba(30,30,46,0.6), transparent);
    border-bottom: 1px solid var(--border-soft);
    display: flex; align-items: center; justify-content: space-between;
  }
  .card h3 .badge { font-size: 10px; padding: 2px 8px; background: var(--panel-2); border-radius: 8px; color: var(--text); font-weight: 500; letter-spacing: 0.5px; text-transform: none; border: 1px solid var(--border-soft); }
  .card .body { flex: 1; overflow-y: auto; padding: 8px 10px; min-height: 0; }
  .card .body::-webkit-scrollbar { width: 6px; }
  .card .body::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
  .card .body::-webkit-scrollbar-track { background: transparent; }

  /* ── Agent Card ── */
  .agent {
    padding: 10px 12px;
    margin-bottom: 6px;
    background: var(--panel-2);
    border-radius: 10px;
    border: 1px solid var(--border-soft);
    transition: border-color 0.2s, transform 0.15s;
    display: flex; align-items: center; gap: 12px;
  }
  .agent:hover { border-color: var(--accent); }
  .agent.thinking { border-color: var(--warn); animation: pulse 1.6s infinite; }
  .agent.speaking { border-color: var(--accent); animation: pulse 1.2s infinite; }
  @keyframes pulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(251,191,36,0); }
    50% { box-shadow: 0 0 0 4px rgba(251,191,36,0.15); }
  }
  .agent .emoji { font-size: 26px; line-height: 1; width: 32px; text-align: center; }
  .agent .meta { flex: 1; min-width: 0; }
  .agent .row1 { display: flex; align-items: baseline; gap: 6px; }
  .agent .name { font-weight: 600; font-size: 13px; }
  .agent .type { font-size: 10px; padding: 1px 6px; border-radius: 6px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--text); font-weight: 500; }
  .agent .type.mgr { background: rgba(96,165,250,0.15); color: var(--mgr); }
  .agent .type.creator { background: rgba(251,191,36,0.15); color: var(--creator); }
  .agent .type.persona { background: rgba(167,139,250,0.15); color: var(--persona); }
  .agent .row2 { display: flex; align-items: center; gap: 6px; font-size: 11px; color: var(--text-dim); margin-top: 3px; }
  .agent .emo { color: var(--text); }
  .agent .bar { flex: 1; max-width: 80px; height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; }
  .agent .bar > span { display: block; height: 100%; background: linear-gradient(90deg, #4a90e2, #e25c4a); transition: width 0.3s; }
  .agent .state-tag { font-size: 9.5px; padding: 2px 6px; border-radius: 5px; letter-spacing: 0.5px; text-transform: uppercase; margin-left: 4px; }
  .agent.thinking .state-tag { background: rgba(251,191,36,0.15); color: var(--warn); }
  .agent.speaking .state-tag { background: rgba(124,183,255,0.15); color: var(--accent); }

  /* ── Channel ── */
  .channel {
    padding: 8px 12px;
    margin-bottom: 4px;
    background: var(--panel-2);
    border-radius: 8px;
    border: 1px solid var(--border-soft);
    display: flex; flex-direction: column; gap: 2px;
  }
  .channel .name {
    display: flex; align-items: center; gap: 6px;
    font-family: "SF Mono", ui-monospace, monospace; font-size: 12.5px;
  }
  .channel .name::before { content: '#'; color: var(--text-faint); font-weight: 400; }
  .channel.kind-mgr .name { color: var(--mgr); }
  .channel.kind-dm .name { color: var(--accent); }
  .channel.kind-group .name { color: var(--ok); }
  .channel.kind-internal-dm .name { color: var(--cmd); }
  .channel.kind-internal-group .name { color: var(--creator); }
  .channel .meta { font-size: 10.5px; color: var(--text-dim); display: flex; gap: 8px; }
  .channel .meta .sep { color: var(--text-faint); }
  .channel.hot { border-color: rgba(110,231,168,0.3); }

  /* ── Conversation ── */
  .msg {
    padding: 8px 10px;
    margin-bottom: 6px;
    background: var(--panel-2);
    border-radius: 8px;
    border-left: 3px solid var(--accent-2);
    font-size: 12.5px;
  }
  .msg.user { border-left-color: var(--user); }
  .msg.mgr { border-left-color: var(--mgr); }
  .msg.creator { border-left-color: var(--creator); }
  .msg.persona { border-left-color: var(--persona); }
  .msg .head { display: flex; gap: 8px; align-items: baseline; font-size: 11px; margin-bottom: 3px; }
  .msg .who { font-weight: 600; color: var(--text); }
  .msg .ch { color: var(--text-faint); font-family: "SF Mono", monospace; font-size: 10.5px; }
  .msg .ts { color: var(--text-faint); font-size: 10.5px; margin-left: auto; }
  .msg .text { color: var(--text); word-break: break-word; white-space: pre-wrap; }

  /* ── Event ── */
  .event {
    padding: 6px 10px; margin-bottom: 4px; font-size: 11.5px;
    border-left: 2px solid var(--cmd); background: var(--panel-2);
    border-radius: 0 6px 6px 0;
  }
  .event .type { color: var(--cmd); font-weight: 600; margin-right: 6px; }
  .event .desc { color: var(--text-dim); }
  .event .ts { color: var(--text-faint); font-size: 10px; margin-left: 6px; }

  /* ── Log ── */
  .log-box { font-family: "SF Mono", ui-monospace, monospace; font-size: 11.5px; white-space: pre-wrap; word-break: break-all; }
  .log-line { padding: 1px 0; }
  .log-line.err { color: var(--err); }
  .log-line.warn { color: var(--warn); }
  .log-line.ok { color: var(--ok); }
  .log-line.cmd { color: var(--cmd); }
  .log-line.tool { color: var(--cmd); font-weight: 500; }
  .log-line.dim { color: var(--text-faint); }

  .empty { padding: 24px 12px; text-align: center; color: var(--text-faint); font-size: 12px; }

  /* footer */
  footer { padding: 8px 20px; background: var(--bg-2); border-top: 1px solid var(--border-soft); font-size: 10.5px; color: var(--text-faint); display: flex; justify-content: space-between; }

  /* responsive */
  @media (max-width: 1100px) {
    .grid { grid-template-columns: 1fr; grid-template-rows: auto auto auto; overflow-y: auto; height: auto; }
    html, body { overflow-y: auto; }
    .app { height: auto; min-height: 100vh; }
  }
</style>
</head><body>
<div class="app">
  <header>
    <span class="brand">◈ Glimi<span class="dot">.</span>Dashboard</span>
    <span class="community" id="community-label">—</span>
    <div class="pills" id="pills"></div>
    <select id="community-select" title="커뮤니티 전환"></select>
  </header>

  <div class="grid">
    <!-- Left: Agents + Events -->
    <div class="col">
      <div class="card" style="flex: 1 1 auto; min-height: 200px;">
        <h3>Members <span class="badge" id="agent-count">0</span></h3>
        <div class="body" id="agents"></div>
      </div>
      <div class="card" style="flex: 0 0 40%; min-height: 140px;">
        <h3>Events <span class="badge" id="event-count">0</span></h3>
        <div class="body" id="events"></div>
      </div>
    </div>

    <!-- Middle: Conversations + Channels -->
    <div class="col">
      <div class="card" style="flex: 2 1 0; min-height: 200px;">
        <h3>Recent Conversations <span class="badge" id="msg-count">0</span></h3>
        <div class="body" id="messages"></div>
      </div>
      <div class="card" style="flex: 1 1 0; min-height: 180px;">
        <h3>Channels <span class="badge" id="channel-count">0</span></h3>
        <div class="body" id="channels"></div>
      </div>
    </div>

    <!-- Right: System Log -->
    <div class="col">
      <div class="card" style="flex: 1 1 auto; min-height: 200px;">
        <h3>System Log <span class="badge" id="log-count">—</span></h3>
        <div class="body log-box" id="logs"></div>
      </div>
    </div>
  </div>
</div>

<script>
const params = new URLSearchParams(location.search);
let COMMUNITY = params.get('community') || null;

function esc(s) { return String(s).replace(/[<>&"]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c])); }
async function j(u) {
  try { const r = await fetch(u); return await r.json(); }
  catch { return null; }
}
function q(u) {
  return COMMUNITY ? `${u}?community=${encodeURIComponent(COMMUNITY)}` : u;
}
function keepBottom(el) {
  const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  return () => { if (atBottom) el.scrollTop = el.scrollHeight; };
}

function classifyLog(line) {
  const low = line.toLowerCase();
  if (/❌|fatal|exception|failed/.test(line) || /\berror\b/i.test(line)) return 'err';
  if (/⚠|warn|오류|경고/i.test(line)) return 'warn';
  if (/✓|완료|ready|success|[Tool] ✓/.test(line)) return 'ok';
  if (/\[Tool\]|<tools>|<\/tools>|<call |<\/call>|<tool_result/.test(line)) return 'tool';
  return '';
}

async function tick() {
  const snap = await j(q('/api/snapshot'));
  const logs = await j(q('/api/logs?tail=100'));
  if (!snap) return;

  COMMUNITY = snap.community_id;
  document.getElementById('community-label').textContent = `community · ${snap.community_id}`;

  // pills
  const b = snap.bot, m = snap.meta;
  document.getElementById('pills').innerHTML = `
    <span class="pill ${b.bot_alive ? 'on' : 'off'}">bot</span>
    <span class="pill ${b.runner_alive ? 'on' : 'neutral'}">runner</span>
    <span class="pill ${b.test_user_alive ? 'on' : 'neutral'}">test-user</span>
    <span class="pill neutral">phase · <b style="color:var(--text)">${esc(m.onboarding_phase || '—')}</b></span>
    <span class="pill neutral">user · <b style="color:var(--text)">${esc(m.user_name || '—')}</b></span>
    <span class="pill neutral">msgs · <b style="color:var(--text)">${snap.total_messages || 0}</b></span>
  `;

  // Agents
  document.getElementById('agent-count').textContent = snap.agents.length;
  document.getElementById('agents').innerHTML = snap.agents.map(a => {
    const pct = Math.min(100, (a.intensity || 0) * 10);
    const stateCls = a.speaking ? 'speaking' : (a.thinking ? 'thinking' : '');
    const stateTag = a.speaking ? '<span class="state-tag">speaking</span>' : a.thinking ? '<span class="state-tag">thinking</span>' : '';
    return `<div class="agent ${stateCls}">
      <span class="emoji">${a.emoji}</span>
      <div class="meta">
        <div class="row1">
          <span class="name">${esc(a.name)}</span>
          <span class="type ${a.type}">${esc(a.type)}</span>
          ${stateTag}
        </div>
        <div class="row2">
          <span class="emo">${esc(a.emotion)}</span>
          <span>${a.intensity}/10</span>
          <div class="bar"><span style="width:${pct}%"></span></div>
          ${a.mbti ? `<span>· ${esc(a.mbti)}</span>` : ''}
        </div>
      </div>
    </div>`;
  }).join('') || '<div class="empty">no members</div>';

  // Channels
  document.getElementById('channel-count').textContent = snap.channels.length;
  document.getElementById('channels').innerHTML = snap.channels.map(c => {
    const ago = c.last_ago ? c.last_ago : '—';
    const hot = c.msg_count > 0 && c.last_ago && !c.last_ago.includes('시간') && !c.last_ago.includes('일') ? 'hot' : '';
    return `<div class="channel kind-${c.kind} ${hot}">
      <div class="name">${esc(c.name)}</div>
      <div class="meta">
        <span>${c.msg_count} msgs</span>
        <span class="sep">·</span>
        <span>${c.participant_count}명</span>
        <span class="sep">·</span>
        <span>${esc(ago)}</span>
      </div>
    </div>`;
  }).join('') || '<div class="empty">no channels</div>';

  // Events
  document.getElementById('event-count').textContent = snap.events.length;
  document.getElementById('events').innerHTML = snap.events.map(e =>
    `<div class="event">
      <span class="type">${esc(e.type)}</span>
      <span class="desc">${esc(e.description)}</span>
      <span class="ts">${esc(e.timestamp.slice(11, 19))}</span>
    </div>`
  ).join('') || '<div class="empty">no events</div>';

  // Conversations
  const msgsEl = document.getElementById('messages');
  const keepMsgs = keepBottom(msgsEl);
  document.getElementById('msg-count').textContent = snap.recent_messages.length;
  msgsEl.innerHTML = snap.recent_messages.map(m => {
    const roleClass = m.is_user ? 'user' : (m.speaker_id.includes('mgr') ? 'mgr' : m.speaker_id.includes('creator') ? 'creator' : 'persona');
    return `<div class="msg ${roleClass}">
      <div class="head">
        <span class="who">${esc(m.speaker)}</span>
        <span class="ch">#${esc(m.channel)}</span>
        <span class="ts">${esc((m.timestamp||'').slice(11, 19))}</span>
      </div>
      <div class="text">${esc(m.message)}</div>
    </div>`;
  }).join('') || '<div class="empty">no conversations yet</div>';
  keepMsgs();

  // Logs
  if (logs && logs.lines) {
    const logEl = document.getElementById('logs');
    const keepLog = keepBottom(logEl);
    document.getElementById('log-count').textContent = `${logs.lines.length} lines`;
    logEl.innerHTML = logs.lines.map(l =>
      `<div class="log-line ${classifyLog(l)}">${esc(l)}</div>`
    ).join('') || '<div class="empty">(log empty)</div>';
    keepLog();
  }
}

async function loadCommunities() {
  const d = await j('/api/communities');
  if (!d) return;
  const sel = document.getElementById('community-select');
  sel.innerHTML = (d.items || []).map(c =>
    `<option value="${esc(c.id)}" ${c.id === d.active ? 'selected' : ''}>${esc(c.id)}</option>`
  ).join('');
  sel.onchange = () => {
    COMMUNITY = sel.value;
    const url = new URL(location.href);
    url.searchParams.set('community', COMMUNITY);
    history.replaceState(null, '', url);
    tick();
  };
}

loadCommunities();
tick();
setInterval(tick, 1500);
</script>
</body></html>
"""


def _read_community(path: str) -> Optional[str]:
    """URL 쿼리에서 community 인자 추출."""
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse(path).query)
    v = q.get("community", [None])[0]
    return v


def _set_active_community(cid: Optional[str]):
    if cid:
        os.environ["GLIMI_COMMUNITY"] = cid
    # community 모듈 캐시 갱신
    from src import community as _comm
    if cid:
        _comm.set_community(cid)


def api_snapshot(path: str) -> dict:
    cid = _read_community(path)
    if cid:
        _set_active_community(cid)
    # 모듈 지연 임포트 — community 설정 후 DB 경로 해석됨
    from src.core import monitor
    snap = monitor.snapshot()
    # 채널 human ago 보강
    for c in snap["channels"]:
        c["last_ago"] = monitor.human_ago(c["last_ts"])
    return snap


def api_logs(path: str) -> dict:
    cid = _read_community(path)
    if cid:
        _set_active_community(cid)
    from src.core import monitor
    from urllib.parse import urlparse, parse_qs
    q = parse_qs(urlparse(path).query)
    tail = int(q.get("tail", ["100"])[0])
    lines = monitor.get_recent_system_logs(tail_lines=tail)
    return {"lines": lines, "count": len(lines)}


def api_communities() -> dict:
    from src import community as _comm
    items = _comm.list_communities()
    return {"items": items, "active": _comm.get_community_id()}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a, **kw):  # silence
        return

    def _send(self, status: int, body: bytes, content_type: str):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self._send(200, body, "application/json; charset=utf-8")

    def _html(self, text: str):
        self._send(200, text.encode("utf-8"), "text/html; charset=utf-8")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            if path in ("/", "/index.html"):
                self._html(HTML)
            elif path == "/api/snapshot":
                self._json(api_snapshot(self.path))
            elif path == "/api/logs":
                self._json(api_logs(self.path))
            elif path == "/api/communities":
                self._json(api_communities())
            else:
                self._send(404, b"not found", "text/plain")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._json({"error": str(e)})


class ReusableServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    parser = argparse.ArgumentParser(description="Glimi Web Dashboard (read-only)")
    parser.add_argument("community", nargs="?", default=None, help="커뮤니티 ID (생략 시 registry default)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()

    if args.community:
        os.environ["GLIMI_COMMUNITY"] = args.community

    os.chdir(str(ROOT))

    from src import community as _comm
    cid = _comm.get_community_id()
    print(f"[web-dashboard] http://{args.host}:{args.port}  (community={cid})")
    with ReusableServer((args.host, args.port), Handler) as srv:
        srv.serve_forever()


# Optional 타입 (Python 3.9 호환)
from typing import Optional  # noqa: E402


if __name__ == "__main__":
    main()
