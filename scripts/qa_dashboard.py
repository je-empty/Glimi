#!/usr/bin/env python3
"""
QA 실시간 대시보드 — 두 터미널(QA runner + Glimi bot)을 웹으로 스트리밍.

포트: 8765
엔드포인트:
  GET /          HTML 페이지 (좌우 2분할)
  GET /qa        QA runner stdout 로그 (tests/e2e/results/latest.log)
  GET /glimi     Glimi bot 시스템 로그 (communities/qa/logs/system.log)
  GET /convo     DB 최근 대화 (보너스)

Preview로 띄우면 Claude UI에서 실시간 관찰 가능.
"""
import http.server
import json
import os
import socketserver
import sqlite3
from pathlib import Path

PORT = 8765
ROOT = Path(__file__).resolve().parent.parent
QA_LOG = ROOT / "tests" / "e2e" / "results" / "latest.log"
GLIMI_LOG = ROOT / "communities" / "qa" / "logs" / "system.log"
DB_PATH = ROOT / "communities" / "qa" / "community.db"

HTML = """<!doctype html>
<html><head>
<meta charset="utf-8">
<title>Glimi QA Dashboard</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0f0f12; color: #d4d4d4; font: 13px/1.5 ui-monospace, "SF Mono", Menlo, monospace; height: 100vh; overflow: hidden; }
  .wrap { display: grid; grid-template-rows: auto 1fr auto; height: 100vh; }
  header { padding: 8px 14px; background: #1a1a20; border-bottom: 1px solid #2a2a30; display: flex; justify-content: space-between; align-items: center; }
  header .title { font-weight: 600; font-size: 14px; }
  header .status { font-size: 11px; color: #888; }
  .cols { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 1px; background: #2a2a30; overflow: hidden; }
  .col { background: #0f0f12; display: flex; flex-direction: column; min-width: 0; }
  .col h2 { padding: 6px 12px; font-size: 11px; color: #888; background: #17171c; text-transform: uppercase; letter-spacing: 0.5px; border-bottom: 1px solid #2a2a30; }
  .col pre { flex: 1; overflow-y: auto; padding: 8px 12px; font-size: 12px; white-space: pre-wrap; word-break: break-all; }
  .col pre::-webkit-scrollbar { width: 6px; }
  .col pre::-webkit-scrollbar-thumb { background: #333; border-radius: 3px; }
  .err { color: #ff6b6b; }
  .warn { color: #ffd166; }
  .ok { color: #95e1a8; }
  .cmd { color: #7cb7ff; }
  .tool { color: #c792ea; }
  footer { padding: 6px 14px; background: #17171c; font-size: 11px; color: #666; border-top: 1px solid #2a2a30; text-align: center; }
  .stale { color: #666; }
</style>
</head><body>
<div class="wrap">
  <header>
    <span class="title">◈ Glimi QA Dashboard</span>
    <span class="status" id="status">연결 중…</span>
  </header>
  <div class="cols">
    <div class="col"><h2>Glimi Bot (system.log)</h2><pre id="glimi">(loading…)</pre></div>
    <div class="col"><h2>QA Runner (latest.log)</h2><pre id="qa">(loading…)</pre></div>
    <div class="col"><h2>Conversation DB</h2><pre id="convo">(loading…)</pre></div>
  </div>
  <footer>auto-refresh 1.5s · port 8765 · Ctrl+C on server to stop</footer>
</div>
<script>
  function colorize(text) {
    return text
      .replace(/❌|FATAL|error|exception|failed/gi, m => `<span class="err">${m}</span>`)
      .replace(/⚠|warn|오류|경고/gi, m => `<span class="warn">${m}</span>`)
      .replace(/✓|OK|완료|ready|success/gi, m => `<span class="ok">${m}</span>`)
      .replace(/\\[Tool\\][^\\n]*/g, m => `<span class="tool">${m}</span>`)
      .replace(/\\[CMD:[^\\]]*\\]|\\[QUERY:[^\\]]*\\]|<tools>|<\\/tools>|<call[^>]*>|<\\/call>/g, m => `<span class="cmd">${m}</span>`);
  }
  async function fetchJson(url) {
    try { const r = await fetch(url); return await r.json(); }
    catch { return null; }
  }
  function pinBottom(el) {
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 50;
    return () => { if (atBottom) el.scrollTop = el.scrollHeight; };
  }
  async function tick() {
    const qaEl = document.getElementById('qa');
    const glEl = document.getElementById('glimi');
    const cvEl = document.getElementById('convo');
    const keepQa = pinBottom(qaEl), keepGl = pinBottom(glEl), keepCv = pinBottom(cvEl);

    const [qa, gl, cv] = await Promise.all([
      fetchJson('/qa'), fetchJson('/glimi'), fetchJson('/convo')
    ]);
    if (qa) qaEl.innerHTML = colorize(qa.content || '(empty)');
    if (gl) glEl.innerHTML = colorize(gl.content || '(empty)');
    if (cv) {
      const lines = (cv.items || []).map(it =>
        `<span class="stale">[${it.ts}]</span> <b>${it.who}</b>@${it.ch}: ${escapeHtml(it.msg)}`
      ).join('\\n');
      cvEl.innerHTML = lines || '(no conversations yet)';
    }
    keepQa(); keepGl(); keepCv();
    document.getElementById('status').textContent =
      `qa=${qa ? qa.lines : '?'} lines · glimi=${gl ? gl.lines : '?'} lines · convo=${cv ? (cv.items||[]).length : '?'} rows`;
  }
  function escapeHtml(s) { return String(s).replace(/[<>&"]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c])); }
  tick();
  setInterval(tick, 1500);
</script>
</body></html>
"""


def tail_text(path: Path, max_bytes: int = 40_000) -> dict:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return {"content": "(file not found)", "lines": 0}
    with open(path, "rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
            f.readline()  # drop partial first line
        data = f.read().decode("utf-8", errors="replace")
    return {"content": data, "lines": data.count("\n")}


def recent_conversations(limit: int = 30) -> dict:
    if not DB_PATH.exists():
        return {"items": []}
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT speaker, channel, message, timestamp FROM conversations "
            "ORDER BY timestamp DESC LIMIT ?",
            (limit,)
        ).fetchall()
        conn.close()
    except Exception as e:
        return {"items": [], "error": str(e)}
    items = [
        {"who": r["speaker"], "ch": r["channel"],
         "msg": r["message"][:200], "ts": (r["timestamp"] or "")[11:19]}
        for r in reversed(rows)
    ]
    return {"items": items}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 조용히

    def _send_json(self, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/qa":
            self._send_json(tail_text(QA_LOG))
        elif self.path == "/glimi":
            self._send_json(tail_text(GLIMI_LOG))
        elif self.path == "/convo":
            self._send_json(recent_conversations())
        else:
            self.send_response(404)
            self.end_headers()


class ReusableServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main():
    os.chdir(str(ROOT))
    with ReusableServer(("127.0.0.1", PORT), Handler) as srv:
        print(f"[dashboard] http://127.0.0.1:{PORT}")
        srv.serve_forever()


if __name__ == "__main__":
    main()
