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

  /* ==== Community switcher ==== */
  .community-btn {
    position: relative; display: flex; align-items: center; gap: 8px;
    background: var(--panel); color: var(--text); border: 1px solid var(--border);
    border-radius: 10px; padding: 6px 12px 6px 10px; font-size: 12.5px;
    font-weight: 600; cursor: pointer; transition: border-color 0.15s, background 0.15s;
  }
  .community-btn:hover { border-color: var(--accent); }
  .community-btn .sv-dot {
    width: 7px; height: 7px; border-radius: 50%; background: var(--ok);
    box-shadow: 0 0 6px var(--ok); animation: live-pulse 1.8s infinite;
  }
  .community-btn.idle .sv-dot { background: var(--text-faint); box-shadow: none; animation: none; }
  .community-btn .chev { font-size: 9px; color: var(--text-faint); margin-left: 4px; }
  @keyframes live-pulse {
    0%, 100% { box-shadow: 0 0 6px var(--ok); }
    50% { box-shadow: 0 0 12px var(--ok); }
  }

  .community-menu {
    display: none; position: absolute; top: 100%; right: 0; margin-top: 6px;
    background: var(--bg-elev); border: 1px solid var(--border); border-radius: 12px;
    min-width: 260px; box-shadow: var(--shadow-lg); z-index: 50;
    padding: 6px; overflow: hidden;
  }
  .community-menu.open { display: block; }
  .community-menu .ci {
    display: flex; align-items: center; gap: 10px; padding: 10px 12px;
    border-radius: 8px; cursor: pointer; transition: background 0.12s;
    font-size: 13px;
  }
  .community-menu .ci:hover { background: var(--panel-2); }
  .community-menu .ci.active { background: color-mix(in srgb, var(--accent) 10%, transparent); }
  .community-menu .ci.idle { opacity: 0.5; }
  .community-menu .ci .ci-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 6px var(--ok); flex-shrink: 0; }
  .community-menu .ci.idle .ci-dot { background: var(--text-faint); box-shadow: none; }
  .community-menu .ci .ci-name { flex: 1; font-weight: 600; font-family: "JetBrains Mono", monospace; font-size: 12.5px; }
  .community-menu .ci .ci-meta { font-size: 10.5px; color: var(--text-dim); font-weight: 400; }
  .community-menu .ci .ci-check { color: var(--accent); font-weight: 700; }
  .community-menu .ci.active .ci-check::before { content: '✓'; }
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
    display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin-bottom: 20px;
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

  /* ==== Avatar ==== */
  .avatar {
    position: relative; flex-shrink: 0; display: inline-block;
    width: 44px; height: 44px; border-radius: 50%;
    background: var(--panel-2); overflow: hidden;
    border: 2px solid var(--border-soft);
  }
  .avatar img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .avatar .emoji-badge {
    position: absolute; bottom: -2px; right: -2px;
    width: 20px; height: 20px; border-radius: 50%;
    background: var(--bg-elev); display: flex; align-items: center; justify-content: center;
    font-size: 13px; border: 2px solid var(--bg-elev); box-shadow: var(--shadow);
  }
  .avatar .emoji-badge.hidden { display: none; }
  .avatar.xl { width: 72px; height: 72px; border-width: 3px; }
  .avatar.xl .emoji-badge { width: 26px; height: 26px; font-size: 16px; bottom: -4px; right: -4px; }
  .avatar.xxl { width: 104px; height: 104px; border-width: 3px; }
  .avatar.xxl .emoji-badge { width: 34px; height: 34px; font-size: 20px; bottom: -4px; right: -4px; border-width: 3px; }

  /* Emotion ring around avatar (colored based on intensity) */
  .avatar.ring { border-color: var(--accent); }
  .avatar.ring-5 { border-color: color-mix(in srgb, var(--warn) 50%, var(--border)); }
  .avatar.ring-7 { border-color: var(--warn); }
  .avatar.ring-9 { border-color: var(--err); box-shadow: 0 0 12px color-mix(in srgb, var(--err) 40%, transparent); }
  .avatar.thinking-ring { border-color: var(--thinking); animation: ring-pulse 1.6s infinite; }
  .avatar.speaking-ring { border-color: var(--speaking); animation: ring-pulse 1.2s infinite; }
  @keyframes ring-pulse {
    0%, 100% { box-shadow: 0 0 0 0 color-mix(in srgb, currentColor 40%, transparent); }
    50% { box-shadow: 0 0 0 4px color-mix(in srgb, currentColor 10%, transparent); }
  }

  /* ==== Offline Mode ==== */
  body.offline .agent-card {
    opacity: 0.55; filter: saturate(0.5) grayscale(0.3);
  }
  body.offline .agent-card .status-dot.active { background: var(--text-faint); box-shadow: none; }
  body.offline .agent-card.thinking, body.offline .agent-card.speaking {
    /* 오프라인인데 DB에 thinking 플래그가 남아있으면 stale → 애니메이션 중지 */
    grid-column: auto;
    animation: none; box-shadow: var(--shadow);
  }
  body.offline .agent-card.thinking .agent-expanded,
  body.offline .agent-card.speaking .agent-expanded { display: none; }
  body.offline .progress-bar > span { animation: none; }
  body.offline .avatar.thinking-ring, body.offline .avatar.speaking-ring { animation: none; }

  .offline-banner {
    padding: 10px 16px; margin-bottom: 18px; border-radius: 10px;
    background: color-mix(in srgb, var(--err) 8%, var(--panel));
    border: 1px solid color-mix(in srgb, var(--err) 30%, transparent);
    color: var(--err); font-size: 12.5px; font-weight: 500;
    align-items: center; gap: 10px;
    display: none;
  }
  body.offline .offline-banner { display: flex; }
  .offline-banner::before { content: '⏸'; font-size: 16px; }
  .offline-banner b { color: var(--err); }
  .offline-banner span.muted { color: var(--text-dim); font-weight: 400; margin-left: auto; }

  /* ==== Hero Overview ==== */
  .hero {
    background: var(--panel);
    border: 1px solid var(--border-soft);
    border-radius: 18px;
    padding: 24px 28px;
    margin-bottom: 20px;
    box-shadow: var(--shadow);
    position: relative; overflow: hidden;
  }
  body.offline .hero { opacity: 0.85; }
  body.offline .hero::before { display: none; }
  .hero::before {
    content: ''; position: absolute; top: 0; right: 0; width: 60%; height: 100%;
    background: radial-gradient(ellipse at top right, color-mix(in srgb, var(--accent) 8%, transparent), transparent 70%);
    pointer-events: none;
  }
  .hero-row { display: flex; align-items: center; gap: 20px; position: relative; }
  .hero-avatars { display: flex; }
  .hero-avatars .avatar { margin-left: -12px; transition: transform 0.2s, z-index 0s 0.2s; }
  .hero-avatars .avatar:first-child { margin-left: 0; }
  .hero-avatars .avatar:hover { transform: translateY(-3px) scale(1.05); z-index: 2; transition: transform 0.2s, z-index 0s; }
  .hero-text h1 {
    font-size: 20px; font-weight: 700; letter-spacing: -0.3px; margin-bottom: 2px;
    display: flex; align-items: center; gap: 8px;
  }
  .hero-text h1 .sv-name { color: var(--accent); }
  .hero-text p {
    color: var(--text-dim); font-size: 13px; line-height: 1.6;
  }
  .hero-pill-row { display: flex; gap: 6px; margin-top: 10px; flex-wrap: wrap; }

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

  .agent-head { display: flex; align-items: center; gap: 12px; }
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

  .model-tag {
    font-size: 9.5px; padding: 1.5px 6px; border-radius: 5px;
    font-family: "JetBrains Mono", monospace; font-weight: 500;
    background: var(--panel-2); color: var(--text-dim); border: 1px solid var(--border-soft);
    display: inline-flex; align-items: center; gap: 3px;
  }
  .model-tag::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: currentColor; }
  .model-tag.claude { color: #d97706; }
  .model-tag.openai { color: #10a37f; }
  .model-tag.local { color: #3b82f6; }
  .model-tag.other { color: var(--text-dim); }
  .model-tag.override { border-color: var(--accent); color: var(--accent); }
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
    display: flex; gap: 10px; align-items: flex-start;
  }
  .msg .msg-avatar {
    width: 28px; height: 28px; border-radius: 50%; background: var(--panel-2);
    overflow: hidden; flex-shrink: 0; border: 1.5px solid var(--border-soft); cursor: pointer;
    transition: border-color 0.15s;
  }
  .msg .msg-avatar:hover { border-color: var(--accent); }
  .msg .msg-avatar img { width: 100%; height: 100%; object-fit: cover; display: block; }
  .msg .msg-avatar.user {
    display: flex; align-items: center; justify-content: center;
    background: color-mix(in srgb, var(--user) 15%, var(--panel-2));
    color: var(--user); font-weight: 700; font-size: 11px;
  }
  .msg .msg-body { flex: 1; min-width: 0; }
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

  /* ==== Lightbox (full avatar) ==== */
  .lightbox {
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.85);
    backdrop-filter: blur(10px); z-index: 100;
    align-items: center; justify-content: center; padding: 40px; cursor: zoom-out;
  }
  .lightbox.open { display: flex; }
  .lightbox img { max-width: 90vw; max-height: 90vh; border-radius: 12px; box-shadow: 0 30px 80px rgba(0,0,0,0.6); }
  .lightbox .lb-caption { position: absolute; bottom: 30px; left: 50%; transform: translateX(-50%); color: #fff; font-size: 14px; font-weight: 600; letter-spacing: 0.3px; text-shadow: 0 2px 8px rgba(0,0,0,0.8); }

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
    padding: 14px 20px; display: flex; align-items: center; gap: 14px;
    border-bottom: 1px solid var(--border); flex-shrink: 0;
  }
  .detail-head .d-emoji { font-size: 28px; line-height: 1; flex-shrink: 0; display: flex; }
  .detail-head .d-emoji .avatar { margin: 0; cursor: pointer; }
  .detail-head .d-emoji .avatar:hover { transform: scale(1.05); transition: transform 0.15s; }
  .detail-head .d-title { font-size: 17px; font-weight: 700; letter-spacing: -0.2px; flex: 1; min-width: 0; }
  .detail-head .d-title small { color: var(--text-dim); font-size: 12px; font-weight: 500; margin-left: 8px; }
  .detail-head .d-close {
    flex-shrink: 0; background: var(--panel-2); color: var(--text);
    border: 1px solid var(--border); border-radius: 8px; padding: 6px 14px;
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
    <div style="position:relative" id="community-switcher-wrap">
      <button class="community-btn" id="community-btn" title="커뮤니티 전환">
        <span class="sv-dot"></span>
        <span id="community-btn-name">—</span>
        <span class="chev">▾</span>
      </button>
      <div class="community-menu" id="community-menu"></div>
    </div>
    <span id="pills-left"></span>
    <div class="stats-right">
      <span id="pills-right"></span>
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
      <div class="offline-banner" id="offline-banner">
        <b>오프라인</b> — 커뮤니티 서버가 실행 중이 아님. 마지막 스냅샷 표시 중 (실시간 아님)
        <span class="muted" id="offline-last"></span>
      </div>
      <div class="hero" id="hero"></div>
      <div class="overview-grid">
        <div class="kpi"><div class="label">Server Status</div><div class="value" id="kpi-server">—</div></div>
        <div class="kpi"><div class="label">Discord Bot</div><div class="value" id="kpi-bot">—</div></div>
        <div class="kpi"><div class="label">Owner</div><div class="value" id="kpi-user">—</div></div>
        <div class="kpi"><div class="label">Onboarding</div><div class="value" id="kpi-phase">—</div></div>
        <div class="kpi"><div class="label">Messages</div><div class="value" id="kpi-msgs">0</div></div>
      </div>
      <div class="section-title">Agents</div>
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

<!-- Lightbox (full avatar) -->
<div class="lightbox" id="lightbox" onclick="this.classList.remove('open')">
  <img id="lightbox-img" src="" alt="">
  <div class="lb-caption" id="lightbox-caption"></div>
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
function avatarHtml(a, size='', opts={}) {
  const cls = ['avatar', size];
  if (a.thinking) cls.push('thinking-ring');
  else if (a.speaking) cls.push('speaking-ring');
  else if (a.intensity >= 9) cls.push('ring-9');
  else if (a.intensity >= 7) cls.push('ring-7');
  else if (a.intensity >= 5) cls.push('ring-5');
  const src = `/api/avatar?id=${encodeURIComponent(a.id)}${COMMUNITY ? '&community=' + encodeURIComponent(COMMUNITY) : ''}`;
  // 평온 + 낮은 강도면 emoji badge 숨김
  const hideBadge = a.emotion === '평온' || opts.hideBadge;
  const clickOpen = opts.clickOpen !== false;
  const onclick = clickOpen ? `onclick="event.stopPropagation(); openFullAvatar('${esc(a.id)}', '${esc(a.name)}')"` : '';
  return `<div class="${cls.filter(Boolean).join(' ')}" title="${esc(a.name)}" ${onclick}>
    <img src="${src}" alt="${esc(a.name)}" loading="lazy" onerror="this.style.display='none'">
    <span class="emoji-badge ${hideBadge ? 'hidden' : ''}">${a.emoji}</span>
  </div>`;
}

function miniAvatarHtml(speakerId, isUser, speakerName) {
  if (isUser) {
    const initial = (speakerName || '?').slice(0, 1);
    return `<div class="msg-avatar user" title="${esc(speakerName)}">${esc(initial)}</div>`;
  }
  const src = `/api/avatar?id=${encodeURIComponent(speakerId)}${COMMUNITY ? '&community=' + encodeURIComponent(COMMUNITY) : ''}`;
  return `<div class="msg-avatar" title="${esc(speakerName)}" onclick="openFullAvatar('${esc(speakerId)}', '${esc(speakerName)}')">
    <img src="${src}" alt="${esc(speakerName)}" loading="lazy" onerror="this.parentElement.innerHTML='<div style=&quot;display:flex;align-items:center;justify-content:center;width:100%;height:100%;font-size:11px;color:var(--text-faint)&quot;>?</div>'">
  </div>`;
}

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
      ${avatarHtml(a)}
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
          ${a.model ? `<span class="model-tag ${a.provider}${a.model_override ? ' override' : ''}" title="${a.model_override ? 'per-agent override' : 'default by type'}">${esc(a.model)}</span>` : ''}
        </div>
      </div>
      <span class="state-badge thinking">thinking</span>
      <span class="state-badge speaking">speaking</span>
    </div>
    ${expanded}
  </div>`;
}

function renderHero(snap) {
  const m = snap.meta;
  const persona = snap.agents.filter(a => a.type === 'persona');
  const mgrs = snap.agents.filter(a => a.type !== 'persona');
  const all = [...mgrs, ...persona];
  const avatarsHtml = all.slice(0, 8).map(a => avatarHtml(a, 'xl')).join('');
  const active = snap.agents.filter(a => a.thinking || a.speaking);
  const offline = !snap.bot.bot_alive;
  let activeText;
  if (offline) {
    activeText = `<span style="color:var(--text-dim)">서버 오프라인 · 마지막 스냅샷</span>`;
  } else if (active.length) {
    const names = active.map(a => `<b style="color:${a.thinking ? 'var(--thinking)' : 'var(--speaking)'}">${esc(a.name)}</b>`).join(', ');
    const tAct = active.some(x => x.thinking);
    const sAct = active.some(x => x.speaking);
    const verb = tAct && sAct ? '생각 · 응답 중' : tAct ? '생각 중' : '응답 중';
    activeText = `${names} ${verb}`;
  } else {
    activeText = `<span style="color:var(--text-dim)">평온 · 모두 대기 중</span>`;
  }

  const userName = m.user_name || '—';
  const phase = m.onboarding_phase || '—';
  const msgCount = snap.total_messages || 0;
  const cm = snap.community_meta || {};
  const descText = cm.description || cm.name || `${userName}의 커뮤니티`;

  return `<div class="hero-row">
    <div class="hero-avatars">
      ${avatarsHtml || '<div style="color:var(--text-faint)">no agents yet</div>'}
    </div>
    <div class="hero-text" style="flex:1">
      <h1><span class="sv-name">${esc(snap.community_id)}</span> · <span style="color:var(--text)">${esc(descText)}</span></h1>
      <p>${activeText}</p>
      <div class="hero-pill-row">
        <span class="pill neutral">owner · <b>${esc(userName)}</b></span>
        <span class="pill neutral">agents · <b>${snap.agents.length}</b></span>
        <span class="pill neutral">channels · <b>${snap.channels.length}</b></span>
        <span class="pill neutral">messages · <b>${msgCount}</b></span>
        <span class="pill neutral">phase · <b>${esc(phase)}</b></span>
      </div>
    </div>
  </div>`;
}

function openFullAvatar(agentId, name) {
  const box = document.getElementById('lightbox');
  const img = document.getElementById('lightbox-img');
  const cap = document.getElementById('lightbox-caption');
  const src = `/api/avatar?id=${encodeURIComponent(agentId)}&variant=full${COMMUNITY ? '&community=' + encodeURIComponent(COMMUNITY) : ''}`;
  img.src = src;
  cap.textContent = name || agentId;
  box.classList.add('open');
}

function renderMessage(m) {
  return `<div class="msg ${roleClass(m)}">
    ${miniAvatarHtml(m.speaker_id, m.is_user, m.speaker)}
    <div class="msg-body">
      <div class="head">
        <span class="who">${esc(m.speaker)}</span>
        <span class="ch" onclick="event.stopPropagation(); openChannel('${esc(m.channel)}')">#${esc(m.channel)}</span>
        <span class="ts">${esc((m.timestamp||'').slice(11, 19))}</span>
      </div>
      <div class="text">${esc(m.message)}</div>
    </div>
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
function openModal(emoji, title, body, agent=null) {
  const emojiEl = document.getElementById('d-emoji');
  if (agent && agent.id) {
    // xxl 아바타로 — 56×56 정도. 클릭하면 -full 버전 lightbox
    emojiEl.innerHTML = avatarHtml({...agent, emotion: agent.emotion}, 'xl', { clickOpen: true });
  } else {
    emojiEl.innerHTML = `<span style="font-size:30px">${esc(emoji)}</span>`;
  }
  const titleEl = document.getElementById('d-title');
  titleEl.innerHTML = esc(title.split(' · ')[0]) + (title.includes(' · ') ? `<small>${esc(title.split(' · ').slice(1).join(' · '))}</small>` : '');
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
  if (d.model) profileLines.push(['Model', `<span class="model-tag ${d.provider}${d.model_override ? ' override' : ''}">${esc(d.model)}</span>${d.model_override ? ' <small style="color:var(--accent)">override</small>' : '<small style="color:var(--text-faint)"> · default</small>'}`, true]);
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
  const chatHtml = (d.primary_chat || []).map(m => renderMessage({...m, channel: d.primary_channel})).join('');

  const body = `
    <div class="detail-section">
      <h4>Profile</h4>
      <dl class="kv">${profileLines.map(([k,v,raw]) => `<dt>${esc(k)}</dt><dd>${raw ? v : esc(v)}</dd>`).join('')}</dl>
    </div>
    ${rels ? `<div class="detail-section"><h4>Relationships · ${d.relationships.length}</h4>${rels}</div>` : ''}
    ${memHtml ? `<div class="detail-section"><h4>Memory</h4>${memHtml}</div>` : ''}
    ${thinkingLogs ? `<div class="detail-section"><h4>Thinking Logs ${d.thinking ? '<span style="color:var(--thinking)">● LIVE</span>' : ''}</h4>${thinkingLogs}</div>` : ''}
    ${chatHtml ? `<div class="detail-section"><h4>Recent Chat · ${d.primary_channel}</h4>${chatHtml}</div>` : ''}
  `;
  openModal(d.emoji, d.name + ' · ' + d.type, body, d);
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

  // Offline 모드 토글 — 봇이 실제로 안 돌면 전체 UI dim + 안내
  if (b.bot_alive) document.body.classList.remove('offline');
  else document.body.classList.add('offline');

  // 마지막 활동 시각 계산 (에이전트 last_active 중 최대값)
  const lastActives = snap.agents.map(a => a.last_active).filter(Boolean).sort();
  if (!b.bot_alive && lastActives.length) {
    const last = lastActives[lastActives.length - 1];
    document.getElementById('offline-last').textContent = `마지막 활동: ${last.slice(0, 19).replace('T', ' ')}`;
  } else {
    document.getElementById('offline-last').textContent = '';
  }

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

  // Hero section
  document.getElementById('hero').innerHTML = renderHero(snap);

  // Overview KPIs
  // Server Status = 서버 전체 살아있는지 (bot alive 기반)
  document.getElementById('kpi-server').innerHTML = b.bot_alive
    ? `<span style="color:var(--ok)">● Online</span>`
    : `<span style="color:var(--err)">○ Offline</span>`;
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
    const diskPct = health.disk_total_bytes ? (health.disk_used_bytes / health.disk_total_bytes * 100).toFixed(1) : 0;
    const memPct = health.sys_mem_pct || 0;
    const glimiMemPct = health.sys_mem_total_bytes ? (health.glimi_mem_bytes / health.sys_mem_total_bytes * 100).toFixed(1) : 0;
    document.getElementById('health-full').innerHTML = `
      <div style="margin-bottom:18px">
        <div class="section-title" style="margin-top:0">Processes</div>
        <div class="health-grid">
          <div class="health-card">
            <h4>Discord Bot</h4>
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
        </div>
      </div>

      <div style="margin-bottom:18px">
        <div class="section-title" style="margin-top:0">Glimi Resource Usage</div>
        <div class="health-grid">
          <div class="health-card">
            <h4>CPU (Glimi procs)</h4>
            <div class="big">${health.glimi_cpu_pct.toFixed(1)}<small style="font-size:13px;color:var(--text-dim)">%</small></div>
            <div class="sub">${health.glimi_proc_count} process${health.glimi_proc_count === 1 ? '' : 'es'}</div>
          </div>
          <div class="health-card">
            <h4>RAM (Glimi procs)</h4>
            <div class="big">${fmtBytes(health.glimi_mem_bytes)}</div>
            <div class="sub">${glimiMemPct}% of system RAM</div>
            <div class="disk-bar"><span style="width:${Math.min(100, parseFloat(glimiMemPct))}%"></span></div>
          </div>
          <div class="health-card">
            <h4>DB Size</h4>
            <div class="big">${fmtBytes(health.db_size_bytes)}</div>
            <div class="sub">community SQLite</div>
          </div>
          <div class="health-card">
            <h4>Log Size</h4>
            <div class="big">${fmtBytes(health.log_size_bytes)}</div>
            <div class="sub">system.log</div>
          </div>
        </div>
      </div>

      <div style="margin-bottom:18px">
        <div class="section-title" style="margin-top:0">System Resources</div>
        <div class="health-grid">
          <div class="health-card">
            <h4>System CPU</h4>
            <div class="big">${health.sys_cpu_pct.toFixed(1)}<small style="font-size:13px;color:var(--text-dim)">%</small></div>
            <div class="sub">load: ${health.sys_load_1m} / ${health.sys_load_5m} / ${health.sys_load_15m}</div>
            <div class="disk-bar"><span style="width:${Math.min(100, health.sys_cpu_pct)}%"></span></div>
          </div>
          <div class="health-card">
            <h4>System RAM</h4>
            <div class="big">${fmtBytes(health.sys_mem_used_bytes)} <small style="font-size:12px;color:var(--text-dim)">/ ${fmtBytes(health.sys_mem_total_bytes)}</small></div>
            <div class="sub">${memPct}% used</div>
            <div class="disk-bar"><span style="width:${memPct}%"></span></div>
          </div>
          <div class="health-card">
            <h4>Disk</h4>
            <div class="big">${fmtBytes(health.disk_used_bytes)} <small style="font-size:12px;color:var(--text-dim)">/ ${fmtBytes(health.disk_total_bytes)}</small></div>
            <div class="sub">free: ${fmtBytes(health.disk_free_bytes)} · ${diskPct}% used</div>
            <div class="disk-bar"><span style="width:${diskPct}%"></span></div>
          </div>
          <div class="health-card" style="opacity:0.5">
            <h4>GPU</h4>
            <div class="big" style="font-size:13px;color:var(--text-faint)">N/A on macOS</div>
            <div class="sub">powermetrics requires sudo</div>
          </div>
        </div>
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
  const btn = document.getElementById('community-btn');
  const menu = document.getElementById('community-menu');
  const activeItem = (d.items || []).find(c => c.id === d.active);

  // 버튼 업데이트 (현재 선택된 커뮤니티)
  document.getElementById('community-btn-name').textContent = d.active;
  if (activeItem && activeItem.running) btn.classList.remove('idle');
  else btn.classList.add('idle');

  // 메뉴 생성
  menu.innerHTML = (d.items || []).map(c => {
    const cls = ['ci'];
    if (c.id === d.active) cls.push('active');
    if (!c.running) cls.push('idle');
    const meta = c.running
      ? `<span class="ci-meta" style="color:var(--ok)">● running${c.last_log_age_sec != null ? ` · ${c.last_log_age_sec}s ago` : ''}</span>`
      : `<span class="ci-meta">○ idle${c.last_log_age_sec != null ? ` · ${c.last_log_age_sec}s ago` : ''}</span>`;
    return `<div class="${cls.join(' ')}" data-cid="${esc(c.id)}">
      <span class="ci-dot"></span>
      <div style="flex:1">
        <div class="ci-name">${esc(c.id)}</div>
        ${meta}
      </div>
      <span class="ci-check"></span>
    </div>`;
  }).join('') || '<div class="empty">no communities</div>';

  // 아이템 클릭 → 전환
  menu.querySelectorAll('.ci').forEach(el => {
    el.addEventListener('click', () => {
      COMMUNITY = el.dataset.cid;
      menu.classList.remove('open');
      const url = new URL(location.href);
      url.searchParams.set('community', COMMUNITY);
      history.replaceState(null, '', url);
      tick();
      loadCommunities();
    });
  });
}

// 버튼 클릭으로 메뉴 토글
document.getElementById('community-btn').addEventListener('click', (e) => {
  e.stopPropagation();
  document.getElementById('community-menu').classList.toggle('open');
});
document.addEventListener('click', (e) => {
  const wrap = document.getElementById('community-switcher-wrap');
  if (wrap && !wrap.contains(e.target)) {
    document.getElementById('community-menu').classList.remove('open');
  }
});

document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
});

loadCommunities();
tick();
setInterval(tick, 1500);
setInterval(loadCommunities, 5000);  // 커뮤니티 running 상태 5초마다 갱신
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
    """각 커뮤니티의 running 상태까지 포함해서 반환.

    running 판별: communities/{id}/logs/system.log가 최근 120초 내 수정됨.
    (로그 라이터가 주기적으로 쓰므로 활성 봇은 파일 mtime이 계속 갱신됨)
    """
    from src import community as _comm
    import time as _t

    items = _comm.list_communities()
    active_id = _comm.get_community_id()
    now = _t.time()

    for it in items:
        try:
            log_path = ROOT / "communities" / it["id"] / "logs" / "system.log"
            if log_path.exists():
                mtime = log_path.stat().st_mtime
                age = now - mtime
                it["running"] = age < 120
                it["last_log_age_sec"] = int(age)
            else:
                it["running"] = False
                it["last_log_age_sec"] = None
        except Exception:
            it["running"] = False
            it["last_log_age_sec"] = None

    return {"items": items, "active": active_id}


def _serve_avatar(handler, path):
    """에이전트 아바타 이미지 서빙."""
    cid = _read_community(path)
    if cid:
        _set_active_community(cid)
    agent_id = _read_query(path, "id", "")
    variant = _read_query(path, "variant", "") or ""  # "" or "full"
    if not agent_id:
        handler._send(404, b"missing id", "text/plain")
        return

    from src import community as _comm
    from src.core.profile import load_profile

    # 1. DB profile의 avatar_filename 우선
    profile = load_profile(agent_id) or {}
    fname = profile.get("avatar_filename") or ""
    target_path = None
    if fname:
        base, ext = os.path.splitext(fname)
        if variant == "full":
            # full variant 탐색: agent-mgr-001.png → agent-mgr-001-full.png
            full_fname = f"{base}-full{ext}"
            target_path = _comm.get_avatar_path(full_fname)
            if not target_path:
                target_path = _comm.get_avatar_path(fname)
        else:
            target_path = _comm.get_avatar_path(fname)

    # 2. agent_id로 직접 스캔
    if not target_path:
        target_path = _comm.find_avatar(agent_id)

    if not target_path or not os.path.exists(target_path):
        # placeholder: 빈 PNG 작은 것
        placeholder = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\x00\x00\x00\x03\x00\x01\x08\x00\x01\x10t\x08\xd7\x00\x00\x00\x00IEND\xaeB`\x82"
        handler.send_response(200)
        handler.send_header("Content-Type", "image/png")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Content-Length", str(len(placeholder)))
        handler.end_headers()
        handler.wfile.write(placeholder)
        return

    try:
        with open(target_path, "rb") as f:
            data = f.read()
    except Exception as e:
        handler._send(500, str(e).encode(), "text/plain")
        return

    # content-type
    ext = os.path.splitext(target_path)[1].lower().lstrip(".")
    ctype = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}.get(ext, "application/octet-stream")
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Cache-Control", "public, max-age=300")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


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
            elif p == "/api/avatar":
                _serve_avatar(self, self.path)
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
