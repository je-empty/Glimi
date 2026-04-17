#!/usr/bin/env python3
"""
Glimi Web Dashboard — 서버 상태 실시간 관찰 (read-only).

CLI dashboard(src/tui/dashboard.py)와 동일한 데이터 소스(src.core.monitor)를 공유.
서버 제어는 wizard 소관 — 이 대시보드는 오직 관찰만.

CLI dashboard의 핵심 UX를 웹으로 옮김:
  - 상단 탭: Overview / Agents / Channels / Events / Logs
  - 에이전트 블록: 평상시 컴팩트, thinking/speaking 시 자동 확장
    (경과 시간 프로그레스 바, 최근 추론 로그, 최근 대화)
  - thinking = 노랑 테두리, speaking = 시안 테두리

실행:
  GLIMI_COMMUNITY=qa python3 scripts/web_dashboard.py
  python3 scripts/web_dashboard.py qa
  python3 scripts/web_dashboard.py dev --port 8765

접속: http://127.0.0.1:8765  (쿼리 ?community=qa 로 live 전환)
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import socketserver
import sys
from pathlib import Path
from typing import Optional
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
    --bg: #07070c;
    --bg-grad: radial-gradient(ellipse at top left, #1a1a2e 0%, #0a0a14 55%, #07070c 100%);
    --panel: #13131f;
    --panel-2: #191927;
    --panel-3: #1f1f30;
    --border: #2a2a3e;
    --border-soft: #1f1f2e;
    --text: #e8e8f0;
    --text-dim: #9393a6;
    --text-faint: #5a5a6d;
    --accent: #7cb7ff;
    --accent-2: #a78bfa;
    --ok: #6ee7a8;
    --warn: #fbbf24;
    --err: #f87171;
    --cmd: #c084fc;
    --thinking: #fde047;
    --speaking: #67e8f9;
    --mgr: #60a5fa;
    --creator: #fbbf24;
    --persona: #a78bfa;
    --user: #fb923c;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; overflow: hidden; }
  body {
    background: var(--bg-grad); background-color: var(--bg);
    color: var(--text);
    font: 13px/1.55 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Pretendard", "Noto Sans KR", sans-serif;
    font-feature-settings: "ss01", "cv01";
  }
  .mono { font-family: "SF Mono", "JetBrains Mono", ui-monospace, Menlo, monospace; }

  /* ── App Shell ── */
  .app { display: grid; grid-template-rows: auto auto 1fr; height: 100vh; }

  /* ── Status Bar ── */
  header.status {
    padding: 10px 22px;
    background: linear-gradient(180deg, rgba(22,22,42,0.95), rgba(14,14,26,0.85));
    backdrop-filter: blur(14px);
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
  }
  .brand { font-size: 15px; font-weight: 700; letter-spacing: 0.3px; color: var(--accent); display: flex; align-items: center; gap: 4px; }
  .brand .dot { color: var(--accent-2); }
  .brand small { font-size: 10px; font-weight: 500; color: var(--text-faint); margin-left: 8px; letter-spacing: 1px; text-transform: uppercase; }
  .pill {
    font-size: 11px; padding: 4px 11px; border-radius: 999px; background: var(--panel);
    color: var(--text-dim); border: 1px solid var(--border-soft);
    display: inline-flex; align-items: center; gap: 6px; white-space: nowrap;
  }
  .pill::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--text-faint); }
  .pill.on::before { background: var(--ok); box-shadow: 0 0 8px var(--ok); }
  .pill.on { color: var(--ok); border-color: rgba(110,231,168,0.3); background: rgba(110,231,168,0.08); }
  .pill.off::before { background: var(--err); }
  .pill.off { color: var(--err); border-color: rgba(248,113,113,0.3); background: rgba(248,113,113,0.08); }
  .pill.neutral { color: var(--text); }
  .pill.neutral b { color: var(--text); }
  .stats-right { margin-left: auto; display: flex; gap: 8px; align-items: center; }
  select.community-sel {
    background: var(--panel); color: var(--text); border: 1px solid var(--border); border-radius: 10px;
    padding: 5px 10px; font-size: 12px; cursor: pointer;
  }

  /* ── Tab Bar ── */
  nav.tabs {
    padding: 0 22px;
    background: var(--bg);
    border-bottom: 1px solid var(--border);
    display: flex; gap: 2px;
    overflow-x: auto;
  }
  nav.tabs button {
    background: transparent; color: var(--text-dim); border: none;
    padding: 11px 16px; font-size: 12.5px; font-weight: 500; cursor: pointer;
    border-bottom: 2px solid transparent; transition: all 0.15s;
    font-family: inherit;
  }
  nav.tabs button:hover { color: var(--text); background: rgba(255,255,255,0.03); }
  nav.tabs button.active { color: var(--accent); border-bottom-color: var(--accent); }
  nav.tabs button .count { font-size: 10px; margin-left: 4px; padding: 1px 6px; background: var(--panel-2); border-radius: 6px; color: var(--text-dim); }
  nav.tabs button.active .count { background: rgba(124,183,255,0.15); color: var(--accent); }

  /* ── Main Content ── */
  main {
    min-height: 0; overflow: hidden; display: flex; flex-direction: column;
  }
  .view { display: none; flex: 1; overflow-y: auto; padding: 18px 22px; }
  .view.active { display: block; }
  .view::-webkit-scrollbar { width: 8px; }
  .view::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

  /* ── Overview Grid ── */
  .overview-grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 14px;
    margin-bottom: 18px;
  }
  .kpi {
    background: var(--panel); border: 1px solid var(--border-soft); border-radius: 12px;
    padding: 14px 18px;
  }
  .kpi .label { font-size: 10.5px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 1px; margin-bottom: 4px; }
  .kpi .value { font-size: 22px; font-weight: 600; color: var(--text); }
  .kpi .value small { font-size: 13px; color: var(--text-dim); font-weight: 400; margin-left: 6px; }

  .section-title {
    font-size: 12px; font-weight: 600; color: var(--text-dim);
    text-transform: uppercase; letter-spacing: 1.5px;
    margin: 20px 2px 10px;
    display: flex; align-items: center; gap: 8px;
  }
  .section-title::after {
    content: ''; flex: 1; height: 1px; background: var(--border-soft);
  }

  /* ── Agent Grid ── */
  .agent-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 12px;
    align-items: start;
  }
  .agent-card {
    background: var(--panel);
    border: 1.5px solid var(--border-soft);
    border-radius: 12px;
    padding: 12px 14px;
    transition: border-color 0.2s, transform 0.2s, box-shadow 0.3s;
    position: relative;
    overflow: hidden;
  }
  .agent-card:hover { border-color: var(--accent); transform: translateY(-1px); }
  .agent-card.mgr { border-left: 3px solid var(--mgr); }
  .agent-card.creator { border-left: 3px solid var(--creator); }
  .agent-card.persona { border-left: 3px solid var(--persona); }

  /* Thinking/speaking: card EXPANDS to full-width + glow animation */
  .agent-card.thinking {
    grid-column: 1 / -1;
    border-color: var(--thinking);
    box-shadow: 0 0 0 1px var(--thinking), 0 0 24px rgba(253,224,71,0.15);
    background: linear-gradient(135deg, var(--panel) 0%, rgba(253,224,71,0.04) 100%);
  }
  .agent-card.speaking {
    grid-column: 1 / -1;
    border-color: var(--speaking);
    box-shadow: 0 0 0 1px var(--speaking), 0 0 24px rgba(103,232,249,0.15);
    background: linear-gradient(135deg, var(--panel) 0%, rgba(103,232,249,0.04) 100%);
  }

  .agent-head { display: flex; align-items: center; gap: 10px; }
  .agent-head .emoji { font-size: 28px; line-height: 1; flex-shrink: 0; }
  .agent-head .info { flex: 1; min-width: 0; }
  .agent-head .name-row { display: flex; align-items: baseline; gap: 6px; }
  .agent-head .name { font-size: 14px; font-weight: 600; }
  .agent-head .type-tag {
    font-size: 9.5px; padding: 1px 6px; border-radius: 5px;
    text-transform: uppercase; letter-spacing: 0.5px; font-weight: 500;
  }
  .agent-head .type-tag.mgr { background: rgba(96,165,250,0.15); color: var(--mgr); }
  .agent-head .type-tag.creator { background: rgba(251,191,36,0.15); color: var(--creator); }
  .agent-head .type-tag.persona { background: rgba(167,139,250,0.15); color: var(--persona); }
  .agent-head .status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-faint); }
  .agent-head .status-dot.active { background: var(--ok); box-shadow: 0 0 6px var(--ok); }

  .agent-head .state-badge {
    font-size: 10.5px; font-weight: 700; padding: 3px 8px; border-radius: 6px;
    letter-spacing: 0.8px; text-transform: uppercase; margin-left: auto;
    display: none;
  }
  .agent-card.thinking .state-badge.thinking { display: inline-block; background: var(--thinking); color: #000; }
  .agent-card.speaking .state-badge.speaking { display: inline-block; background: var(--speaking); color: #000; }
  .agent-card.thinking .state-badge.thinking::before { content: '🧠 '; }
  .agent-card.speaking .state-badge.speaking::before { content: '💬 '; }

  .agent-meta { display: flex; gap: 10px; align-items: center; margin-top: 6px; font-size: 11px; color: var(--text-dim); }
  .agent-meta .emo-bar { display: flex; align-items: center; gap: 4px; }
  .agent-meta .bar { width: 60px; height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; }
  .agent-meta .bar > span { display: block; height: 100%; background: linear-gradient(90deg, #4a90e2, #e25c4a); transition: width 0.3s; }

  /* Expanded panel when thinking/speaking */
  .agent-expanded { display: none; margin-top: 12px; }
  .agent-card.thinking .agent-expanded,
  .agent-card.speaking .agent-expanded { display: block; }

  .progress-wrap { display: flex; align-items: center; gap: 10px; font-size: 11px; color: var(--text-dim); margin-bottom: 10px; }
  .progress-wrap .elapsed { font-family: "SF Mono", monospace; color: var(--text); font-weight: 600; }
  .progress-bar {
    flex: 1; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden;
    position: relative;
  }
  .progress-bar > span {
    display: block; height: 100%; width: 100%;
    background: linear-gradient(90deg, transparent, var(--thinking), transparent);
    background-size: 40% 100%; background-repeat: no-repeat;
    animation: slide 2s linear infinite;
  }
  .agent-card.speaking .progress-bar > span { background: linear-gradient(90deg, transparent, var(--speaking), transparent); background-size: 40% 100%; background-repeat: no-repeat; }
  @keyframes slide {
    0% { background-position: -40% 0; }
    100% { background-position: 140% 0; }
  }

  .agent-logs {
    font-family: "SF Mono", ui-monospace, monospace;
    font-size: 10.5px; color: var(--text-dim);
    background: var(--panel-3); border-radius: 8px; padding: 8px 10px;
    max-height: 100px; overflow-y: auto; margin-bottom: 8px;
  }
  .agent-logs .logline { padding: 1px 0; white-space: pre-wrap; word-break: break-all; }

  .agent-chat {
    background: var(--panel-3); border-radius: 8px; padding: 8px 10px;
    font-size: 11.5px;
  }
  .agent-chat .cline { padding: 2px 0; }
  .agent-chat .cline b { color: var(--accent-2); margin-right: 6px; }
  .agent-chat .cline.user b { color: var(--user); }

  /* ── Channel Grid ── */
  .channel-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 10px;
  }
  .channel-card {
    background: var(--panel); border: 1px solid var(--border-soft); border-radius: 10px;
    padding: 10px 14px; display: flex; flex-direction: column; gap: 4px;
    border-left: 3px solid var(--text-faint);
  }
  .channel-card.kind-mgr { border-left-color: var(--mgr); }
  .channel-card.kind-dm { border-left-color: var(--accent); }
  .channel-card.kind-group { border-left-color: var(--ok); }
  .channel-card.kind-internal-dm { border-left-color: var(--cmd); }
  .channel-card.kind-internal-group { border-left-color: var(--creator); }
  .channel-card .name { font-family: "SF Mono", monospace; font-size: 12.5px; font-weight: 500; }
  .channel-card .name::before { content: '#'; color: var(--text-faint); }
  .channel-card .meta { font-size: 10.5px; color: var(--text-dim); display: flex; gap: 8px; }
  .channel-card .meta .sep { color: var(--text-faint); }
  .channel-card.hot { border-color: rgba(110,231,168,0.3); }

  /* ── Messages ── */
  .msg-list { display: flex; flex-direction: column; gap: 6px; }
  .msg {
    padding: 8px 12px; border-radius: 8px;
    background: var(--panel);
    border-left: 3px solid var(--persona);
    border-top: 1px solid var(--border-soft);
    border-right: 1px solid var(--border-soft);
    border-bottom: 1px solid var(--border-soft);
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

  /* ── Events ── */
  .event-list { display: flex; flex-direction: column; gap: 4px; }
  .event { padding: 8px 12px; font-size: 11.5px; background: var(--panel); border-left: 2px solid var(--cmd); border-radius: 0 8px 8px 0; }
  .event .type { color: var(--cmd); font-weight: 600; margin-right: 8px; }
  .event .desc { color: var(--text-dim); }
  .event .ts { color: var(--text-faint); font-size: 10px; margin-left: 6px; }

  /* ── Log View ── */
  .log-view {
    font-family: "SF Mono", ui-monospace, monospace; font-size: 11.5px;
    white-space: pre-wrap; word-break: break-all;
    background: var(--panel); padding: 12px 16px; border-radius: 10px;
    border: 1px solid var(--border-soft);
    max-height: calc(100vh - 200px); overflow-y: auto;
  }
  .log-view::-webkit-scrollbar { width: 6px; }
  .log-view::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
  .log-line { padding: 1px 0; }
  .log-line.err { color: var(--err); }
  .log-line.warn { color: var(--warn); }
  .log-line.ok { color: var(--ok); }
  .log-line.cmd { color: var(--cmd); }
  .log-line.tool { color: var(--cmd); font-weight: 500; }
  .log-line.dim { color: var(--text-faint); }

  .empty { padding: 32px 12px; text-align: center; color: var(--text-faint); font-size: 12px; font-style: italic; }
</style>
</head><body>
<div class="app">
  <!-- Status Bar -->
  <header class="status">
    <span class="brand">◈ Glimi<span class="dot">.</span><small>dashboard</small></span>
    <span id="pills-left"></span>
    <div class="stats-right">
      <span id="pills-right"></span>
      <select class="community-sel" id="community-select" title="커뮤니티 전환"></select>
    </div>
  </header>

  <!-- Tab Nav -->
  <nav class="tabs" id="tabs">
    <button data-tab="overview" class="active">Overview</button>
    <button data-tab="agents">Agents <span class="count" id="tc-agents">0</span></button>
    <button data-tab="channels">Channels <span class="count" id="tc-channels">0</span></button>
    <button data-tab="messages">Messages <span class="count" id="tc-messages">0</span></button>
    <button data-tab="events">Events <span class="count" id="tc-events">0</span></button>
    <button data-tab="logs">Logs</button>
  </nav>

  <!-- Views -->
  <main>
    <div class="view active" id="view-overview">
      <div class="overview-grid">
        <div class="kpi"><div class="label">Bot Status</div><div class="value" id="kpi-bot">—</div></div>
        <div class="kpi"><div class="label">Community · User</div><div class="value" id="kpi-user">—</div></div>
        <div class="kpi"><div class="label">Onboarding Phase</div><div class="value" id="kpi-phase">—</div></div>
        <div class="kpi"><div class="label">Total Messages</div><div class="value" id="kpi-msgs">0</div></div>
      </div>
      <div class="section-title">Active Members</div>
      <div class="agent-grid" id="overview-agents"></div>
      <div class="section-title">Recent Conversations</div>
      <div class="msg-list" id="overview-msgs"></div>
    </div>

    <div class="view" id="view-agents">
      <div class="agent-grid" id="agents-full"></div>
    </div>

    <div class="view" id="view-channels">
      <div class="channel-grid" id="channels-full"></div>
    </div>

    <div class="view" id="view-messages">
      <div class="msg-list" id="messages-full"></div>
    </div>

    <div class="view" id="view-events">
      <div class="event-list" id="events-full"></div>
    </div>

    <div class="view" id="view-logs">
      <div class="log-view" id="logs-full"></div>
    </div>
  </main>
</div>

<script>
const params = new URLSearchParams(location.search);
let COMMUNITY = params.get('community') || null;
let ACTIVE_TAB = 'overview';

function esc(s) { return String(s ?? '').replace(/[<>&"]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c])); }
async function j(u) { try { const r = await fetch(u); return await r.json(); } catch { return null; } }
function q(u) { return COMMUNITY ? `${u}${u.includes('?') ? '&' : '?'}community=${encodeURIComponent(COMMUNITY)}` : u; }
function atBottom(el) { return el.scrollHeight - el.scrollTop - el.clientHeight < 80; }
function classifyLog(line) {
  if (/❌|FATAL|Exception|failed|오류/.test(line) || /\berror\b/i.test(line)) return 'err';
  if (/⚠|warn|경고/i.test(line)) return 'warn';
  if (/✓|완료|ready|success|Tool registered/i.test(line)) return 'ok';
  if (/\[Tool\]|<tools>|<\/tools>|<call |<\/call>|<tool_result/i.test(line)) return 'tool';
  return '';
}

function fmtElapsed(secs) {
  if (!secs) return '0s';
  if (secs < 60) return `${Math.floor(secs)}s`;
  return `${Math.floor(secs/60)}:${String(Math.floor(secs%60)).padStart(2,'0')}`;
}

function roleClass(m) {
  if (m.is_user) return 'user';
  if (m.speaker_id && m.speaker_id.includes('mgr')) return 'mgr';
  if (m.speaker_id && m.speaker_id.includes('creator')) return 'creator';
  return 'persona';
}

function renderAgent(a, compact=false) {
  const expanded = a.thinking || a.speaking;
  const cls = [
    'agent-card', a.type,
    a.thinking ? 'thinking' : '',
    a.speaking ? 'speaking' : '',
  ].filter(Boolean).join(' ');
  const pct = Math.min(100, (a.intensity || 0) * 10);
  const elapsedSec = a.thinking ? a.thinking_seconds : a.speaking ? a.speaking_seconds : 0;
  const dot = a.status === 'active' ? 'active' : '';

  let expandedHtml = '';
  if (expanded) {
    const logLines = (a._logs || []).map(l => `<div class="logline">${esc(l)}</div>`).join('');
    const chatLines = (a._chat || []).map(c =>
      `<div class="cline ${c.is_user ? 'user' : ''}"><b>${esc(c.speaker)}:</b>${esc(c.message.slice(0, 90))}</div>`
    ).join('');
    expandedHtml = `
      <div class="agent-expanded">
        <div class="progress-wrap">
          <span>${a.thinking ? '추론 중' : '전송 중'}</span>
          <div class="progress-bar"><span></span></div>
          <span class="elapsed">${fmtElapsed(elapsedSec)}</span>
        </div>
        ${logLines ? `<div class="agent-logs">${logLines}</div>` : ''}
        ${chatLines ? `<div class="agent-chat">${chatLines}</div>` : ''}
      </div>
    `;
  }

  return `<div class="${cls}">
    <div class="agent-head">
      <span class="emoji">${a.emoji}</span>
      <div class="info">
        <div class="name-row">
          <span class="status-dot ${dot}"></span>
          <span class="name">${esc(a.name)}</span>
          <span class="type-tag ${a.type}">${esc(a.type)}</span>
        </div>
        <div class="agent-meta">
          <span>${esc(a.emotion)}</span>
          <div class="emo-bar">
            <div class="bar"><span style="width:${pct}%"></span></div>
            <span>${a.intensity}/10</span>
          </div>
          ${a.mbti ? `<span>· ${esc(a.mbti)}</span>` : ''}
        </div>
      </div>
      <span class="state-badge thinking">thinking</span>
      <span class="state-badge speaking">speaking</span>
    </div>
    ${expandedHtml}
  </div>`;
}

function renderMessage(m) {
  return `<div class="msg ${roleClass(m)}">
    <div class="head">
      <span class="who">${esc(m.speaker)}</span>
      <span class="ch">#${esc(m.channel)}</span>
      <span class="ts">${esc((m.timestamp||'').slice(11, 19))}</span>
    </div>
    <div class="text">${esc(m.message)}</div>
  </div>`;
}

function renderChannel(c) {
  const hot = c.msg_count > 0 && c.last_ago && !c.last_ago.includes('시간') && !c.last_ago.includes('일');
  return `<div class="channel-card kind-${c.kind} ${hot ? 'hot' : ''}">
    <div class="name">${esc(c.name)}</div>
    <div class="meta">
      <span>${c.msg_count} msgs</span>
      <span class="sep">·</span>
      <span>${c.participant_count}명</span>
      <span class="sep">·</span>
      <span>${esc(c.last_ago || '—')}</span>
    </div>
  </div>`;
}

function renderEvent(e) {
  return `<div class="event">
    <span class="type">${esc(e.type)}</span>
    <span class="desc">${esc(e.description)}</span>
    <span class="ts">${esc((e.timestamp||'').slice(11, 19))}</span>
  </div>`;
}

async function tick() {
  const snap = await j(q('/api/snapshot'));
  const logs = await j(q('/api/logs?tail=200'));
  if (!snap) return;

  COMMUNITY = snap.community_id;
  const b = snap.bot, m = snap.meta;

  // ── Status bar pills ──
  const leftPills = [
    `<span class="pill ${b.bot_alive ? 'on' : 'off'}">bot</span>`,
    `<span class="pill ${b.runner_alive ? 'on' : 'neutral'}">runner</span>`,
    `<span class="pill ${b.test_user_alive ? 'on' : 'neutral'}">test-user</span>`,
  ].join('');
  document.getElementById('pills-left').innerHTML = leftPills;

  const rightPills = [
    `<span class="pill neutral">phase · <b>${esc(m.onboarding_phase || '—')}</b></span>`,
    `<span class="pill neutral">user · <b>${esc(m.user_name || '—')}</b></span>`,
    `<span class="pill neutral">msgs · <b>${snap.total_messages || 0}</b></span>`,
    `<span class="pill neutral">· ${esc(snap.community_id)}</span>`,
  ].join('');
  document.getElementById('pills-right').innerHTML = rightPills;

  // ── Tab counts ──
  document.getElementById('tc-agents').textContent = snap.agents.length;
  document.getElementById('tc-channels').textContent = snap.channels.length;
  document.getElementById('tc-messages').textContent = snap.recent_messages.length;
  document.getElementById('tc-events').textContent = snap.events.length;

  // ── Enrich thinking/speaking agents with logs + chat (extra fetch) ──
  const active = snap.agents.filter(a => a.thinking || a.speaking);
  if (active.length) {
    await Promise.all(active.map(async (a) => {
      const extra = await j(q(`/api/agent_activity?id=${encodeURIComponent(a.id)}`));
      if (extra) { a._logs = extra.logs || []; a._chat = extra.chat || []; }
    }));
  }

  // ── Overview ──
  document.getElementById('kpi-bot').innerHTML = b.bot_alive
    ? `<span style="color:var(--ok)">● Running</span>`
    : `<span style="color:var(--err)">○ Stopped</span>`;
  document.getElementById('kpi-user').innerHTML = `${esc(m.user_name || '—')}<small>@${esc(snap.community_id)}</small>`;
  document.getElementById('kpi-phase').innerHTML = `${esc(m.onboarding_phase || '—')}`;
  document.getElementById('kpi-msgs').innerHTML = `${snap.total_messages}<small>total</small>`;

  document.getElementById('overview-agents').innerHTML =
    snap.agents.map(a => renderAgent(a, true)).join('') || '<div class="empty">no members</div>';

  const msgsEl = document.getElementById('overview-msgs');
  const keepMsgs = atBottom(msgsEl);
  msgsEl.innerHTML = snap.recent_messages.slice(-10).map(renderMessage).join('') || '<div class="empty">no conversations yet</div>';
  if (keepMsgs) msgsEl.scrollTop = msgsEl.scrollHeight;

  // ── Full tabs ──
  document.getElementById('agents-full').innerHTML =
    snap.agents.map(a => renderAgent(a)).join('') || '<div class="empty">no members</div>';
  document.getElementById('channels-full').innerHTML =
    snap.channels.map(renderChannel).join('') || '<div class="empty">no channels</div>';
  const fullMsgsEl = document.getElementById('messages-full');
  const keepFull = atBottom(fullMsgsEl);
  fullMsgsEl.innerHTML = snap.recent_messages.map(renderMessage).join('') || '<div class="empty">no conversations yet</div>';
  if (keepFull) fullMsgsEl.scrollTop = fullMsgsEl.scrollHeight;
  document.getElementById('events-full').innerHTML =
    snap.events.map(renderEvent).join('') || '<div class="empty">no events</div>';

  // Logs tab
  if (logs && logs.lines) {
    const logEl = document.getElementById('logs-full');
    const keepLog = atBottom(logEl);
    logEl.innerHTML = logs.lines.map(l => `<div class="log-line ${classifyLog(l)}">${esc(l)}</div>`).join('') || '<div class="empty">(log empty)</div>';
    if (keepLog) logEl.scrollTop = logEl.scrollHeight;
  }
}

function initTabs() {
  document.querySelectorAll('nav.tabs button').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('nav.tabs button').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
      btn.classList.add('active');
      const tab = btn.dataset.tab;
      document.getElementById('view-' + tab).classList.add('active');
      ACTIVE_TAB = tab;
    });
  });
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

initTabs();
loadCommunities();
tick();
setInterval(tick, 1500);
</script>
</body></html>
"""


