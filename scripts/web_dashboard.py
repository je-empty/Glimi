#!/usr/bin/env python3
"""
Glimi Web Dashboard — 서버 상태 실시간 관찰 (read-only).

CLI dashboard(src/tui/dashboard.py)의 8개 뷰를 웹으로 전부 이식.
서버 제어는 wizard 소관 — 이 대시보드는 오직 관찰만.

실행:
  GLIMI_COMMUNITY=qa python3 scripts/web_dashboard.py
  python3 scripts/web_dashboard.py qa
  python3 scripts/web_dashboard.py dev --port 8765
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
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  /* ==== Theme variables ==== */
  :root[data-theme="light"] {
    --bg: #f6f7fb;
    --bg-elev: #ffffff;
    --panel: #ffffff;
    --panel-2: #f2f3f9;
    --panel-3: #e9eaf3;
    --border: #dfe1ec;
    --border-soft: #eceef5;
    --text: #1a1b25;
    --text-dim: #62647a;
    --text-faint: #9a9db1;
    --accent: #4f46e5;
    --accent-2: #8b5cf6;
    --ok: #16a34a;
    --warn: #ca8a04;
    --err: #dc2626;
    --cmd: #9333ea;
    --thinking: #ca8a04;
    --speaking: #0891b2;
    --mgr: #2563eb;
    --creator: #d97706;
    --persona: #7c3aed;
    --user: #ea580c;
    --shadow: 0 1px 3px rgba(20,22,40,0.06), 0 1px 2px rgba(20,22,40,0.04);
    --shadow-lg: 0 10px 30px rgba(20,22,40,0.08), 0 2px 8px rgba(20,22,40,0.04);
    --glow-thinking: 0 0 0 1px rgba(202,138,4,0.6), 0 0 28px rgba(202,138,4,0.15);
    --glow-speaking: 0 0 0 1px rgba(8,145,178,0.6), 0 0 28px rgba(8,145,178,0.15);
  }
  :root[data-theme="dark"] {
    --bg: #0a0a10;
    --bg-elev: #111119;
    --panel: #151521;
    --panel-2: #1b1b2a;
    --panel-3: #232336;
    --border: #2d2d42;
    --border-soft: #1f1f30;
    --text: #e8e8f0;
    --text-dim: #9a9ab0;
    --text-faint: #5a5a6d;
    --accent: #818cf8;
    --accent-2: #c084fc;
    --ok: #4ade80;
    --warn: #fbbf24;
    --err: #f87171;
    --cmd: #d8b4fe;
    --thinking: #fde047;
    --speaking: #67e8f9;
    --mgr: #93c5fd;
    --creator: #fcd34d;
    --persona: #c4b5fd;
    --user: #fdba74;
    --shadow: 0 1px 3px rgba(0,0,0,0.3), 0 1px 2px rgba(0,0,0,0.2);
    --shadow-lg: 0 10px 30px rgba(0,0,0,0.4);
    --glow-thinking: 0 0 0 1px var(--thinking), 0 0 28px rgba(253,224,71,0.15);
    --glow-speaking: 0 0 0 1px var(--speaking), 0 0 28px rgba(103,232,249,0.15);
  }

  * { box-sizing: border-box; margin: 0; padding: 0; }
  html, body { height: 100%; overflow: hidden; }
  body {
    background: var(--bg);
    color: var(--text);
    font: 13px/1.55 "Inter", -apple-system, BlinkMacSystemFont, "Pretendard", "Noto Sans KR", sans-serif;
    font-feature-settings: "cv02", "cv03", "cv04", "cv11", "ss01";
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }
  .mono { font-family: "JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace; font-size: 12px; }

  button, select, input { font-family: inherit; color: inherit; }

  /* ==== Shell ==== */
  .app { display: grid; grid-template-rows: auto auto 1fr; height: 100vh; }

  header.status {
    padding: 11px 24px;
    background: var(--bg-elev);
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 14px; flex-wrap: wrap;
    box-shadow: var(--shadow);
    z-index: 5;
  }
  .brand {
    font-size: 14px; font-weight: 700; letter-spacing: -0.2px;
    color: var(--accent); display: flex; align-items: baseline; gap: 3px;
  }
  .brand .dot { color: var(--accent-2); }
  .brand small { font-size: 10px; font-weight: 500; color: var(--text-faint); margin-left: 10px; letter-spacing: 1.3px; text-transform: uppercase; }
  .pill {
    font-size: 11px; font-weight: 500; padding: 4px 11px; border-radius: 999px;
    background: var(--panel-2); color: var(--text-dim); border: 1px solid var(--border-soft);
    display: inline-flex; align-items: center; gap: 6px; white-space: nowrap;
  }
  .pill::before { content: ''; width: 6px; height: 6px; border-radius: 50%; background: var(--text-faint); }
  .pill.on { color: var(--ok); border-color: color-mix(in srgb, var(--ok) 30%, transparent); background: color-mix(in srgb, var(--ok) 10%, var(--panel-2)); }
  .pill.on::before { background: var(--ok); box-shadow: 0 0 6px var(--ok); }
  .pill.off { color: var(--err); border-color: color-mix(in srgb, var(--err) 30%, transparent); background: color-mix(in srgb, var(--err) 10%, var(--panel-2)); }
  .pill.off::before { background: var(--err); }
  .pill.neutral b { color: var(--text); font-weight: 600; }
  .stats-right { margin-left: auto; display: flex; gap: 8px; align-items: center; }

  select, .btn-icon {
    background: var(--panel); color: var(--text); border: 1px solid var(--border); border-radius: 9px;
    padding: 5px 10px; font-size: 12px; cursor: pointer;
    transition: border-color 0.15s, background 0.15s;
  }
  select:hover, .btn-icon:hover { border-color: var(--accent); }
  .btn-icon { width: 32px; height: 32px; padding: 0; display: inline-flex; align-items: center; justify-content: center; }

  /* ==== Tabs ==== */
  nav.tabs {
    padding: 0 20px;
    background: var(--bg-elev);
    border-bottom: 1px solid var(--border);
    display: flex; gap: 2px;
    overflow-x: auto;
    z-index: 4;
  }
  nav.tabs button {
    background: transparent; color: var(--text-dim); border: none;
    padding: 12px 16px; font-size: 12.5px; font-weight: 500; cursor: pointer;
    border-bottom: 2px solid transparent; transition: color 0.15s, border-color 0.15s, background 0.15s;
    white-space: nowrap;
  }
  nav.tabs button:hover { color: var(--text); background: var(--panel-2); }
  nav.tabs button.active { color: var(--accent); border-bottom-color: var(--accent); }
  nav.tabs button .count {
    font-size: 10px; margin-left: 6px; padding: 1px 7px;
    background: var(--panel-2); border-radius: 6px; color: var(--text-dim); font-weight: 500;
  }
  nav.tabs button.active .count { background: color-mix(in srgb, var(--accent) 15%, transparent); color: var(--accent); }

  /* ==== Main + views ==== */
  main { min-height: 0; overflow: hidden; display: flex; flex-direction: column; }
  .view { display: none; flex: 1; overflow-y: auto; padding: 20px 24px; scroll-behavior: smooth; }
  .view.active { display: block; }
  .view::-webkit-scrollbar { width: 8px; }
  .view::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

  /* ==== Overview KPI ==== */
  .overview-grid {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 20px;
  }
  .kpi {
    background: var(--panel); border: 1px solid var(--border-soft); border-radius: 12px;
    padding: 14px 18px; box-shadow: var(--shadow);
  }
  .kpi .label { font-size: 10.5px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 1.1px; margin-bottom: 5px; font-weight: 600; }
  .kpi .value { font-size: 20px; font-weight: 700; color: var(--text); display: flex; align-items: baseline; gap: 6px; }
  .kpi .value small { font-size: 11px; color: var(--text-dim); font-weight: 400; }

  .section-title {
    font-size: 11.5px; font-weight: 700; color: var(--text-dim);
    text-transform: uppercase; letter-spacing: 1.5px;
    margin: 22px 2px 10px;
    display: flex; align-items: center; gap: 10px;
  }
  .section-title::after { content: ''; flex: 1; height: 1px; background: var(--border-soft); }

  /* ==== Agent Card ==== */
  .agent-grid {
    display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 12px; align-items: start;
  }
  .agent-card {
    background: var(--panel); border: 1.5px solid var(--border-soft); border-radius: 14px;
    padding: 13px 15px; transition: border-color 0.2s, transform 0.2s, box-shadow 0.3s;
    position: relative; overflow: hidden; cursor: pointer;
    box-shadow: var(--shadow);
  }
  .agent-card:hover { border-color: var(--accent); transform: translateY(-1px); box-shadow: var(--shadow-lg); }
  .agent-card.mgr { border-left: 3px solid var(--mgr); }
  .agent-card.creator { border-left: 3px solid var(--creator); }
  .agent-card.persona { border-left: 3px solid var(--persona); }
  .agent-card.thinking {
    grid-column: 1 / -1;
    border-color: var(--thinking);
    box-shadow: var(--glow-thinking), var(--shadow-lg);
  }
  .agent-card.speaking {
    grid-column: 1 / -1;
    border-color: var(--speaking);
    box-shadow: var(--glow-speaking), var(--shadow-lg);
  }

  .agent-head { display: flex; align-items: center; gap: 11px; }
  .agent-head .emoji { font-size: 28px; line-height: 1; flex-shrink: 0; }
  .agent-head .info { flex: 1; min-width: 0; }
  .agent-head .name-row { display: flex; align-items: center; gap: 6px; }
  .agent-head .name { font-size: 14px; font-weight: 600; letter-spacing: -0.1px; }
  .agent-head .type-tag {
    font-size: 9.5px; padding: 2px 6px; border-radius: 5px;
    text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600;
  }
  .agent-head .type-tag.mgr { background: color-mix(in srgb, var(--mgr) 15%, transparent); color: var(--mgr); }
  .agent-head .type-tag.creator { background: color-mix(in srgb, var(--creator) 15%, transparent); color: var(--creator); }
  .agent-head .type-tag.persona { background: color-mix(in srgb, var(--persona) 15%, transparent); color: var(--persona); }
  .agent-head .status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--text-faint); }
  .agent-head .status-dot.active { background: var(--ok); box-shadow: 0 0 6px var(--ok); }

  .state-badge {
    font-size: 10.5px; font-weight: 700; padding: 3px 9px; border-radius: 6px;
    letter-spacing: 0.8px; text-transform: uppercase; margin-left: auto;
    display: none;
  }
  .agent-card.thinking .state-badge.thinking { display: inline-block; background: var(--thinking); color: #1a1b25; }
  .agent-card.speaking .state-badge.speaking { display: inline-block; background: var(--speaking); color: #1a1b25; }
  .agent-card.thinking .state-badge.thinking::before { content: '🧠 '; }
  .agent-card.speaking .state-badge.speaking::before { content: '💬 '; }

  .agent-meta { display: flex; gap: 10px; align-items: center; margin-top: 7px; font-size: 11px; color: var(--text-dim); }
  .agent-meta .bar { width: 60px; height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; }
  .agent-meta .bar > span { display: block; height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); transition: width 0.3s; }

  .agent-expanded { display: none; margin-top: 12px; }
  .agent-card.thinking .agent-expanded, .agent-card.speaking .agent-expanded { display: block; }
  .progress-wrap { display: flex; align-items: center; gap: 10px; font-size: 11px; color: var(--text-dim); margin-bottom: 10px; }
  .progress-wrap .elapsed { font-family: "JetBrains Mono", monospace; color: var(--text); font-weight: 600; }
  .progress-bar { flex: 1; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }
  .progress-bar > span {
    display: block; height: 100%; width: 100%;
    background: linear-gradient(90deg, transparent, var(--thinking), transparent);
    background-size: 40% 100%; background-repeat: no-repeat;
    animation: slide 2s linear infinite;
  }
  .agent-card.speaking .progress-bar > span { background: linear-gradient(90deg, transparent, var(--speaking), transparent); background-size: 40% 100%; background-repeat: no-repeat; }
  @keyframes slide { 0% { background-position: -40% 0; } 100% { background-position: 140% 0; } }

  .agent-logs, .agent-chat {
    background: var(--panel-3); border-radius: 8px; padding: 8px 11px;
    font-size: 11px; color: var(--text-dim); margin-bottom: 8px;
  }
  .agent-logs { font-family: "JetBrains Mono", monospace; max-height: 110px; overflow-y: auto; }
  .agent-logs .logline { padding: 1px 0; white-space: pre-wrap; word-break: break-all; }
  .agent-chat .cline { padding: 2px 0; font-size: 11.5px; color: var(--text); }
  .agent-chat .cline b { color: var(--accent-2); margin-right: 6px; font-weight: 600; }
  .agent-chat .cline.user b { color: var(--user); }

  /* ==== Channels ==== */
  .channel-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
  .channel-card {
    background: var(--panel); border: 1px solid var(--border-soft); border-radius: 10px;
    padding: 11px 15px; display: flex; flex-direction: column; gap: 4px; cursor: pointer;
    border-left: 3px solid var(--text-faint); transition: border-color 0.15s, transform 0.2s;
    box-shadow: var(--shadow);
  }
  .channel-card:hover { transform: translateY(-1px); box-shadow: var(--shadow-lg); }
  .channel-card.kind-mgr { border-left-color: var(--mgr); }
  .channel-card.kind-dm { border-left-color: var(--accent); }
  .channel-card.kind-group { border-left-color: var(--ok); }
  .channel-card.kind-internal-dm { border-left-color: var(--cmd); }
  .channel-card.kind-internal-group { border-left-color: var(--creator); }
  .channel-card .name { font-family: "JetBrains Mono", monospace; font-size: 12.5px; font-weight: 500; color: var(--text); }
  .channel-card .name::before { content: '#'; color: var(--text-faint); font-weight: 400; }
  .channel-card .meta { font-size: 10.5px; color: var(--text-dim); display: flex; gap: 8px; }
  .channel-card .meta .sep { color: var(--text-faint); }
  .channel-group-title { font-size: 11px; font-weight: 700; color: var(--text-dim); text-transform: uppercase; letter-spacing: 1.5px; margin: 18px 0 8px; }

  /* ==== Messages ==== */
  .msg-list { display: flex; flex-direction: column; gap: 6px; }
  .msg {
    padding: 9px 13px; border-radius: 9px;
    background: var(--panel); border: 1px solid var(--border-soft);
    border-left: 3px solid var(--persona);
    font-size: 12.5px; box-shadow: var(--shadow);
  }
  .msg.user { border-left-color: var(--user); }
  .msg.mgr { border-left-color: var(--mgr); }
  .msg.creator { border-left-color: var(--creator); }
  .msg.persona { border-left-color: var(--persona); }
  .msg .head { display: flex; gap: 8px; align-items: baseline; font-size: 11px; margin-bottom: 3px; }
  .msg .who { font-weight: 600; color: var(--text); }
  .msg .ch { color: var(--text-faint); font-family: "JetBrains Mono", monospace; font-size: 10.5px; cursor: pointer; }
  .msg .ch:hover { color: var(--accent); }
  .msg .ts { color: var(--text-faint); font-size: 10.5px; margin-left: auto; }
  .msg .text { color: var(--text); word-break: break-word; white-space: pre-wrap; }

  /* ==== Events ==== */
  .event-list { display: flex; flex-direction: column; gap: 5px; }
  .event {
    padding: 8px 13px; font-size: 11.5px;
    background: var(--panel); border: 1px solid var(--border-soft);
    border-left: 2px solid var(--cmd); border-radius: 0 8px 8px 0;
    box-shadow: var(--shadow);
  }
  .event .type { color: var(--cmd); font-weight: 600; margin-right: 8px; }
  .event .desc { color: var(--text-dim); }
  .event .ts { color: var(--text-faint); font-size: 10px; margin-left: 6px; }

  /* ==== Log ==== */
  .log-view {
    font-family: "JetBrains Mono", monospace; font-size: 11.5px;
    white-space: pre-wrap; word-break: break-all;
    background: var(--panel); padding: 14px 18px; border-radius: 10px;
    border: 1px solid var(--border-soft); box-shadow: var(--shadow);
    height: calc(100vh - 200px); overflow-y: auto;
  }
  .log-line { padding: 1px 0; }
  .log-line.err { color: var(--err); }
  .log-line.warn { color: var(--warn); }
  .log-line.ok { color: var(--ok); }
  .log-line.cmd { color: var(--cmd); }
  .log-line.tool { color: var(--cmd); font-weight: 500; }

  /* ==== Detail Modal ==== */
  .detail-backdrop {
    position: fixed; inset: 0; background: rgba(10, 12, 25, 0.5);
    backdrop-filter: blur(6px); z-index: 20; display: none;
    align-items: center; justify-content: center; padding: 24px;
  }
  :root[data-theme="light"] .detail-backdrop { background: rgba(20, 24, 40, 0.25); }
  .detail-backdrop.open { display: flex; }
  .detail-panel {
    background: var(--bg-elev); border: 1px solid var(--border);
    border-radius: 14px; width: 100%; max-width: 960px; max-height: 92vh;
    overflow: hidden; display: flex; flex-direction: column;
    box-shadow: var(--shadow-lg);
  }
  .detail-head {
    padding: 16px 22px; display: flex; align-items: center; gap: 14px;
    border-bottom: 1px solid var(--border);
  }
  .detail-head .d-emoji { font-size: 34px; }
  .detail-head .d-title { font-size: 18px; font-weight: 700; }
  .detail-head .d-close {
    margin-left: auto; background: var(--panel-2); color: var(--text);
    border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px;
    font-size: 12px; cursor: pointer;
  }
  .detail-head .d-close:hover { background: var(--panel-3); }
  .detail-body { padding: 18px 22px; overflow-y: auto; flex: 1; }
  .detail-section {
    margin-bottom: 20px; padding: 14px 16px;
    background: var(--panel); border: 1px solid var(--border-soft); border-radius: 10px;
  }
  .detail-section h4 { font-size: 11px; font-weight: 700; color: var(--text-dim); text-transform: uppercase; letter-spacing: 1.2px; margin-bottom: 10px; }
  .kv { display: grid; grid-template-columns: 110px 1fr; gap: 8px 14px; font-size: 12.5px; }
  .kv dt { color: var(--text-dim); font-weight: 500; }
  .kv dd { color: var(--text); }

  .rel-row { display: flex; align-items: center; gap: 10px; padding: 6px 0; font-size: 12px; }
  .rel-row .rname { font-weight: 600; min-width: 80px; }
  .rel-row .rtype { color: var(--text-dim); }
  .rel-row .intimacy-bar { flex: 1; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }
  .rel-row .intimacy-bar > span { display: block; height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); }
  .rel-row .intimacy-num { font-family: "JetBrains Mono", monospace; font-size: 11px; color: var(--text-dim); min-width: 26px; text-align: right; }

  .mem-block { margin-bottom: 14px; }
  .mem-block h5 { font-size: 12px; font-weight: 600; margin-bottom: 6px; color: var(--text); display: flex; align-items: center; gap: 6px; }
  .mem-block h5 .ch-icon { color: var(--accent); }
  .mem-item { padding: 6px 10px; background: var(--panel-2); border-radius: 6px; margin-bottom: 4px; font-size: 12px; display: flex; gap: 10px; align-items: flex-start; }
  .mem-item .lvl { font-family: "JetBrains Mono", monospace; font-size: 10px; color: var(--accent-2); font-weight: 600; padding-top: 1px; flex-shrink: 0; }
  .mem-item .mcontent { flex: 1; color: var(--text-dim); }
  .mem-item .mts { color: var(--text-faint); font-size: 10px; margin-left: auto; font-family: "JetBrains Mono", monospace; }

  /* ==== Health ==== */
  .health-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }
  .health-card {
    background: var(--panel); border: 1px solid var(--border-soft); border-radius: 12px;
    padding: 16px 20px; box-shadow: var(--shadow);
  }
  .health-card h4 { font-size: 10.5px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 1.2px; margin-bottom: 8px; font-weight: 700; }
  .health-card .big { font-size: 18px; font-weight: 700; color: var(--text); }
  .health-card .sub { font-size: 11px; color: var(--text-dim); margin-top: 4px; }
  .disk-bar { margin-top: 8px; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }
  .disk-bar > span { display: block; height: 100%; background: linear-gradient(90deg, var(--ok), var(--warn)); }

  .empty { padding: 32px 12px; text-align: center; color: var(--text-faint); font-size: 12px; font-style: italic; }

  /* Responsive */
  @media (max-width: 900px) {
    .overview-grid { grid-template-columns: repeat(2, 1fr); }
    .view { padding: 14px 16px; }
  }
</style>
</head><body>
<div class="app">
  <header class="status">
    <span class="brand">◈ Glimi<span class="dot">.</span><small>dashboard</small></span>
    <span id="pills-left"></span>
    <div class="stats-right">
      <span id="pills-right"></span>
      <select class="community-sel" id="community-select" title="커뮤니티 전환"></select>
      <button class="btn-icon" id="theme-toggle" title="테마 전환">☀</button>
    </div>
  </header>

  <nav class="tabs" id="tabs">
    <button data-tab="overview" class="active">Overview</button>
    <button data-tab="agents">Agents <span class="count" id="tc-agents">0</span></button>
    <button data-tab="channels">Channels <span class="count" id="tc-channels">0</span></button>
    <button data-tab="messages">Messages <span class="count" id="tc-messages">0</span></button>
    <button data-tab="events">Events <span class="count" id="tc-events">0</span></button>
    <button data-tab="health">Health</button>
    <button data-tab="sync">Sync</button>
    <button data-tab="dev">Dev</button>
    <button data-tab="usage">Usage</button>
    <button data-tab="logs">Logs</button>
  </nav>

  <main>
    <!-- Overview -->
    <div class="view active" id="view-overview">
      <div class="overview-grid">
        <div class="kpi"><div class="label">Bot Status</div><div class="value" id="kpi-bot">—</div></div>
        <div class="kpi"><div class="label">User</div><div class="value" id="kpi-user">—</div></div>
        <div class="kpi"><div class="label">Onboarding</div><div class="value" id="kpi-phase">—</div></div>
        <div class="kpi"><div class="label">Messages</div><div class="value" id="kpi-msgs">0</div></div>
      </div>
      <div class="section-title">Active Members</div>
      <div class="agent-grid" id="overview-agents"></div>
      <div class="section-title">Recent Conversations</div>
      <div class="msg-list" id="overview-msgs"></div>
    </div>

    <div class="view" id="view-agents"><div class="agent-grid" id="agents-full"></div></div>

    <div class="view" id="view-channels"><div id="channels-full"></div></div>

    <div class="view" id="view-messages"><div class="msg-list" id="messages-full"></div></div>

    <div class="view" id="view-events"><div class="event-list" id="events-full"></div></div>

    <div class="view" id="view-health"><div class="health-grid" id="health-full"></div></div>

    <div class="view" id="view-sync"><div id="sync-full"></div></div>

    <div class="view" id="view-dev"><div id="dev-full"></div></div>

    <div class="view" id="view-usage"><div id="usage-full"></div></div>

    <div class="view" id="view-logs"><div class="log-view" id="logs-full"></div></div>
  </main>
</div>

<!-- Detail Modal -->
<div class="detail-backdrop" id="detail-backdrop">
  <div class="detail-panel">
    <div class="detail-head">
      <span class="d-emoji" id="d-emoji">◆</span>
      <span class="d-title" id="d-title">—</span>
      <button class="d-close" id="d-close">닫기</button>
    </div>
    <div class="detail-body" id="d-body"></div>
  </div>
</div>

<script>
// ==== State ====
const params = new URLSearchParams(location.search);
let COMMUNITY = params.get('community') || null;
let THEME = localStorage.getItem('glimi-theme') || 'light';
document.documentElement.setAttribute('data-theme', THEME);

// ==== Utils ====
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
function fmtBytes(n) {
  if (!n) return '0 B';
  const u = ['B','KB','MB','GB','TB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${u[i]}`;
}
function roleClass(m) {
  if (m.is_user) return 'user';
  const id = m.speaker_id || '';
  if (id.includes('mgr')) return 'mgr';
  if (id.includes('creator')) return 'creator';
  return 'persona';
}
function chIcon(ch) {
  if (!ch) return '📝';
  if (ch.startsWith('mgr')) return '📋';
  if (ch.startsWith('dm-')) return '💬';
  if (ch.startsWith('group-')) return '👥';
  if (ch.startsWith('internal-dm')) return '🔒';
  if (ch.startsWith('internal-group')) return '🔒👥';
  return '📝';
}

// ==== Theme ====
document.getElementById('theme-toggle').addEventListener('click', () => {
  THEME = THEME === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', THEME);
  document.getElementById('theme-toggle').textContent = THEME === 'light' ? '☀' : '🌙';
  localStorage.setItem('glimi-theme', THEME);
});
document.getElementById('theme-toggle').textContent = THEME === 'light' ? '☀' : '🌙';

// ==== Tabs ====
document.querySelectorAll('nav.tabs button').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('nav.tabs button').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('view-' + btn.dataset.tab).classList.add('active');
  });
});

// ==== Renderers ====
function renderAgent(a, clickable=true) {
  const cls = ['agent-card', a.type, a.thinking ? 'thinking' : '', a.speaking ? 'speaking' : ''].filter(Boolean).join(' ');
  const pct = Math.min(100, (a.intensity || 0) * 10);
  const elapsed = a.thinking ? a.thinking_seconds : a.speaking ? a.speaking_seconds : 0;
  const dot = a.status === 'active' ? 'active' : '';

  let expanded = '';
  if (a.thinking || a.speaking) {
    const logs = (a._logs || []).map(l => `<div class="logline">${esc(l)}</div>`).join('');
    const chat = (a._chat || []).map(c =>
      `<div class="cline ${c.is_user ? 'user' : ''}"><b>${esc(c.speaker)}:</b>${esc((c.message||'').slice(0, 90))}</div>`
    ).join('');
    expanded = `<div class="agent-expanded">
      <div class="progress-wrap">
        <span>${a.thinking ? '추론 중' : '전송 중'}</span>
        <div class="progress-bar"><span></span></div>
        <span class="elapsed">${fmtElapsed(elapsed)}</span>
      </div>
      ${logs ? `<div class="agent-logs">${logs}</div>` : ''}
      ${chat ? `<div class="agent-chat">${chat}</div>` : ''}
    </div>`;
  }

  const onclick = clickable ? `onclick="openAgent('${esc(a.id)}')"` : '';
  return `<div class="${cls}" ${onclick}>
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
          <div class="bar"><span style="width:${pct}%"></span></div>
          <span>${a.intensity}/10</span>
          ${a.mbti ? `<span>· ${esc(a.mbti)}</span>` : ''}
          ${a.age ? `<span>· ${a.age}y</span>` : ''}
        </div>
      </div>
      <span class="state-badge thinking">thinking</span>
      <span class="state-badge speaking">speaking</span>
    </div>
    ${expanded}
  </div>`;
}

function renderMessage(m) {
  return `<div class="msg ${roleClass(m)}">
    <div class="head">
      <span class="who">${esc(m.speaker)}</span>
      <span class="ch" onclick="openChannel('${esc(m.channel)}')">#${esc(m.channel)}</span>
      <span class="ts">${esc((m.timestamp||'').slice(11, 19))}</span>
    </div>
    <div class="text">${esc(m.message)}</div>
  </div>`;
}

function renderChannelCard(c) {
  return `<div class="channel-card kind-${c.kind}" onclick="openChannel('${esc(c.name)}')">
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

function renderChannelsGrouped(channels) {
  const groups = { mgr: [], dm: [], group: [], 'internal-dm': [], 'internal-group': [] };
  channels.forEach(c => { (groups[c.kind] || groups.mgr).push(c); });
  const labels = {
    'mgr': '관리 채널',
    'dm': '오너 DM',
    'group': '오너 그룹',
    'internal-dm': '내부 DM (멤버끼리)',
    'internal-group': '내부 그룹 (멤버끼리)',
  };
  let html = '';
  for (const k of ['mgr', 'dm', 'group', 'internal-dm', 'internal-group']) {
    if (!groups[k].length) continue;
    html += `<div class="channel-group-title">${labels[k]} · ${groups[k].length}</div>`;
    html += `<div class="channel-grid">${groups[k].map(renderChannelCard).join('')}</div>`;
  }
  return html || '<div class="empty">no channels</div>';
}

function renderEvent(e) {
  return `<div class="event">
    <span class="type">${esc(e.type)}</span>
    <span class="desc">${esc(e.description)}</span>
    <span class="ts">${esc((e.timestamp||'').slice(11, 19))}</span>
  </div>`;
}

// ==== Detail Modal ====
function openModal(emoji, title, body) {
  document.getElementById('d-emoji').textContent = emoji;
  document.getElementById('d-title').textContent = title;
  document.getElementById('d-body').innerHTML = body;
  document.getElementById('detail-backdrop').classList.add('open');
}
function closeModal() { document.getElementById('detail-backdrop').classList.remove('open'); }
document.getElementById('d-close').addEventListener('click', closeModal);
document.getElementById('detail-backdrop').addEventListener('click', (e) => {
  if (e.target.id === 'detail-backdrop') closeModal();
});

async function openAgent(id) {
  const d = await j(q(`/api/agent?id=${encodeURIComponent(id)}`));
  if (!d || d.error) { openModal('⚠', 'Error', `<div class="empty">${esc(d?.error || 'failed to load')}</div>`); return; }

  const profileLines = [];
  if (d.age) profileLines.push(['Age', `${d.age}y/o`]);
  if (d.mbti) profileLines.push(['MBTI', d.mbti]);
  if (d.enneagram) profileLines.push(['Enneagram', d.enneagram]);
  if (d.traits && d.traits.length) profileLines.push(['Traits', d.traits.slice(0,5).join(' · ')]);
  profileLines.push(['Emotion', `${d.emoji} ${d.emotion} (${d.intensity}/10)`]);
  profileLines.push(['Status', d.thinking ? '🧠 Thinking' : d.speaking ? '💬 Speaking' : (d.status === 'active' ? '● Active' : d.status)]);
  if (d.relationship_to_owner?.type) {
    const r = d.relationship_to_owner;
    profileLines.push(['Owner', `${r.type}${r.pet_name ? ' (' + r.pet_name + ')' : ''}${r.duration ? ' · ' + r.duration : ''}`]);
  }
  if (d.background) profileLines.push(['Background', d.background]);

  const rels = (d.relationships || []).map(r => {
    const pct = Math.min(100, r.intimacy);
    return `<div class="rel-row">
      <span class="rname">${esc(r.other_name)}</span>
      <span class="rtype">${esc(r.type)}</span>
      <div class="intimacy-bar"><span style="width:${pct}%"></span></div>
      <span class="intimacy-num">${r.intimacy}</span>
      ${r.dynamics ? `<span style="color:var(--text-faint);font-size:10.5px">${esc(r.dynamics.slice(0,40))}</span>` : ''}
    </div>`;
  }).join('');

  let memHtml = '';
  for (const [ch, mems] of Object.entries(d.memories_by_channel || {})) {
    memHtml += `<div class="mem-block">
      <h5><span class="ch-icon">${chIcon(ch)}</span> ${esc(ch)} <span style="color:var(--text-faint);font-weight:400">(${mems.length})</span></h5>
      ${mems.map(m => `<div class="mem-item">
        <span class="lvl">L${m.level}${m.mem_type ? '·'+esc(m.mem_type[0].toUpperCase()) : ''}</span>
        <span class="mcontent">${esc(m.content)}</span>
        <span class="mts">${esc((m.created_at||'').slice(5, 16))}</span>
      </div>`).join('')}
    </div>`;
  }

  const thinkingLogs = (d.thinking_logs || []).map(l => `<div class="logline" style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-dim);padding:2px 0">${esc(l)}</div>`).join('');
  const chatHtml = (d.primary_chat || []).map(m => {
    const cls = m.is_user ? 'user' : 'persona';
    return `<div class="msg ${cls}" style="margin-bottom:4px">
      <div class="head"><span class="who">${esc(m.speaker)}</span><span class="ts">${esc((m.timestamp||'').slice(11,19))}</span></div>
      <div class="text">${esc(m.message)}</div>
    </div>`;
  }).join('');

  const body = `
    <div class="detail-section">
      <h4>Profile</h4>
      <dl class="kv">${profileLines.map(([k,v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>
    </div>
    ${rels ? `<div class="detail-section"><h4>Relationships · ${d.relationships.length}</h4>${rels}</div>` : ''}
    ${memHtml ? `<div class="detail-section"><h4>Memory</h4>${memHtml}</div>` : ''}
    ${thinkingLogs ? `<div class="detail-section"><h4>Thinking Logs ${d.thinking ? '<span style="color:var(--thinking)">● LIVE</span>' : ''}</h4>${thinkingLogs}</div>` : ''}
    ${chatHtml ? `<div class="detail-section"><h4>Recent Chat · ${d.primary_channel}</h4>${chatHtml}</div>` : ''}
  `;
  openModal(d.emoji, d.name + ' · ' + d.type, body);
}

async function openChannel(name) {
  const d = await j(q(`/api/channel?name=${encodeURIComponent(name)}`));
  if (!d) { openModal('⚠', 'Error', '<div class="empty">failed to load</div>'); return; }
  const parts = (d.participants || []).map(p => `<span class="pill neutral">${esc(p.name)}${p.type ? ' · ' + esc(p.type) : ''}</span>`).join(' ');
  const msgs = (d.messages || []).map(m => renderMessage(m)).join('');
  const body = `
    <div class="detail-section">
      <h4>Participants · ${d.participants.length}</h4>
      <div style="display:flex;gap:6px;flex-wrap:wrap">${parts || '<span style="color:var(--text-faint)">none</span>'}</div>
    </div>
    <div class="detail-section">
      <h4>All Messages · ${d.message_count}</h4>
      <div class="msg-list">${msgs || '<div class="empty">no messages</div>'}</div>
    </div>`;
  openModal(chIcon(name), '#' + name, body);
}

// ==== Main tick ====
async function tick() {
  const snap = await j(q('/api/snapshot'));
  const logs = await j(q('/api/logs?tail=200'));
  const health = await j(q('/api/health'));
  const dev = await j(q('/api/dev'));
  const usage = await j(q('/api/usage'));
  if (!snap) return;

  COMMUNITY = snap.community_id;
  const b = snap.bot, m = snap.meta;

  document.getElementById('pills-left').innerHTML = [
    `<span class="pill ${b.bot_alive ? 'on' : 'off'}">bot</span>`,
    `<span class="pill ${b.runner_alive ? 'on' : 'neutral'}">runner</span>`,
    `<span class="pill ${b.test_user_alive ? 'on' : 'neutral'}">test-user</span>`,
  ].join('');
  document.getElementById('pills-right').innerHTML = [
    `<span class="pill neutral">phase · <b>${esc(m.onboarding_phase || '—')}</b></span>`,
    `<span class="pill neutral">user · <b>${esc(m.user_name || '—')}</b></span>`,
    `<span class="pill neutral">msgs · <b>${snap.total_messages || 0}</b></span>`,
  ].join('');

  document.getElementById('tc-agents').textContent = snap.agents.length;
  document.getElementById('tc-channels').textContent = snap.channels.length;
  document.getElementById('tc-messages').textContent = snap.recent_messages.length;
  document.getElementById('tc-events').textContent = snap.events.length;

  // 확장된 agent들 로그+채팅 추가 fetch
  const active = snap.agents.filter(a => a.thinking || a.speaking);
  if (active.length) {
    await Promise.all(active.map(async (a) => {
      const extra = await j(q(`/api/agent_activity?id=${encodeURIComponent(a.id)}`));
      if (extra) { a._logs = extra.logs || []; a._chat = extra.chat || []; }
    }));
  }

  // Overview KPIs
  document.getElementById('kpi-bot').innerHTML = b.bot_alive
    ? `<span style="color:var(--ok)">● Running</span>`
    : `<span style="color:var(--err)">○ Stopped</span>`;
  document.getElementById('kpi-user').innerHTML = `${esc(m.user_name || '—')}<small>@${esc(snap.community_id)}</small>`;
  document.getElementById('kpi-phase').innerHTML = esc(m.onboarding_phase || '—');
  document.getElementById('kpi-msgs').innerHTML = `${snap.total_messages}<small>total</small>`;

  document.getElementById('overview-agents').innerHTML =
    snap.agents.map(a => renderAgent(a)).join('') || '<div class="empty">no members</div>';
  const ovMsgs = document.getElementById('overview-msgs');
  const keepOv = atBottom(ovMsgs);
  ovMsgs.innerHTML = snap.recent_messages.slice(-10).map(renderMessage).join('') || '<div class="empty">no conversations yet</div>';
  if (keepOv) ovMsgs.scrollTop = ovMsgs.scrollHeight;

  // Full tabs
  document.getElementById('agents-full').innerHTML =
    snap.agents.map(a => renderAgent(a)).join('') || '<div class="empty">no members</div>';
  document.getElementById('channels-full').innerHTML = renderChannelsGrouped(snap.channels);
  const fm = document.getElementById('messages-full');
  const keepFm = atBottom(fm);
  fm.innerHTML = snap.recent_messages.map(renderMessage).join('') || '<div class="empty">no conversations yet</div>';
  if (keepFm) fm.scrollTop = fm.scrollHeight;
  document.getElementById('events-full').innerHTML =
    snap.events.map(renderEvent).join('') || '<div class="empty">no events</div>';

  // Health
  if (health) {
    const usedPct = health.disk_total_bytes ? (health.disk_used_bytes / health.disk_total_bytes * 100).toFixed(1) : 0;
    document.getElementById('health-full').innerHTML = `
      <div class="health-card">
        <h4>Bot Process</h4>
        <div class="big">${health.bot_alive ? '<span style="color:var(--ok)">● Running</span>' : '<span style="color:var(--err)">○ Stopped</span>'}</div>
        ${health.pid ? `<div class="sub">PID: ${esc(health.pid)}</div>` : ''}
      </div>
      <div class="health-card">
        <h4>QA Runner</h4>
        <div class="big">${health.runner_alive ? '<span style="color:var(--ok)">● Active</span>' : '<span style="color:var(--text-faint)">○ Idle</span>'}</div>
        <div class="sub">${health.test_user_alive ? 'test-user bot alive' : ''}</div>
      </div>
      <div class="health-card">
        <h4>Dev Mode</h4>
        <div class="big">${health.dev_active ? '<span style="color:var(--warn)">● Active</span>' : '<span style="color:var(--text-faint)">○ Off</span>'}</div>
      </div>
      <div class="health-card">
        <h4>DB Size</h4>
        <div class="big">${fmtBytes(health.db_size_bytes)}</div>
      </div>
      <div class="health-card">
        <h4>Log Size</h4>
        <div class="big">${fmtBytes(health.log_size_bytes)}</div>
      </div>
      <div class="health-card">
        <h4>Disk Usage</h4>
        <div class="big">${fmtBytes(health.disk_used_bytes)} / ${fmtBytes(health.disk_total_bytes)}</div>
        <div class="sub">free: ${fmtBytes(health.disk_free_bytes)}</div>
        <div class="disk-bar"><span style="width:${usedPct}%"></span></div>
      </div>
    `;
  }

  // Sync (read-only view of channels needing sync etc.)
  document.getElementById('sync-full').innerHTML = `
    <div class="detail-section" style="margin-top:0">
      <h4>Sync Status</h4>
      <div style="color:var(--text-dim);font-size:12.5px;line-height:1.6">
        현재 DB에 등록된 채널과 Discord 쪽 채널 비교는 bot 프로세스만 할 수 있음.<br>
        이 대시보드는 read-only 관찰 뷰 — Scan/Sync 실행은 <b>wizard</b>에서 진행:<br>
        <code style="background:var(--panel-2);padding:2px 6px;border-radius:4px">python -m src.tui.wizard</code>
      </div>
    </div>
    <div class="detail-section">
      <h4>DB-registered Channels · ${snap.channels.length}</h4>
      ${renderChannelsGrouped(snap.channels)}
    </div>
  `;

  // Dev
  if (dev) {
    const p = dev.pending, r = dev.result;
    document.getElementById('dev-full').innerHTML = `
      <div class="detail-section" style="margin-top:0">
        <h4>Dev Mode Status</h4>
        <div class="big" style="font-size:16px">${dev.active ? '<span style="color:var(--warn)">● Opus 작업 중</span>' : '<span style="color:var(--text-faint)">○ 대기</span>'}</div>
      </div>
      ${p ? `<div class="detail-section"><h4>Pending Request</h4><pre style="white-space:pre-wrap;font-family:'JetBrains Mono',monospace;font-size:11.5px;color:var(--text-dim)">${esc(JSON.stringify(p, null, 2))}</pre></div>` : ''}
      ${r ? `<div class="detail-section"><h4>Last Result</h4><pre style="white-space:pre-wrap;font-family:'JetBrains Mono',monospace;font-size:11.5px;color:var(--text-dim)">${esc(JSON.stringify(r, null, 2))}</pre></div>` : ''}
      ${!p && !r ? '<div class="empty">No dev activity</div>' : ''}
    `;
  }

  // Usage
  if (usage) {
    const entries = Object.entries(usage).filter(([k,v]) => typeof v !== 'object');
    document.getElementById('usage-full').innerHTML = `
      <div class="overview-grid">
        ${entries.map(([k, v]) => `
          <div class="kpi">
            <div class="label">${esc(k.replace(/_/g, ' '))}</div>
            <div class="value">${esc(String(v))}</div>
          </div>`).join('')}
      </div>
      <div class="detail-section">
        <h4>Source</h4>
        <div style="color:var(--text-dim);font-size:12px">
          ${usage.source === 'log-derived'
            ? 'Derived from recent system.log — CLI 호출 카운트 근사치 (~/.claude/usage.json 없을 때 폴백)'
            : `External source: ${esc(usage.source || 'unknown')}`}
        </div>
      </div>
    `;
  }

  // Logs
  if (logs && logs.lines) {
    const logEl = document.getElementById('logs-full');
    const keepLog = atBottom(logEl);
    logEl.innerHTML = logs.lines.map(l => `<div class="log-line ${classifyLog(l)}">${esc(l)}</div>`).join('') || '<div class="empty">(log empty)</div>';
    if (keepLog) logEl.scrollTop = logEl.scrollHeight;
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

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
});

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


def _read_query(path: str, key: str, default: Optional[str] = None) -> Optional[str]:
    q = parse_qs(urlparse(path).query)
    v = q.get(key, [default])[0]
    return v


def api_snapshot(path):
    if _read_community(path):
        _set_active_community(_read_community(path))
    from src.core import monitor
    snap = monitor.snapshot()
    for c in snap["channels"]:
        c["last_ago"] = monitor.human_ago(c["last_ts"])
    return snap


def api_logs(path):
    if _read_community(path):
        _set_active_community(_read_community(path))
    from src.core import monitor
    tail = int(_read_query(path, "tail", "150") or 150)
    return {"lines": monitor.get_recent_system_logs(tail_lines=tail)}


def api_agent_activity(path):
    if _read_community(path):
        _set_active_community(_read_community(path))
    from src.core import monitor
    aid = _read_query(path, "id", "")
    if not aid:
        return {"logs": [], "chat": []}
    return {
        "logs": monitor.get_agent_thinking_logs(aid, n=5),
        "chat": monitor.get_agent_recent_chat(aid, limit=3),
    }


def api_agent_detail(path):
    if _read_community(path):
        _set_active_community(_read_community(path))
    from src.core import monitor
    aid = _read_query(path, "id", "")
    if not aid:
        return {"error": "missing id"}
    return monitor.get_agent_detail(aid)


def api_channel_detail(path):
    if _read_community(path):
        _set_active_community(_read_community(path))
    from src.core import monitor
    name = _read_query(path, "name", "")
    if not name:
        return {"error": "missing name"}
    return monitor.get_channel_detail(name)


def api_health(path):
    if _read_community(path):
        _set_active_community(_read_community(path))
    from src.core import monitor
    return monitor.get_health()


def api_dev(path):
    if _read_community(path):
        _set_active_community(_read_community(path))
    from src.core import monitor
    return monitor.get_dev_state()


def api_usage(path):
    if _read_community(path):
        _set_active_community(_read_community(path))
    from src.core import monitor
    return monitor.get_usage_stats()


def api_communities():
    from src import community as _comm
    return {"items": _comm.list_communities(), "active": _comm.get_community_id()}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a, **kw):
        return

    def _send(self, status, body, ct):
        self.send_response(status)
        self.send_header("Content-Type", ct)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self._send(200, body, "application/json; charset=utf-8")

    def _html(self, text):
        self._send(200, text.encode("utf-8"), "text/html; charset=utf-8")

    def do_GET(self):
        p = urlparse(self.path).path
        try:
            if p in ("/", "/index.html"):
                self._html(HTML)
            elif p == "/api/snapshot":
                self._json(api_snapshot(self.path))
            elif p == "/api/logs":
                self._json(api_logs(self.path))
            elif p == "/api/agent_activity":
                self._json(api_agent_activity(self.path))
            elif p == "/api/agent":
                self._json(api_agent_detail(self.path))
            elif p == "/api/channel":
                self._json(api_channel_detail(self.path))
            elif p == "/api/health":
                self._json(api_health(self.path))
            elif p == "/api/dev":
                self._json(api_dev(self.path))
            elif p == "/api/usage":
                self._json(api_usage(self.path))
            elif p == "/api/communities":
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
    parser.add_argument("community", nargs="?", default=None)
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