def _read_community(path: str) -> Optional[str]:
    q = parse_qs(urlparse(path).query)
    return q.get("community", [None])[0]


def _set_active_community(cid: Optional[str]):
    if cid:
        os.environ["GLIMI_COMMUNITY"] = cid
    from src import community as _comm
    if cid:
        _comm.set_community(cid)


def api_snapshot(path: str) -> dict:
    cid = _read_community(path)
    if cid:
        _set_active_community(cid)
    from src.core import monitor
    snap = monitor.snapshot()
    for c in snap["channels"]:
        c["last_ago"] = monitor.human_ago(c["last_ts"])
    return snap


def api_logs(path: str) -> dict:
    cid = _read_community(path)
    if cid:
        _set_active_community(cid)
    from src.core import monitor
    q = parse_qs(urlparse(path).query)
    tail = int(q.get("tail", ["150"])[0])
    lines = monitor.get_recent_system_logs(tail_lines=tail)
    return {"lines": lines, "count": len(lines)}


def api_agent_activity(path: str) -> dict:
    cid = _read_community(path)
    if cid:
        _set_active_community(cid)
    from src.core import monitor
    q = parse_qs(urlparse(path).query)
    agent_id = q.get("id", [""])[0]
    if not agent_id:
        return {"logs": [], "chat": []}
    return {
        "logs": monitor.get_agent_thinking_logs(agent_id, n=5),
        "chat": monitor.get_agent_recent_chat(agent_id, limit=3),
    }


def api_communities() -> dict:
    from src import community as _comm
    items = _comm.list_communities()
    return {"items": items, "active": _comm.get_community_id()}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a, **kw):
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
            elif path == "/api/agent_activity":
                self._json(api_agent_activity(self.path))
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


if __name__ == "__main__":
    main()
