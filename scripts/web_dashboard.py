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
  html, body { height: 100%; overflow: hidden; isolation: isolate; }
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
    padding: 12px 24px;
    background: var(--bg-elev);
    border-bottom: 1px solid var(--border);
    display: flex; align-items: center; gap: 14px;
    box-shadow: var(--shadow);
    z-index: 100;
    min-height: 58px;
    position: relative;
  }
  .brand {
    display: flex; align-items: center; gap: 10px; white-space: nowrap;
  }
  .brand-logo {
    width: 32px; height: 32px; object-fit: contain; border-radius: 7px;
    display: block;
  }
  .brand-name { font-size: 15px; font-weight: 700; letter-spacing: -0.3px; color: var(--text); }

  /* ==== Community switcher ==== */
  .community-btn {
    position: relative; display: flex; align-items: center; gap: 8px;
    background: var(--panel); color: var(--text); border: 1px solid var(--border);
    border-radius: 10px; padding: 6px 12px 6px 10px; font-size: 12.5px;
    font-weight: 600; cursor: pointer; transition: all 0.15s;
  }
  /* 실행 중 → 초록 테마 */
  .community-btn:not(.stopped) {
    background: color-mix(in srgb, var(--ok) 10%, var(--panel));
    border-color: color-mix(in srgb, var(--ok) 35%, var(--border));
    color: var(--ok);
  }
  .community-btn:not(.stopped):hover { background: color-mix(in srgb, var(--ok) 18%, var(--panel)); }
  /* 중단된 서버 → 회색 */
  .community-btn.stopped {
    color: var(--text-dim);
  }
  .community-btn.stopped:hover { border-color: var(--accent); }
  .community-btn .sv-dot {
    width: 7px; height: 7px; border-radius: 50%; background: var(--ok);
    box-shadow: 0 0 6px var(--ok); animation: live-pulse 1.8s infinite;
  }
  .community-btn.stopped .sv-dot { background: var(--text-faint); box-shadow: none; animation: none; }
  .community-btn .chev { font-size: 9px; opacity: 0.6; margin-left: 4px; }
  @keyframes live-pulse {
    0%, 100% { box-shadow: 0 0 6px var(--ok); }
    50% { box-shadow: 0 0 12px var(--ok); }
  }

  .community-menu {
    display: none; position: absolute; top: calc(100% + 8px); left: 0;
    background: var(--bg-elev); border: 1px solid var(--border); border-radius: 12px;
    min-width: 280px; max-width: 360px; box-shadow: var(--shadow-lg); z-index: 1000;
    padding: 6px; overflow: auto; max-height: 70vh;
  }
  .community-menu.open { display: block; }
  .community-menu .ci {
    display: flex; align-items: center; gap: 10px; padding: 10px 12px;
    border-radius: 8px; cursor: pointer; transition: background 0.12s;
    font-size: 13px;
  }
  .community-menu .ci:hover { background: var(--panel-2); }
  .community-menu .ci.active { background: color-mix(in srgb, var(--accent) 10%, transparent); }
  .community-menu .ci.stopped { opacity: 0.55; }
  .community-menu .ci .ci-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--ok); box-shadow: 0 0 6px var(--ok); flex-shrink: 0; }
  .community-menu .ci.stopped .ci-dot { background: var(--text-faint); box-shadow: none; }
  .community-menu .ci .ci-name { flex: 1; font-weight: 600; font-family: "JetBrains Mono", monospace; font-size: 12.5px; }
  .community-menu .ci .ci-meta { font-size: 10.5px; color: var(--text-dim); font-weight: 400; }
  .community-menu .ci .ci-check { color: var(--accent); font-weight: 700; }
  .community-menu .ci.active .ci-check::before { content: '✓'; }

  /* Language switcher — 국기 버튼 + 드롭다운 */
  .lang-menu {
    display: none; position: absolute; top: calc(100% + 8px); right: 0;
    background: var(--bg-elev); border: 1px solid var(--border); border-radius: 12px;
    min-width: 180px; box-shadow: var(--shadow-lg); z-index: 1000;
    padding: 6px; overflow: hidden;
  }
  .lang-menu.open { display: block; }
  .lang-menu .li {
    display: flex; align-items: center; gap: 10px; padding: 10px 12px;
    border-radius: 8px; cursor: pointer; transition: background 0.12s;
    font-size: 13px; font-weight: 500; color: var(--text);
  }
  .lang-menu .li:hover { background: var(--panel-2); }
  .lang-menu .li.active { background: color-mix(in srgb, var(--accent) 10%, transparent); }
  .lang-menu .li .li-flag { font-size: 18px; line-height: 1; }
  .lang-menu .li .li-name { flex: 1; }
  .lang-menu .li .li-check { color: var(--accent); font-weight: 700; opacity: 0; }
  .lang-menu .li.active .li-check { opacity: 1; }
  .lang-menu .li.active .li-check::before { content: '✓'; }
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

  /* ==== Supervisor view ==== */
  body:not(.show-supervisors) .sup-tab { display: none; }
  #supervisor-toggle.active {
    background: color-mix(in srgb, var(--accent) 15%, var(--panel));
    border-color: var(--accent);
    color: var(--accent);
  }

  .sup-card {
    padding: 14px 18px; margin-bottom: 10px;
    background: var(--panel); border: 1px solid var(--border-soft);
    border-left: 3px solid var(--text-faint); border-radius: 10px;
    box-shadow: var(--shadow); transition: border-color 0.2s, opacity 0.3s;
  }
  .sup-card.active { border-left-color: var(--ok); }
  .sup-card.intervening { border-left-color: var(--warn); box-shadow: 0 0 0 1px var(--warn), var(--shadow); }
  .sup-card.inactive { opacity: 0.5; border-left-color: var(--text-faint); }
  .sup-card .sup-head { display: flex; align-items: center; gap: 10px; margin-bottom: 6px; }
  .sup-card .sup-icon { font-size: 22px; }
  .sup-card .sup-name { font-size: 14px; font-weight: 700; color: var(--text); flex: 1; }
  .sup-card .sup-badge {
    font-size: 10.5px; font-weight: 700; padding: 3px 10px; border-radius: 999px;
    text-transform: uppercase; letter-spacing: 0.7px;
  }
  .sup-card .sup-badge.active { background: color-mix(in srgb, var(--ok) 15%, transparent); color: var(--ok); border: 1px solid color-mix(in srgb, var(--ok) 30%, transparent); }
  .sup-card .sup-badge.inactive { background: var(--panel-2); color: var(--text-faint); border: 1px solid var(--border); }
  .sup-card .sup-badge.intervening { background: color-mix(in srgb, var(--warn) 20%, transparent); color: var(--warn); border: 1px solid color-mix(in srgb, var(--warn) 40%, transparent); animation: pulse-bg 1.2s infinite; }
  @keyframes pulse-bg { 50% { background: color-mix(in srgb, var(--warn) 35%, transparent); } }
  .sup-card .sup-desc { color: var(--text-dim); font-size: 12px; line-height: 1.55; margin-bottom: 8px; }
  .sup-card .sup-targets { display: flex; gap: 4px; flex-wrap: wrap; margin-bottom: 8px; }
  .sup-card .sup-target-pill {
    font-size: 10.5px; padding: 2px 8px; background: var(--panel-2); border-radius: 6px;
    color: var(--text-dim); border: 1px solid var(--border-soft);
    font-family: "JetBrains Mono", monospace;
  }
  .sup-card .sup-logs {
    font-family: "JetBrains Mono", monospace; font-size: 10.5px;
    background: var(--panel-3); border-radius: 8px; padding: 8px 10px;
    color: var(--text-dim); max-height: 140px; overflow-y: auto;
  }
  .sup-card .sup-meta { font-size: 10.5px; color: var(--text-faint); display: flex; gap: 12px; }

  /* Supervisor nodes in graph — 육각형 스타일 */
  .graph-svg .sup-edge { stroke-dasharray: 3 3; opacity: 0.7; }
  .graph-svg .sup-edge.active { opacity: 1; stroke-width: 2; }
  .graph-svg .sup-edge.intervening { opacity: 1; stroke-width: 2.5; stroke-dasharray: 4 3; animation: edge-flow 0.8s linear infinite; }

  /* ==== Connection Graph (HTML + SVG hybrid) ==== */
  .graph-panel {
    background: var(--panel); border: 1px solid var(--border-soft); border-radius: 14px;
    padding: 16px 20px; margin-bottom: 20px; box-shadow: var(--shadow);
    position: relative; overflow: visible;
    transition: background 0.2s;
  }
  /* Fullscreen mode */
  body.graph-fullscreen .graph-panel {
    position: fixed !important; inset: 20px !important; z-index: 2147483500 !important;
    margin: 0; padding: 20px 28px;
    max-width: none; max-height: none;
  }
  body.graph-fullscreen .graph-stage { height: calc(100vh - 160px) !important; }
  /* Hide everything else when graph fullscreen */
  body.graph-fullscreen header,
  body.graph-fullscreen nav.tabs,
  body.graph-fullscreen main > .view > :not(.graph-panel),
  body.graph-fullscreen .view:not(.active) { visibility: hidden; }
  body.graph-fullscreen main { overflow: visible; }
  .graph-fs-btn {
    background: var(--panel-2); color: var(--text); border: 1px solid var(--border);
    border-radius: 7px; padding: 4px 10px; font-size: 11px; cursor: pointer;
    font-family: inherit;
  }
  .graph-fs-btn:hover { border-color: var(--accent); background: var(--panel-3); }
  .graph-panel .graph-head { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
  .graph-panel .graph-head h3 {
    font-size: 11.5px; font-weight: 700; color: var(--text-dim);
    text-transform: uppercase; letter-spacing: 1.3px;
  }
  .graph-panel .graph-head .note { color: var(--text-faint); font-size: 11px; margin-left: auto; }
  .graph-stage {
    position: relative; width: 100%; height: 440px;
    /* overflow: hidden — 그래프가 블록 밖으로 새는 치명적 문제 원천 차단 */
    overflow: hidden;
    border-radius: 8px;
  }
  .graph-stage svg.graph-edges {
    position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none;
    /* SVG 도 clip — viewBox 밖 요소 있으면 잘림 (안전망) */
    overflow: hidden;
  }
  .graph-edges .edge {
    fill: none; stroke-linecap: round;
    transition: stroke-width 0.3s, opacity 0.3s;
  }
  .graph-edges .edge.dim { opacity: 0.35; }
  .graph-edges .edge.live { stroke-dasharray: 6 4; animation: edge-flow 1.6s linear infinite; }
  @keyframes edge-flow { to { stroke-dashoffset: -20; } }
  .graph-edges .edge-label {
    font-family: "JetBrains Mono", monospace; font-size: 10.5px; font-weight: 500;
    fill: var(--text);
    pointer-events: none;
  }
  .graph-edges .edge-label-bg {
    fill: var(--panel); stroke: var(--border); stroke-width: 1;
    filter: drop-shadow(0 1px 3px rgba(0,0,0,0.08));
    transition: all 0.2s;
  }
  .graph-edges .edge-label-bg.live {
    stroke: var(--accent); stroke-width: 1.5;
  }
  .graph-edges .edge-label-group { pointer-events: auto; }
  .graph-edges .edge-label-group:hover .edge-label-bg {
    fill: var(--panel-2); stroke: var(--accent); stroke-width: 2;
  }
  .graph-node {
    position: absolute; transform: translate(-50%, -50%);
    display: flex; flex-direction: column; align-items: center; gap: 4px;
    cursor: pointer; transition: transform 0.2s;
    animation: node-in 0.5s cubic-bezier(0.34, 1.2, 0.64, 1);
  }
  @keyframes node-in {
    from { opacity: 0; transform: translate(-50%, -50%) scale(0.3); }
    to { opacity: 1; transform: translate(-50%, -50%) scale(1); }
  }
  .graph-node:hover { transform: translate(-50%, -50%) scale(1.08); z-index: 2; }
  .graph-edges .edge { animation: edge-in 0.6s ease-out; }
  .graph-edges .edge-label-group { animation: label-in 0.5s ease-out 0.2s both; }
  @keyframes edge-in {
    from { stroke-opacity: 0; stroke-dashoffset: 100; stroke-dasharray: 100; }
    to { stroke-opacity: 1; stroke-dashoffset: 0; stroke-dasharray: 0; }
  }
  @keyframes label-in {
    from { opacity: 0; transform: scale(0.5); transform-origin: center; }
    to { opacity: 1; transform: scale(1); }
  }
  .graph-node.center { /* owner, no hover lift */ }
  .graph-node .gn-name {
    font-size: 11px; font-weight: 600; color: var(--text);
    text-align: center; padding: 1px 6px; border-radius: 4px;
    background: color-mix(in srgb, var(--panel) 85%, transparent);
    backdrop-filter: blur(4px);
    white-space: nowrap;
  }
  .graph-node .gn-ring {
    width: 56px; height: 56px; border-radius: 50%;
    border: 3px solid var(--border); background: var(--panel-2);
    overflow: hidden; display: flex; align-items: center; justify-content: center;
    font-size: 24px;
    box-shadow: var(--shadow);
  }
  .graph-node .gn-ring.mgr { border-color: var(--mgr); }
  .graph-node .gn-ring.creator { border-color: var(--creator); }
  .graph-node .gn-ring.persona { border-color: var(--persona); }
  .graph-node .gn-ring.owner { border-color: var(--user); }
  .graph-node .gn-ring.thinking {
    border-color: var(--thinking);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--thinking) 30%, transparent), var(--shadow);
    animation: pulse-ring 1.3s infinite;
  }
  .graph-node .gn-ring.speaking {
    border-color: var(--speaking);
    box-shadow: 0 0 0 2px color-mix(in srgb, var(--speaking) 30%, transparent), var(--shadow);
    animation: pulse-ring 1.0s infinite;
  }
  @keyframes pulse-ring {
    0%,100% { box-shadow: 0 0 0 0 currentColor, var(--shadow); }
    50% { box-shadow: 0 0 0 6px color-mix(in srgb, currentColor 15%, transparent), var(--shadow); }
  }
  .graph-node .gn-ring img { width: 100%; height: 100%; object-fit: cover; }
  /* Supervisor nodes — hexagon-ish 룩 */
  .graph-node.sup .gn-ring {
    width: 44px; height: 44px; border-radius: 10px;
    transform: rotate(45deg);
    border-style: dashed;
    border-color: var(--accent-2);
  }
  .graph-node.sup .gn-ring > * { transform: rotate(-45deg); }
  .graph-node.sup.active .gn-ring { border-style: solid; }
  .graph-node.sup.intervening .gn-ring {
    border-color: var(--warn); border-style: solid;
    animation: pulse-ring 0.9s infinite;
  }
  .graph-empty {
    padding: 40px 12px; text-align: center; color: var(--text-faint); font-size: 12px; font-style: italic;
  }
  .graph-legend {
    display: flex; gap: 14px; margin-top: 10px; font-size: 10.5px; color: var(--text-dim); flex-wrap: wrap;
  }
  .graph-legend .item { display: flex; align-items: center; gap: 5px; }
  .graph-legend .swatch { width: 12px; height: 3px; border-radius: 2px; }

  /* Supervisor edge (overlay) */
  .graph-edges .sup-edge { stroke-dasharray: 5 4; opacity: 0.9; }
  .graph-edges .sup-edge.idle { opacity: 0.7; stroke-width: 1.6; }
  .graph-edges .sup-edge.active { opacity: 1; stroke-width: 2; }
  .graph-edges .sup-edge.intervening { opacity: 1; stroke-width: 2.5; stroke-dasharray: 4 3; animation: edge-flow 0.8s linear infinite; }

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
    display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 380px));
    gap: 12px; align-items: start; justify-content: start;
  }
  .agent-card {
    background: var(--panel); border: 1.5px solid var(--border-soft); border-radius: 14px;
    padding: 13px 15px; transition: border-color 0.2s, transform 0.2s, box-shadow 0.3s;
    position: relative; overflow: hidden; cursor: pointer;
    box-shadow: var(--shadow);
    min-width: 0;
  }
  .agent-card:hover { border-color: var(--accent); transform: translateY(-1px); box-shadow: var(--shadow-lg); }
  .agent-card.mgr { border-left: 3px solid var(--mgr); }
  .agent-card.creator { border-left: 3px solid var(--creator); }
  .agent-card.persona { border-left: 3px solid var(--persona); }
  .agent-card.thinking {
    grid-column: span 2;
    max-width: 760px;
    border-color: var(--thinking);
    box-shadow: var(--glow-thinking), var(--shadow-lg);
  }
  .agent-card.speaking {
    grid-column: span 2;
    max-width: 760px;
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
  .agent-head .type-tag.supervisor { background: color-mix(in srgb, var(--accent-2) 15%, transparent); color: var(--accent-2); }

  .model-tag {
    font-size: 9.5px; padding: 1.5px 6px; border-radius: 5px;
    font-family: "JetBrains Mono", monospace; font-weight: 500;
    background: var(--panel-2); color: var(--text-dim);
    border: 1px solid var(--border-soft) !important;
    display: inline-flex; align-items: center; gap: 3px;
  }
  .model-tag::before { content: ''; width: 5px; height: 5px; border-radius: 50%; background: currentColor; flex: 0 0 auto; }
  /* Provider tint (최상위 fallback) */
  .model-tag.claude { color: #d97706; }
  .model-tag.openai { color: #10a37f; }
  .model-tag.local { color: #3b82f6; }
  .model-tag.other { color: var(--text-dim); }
  /* Model family tint (provider 보다 구체적) — multi-chip 일관성 */
  .model-tag.m-haiku { color: #0891b2; border-color: color-mix(in srgb, #0891b2 35%, var(--border-soft)) !important; }
  .model-tag.m-sonnet { color: #7c3aed; border-color: color-mix(in srgb, #7c3aed 35%, var(--border-soft)) !important; }
  .model-tag.m-opus { color: #c2410c; border-color: color-mix(in srgb, #c2410c 35%, var(--border-soft)) !important; }
  .model-tag.m-gpt { color: #10a37f; border-color: color-mix(in srgb, #10a37f 35%, var(--border-soft)) !important; }
  .model-tag.m-gemini { color: #3b82f6; border-color: color-mix(in srgb, #3b82f6 35%, var(--border-soft)) !important; }
  .model-tag.override { border-color: var(--accent) !important; color: var(--accent); }
  .model-chip-row {
    display: inline-flex; align-items: center; gap: 4px; flex-wrap: wrap; vertical-align: middle;
  }
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

  .agent-meta {
    display: flex; flex-wrap: wrap; gap: 4px 8px; align-items: center;
    margin-top: 6px; font-size: 11px; color: var(--text-dim);
    min-width: 0;
  }
  .agent-meta > * { flex-shrink: 0; }
  .agent-meta .bar { width: 48px; height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; }
  .agent-meta .bar > span { display: block; height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); transition: width 0.3s; }
  .agent-meta .sep { color: var(--text-faint); }
  .agent-footer {
    display: flex; justify-content: space-between; align-items: center;
    margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border-soft);
    font-size: 10.5px; color: var(--text-faint); gap: 8px;
  }
  .agent-footer .model-tag { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
  .agent-footer .model-chip-row { min-width: 0; flex-wrap: wrap; gap: 3px; }

  .agent-expanded { display: none; margin-top: 12px; }
  .agent-card.thinking .agent-expanded, .agent-card.speaking .agent-expanded { display: block; }
  .progress-wrap { display: flex; align-items: center; gap: 10px; font-size: 11px; color: var(--text-dim); margin-bottom: 10px; }
  .progress-wrap .elapsed { font-family: "JetBrains Mono", monospace; color: var(--text); font-weight: 600; }
  /* 진행바 — 단정한 시머 한 레이어 */
  .progress-bar {
    flex: 1; height: 4px; border-radius: 999px; overflow: hidden;
    background: color-mix(in srgb, var(--text-faint) 16%, transparent);
    position: relative;
  }
  .progress-bar > span {
    display: block; height: 100%; width: 100%;
    background: linear-gradient(90deg,
      transparent 0%,
      color-mix(in srgb, var(--accent) 35%, transparent) 30%,
      var(--accent) 50%,
      color-mix(in srgb, var(--accent) 35%, transparent) 70%,
      transparent 100%);
    background-size: 220% 100%;
    animation: bar-shimmer 1.6s linear infinite;
  }
  .agent-card.speaking .progress-bar > span {
    background: linear-gradient(90deg,
      transparent 0%,
      color-mix(in srgb, var(--speaking) 35%, transparent) 30%,
      var(--speaking) 50%,
      color-mix(in srgb, var(--speaking) 35%, transparent) 70%,
      transparent 100%);
    background-size: 220% 100%;
  }
  @keyframes bar-shimmer {
    0%   { background-position: 200% 0; }
    100% { background-position: -200% 0; }
  }

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
  .msg-del-btn {
    position: absolute; top: 8px; right: 8px;
    background: transparent; border: 1px solid transparent; color: var(--text-faint);
    width: 24px; height: 24px; border-radius: 6px; font-size: 12px; cursor: pointer;
    opacity: 0; transition: opacity 0.15s, border-color 0.15s, color 0.15s;
    display: flex; align-items: center; justify-content: center;
  }
  .msg:hover .msg-del-btn { opacity: 1; }
  .msg-del-btn:hover { color: var(--err); border-color: var(--err); }

  /* ==== Lightbox (full avatar) ==== */
  .lightbox {
    display: none; position: fixed !important; inset: 0 !important;
    background: rgba(0,0,0,0.85);
    backdrop-filter: blur(10px); z-index: 2147483640 !important;
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
    position: fixed !important; inset: 0 !important;
    background: rgba(10, 12, 25, 0.6);
    backdrop-filter: blur(8px); z-index: 2147483600 !important; display: none;
    align-items: flex-start; justify-content: center;
    padding: 24px;
  }
  :root[data-theme="light"] .detail-backdrop { background: rgba(20, 24, 40, 0.25); }
  .detail-backdrop.open { display: flex; }
  .detail-panel {
    background: var(--bg-elev); border: 1px solid var(--border);
    border-radius: 14px; width: 100%; max-width: 960px;
    max-height: calc(100vh - 48px);
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

  .rel-row {
    display: grid;
    grid-template-columns: 110px 160px 1fr 40px;
    align-items: center; gap: 10px;
    padding: 6px 2px;
    font-size: 12px;
    border-bottom: 1px dashed var(--border-soft);
  }
  .rel-row:last-child { border-bottom: none; }
  .rel-row .rname { font-weight: 600; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .rel-row .rtype {
    color: var(--text-dim); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    padding: 2px 8px; background: var(--panel-2); border-radius: 5px; font-size: 11px;
  }
  .rel-row .intimacy-bar { height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }
  .rel-row .intimacy-bar > span { display: block; height: 100%; background: linear-gradient(90deg, var(--accent), var(--accent-2)); transition: width 0.3s; }
  .rel-row .intimacy-num { font-family: "JetBrains Mono", monospace; font-size: 11px; color: var(--text-dim); text-align: right; }
  .rel-row .dynamics {
    grid-column: 1 / -1;
    color: var(--text-faint); font-size: 10.5px;
    padding-left: 120px; padding-top: 2px; padding-bottom: 4px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }

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

  /* Loading state (서버 전환 등) */
  .loading-bar {
    position: fixed; top: 0; left: 0; right: 0; height: 3px; z-index: 2147483000;
    background: linear-gradient(90deg, transparent, var(--accent), var(--accent-2), transparent);
    background-size: 200% 100%;
    opacity: 0; pointer-events: none;
    transition: opacity 0.2s;
  }
  body.switching .loading-bar {
    opacity: 1; animation: loading-slide 1.2s linear infinite;
  }
  @keyframes loading-slide {
    0% { background-position: -100% 0; }
    100% { background-position: 100% 0; }
  }
  body.switching main { opacity: 0.4; pointer-events: none; transition: opacity 0.2s; }

  /* Empty community state */
  .empty-banner {
    display: none; padding: 40px 32px; background: var(--panel);
    border: 1px dashed var(--border); border-radius: 14px; text-align: center;
    color: var(--text-dim); margin-bottom: 20px;
  }
  body.community-empty .empty-banner { display: block; }
  body.community-empty .overview-grid,
  body.community-empty #overview-agents,
  body.community-empty #overview-msgs,
  body.community-empty .section-title { display: none; }
  .empty-banner h2 { font-size: 18px; font-weight: 700; color: var(--text); margin-bottom: 6px; }
  .empty-banner .hint { font-size: 12.5px; margin-top: 8px; color: var(--text-faint); }
  .empty-banner code { background: var(--panel-2); padding: 2px 8px; border-radius: 4px; font-family: "JetBrains Mono", monospace; font-size: 11.5px; color: var(--text); }

  /* ==== Action Buttons ==== */
  .act-btn {
    background: var(--panel-2); color: var(--text); border: 1px solid var(--border);
    border-radius: 9px; padding: 7px 14px; font-size: 12.5px; font-weight: 500; cursor: pointer;
    transition: all 0.15s; font-family: inherit;
  }
  .act-btn:hover:not(:disabled) { border-color: var(--accent); background: var(--panel-3); }
  .act-btn:disabled { opacity: 0.4; cursor: not-allowed; }
  .act-btn.primary { background: color-mix(in srgb, var(--accent) 12%, var(--panel-2)); border-color: color-mix(in srgb, var(--accent) 40%, transparent); color: var(--accent); }
  .act-btn.primary:hover:not(:disabled) { background: color-mix(in srgb, var(--accent) 20%, var(--panel-2)); }
  .act-btn.success { background: color-mix(in srgb, var(--ok) 12%, var(--panel-2)); border-color: color-mix(in srgb, var(--ok) 40%, transparent); color: var(--ok); }
  .act-btn.success:hover:not(:disabled) { background: color-mix(in srgb, var(--ok) 20%, var(--panel-2)); }
  .act-btn.danger { background: color-mix(in srgb, var(--err) 10%, var(--panel-2)); border-color: color-mix(in srgb, var(--err) 40%, transparent); color: var(--err); }
  .act-btn.danger:hover:not(:disabled) { background: color-mix(in srgb, var(--err) 20%, var(--panel-2)); }
  .act-btn.small { padding: 4px 10px; font-size: 11.5px; }

  .trash-item {
    display: flex; gap: 8px; align-items: center; padding: 6px 10px;
    background: var(--panel-2); border-radius: 6px; margin-bottom: 4px; font-size: 11.5px;
  }
  .trash-item .ch { color: var(--cmd); font-family: "JetBrains Mono", monospace; font-size: 10.5px; }
  .trash-item .who { color: var(--text); font-weight: 600; }
  .trash-item .msg { color: var(--text-dim); flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

  /* toast */
  .toast {
    position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
    background: var(--panel); border: 1px solid var(--border); border-radius: 10px;
    padding: 12px 20px; box-shadow: var(--shadow-lg); font-size: 13px; z-index: 4000;
    display: none; max-width: 500px;
  }
  .toast.show { display: block; animation: toast-in 0.2s ease-out; }
  .toast.err { border-color: var(--err); color: var(--err); }
  .toast.ok { border-color: var(--ok); color: var(--ok); }
  @keyframes toast-in { from { opacity: 0; transform: translate(-50%, 10px); } to { opacity: 1; transform: translate(-50%, 0); } }

  /* Responsive */
  @media (max-width: 900px) {
    .overview-grid { grid-template-columns: repeat(2, 1fr); }
    .view { padding: 14px 16px; }
  }
</style>
</head><body>
<div class="app">
  <header class="status">
    <span class="brand" onclick="openImgLightbox('/logo', 'Glimi')" style="cursor:pointer" title="Glimi">
      <img src="/logo" alt="Glimi" class="brand-logo">
      <span class="brand-name">Glimi</span>
    </span>

    <div style="position:relative" id="community-switcher-wrap">
      <button class="community-btn" id="community-btn" title="커뮤니티 전환">
        <span class="sv-dot"></span>
        <span id="community-btn-name">—</span>
        <span class="chev">▾</span>
      </button>
      <div class="community-menu" id="community-menu"></div>
    </div>

    <div style="flex:1"></div>

    <div style="position:relative" id="lang-switcher-wrap">
      <button class="btn-icon" id="lang-toggle" title="언어">🌐</button>
      <div class="lang-menu" id="lang-menu"></div>
    </div>
    <button class="btn-icon" id="supervisor-toggle" title="Supervisor view — 내면 조종 보기">💭</button>
    <button class="btn-icon" id="theme-toggle" title="Theme">☀</button>
  </header>

  <nav class="tabs" id="tabs">
    <button data-tab="overview" class="active">Overview</button>
    <button data-tab="agents">Agents <span class="count" id="tc-agents">0</span></button>
    <button data-tab="channels">Channels <span class="count" id="tc-channels">0</span></button>
    <button data-tab="messages">Messages <span class="count" id="tc-messages">0</span></button>
    <button data-tab="scenes">Scenes <span class="count" id="tc-scenes">0</span></button>
    <button data-tab="events">Events <span class="count" id="tc-events">0</span></button>
    <button data-tab="supervisors" class="sup-tab">Supervisors <span class="count" id="tc-supervisors">0</span></button>
    <button data-tab="health">Health</button>
    <button data-tab="sync">Sync</button>
    <button data-tab="dev">Dev</button>
    <button data-tab="usage">Usage</button>
    <button data-tab="logs">Logs</button>
  </nav>

  <main>
    <!-- Overview -->
    <div class="view active" id="view-overview">
      <div class="empty-banner">
        <h2>📭 이 커뮤니티는 비어있어요</h2>
        <div>아직 에이전트나 대화가 없어요. 커뮤니티 서버를 시작하면 데이터가 채워집니다.</div>
        <div class="hint">서버 시작: <code>./scripts/run.sh <span id="empty-cid">—</span></code>  또는 Sync 탭에서 <b>▶ 서버 시작</b></div>
      </div>
      <div class="offline-banner" id="offline-banner">
        <b>오프라인</b> — 커뮤니티 서버가 실행 중이 아님. 마지막 스냅샷 표시 중 (실시간 아님)
        <span class="muted" id="offline-last"></span>
      </div>
      <div class="hero" id="hero"></div>
      <div class="graph-panel" id="graph-panel"></div>
      <div class="overview-grid">
        <div class="kpi"><div class="label">Server Status</div><div class="value" id="kpi-server">—</div></div>
        <div class="kpi"><div class="label">Discord Bot</div><div class="value" id="kpi-bot">—</div></div>
        <div class="kpi"><div class="label">Owner</div><div class="value" id="kpi-user">—</div></div>
        <div class="kpi"><div class="label">Active Scene</div><div class="value" id="kpi-scene">—</div></div>
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

    <div class="view" id="view-scenes"><div id="scenes-full"></div></div>
    <div class="view" id="view-events"><div class="event-list" id="events-full"></div></div>

    <div class="view" id="view-health"><div class="health-grid" id="health-full"></div></div>

    <div class="view" id="view-sync"><div id="sync-full"></div></div>

    <div class="view" id="view-dev"><div id="dev-full"></div></div>

    <div class="view" id="view-usage"><div id="usage-full"></div></div>

    <div class="view" id="view-supervisors"><div id="supervisors-full"></div></div>
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

<!-- Loading bar -->
<div class="loading-bar"></div>

<!-- Toast -->
<div class="toast" id="toast"></div>

<script src="https://unpkg.com/cytoscape@3.30.2/dist/cytoscape.min.js"></script>
<script>
// ==== State ====
const params = new URLSearchParams(location.search);
let COMMUNITY = params.get('community') || null;
let THEME = localStorage.getItem('glimi-theme') || 'light';
document.documentElement.setAttribute('data-theme', THEME);

// ==== i18n ====
// LANG_OVERRIDE: 'ko' | 'en' | null (null = 서버 설정 따라감)
// 번역 dict는 /api/i18n?lang=... 엔드포인트에서 로드 (i18n/dashboard.{ko,en}.json)
let LANG_OVERRIDE = localStorage.getItem('glimi-lang') || null;
let SERVER_LANG = 'ko';
let I18N_CACHE = {};  // lang → dict

async function loadLang(lang) {
  if (I18N_CACHE[lang]) return I18N_CACHE[lang];
  try {
    const r = await fetch(`/api/i18n?lang=${encodeURIComponent(lang)}`);
    I18N_CACHE[lang] = await r.json();
  } catch {
    I18N_CACHE[lang] = {};
  }
  return I18N_CACHE[lang];
}

function currentLang() { return LANG_OVERRIDE || SERVER_LANG || 'ko'; }
function t(key, vars) {
  const dict = I18N_CACHE[currentLang()] || I18N_CACHE.ko || {};
  let s = dict[key] || (I18N_CACHE.ko && I18N_CACHE.ko[key]) || key;
  if (vars) Object.entries(vars).forEach(([k, v]) => { s = s.replace(`{${k}}`, v); });
  return s;
}

// === removed inline I18N dict (moved to i18n/dashboard.{ko,en}.json) ===
const I18N_UNUSED_OLD = {
  ko: {
    // Banners
    offline_title: '오프라인',
    offline_msg: '커뮤니티 서버가 실행 중이 아님. 마지막 스냅샷 표시 중 (실시간 아님)',
    offline_last: '마지막 활동',
    empty_community_title: '📭 이 커뮤니티는 비어있어요',
    empty_community_msg: '아직 에이전트나 대화가 없어요. 커뮤니티 서버를 시작하면 데이터가 채워집니다.',
    empty_community_hint: '서버 시작',
    // KPI
    kpi_server: 'Server Status',
    kpi_bot: 'Discord Bot',
    kpi_owner: 'Owner',
    kpi_scene: 'Active Scene',
    kpi_msgs: 'Messages',
    online: '● Online',
    offline_short: '○ Offline',
    running: '● Running',
    stopped: '○ Stopped',
    nothing_active: 'nothing active',
    // Sections
    section_active_members: 'Agents',
    section_recent_conv: 'Recent Conversations',
    // Tabs
    tab_overview: 'Overview', tab_agents: 'Agents', tab_channels: 'Channels',
    tab_messages: 'Messages', tab_scenes: 'Scenes', tab_events: 'Events',
    tab_health: 'Health', tab_sync: 'Sync', tab_dev: 'Dev', tab_usage: 'Usage',
    tab_supervisors: 'Supervisors', tab_logs: 'Logs',
    // Buttons
    btn_server_start: '▶ 서버 시작',
    btn_server_stop: '⏸ 서버 중단',
    btn_server_restart: '↻ 재시작',
    btn_scan: '🔍 Scan Discord',
    btn_sync: '▶ Full Sync',
    btn_restore: '↻ Restore Messages',
    btn_clear_msgs: '🧹 메시지 전체 삭제 (DB만)',
    btn_delete_ch: '🗑 채널 삭제',
    btn_refresh: '새로고침',
    btn_empty_trash: 'Empty Trash',
    btn_close: '닫기',
    // Section titles
    sec_processes: 'Processes',
    sec_glimi_resources: 'Glimi Resource Usage',
    sec_system_resources: 'System Resources',
    sec_server_control: 'Server Control',
    sec_sync_actions: 'Sync Actions',
    sec_trash: 'Trash',
    sec_db_channels: 'DB-registered Channels',
    sec_profile: 'Profile',
    sec_relationships: 'Relationships',
    sec_memory: 'Memory',
    sec_thinking_logs: 'Thinking Logs',
    sec_recent_chat: 'Recent Chat',
    sec_participants: 'Participants',
    sec_all_messages: 'All Messages',
    sec_actions: 'Actions',
    sec_connection_graph: 'Connection Graph',
    // Status
    status_active: '진행 중',
    status_completed: '완료',
    status_not_started: '시작 전',
    active_badge: '● ACTIVE',
    idle_badge: '○ IDLE',
    intervening_badge: '● INTERVENING',
    live_label: '● LIVE',
    thinking: '생각 중',
    speaking: '응답 중',
    calm_idle: '평온 · 모두 대기 중',
    // Misc
    loading: '로딩 중…',
    no_data: '데이터 없음',
    no_members: '멤버 없음',
    no_channels: '채널 없음',
    no_events: '기록된 이벤트 없음',
    no_scenes: '씬 정보 없음',
    no_supervisors: '등록된 감시자 없음',
    no_msgs: '대화 없음',
    no_trash: '휴지통 비어있음',
    // Field labels
    f_age: 'Age', f_mbti: 'MBTI', f_enneagram: 'Enneagram', f_traits: 'Traits',
    f_emotion: 'Emotion', f_status: 'Status', f_model: 'Model', f_owner: 'Owner',
    f_background: 'Background',
    f_started: '시작', f_completed: '완료', f_last_active: 'last active',
    // Sync
    sync_guard_running: 'ℹ 서버 실행 중 — Sync 버튼 클릭 시 자동으로 서버 중단 → 작업 → 재시작 진행. 취소 버튼 제공됨.',
    sync_guard_stopped: '○ 서버 오프라인 — 모든 sync 작업 즉시 가능.',
    sync_hint: 'Discord 서버와 DB 사이 상태를 맞추는 작업. 서버 실행 중이면 자동 중단·작업·재시작.',
    trash_hint: '휴지통 — 채널/메시지 삭제 시 완전 삭제 대신 여기로 옮겨짐. 실수 복구용 안전망.',
    // Confirm dialogs
    confirm_clear: '#{ch}의 DB 메시지 전체 삭제. Discord 채널은 유지. 진행?',
    confirm_delete_ch: '채널 #{ch} 완전 삭제. 복구 어려움. 진행?',
    confirm_trash_msg: '이 메시지를 trash로 옮길까? (복구 가능)',
    confirm_empty_trash: 'Trash 전체 비우기. 되돌릴 수 없음. 진행?',
    confirm_stop_server: '커뮤니티 서버 중단?',
    confirm_restart_server: '서버 재시작? (10~20초 소요)',
    confirm_sync_restart: '{act}를 실행하려면 서버 일시 중단이 필요. 중단 → 실행 → 재시작 자동으로 진행할까?',
  },
  en: {
    offline_title: 'Offline',
    offline_msg: 'Community server is not running. Showing last snapshot (not live).',
    offline_last: 'last activity',
    empty_community_title: '📭 This community is empty',
    empty_community_msg: "No agents or conversations yet. Start the community server to populate data.",
    empty_community_hint: 'Start server',
    kpi_server: 'Server Status', kpi_bot: 'Discord Bot', kpi_owner: 'Owner',
    kpi_scene: 'Active Scene', kpi_msgs: 'Messages',
    online: '● Online', offline_short: '○ Offline',
    running: '● Running', stopped: '○ Stopped',
    nothing_active: 'nothing active',
    section_active_members: 'Agents', section_recent_conv: 'Recent Conversations',
    tab_overview: 'Overview', tab_agents: 'Agents', tab_channels: 'Channels',
    tab_messages: 'Messages', tab_scenes: 'Scenes', tab_events: 'Events',
    tab_health: 'Health', tab_sync: 'Sync', tab_dev: 'Dev', tab_usage: 'Usage',
    tab_supervisors: 'Supervisors', tab_logs: 'Logs',
    btn_server_start: '▶ Start Server', btn_server_stop: '⏸ Stop Server',
    btn_server_restart: '↻ Restart',
    btn_scan: '🔍 Scan Discord', btn_sync: '▶ Full Sync', btn_restore: '↻ Restore Messages',
    btn_clear_msgs: '🧹 Clear All Messages (DB only)',
    btn_delete_ch: '🗑 Delete Channel',
    btn_refresh: 'Refresh', btn_empty_trash: 'Empty Trash', btn_close: 'Close',
    sec_processes: 'Processes', sec_glimi_resources: 'Glimi Resource Usage',
    sec_system_resources: 'System Resources', sec_server_control: 'Server Control',
    sec_sync_actions: 'Sync Actions', sec_trash: 'Trash',
    sec_db_channels: 'DB-registered Channels',
    sec_profile: 'Profile', sec_relationships: 'Relationships',
    sec_memory: 'Memory', sec_thinking_logs: 'Thinking Logs',
    sec_recent_chat: 'Recent Chat', sec_participants: 'Participants',
    sec_all_messages: 'All Messages', sec_actions: 'Actions',
    sec_connection_graph: 'Connection Graph',
    status_active: 'Active', status_completed: 'Completed', status_not_started: 'Not Started',
    active_badge: '● ACTIVE', idle_badge: '○ IDLE', intervening_badge: '● INTERVENING',
    live_label: '● LIVE',
    thinking: 'thinking', speaking: 'speaking',
    calm_idle: 'calm · all idle',
    loading: 'Loading…', no_data: 'No data',
    no_members: 'No members', no_channels: 'No channels',
    no_events: 'No events recorded',
    no_scenes: 'No scenes', no_supervisors: 'No supervisors registered',
    no_msgs: 'No conversations', no_trash: 'Trash is empty',
    f_age: 'Age', f_mbti: 'MBTI', f_enneagram: 'Enneagram', f_traits: 'Traits',
    f_emotion: 'Emotion', f_status: 'Status', f_model: 'Model', f_owner: 'Owner',
    f_background: 'Background',
    f_started: 'Started', f_completed: 'Completed', f_last_active: 'last active',
    sync_guard_running: 'ℹ Server is running — clicking a sync button will auto stop server → run → restart. A confirm dialog lets you cancel.',
    sync_guard_stopped: '○ Server offline — all sync actions available.',
    sync_hint: 'Synchronize state between Discord and the DB. Server is auto-stopped/restarted as needed.',
    trash_hint: 'Trash — deleted channels/messages go here first. Safety net for accidental deletion.',
    confirm_clear: 'Clear all messages in #{ch} from DB? Discord channel will be kept.',
    confirm_delete_ch: 'Delete channel #{ch} completely? Hard to recover.',
    confirm_trash_msg: 'Move this message to trash? (recoverable)',
    confirm_empty_trash: 'Empty the Trash permanently? This cannot be undone.',
    confirm_stop_server: 'Stop the community server?',
    confirm_restart_server: 'Restart the server? (takes 10-20s)',
    confirm_sync_restart: 'Running {act} needs a temporary server stop. Auto stop → run → restart. Continue?',
  },
};
// (duplicate currentLang/t removed — defined earlier using fetched I18N_CACHE)

// ==== Utils ====
function esc(s) { return String(s ?? '').replace(/[<>&"]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;'}[c])); }

// Model 표시: " · " 구분자로 여러 모델 → 각 모델별 chip 블록
//   모델 이름에서 family 추출 (haiku / sonnet / opus / gpt / gemini) → 일관된 색
//   "+" 구분자 제거 — chip 자체로 구분
function _modelFamilyClass(p) {
  const s = String(p).toLowerCase();
  if (s.includes('haiku')) return 'm-haiku';
  if (s.includes('sonnet')) return 'm-sonnet';
  if (s.includes('opus')) return 'm-opus';
  if (s.includes('gpt') || s.includes('o1') || s.includes('o3')) return 'm-gpt';
  if (s.includes('gemini')) return 'm-gemini';
  return '';
}
function renderModelChips(d, compact) {
  if (!d || !d.model) return '';
  const raw = String(d.model);
  const parts = raw.split(/\s*·\s*/).map(s => s.trim()).filter(Boolean);
  const provider = d.provider || '';
  const override = d.model_override ? ' override' : '';
  const title = d.model_override ? 'per-agent override' : 'default';
  const chips = parts.map(p => {
    const fam = _modelFamilyClass(p);
    const classes = ['model-tag', provider, fam, override.trim()].filter(Boolean).join(' ');
    return `<span class="${classes}" title="${esc(title)}">${esc(p)}</span>`;
  }).join('');
  const suffix = compact
    ? ''
    : (d.model_override
        ? ' <small style="color:var(--accent)">override</small>'
        : '<small style="color:var(--text-faint)"> · default</small>');
  return `<span class="model-chip-row">${chips}</span>${suffix}`;
}
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

function renderGpuCard(gpu, sysMemTotal, sysMemUsed) {
  if (!gpu || !gpu.supported) {
    return `<div class="health-card" style="opacity:0.5">
      <h4>GPU</h4>
      <div class="big" style="font-size:13px;color:var(--text-faint)">감지되지 않음</div>
      <div class="sub">${esc(gpu?.platform || 'unknown platform')}</div>
    </div>`;
  }
  if (gpu.unified_memory) {
    // Apple Silicon: unified memory — GPU VRAM = system RAM 공유
    const pct = sysMemTotal ? (sysMemUsed / sysMemTotal * 100).toFixed(1) : 0;
    return `<div class="health-card">
      <h4>GPU · ${esc(gpu.name || 'Apple Silicon')}</h4>
      <div class="big" style="font-size:15px">${esc(gpu.name || 'Apple Silicon')}${gpu.cores ? ` · ${gpu.cores} cores` : ''}</div>
      <div class="sub">Unified Memory (${fmtBytes(sysMemTotal)} shared w/ RAM)</div>
      <div class="disk-bar"><span style="width:${pct}%"></span></div>
    </div>`;
  }
  // Dedicated GPU (e.g. NVIDIA)
  const vramPct = gpu.vram_total_bytes ? (gpu.vram_used_bytes / gpu.vram_total_bytes * 100).toFixed(1) : 0;
  return `<div class="health-card">
    <h4>GPU · ${esc(gpu.name || 'GPU')}</h4>
    <div class="big">${gpu.utilization_pct}<small style="font-size:13px;color:var(--text-dim)">%</small></div>
    <div class="sub">VRAM: ${fmtBytes(gpu.vram_used_bytes)} / ${fmtBytes(gpu.vram_total_bytes)} · ${vramPct}%</div>
    <div class="disk-bar"><span style="width:${vramPct}%"></span></div>
  </div>`;
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

// ==== Supervisor view toggle ====
let SHOW_SUP = localStorage.getItem('glimi-show-supervisors') === 'true';
function applySupVisibility() {
  document.body.classList.toggle('show-supervisors', SHOW_SUP);
  document.getElementById('supervisor-toggle').classList.toggle('active', SHOW_SUP);
  // 비활성화 시 Supervisors 탭에 있었으면 overview로 돌리기
  if (!SHOW_SUP) {
    const supView = document.getElementById('view-supervisors');
    if (supView && supView.classList.contains('active')) {
      document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
      document.querySelectorAll('nav.tabs button').forEach(b => b.classList.remove('active'));
      document.getElementById('view-overview').classList.add('active');
      document.querySelector('nav.tabs button[data-tab="overview"]').classList.add('active');
    }
  }
}
applySupVisibility();
document.getElementById('supervisor-toggle').addEventListener('click', () => {
  SHOW_SUP = !SHOW_SUP;
  localStorage.setItem('glimi-show-supervisors', SHOW_SUP ? 'true' : 'false');
  applySupVisibility();
  lastGraphSig = null;  // supervisor 노드 출현/사라짐 → 재렌더
  tick();
});

// ==== Language toggle (flag button + dropdown menu) ====
const LANG_OPTIONS = [
  { id: null,  flag: '🌐', label: 'Auto' },
  { id: 'ko',  flag: '🇰🇷', label: '한국어' },
  { id: 'en',  flag: '🇺🇸', label: 'English' },
];
function applyLangLabel() {
  const btn = document.getElementById('lang-toggle');
  if (!btn) return;
  const l = currentLang();
  // 버튼에는 항상 현재 활성 언어의 국기만 (Auto면 서버언어 국기)
  const flag = LANG_OVERRIDE
    ? (LANG_OVERRIDE === 'ko' ? '🇰🇷' : '🇺🇸')
    : (l === 'ko' ? '🇰🇷' : '🇺🇸');
  btn.textContent = flag;
  btn.title = LANG_OVERRIDE
    ? (LANG_OVERRIDE === 'ko' ? '한국어 (고정) — 클릭하여 변경' : 'English (fixed) — click to change')
    : `Auto — server: ${SERVER_LANG.toUpperCase()}`;
  renderLangMenu();
  applyStaticI18n();
}
function renderLangMenu() {
  const menu = document.getElementById('lang-menu');
  if (!menu) return;
  menu.innerHTML = LANG_OPTIONS.map(opt => {
    const active = (opt.id === LANG_OVERRIDE) || (opt.id === null && !LANG_OVERRIDE);
    const sub = opt.id === null ? ` <span style="color:var(--text-faint);font-size:11px">(${SERVER_LANG.toUpperCase()})</span>` : '';
    return `<div class="li ${active ? 'active' : ''}" data-lang="${opt.id === null ? '' : opt.id}">
      <span class="li-flag">${opt.flag}</span>
      <span class="li-name">${opt.label}${sub}</span>
      <span class="li-check"></span>
    </div>`;
  }).join('');
  menu.querySelectorAll('.li').forEach(el => {
    el.addEventListener('click', () => {
      const v = el.dataset.lang;
      LANG_OVERRIDE = v ? v : null;
      if (LANG_OVERRIDE) localStorage.setItem('glimi-lang', LANG_OVERRIDE);
      else localStorage.removeItem('glimi-lang');
      menu.classList.remove('open');
      applyLangLabel();
      tick();
    });
  });
}
function applyStaticI18n() {
  // 탭 라벨
  const tabMap = {
    overview: 'tab_overview', agents: 'tab_agents', channels: 'tab_channels',
    messages: 'tab_messages', scenes: 'tab_scenes', events: 'tab_events',
    health: 'tab_health', sync: 'tab_sync', dev: 'tab_dev', usage: 'tab_usage',
    supervisors: 'tab_supervisors', logs: 'tab_logs',
  };
  document.querySelectorAll('nav.tabs button[data-tab]').forEach(btn => {
    const k = tabMap[btn.dataset.tab];
    if (!k) return;
    const cnt = btn.querySelector('.count');
    const cntHtml = cnt ? cnt.outerHTML : '';
    btn.innerHTML = t(k) + ' ' + cntHtml;
  });
  // KPI labels
  const kpiMap = [['kpi-server','kpi_server'],['kpi-bot','kpi_bot'],['kpi-user','kpi_owner'],['kpi-scene','kpi_scene'],['kpi-msgs','kpi_msgs']];
  kpiMap.forEach(([id, k]) => {
    const el = document.getElementById(id);
    if (el && el.previousElementSibling && el.previousElementSibling.classList.contains('label')) {
      el.previousElementSibling.textContent = t(k);
    }
  });
  // Detail close button
  const closeBtn = document.getElementById('d-close');
  if (closeBtn) closeBtn.textContent = t('btn_close');
}
document.getElementById('lang-toggle').addEventListener('click', (ev) => {
  ev.stopPropagation();
  const menu = document.getElementById('lang-menu');
  if (!menu) return;
  renderLangMenu();
  menu.classList.toggle('open');
});
document.addEventListener('click', (ev) => {
  const wrap = document.getElementById('lang-switcher-wrap');
  if (!wrap) return;
  if (!wrap.contains(ev.target)) {
    document.getElementById('lang-menu')?.classList.remove('open');
  }
});

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
  // last_active를 상대 시간으로 표시
  let agoText = '';
  if (a.last_active) {
    try {
      const dt = new Date(a.last_active);
      const secs = (Date.now() - dt.getTime()) / 1000;
      if (secs < 60) agoText = `${Math.floor(secs)}s`;
      else if (secs < 3600) agoText = `${Math.floor(secs/60)}m`;
      else if (secs < 86400) agoText = `${Math.floor(secs/3600)}h`;
      else agoText = `${Math.floor(secs/86400)}d`;
    } catch {}
  }
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
          ${a.mbti ? `<span class="sep">·</span><span>${esc(a.mbti)}</span>` : ''}
          ${a.age ? `<span class="sep">·</span><span>${a.age}y</span>` : ''}
        </div>
      </div>
      <span class="state-badge thinking">thinking</span>
      <span class="state-badge speaking">speaking</span>
    </div>
    <div class="agent-footer">
      ${a.model ? renderModelChips(a, true) : '<span></span>'}
      ${agoText ? `<span title="last active">${agoText} ago</span>` : ''}
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
      ${avatarsHtml || '<div style="color:var(--text-faint);padding:16px 0">no agents yet</div>'}
    </div>
    <div class="hero-text" style="flex:1">
      <h1><span class="sv-name">${esc(snap.community_id)}</span> <span style="color:var(--text-faint);font-weight:400"> · ${esc(descText)}</span></h1>
      <p>${activeText}</p>
    </div>
  </div>`;
}

function openImgLightbox(src, caption) {
  const box = document.getElementById('lightbox');
  const img = document.getElementById('lightbox-img');
  const cap = document.getElementById('lightbox-caption');
  img.src = src;
  cap.textContent = caption || '';
  box.classList.add('open');
}

function openFullAvatar(agentId, name) {
  const src = `/api/avatar?id=${encodeURIComponent(agentId)}&variant=full${COMMUNITY ? '&community=' + encodeURIComponent(COMMUNITY) : ''}`;
  openImgLightbox(src, name || agentId);
}

// 모든 <img> 클릭 시 자동으로 lightbox 띄우기 (delegation)
document.addEventListener('click', (e) => {
  const img = e.target.closest('img');
  if (!img) return;
  // 이미 lightbox 안의 이미지거나 미니 상태면 스킵
  if (img.closest('.lightbox')) return;
  // 아바타/로고는 별도 핸들러 우선 (onclick이 있으면 자동 스킵)
  if (img.closest('[onclick]') && img.closest('[onclick]') !== img) return;
  // 그 외 일반 이미지: 원본 띄우기
  e.stopPropagation();
  openImgLightbox(img.src, img.alt || '');
});

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
    'mgr': 'Manager',
    'dm': 'DM',
    'group': 'Group',
    'internal-dm': 'Internal DM',
    'internal-group': 'Internal Group',
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
  // Age: 가독성 — 한국어면 "만 N세 (한국나이 N+1)" 식 / 영어면 "N years old"
  //   한국나이 = 현재연도 - 출생연도 + 1 (전통 세는나이; birth_year 있을 때만)
  if (d.age) {
    const lang = currentLang();
    if (lang === 'ko') {
      let ageStr = `만 ${d.age}세`;
      if (d.birth_year) {
        const koreanAge = (new Date()).getFullYear() - d.birth_year + 1;
        if (koreanAge !== d.age) ageStr += ` (한국나이 ${koreanAge}세)`;
      }
      profileLines.push(['Age', ageStr]);
    } else {
      profileLines.push(['Age', `${d.age} years old`]);
    }
  }
  if (d.gender) profileLines.push(['Gender', d.gender]);
  if (d.mbti) profileLines.push(['MBTI', d.mbti]);
  if (d.enneagram) profileLines.push(['Enneagram', d.enneagram]);
  if (d.traits && d.traits.length) profileLines.push(['Traits', d.traits.slice(0,5).join(' · ')]);
  profileLines.push(['Emotion', `${d.emoji} ${d.emotion} (${d.intensity}/10)`]);
  // 서버 오프라인이면 thinking/speaking/active 상태는 의미 없음 → Inactive 로 강제
  //   (DB status 는 archived 같은 영속 상태만 의미; runtime 상태는 봇이 실행 중일 때만 유효)
  const isOffline = document.body.classList.contains('offline');
  let statusHtml;
  if (isOffline) {
    statusHtml = '<span style="color:var(--text-dim)">○ Inactive (서버 오프라인)</span>';
  } else if (d.thinking) {
    statusHtml = '<span style="color:var(--thinking)">🧠 Thinking</span>';
  } else if (d.speaking) {
    statusHtml = '<span style="color:var(--speaking)">💬 Speaking</span>';
  } else if (d.status === 'active') {
    statusHtml = '<span style="color:var(--ok)">● Active</span>';
  } else {
    statusHtml = `<span style="color:var(--text-dim)">○ ${esc(d.status)}</span>`;
  }
  profileLines.push(['Status', statusHtml, true]);
  if (d.model) profileLines.push(['Model', renderModelChips(d), true]);
  if (d.relationship_to_owner?.type) {
    const r = d.relationship_to_owner;
    profileLines.push(['Owner', `${r.type}${r.pet_name ? ' (' + r.pet_name + ')' : ''}${r.duration ? ' · ' + r.duration : ''}`]);
  }
  if (d.background) profileLines.push(['Background', d.background]);

  const rels = (d.relationships || []).map(r => {
    const pct = Math.min(100, r.intimacy);
    return `<div class="rel-row">
      <span class="rname" title="${esc(r.other_name)}">${esc(r.other_name)}</span>
      <span class="rtype" title="${esc(r.type)}">${esc(r.type)}</span>
      <div class="intimacy-bar"><span style="width:${pct}%"></span></div>
      <span class="intimacy-num">${r.intimacy}</span>
      ${r.dynamics ? `<span class="dynamics" title="${esc(r.dynamics)}">${esc(r.dynamics)}</span>` : ''}
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
  const msgs = (d.messages || []).map(m => renderMessageWithActions(m, name)).join('');
  const protected_ch = name.startsWith('mgr-') || name.startsWith('dm-');
  const actions = `
    <div class="detail-section">
      <h4>Actions</h4>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="act-btn danger small" onclick="doChannelClear('${esc(name)}')">🧹 메시지 전체 삭제 (DB만)</button>
        ${!protected_ch ? `<button class="act-btn danger small" onclick="doChannelDelete('${esc(name)}')">🗑 채널 삭제</button>` : ''}
      </div>
    </div>`;
  const body = `
    <div class="detail-section">
      <h4>Participants · ${d.participants.length}</h4>
      <div style="display:flex;gap:6px;flex-wrap:wrap">${parts || '<span style="color:var(--text-faint)">none</span>'}</div>
    </div>
    ${actions}
    <div class="detail-section">
      <h4>All Messages · ${d.message_count}</h4>
      <div style="color:var(--text-dim);font-size:11px;margin-bottom:8px">각 메시지 우측 🗑 버튼으로 개별 trash 이동</div>
      <div class="msg-list" id="ch-messages-${esc(name)}">${msgs || '<div class="empty">no messages</div>'}</div>
    </div>`;
  openModal(chIcon(name), '#' + name, body);
}

function renderMessageWithActions(m, channelName) {
  return `<div class="msg ${roleClass(m)}" data-msg-id="${m.id || ''}" style="position:relative">
    ${miniAvatarHtml(m.speaker_id, m.is_user, m.speaker)}
    <div class="msg-body" style="padding-right:28px">
      <div class="head">
        <span class="who">${esc(m.speaker)}</span>
        <span class="ch" onclick="event.stopPropagation(); openChannel('${esc(m.channel)}')">#${esc(m.channel)}</span>
        <span class="ts">${esc((m.timestamp||'').slice(11, 19))}</span>
      </div>
      <div class="text">${esc(m.message)}</div>
    </div>
    ${m.id ? `<button class="msg-del-btn" onclick="event.stopPropagation(); doTrashMessage('${esc(channelName)}', ${m.id}, this)" title="이 메시지 Trash로 이동">🗑</button>` : ''}
  </div>`;
}

async function doTrashMessage(channel, msgId, btn) {
  if (!confirm('이 메시지를 trash로 옮길까? (복구 가능)')) return;
  const r = await postJson(q('/api/action/trash_message'), {channel, message_id: msgId});
  if (r.error) return toast(r.message || r.error, 'err');
  toast('trash로 이동됨', 'ok');
  // 해당 메시지 카드 fade out + remove
  const card = btn?.closest('.msg');
  if (card) {
    card.style.transition = 'opacity 0.3s, transform 0.3s';
    card.style.opacity = '0';
    card.style.transform = 'translateX(20px)';
    setTimeout(() => card.remove(), 300);
  }
}

// ==== Mutation actions ====
function toast(msg, variant='ok', ms=3000) {
  const el = document.getElementById('toast');
  el.className = `toast show ${variant}`;
  el.textContent = msg;
  setTimeout(() => { el.classList.remove('show'); }, ms);
}

async function postJson(url, body) {
  try {
    const r = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body || {}),
    });
    return await r.json();
  } catch (e) {
    return {error: 'fetch_failed', message: String(e)};
  }
}

async function waitFor(cond, msEach=500, maxTries=60) {
  for (let i = 0; i < maxTries; i++) {
    if (await cond()) return true;
    await new Promise(r => setTimeout(r, msEach));
  }
  return false;
}

async function isBotRunning() {
  const d = await j('/api/communities');
  if (!d) return false;
  const item = (d.items || []).find(c => c.id === (COMMUNITY || d.active));
  return !!(item && item.running);
}

async function runSyncAction(action) {
  const endpoints = {
    scan: '/api/action/scan_discord',
    sync: '/api/action/run_sync',
    restore: '/api/action/restore',
  };
  const labels = { scan: 'Scan Discord', sync: 'Full Sync', restore: 'Restore Messages' };
  const out = document.getElementById('sync-output');
  const appendOut = (s) => { out.textContent += s + '\n'; out.scrollTop = out.scrollHeight; };
  out.textContent = '';

  // 서버 실행 중이면 자동 stop → run → restart 플로우
  const running = await isBotRunning();
  let restartAfter = false;

  if (running) {
    if (!confirm(`${labels[action]}를 실행하려면 서버 일시 중단이 필요. 중단 → 실행 → 재시작 자동으로 진행할까?`)) {
      appendOut('❌ 취소됨');
      return;
    }
    restartAfter = true;
    appendOut('⏸ 서버 중단 중...');
    const stopR = await postJson(q('/api/action/stop_server'), {});
    if (stopR.error) { appendOut(`❌ 중단 실패: ${stopR.message || stopR.error}`); toast('중단 실패', 'err'); return; }
    appendOut(`✓ 프로세스 ${stopR.count}개 종료`);
    // running=false 될 때까지 대기 (최대 30초)
    const stopped = await waitFor(async () => !(await isBotRunning()), 1000, 30);
    if (!stopped) { appendOut('⚠ 서버가 여전히 running 감지 — 계속 진행'); }
    appendOut('● 서버 오프라인 확인');
  }

  appendOut(`▶ ${labels[action]} 실행 중...`);
  const r = await postJson(q(endpoints[action]), {});
  if (r.error) {
    appendOut(`❌ ${r.message || r.error}`);
    toast(r.message || r.error, 'err');
  } else {
    appendOut('✓ 완료');
    if (r.logs && r.logs.length) appendOut(r.logs.join('\n'));
    if (r.result) appendOut(JSON.stringify(r.result, null, 2));
    toast(`${labels[action]} 완료`, 'ok');
  }

  if (restartAfter) {
    appendOut('\n▶ 서버 재시작 중...');
    const startR = await postJson(q('/api/action/start_server'), {});
    if (startR.error) { appendOut(`⚠ 재시작 실패: ${startR.message || startR.error}`); toast('재시작 실패 — 수동 기동 필요', 'err', 5000); }
    else { appendOut('● 서버 재시작 요청됨 (10~20초 후 online)'); toast('서버 재시작 중', 'ok'); }
  }
  tick();
}

async function doChannelClear(channel) {
  if (!confirm(`#${channel}의 DB 메시지 전체 삭제. Discord 채널은 유지. 진행?`)) return;
  const r = await postJson(q('/api/action/channel_clear'), {channel});
  if (r.error) return toast(r.message || r.error, 'err');
  toast(`#${channel} 메시지 ${r.deleted?.deleted_count || '?'}개 삭제됨`, 'ok');
  closeModal();
  tick();
}

async function doChannelDelete(channel) {
  if (!confirm(`채널 #${channel} 완전 삭제. ${channel.startsWith('mgr-') ? 'mgr 채널은 보호돼야 함!' : '복구 어려움.'} 진행?`)) return;
  const r = await postJson(q('/api/action/channel_delete'), {channel});
  if (r.error) return toast(r.message || r.error, 'err');
  toast(`#${channel} 삭제됨. ${r.note || ''}`, 'ok');
  closeModal();
  tick();
}

async function loadTrash() {
  const r = await postJson(q('/api/action/trash_list'), {});
  const countEl = document.getElementById('trash-count');
  const listEl = document.getElementById('trash-list');
  if (!r.ok) {
    if (countEl) countEl.textContent = 'error';
    return;
  }
  const items = r.items || [];
  if (countEl) countEl.textContent = `${items.length}건`;
  if (!listEl) return;
  listEl.innerHTML = items.length ? items.slice(0, 30).map(t =>
    `<div class="trash-item">
      <span class="ch">#${esc(t.channel || '')}</span>
      <span class="who">${esc(t.speaker || '')}</span>
      <span class="msg">${esc((t.message || '').slice(0, 80))}</span>
      <button class="act-btn small" onclick="restoreTrash(${t.id})">복구</button>
    </div>`
  ).join('') : '<div class="empty">trash empty</div>';
}

async function restoreTrash(tid) {
  const r = await postJson(q('/api/action/trash_restore'), {trash_id: tid});
  if (r.error) return toast(r.message || r.error, 'err');
  toast('복구됨', 'ok');
  loadTrash();
  tick();
}

async function emptyTrash() {
  if (!confirm('Trash 전체 비우기. 되돌릴 수 없음. 진행?')) return;
  const r = await postJson(q('/api/action/trash_empty'), {});
  if (r.error) return toast(r.message || r.error, 'err');
  toast('Trash 비워짐', 'ok');
  loadTrash();
}

async function runServerControl(action) {
  const labels = { start: '시작', stop: '중단', restart: '재시작' };
  const endpoints = { start: 'start_server', stop: 'stop_server', restart: 'restart_server' };
  const out = document.getElementById('sync-output');
  const appendOut = (s) => { if (out) { out.textContent += s + '\n'; out.scrollTop = out.scrollHeight; } };
  if (action === 'stop' && !confirm('커뮤니티 서버 중단?')) return;
  if (action === 'restart' && !confirm('서버 재시작? (10~20초 소요)')) return;

  if (out) out.textContent = `▶ 서버 ${labels[action]} 중...\n`;
  const r = await postJson(q(`/api/action/${endpoints[action]}`), {});
  if (r.error) {
    appendOut(`❌ ${r.message || r.error}`);
    toast(`서버 ${labels[action]} 실패: ${r.message || r.error}`, 'err');
    return;
  }
  appendOut(`✓ 서버 ${labels[action]} 요청 완료`);
  if (r.count !== undefined) appendOut(`  종료된 프로세스: ${r.count}개`);
  if (r.message) appendOut(`  ${r.message}`);
  toast(`서버 ${labels[action]} ${action === 'stop' ? '완료' : '중'}`, 'ok');
  setTimeout(() => { tick(); loadCommunities(); }, 2000);
}

// ==== Main tick ====
// ==== Supervisors (agent card 포맷으로 재사용) ====
// name 기반 친화 표시명 매핑
const SUP_DISPLAY_NAME = {
  'onboarding': 'Onboarding',
  'channel-conv': 'Channel Conversation',
};
function supDisplayName(name) {
  return SUP_DISPLAY_NAME[name] || name;
}
function supervisorAsAgent(s) {
  const statusEmoji = s.intervening ? '🔥' : (s.active ? '💭' : '💤');
  const emotion = s.intervening ? '개입 중' : (s.active ? '감시 중' : '대기');
  return {
    id: `sup:${s.name}`,
    type: 'supervisor',
    name: supDisplayName(s.name),
    status: s.active ? 'active' : 'inactive',
    emotion,
    emoji: s.icon || statusEmoji,
    intensity: s.intervening ? 10 : (s.active ? 5 : 0),
    mbti: '',
    age: 0,
    last_active: s.last_action || '',
    thinking: s.intervening,
    speaking: false,
    thinking_seconds: s.seconds_since_action || 0,
    speaking_seconds: 0,
    // supervisor는 Haiku judge + Sonnet inject 혼용
    model: 'claude-haiku-4-5 · claude-sonnet-4-6',
    provider: 'claude',
    model_override: false,
    _sup: s,  // 원본 supervisor 데이터
  };
}

function renderSupervisorsTab(supervisors) {
  if (!supervisors || !supervisors.length) {
    return '<div class="empty">등록된 감시자 없음</div>';
  }
  const active = supervisors.filter(s => s.active);
  const inactive = supervisors.filter(s => !s.active);

  const renderGroup = (title, arr, hint) => {
    if (!arr.length) return '';
    // renderAgent 재사용 — 같은 양식으로 렌더. agent-grid로 감싸서 hover/layout 동일.
    const cards = arr.map(s => renderAgent(supervisorAsAgent(s))).join('');
    return `<div class="detail-section"${title === 'Active' ? ' style="margin-top:0"' : ''}>
      <h4>${esc(title)} · ${arr.length}</h4>
      ${hint ? `<div style="color:var(--text-dim);font-size:11.5px;margin-bottom:10px">${esc(hint)}</div>` : ''}
      <div class="agent-grid">${cards}</div>
    </div>`;
  };

  return [
    renderGroup('Active', active, '현재 조건 충족 — 백그라운드 감시 중'),
    renderGroup('Idle', inactive, '현재 조건 미충족 — 트리거 대기'),
  ].join('');
}

// 그래프 구조 서명 — 다르면 재렌더, 같으면 live 상태만 업데이트
let lastGraphSig = null;
function graphSignature(snap) {
  const agents = snap.agents.map(a => a.id).sort().join(',');
  const chans = (snap.channels || [])
    .filter(c => c.msg_count > 0 || c.status === 'running')
    .map(c => `${c.name}:${c.participant_count}:${c.status}`)
    .sort().join('|');
  const sups = SHOW_SUP
    ? (snap.supervisors || []).map(s => `${s.name}:${s.active ? 1 : 0}`).sort().join(',')
    : '';
  return `${agents}||${chans}||${sups}||${SHOW_SUP ? 1 : 0}||${document.body.classList.contains('graph-fullscreen') ? 'fs' : 'n'}`;
}

// ==== Connection Graph (Cytoscape.js) ====
// 자체 제작 SVG 그래프(휴리스틱 충돌회피, 라벨 push 등) 폐기 → cytoscape.js
//   - 데이터 빌드: snap → cy elements (nodes / edges) 만 책임
//   - 레이아웃 / 충돌회피 / 라벨배치 / 다중엣지 spread = 라이브러리에 위임
//   - signature 변할 때 destroy + recreate, live 상태만 변하면 cy.batch()로 클래스 토글
let cyInstance = null;

let cyLiveAnimTimer = null;
function destroyCyGraph() {
  if (cyLiveAnimTimer) { clearInterval(cyLiveAnimTimer); cyLiveAnimTimer = null; }
  if (cyInstance) {
    try { cyInstance.destroy(); } catch (e) {}
    cyInstance = null;
  }
}

// 추론/발화 중 노드: border-width + 색상 펄스 (skin-of-the-teeth halo via underlay-padding)
let cyNodePulseTimer = null;
let cyNodePulsePrev = [];
function _resetNodeInlineStyle(n) {
  try { n.removeStyle('border-width underlay-color underlay-padding underlay-opacity underlay-shape'); }
  catch (e) {}
}
function startNodePulseAnimation() {
  if (!cyInstance) return;
  if (cyNodePulseTimer) { clearInterval(cyNodePulseTimer); cyNodePulseTimer = null; }
  // 이전 라운드에서 펄스 적용한 노드들의 inline 스타일 제거 (class 빠진 노드 깨끗이)
  for (const n of cyNodePulsePrev) {
    if (!n.hasClass('thinking') && !n.hasClass('speaking')) _resetNodeInlineStyle(n);
  }
  // 오프라인 (stale flag)이면 펄스 안 함 — agent-card와 동일 정책
  if (document.body.classList.contains('offline')) {
    cyInstance.nodes('.thinking, .speaking').forEach(_resetNodeInlineStyle);
    cyNodePulsePrev = [];
    return;
  }
  const liveNodes = cyInstance.nodes('.thinking, .speaking');
  cyNodePulsePrev = liveNodes.toArray();
  if (liveNodes.length === 0) return;
  let pulse = 0;
  cyNodePulseTimer = setInterval(() => {
    pulse = (pulse + 0.06) % (Math.PI * 2);
    const sin = Math.sin(pulse);
    const ease = (sin + 1) * 0.5;            // 0 ~ 1
    const borderWidth = 4.5 + ease * 1.0;    // 4.5 ~ 5.5
    const underlayPad = 2 + ease * 6;        // 2 ~ 8
    const underlayOp = 0.10 + ease * 0.18;   // 0.10 ~ 0.28
    cyInstance.batch(() => {
      liveNodes.forEach(n => {
        const isSpeak = n.hasClass('speaking');
        const color = isSpeak ? n.cy().scratch('_speakingColor') : n.cy().scratch('_thinkingColor');
        n.style({
          'border-width': borderWidth,
          'underlay-color': color,
          'underlay-padding': underlayPad,
          'underlay-opacity': underlayOp,
          'underlay-shape': 'ellipse',
        });
      });
    });
  }, 60);
}

// 라이브(활성) 엣지: 굵기 + 글로우 padding 펄스 — solid line 위로 pulsing halo 효과
function startLiveEdgeAnimation() {
  if (!cyInstance) return;
  if (cyLiveAnimTimer) { clearInterval(cyLiveAnimTimer); cyLiveAnimTimer = null; }
  const liveEdges = cyInstance.edges('.live');
  if (liveEdges.length === 0) return;
  // 오프라인이면 정적 라인만
  if (document.body.classList.contains('offline')) {
    cyInstance.batch(() => {
      liveEdges.forEach(e => e.style({ 'width': 2, 'opacity': 0.5, 'overlay-opacity': 0 }));
    });
    return;
  }
  let pulse = 0;
  cyLiveAnimTimer = setInterval(() => {
    pulse = (pulse + 0.1) % (Math.PI * 2);
    const sin = Math.sin(pulse);
    const width = 3 + sin * 0.8;          // 2.2 ~ 3.8
    const overlayOp = 0.18 + sin * 0.12;   // 0.06 ~ 0.30
    const overlayPad = 5 + sin * 3;        // 2 ~ 8
    cyInstance.batch(() => {
      liveEdges.forEach(e => {
        e.style({
          'width': width,
          'overlay-color': cyInstance.scratch('_thinkingColor'),
          'overlay-opacity': overlayOp,
          'overlay-padding': overlayPad,
        });
      });
    });
  }, 50);
}

// 구조 동일 → 노드 live 상태(thinking/speaking, sup active/intervening) cy 클래스 토글
function updateGraphLiveState(snap) {
  if (!cyInstance) return;
  const agentMap = {};
  for (const a of snap.agents) agentMap[a.id] = a;
  // 채널별 활성 상태 재계산 (recent OR party thinking/speaking)
  const liveChannels = new Set();
  for (const c of (snap.channels || [])) {
    const recent = c.last_ago && (
      c.last_ago === '방금' ||
      c.last_ago.includes('초') ||
      (c.last_ago.includes('분') && parseInt(c.last_ago) < 2)
    );
    const party = (c.participants || []).some(pid => {
      const ag = agentMap[pid];
      return ag && (ag.thinking || ag.speaking);
    });
    if (recent || party) liveChannels.add(c.name);
  }
  let liveCountChanged = false;
  cyInstance.batch(() => {
    for (const a of snap.agents) {
      const n = cyInstance.getElementById(a.id);
      if (n.empty()) continue;
      n.toggleClass('thinking', !!a.thinking);
      n.toggleClass('speaking', !!a.speaking);
    }
    cyInstance.edges().forEach(e => {
      const ch = e.data('channel');
      const wasLive = e.hasClass('live');
      const nowLive = liveChannels.has(ch);
      if (wasLive !== nowLive) {
        e.toggleClass('live', nowLive);
        liveCountChanged = true;
      }
    });
    if (SHOW_SUP) {
      for (const s of (snap.supervisors || [])) {
        const n = cyInstance.getElementById('sup:' + s.name);
        if (n.empty()) continue;
        n.toggleClass('active', !!s.active);
        n.toggleClass('intervening', !!s.intervening);
      }
    }
  });
  if (liveCountChanged) {
    startLiveEdgeAnimation();
  }
  startNodePulseAnimation();
}

// snap → { nodes, edges } cytoscape elements
function buildGraphElements(snap) {
  const ownerName = snap.meta?.user_name || 'Owner';
  const idToAgent = {};
  for (const a of snap.agents) idToAgent[a.id] = a;

  // 활성 채널만 (msg_count > 0 또는 running)
  const channels = (snap.channels || []).filter(c => {
    if (c.participant_count < 1) return false;
    return c.msg_count > 0 || c.status === 'running';
  });

  // raw edges — 채널 단위 + 참여자 모든 쌍 조합 (그룹 채널이면 N choose 2 개 엣지)
  const rawEdges = [];
  const involvedAgentIds = new Set();
  let ownerInvolved = false;
  for (const c of channels) {
    const parts = [];
    const includeOwner = (c.kind === 'dm' || c.kind === 'group' || c.kind === 'mgr');
    if (includeOwner) { parts.push('__owner__'); ownerInvolved = true; }
    for (const pid of (c.participants || [])) {
      if (idToAgent[pid]) {
        parts.push(pid);
        involvedAgentIds.add(pid);
      }
    }
    if (parts.length < 2) continue;
    // 활성 판정: 최근 발화 OR 참여자(에이전트 또는 owner) 중 한 명이라도 활동 중
    const recentLive = c.last_ago && (
      c.last_ago === '방금' ||
      c.last_ago.includes('초') ||
      (c.last_ago.includes('분') && parseInt(c.last_ago) < 2)
    );
    const partyLive = (c.participants || []).some(pid => {
      const ag = idToAgent[pid];
      return ag && (ag.thinking || ag.speaking);
    });
    // owner가 채널의 활동 주체일 수도 있음 — last_speaker 가 owner 면 즉시 활성
    const ownerActive = includeOwner && c.last_speaker && (
      c.last_speaker.startsWith('user') ||
      c.last_speaker === 'test-user' ||
      c.last_speaker === 'owner'
    ) && recentLive;
    const live = recentLive || partyLive || ownerActive;
    for (let i = 0; i < parts.length; i++) {
      for (let j = i + 1; j < parts.length; j++) {
        rawEdges.push({
          source: parts[i],
          target: parts[j],
          channel: c.name,
          kind: c.kind,
          live,
          msg_count: c.msg_count,
        });
      }
    }
  }

  // 엣지 없어도 mgr/creator 는 항상 표시
  for (const a of snap.agents) {
    if (a.type === 'mgr' || a.type === 'creator') involvedAgentIds.add(a.id);
  }

  // 노드 정렬: mgr 먼저 → creator → persona (concentric 배치 순서 결정)
  //   N=3 + startAngle=π 면: mgr 이 왼쪽, creator 가 오른쪽 으로 자연 배치됨
  const typeRank = { mgr: 0, creator: 1, persona: 2 };
  const sortedAgentIds = Array.from(involvedAgentIds).sort((a, b) => {
    const ra = typeRank[idToAgent[a]?.type] ?? 9;
    const rb = typeRank[idToAgent[b]?.type] ?? 9;
    return ra - rb;
  });

  const nodes = [];
  if (ownerInvolved) {
    nodes.push({
      data: { id: '__owner__', label: ownerName, kind: 'owner' },
      classes: 'owner',
    });
  }
  for (const aid of sortedAgentIds) {
    const a = idToAgent[aid];
    if (!a) continue;
    const liveCls = a.thinking ? 'thinking' : a.speaking ? 'speaking' : '';
    const avatar = `/api/avatar?id=${encodeURIComponent(a.id)}${COMMUNITY ? '&community=' + encodeURIComponent(COMMUNITY) : ''}`;
    nodes.push({
      data: { id: a.id, label: a.name, kind: 'agent', agentType: a.type, avatar },
      classes: ('agent ' + a.type + ' ' + liveCls).trim(),
    });
  }

  // Supervisor 노드 + 엣지
  const supEdges = [];
  if (SHOW_SUP && snap.supervisors) {
    const visibleSups = snap.supervisors.filter(s => {
      const tn = (s.target_agents || []).filter(aid => involvedAgentIds.has(aid));
      return tn.length > 0 || s.active || s.intervening;
    });
    for (const s of visibleSups) {
      const supId = 'sup:' + s.name;
      const cls = ['sup'];
      if (s.active) cls.push('active');
      if (s.intervening) cls.push('intervening');
      // 아이콘 이모지 → SVG text. viewBox 200x200 + 작은 font-size → diamond shape 안에 안전하게 fit
      const iconChar = s.icon || '◆';
      const iconSvg = 'data:image/svg+xml;utf8,' + encodeURIComponent(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200"><text x="100" y="125" font-size="80" text-anchor="middle" font-family="-apple-system,Segoe UI Emoji,Apple Color Emoji,Noto Color Emoji,sans-serif">' + iconChar + '</text></svg>'
      );
      nodes.push({
        data: { id: supId, label: supDisplayName(s.name), kind: 'sup', icon: iconChar, iconSvg },
        classes: cls.join(' '),
      });
      for (const aid of (s.target_agents || [])) {
        if (!involvedAgentIds.has(aid)) continue;
        let ec = 'sup-edge ';
        if (s.intervening) ec += 'intervening';
        else if (s.active) ec += 'active';
        else ec += 'idle';
        supEdges.push({
          data: { id: 'supedge:' + s.name + ':' + aid, source: supId, target: aid, kind: 'sup', label: '' },
          classes: ec,
        });
      }
    }
  }

  // cy edges (unique IDs, 라벨 = 채널명, 너무 길면 잘라냄)
  //   owner spoke 면 source=__owner__ target=agent 순서 보장됨 (위 parts 빌드 순서)
  //   → target-label 로 렌더하면 라벨이 agent 쪽 끝에 붙어 owner 중심에서 분산됨
  const truncLabel = (s) => (s.length > 16 ? s.slice(0, 14) + '…' : s);
  const edges = rawEdges.map((e, i) => ({
    data: {
      id: 'e' + i,
      source: e.source,
      target: e.target,
      label: truncLabel(e.channel),
      channel: e.channel,
      kind: e.kind,
      cpd: 0,
      cpw: 0.5,
    },
    classes: 'ch-' + e.kind + (e.live ? ' live' : ''),
  }));

  // 같은 source-target 페어가 여러 개면 perpendicular 방향으로 spread
  //   → unbundled-bezier 의 control-point-distances 에 페어별 인덱스 기반 offset 부여
  //   → 단일 엣지면 cpd=0 (직선)
  const pairBuckets = {};
  for (const e of edges) {
    const k = [e.data.source, e.data.target].sort().join('||');
    (pairBuckets[k] = pairBuckets[k] || []).push(e);
  }
  const PAIR_SPREAD = 38;  // 인접 엣지 간 px 거리
  for (const k in pairBuckets) {
    const grp = pairBuckets[k];
    const n = grp.length;
    if (n <= 1) continue;
    grp.forEach((e, i) => {
      e.data.cpd = (i - (n - 1) / 2) * PAIR_SPREAD;
    });
  }

  return { nodes, edges: edges.concat(supEdges) };
}

function pickGraphLayout(nodeCount, fullscreen) {
  // concentric — owner 중앙, agents 외곽 ring, supervisors 더 외곽
  //   fullscreen: spacingFactor 키워서 ring 반경 ↑ → 노드끼리 + 오너-에이전트 거리 넓어짐
  //   fit: true 가 알아서 캔버스 안으로 스케일 — spacingFactor 는 단순히 ratio 로 작용
  const minSpace = nodeCount <= 4 ? 120 : (nodeCount <= 8 ? 75 : 50);
  const spacingF = nodeCount <= 4 ? 1.4 : 1.25;
  return {
    name: 'concentric',
    concentric: function(node) {
      const k = node.data('kind');
      if (k === 'owner') return 3;
      if (k === 'agent') return 2;
      return 1;
    },
    levelWidth: function() { return 1; },
    // overview 는 padding 작게 → 노드들이 캔버스 가득 채워 크게 보임
    minNodeSpacing: fullscreen ? minSpace * 1.4 : minSpace,
    spacingFactor: fullscreen ? spacingF * 1.25 : spacingF,
    avoidOverlap: true,
    fit: true,
    padding: fullscreen ? 140 : 25,
    // N=3: startAngle=π → mgr(첫번째)는 왼쪽, creator(두번째)는 오른쪽
    // 그 외: top 부터 시작 (-π/2)
    startAngle: nodeCount === 3 ? Math.PI : -Math.PI / 2,
    animate: false,
  };
}

function renderConnectionGraph(snap) {
  // 활성 채널 + mgr/creator 존재 여부만 빠르게 체크 → 빈 상태면 placeholder
  const fullscreen = document.body.classList.contains('graph-fullscreen');
  const channels = (snap.channels || []).filter(c =>
    c.participant_count >= 1 && (c.msg_count > 0 || c.status === 'running')
  );
  const hasMgrCreator = snap.agents.some(a => a.type === 'mgr' || a.type === 'creator');
  const hasContent = channels.length > 0 || hasMgrCreator;

  const headHtml = `<div class="graph-head">
      <h3>Connection Graph</h3>
      <span class="note" id="graph-note"></span>
      <button class="graph-fs-btn" onclick="toggleGraphFullscreen()">${fullscreen ? '✕ 닫기' : '⛶ 전체보기'}</button>
    </div>`;

  if (!hasContent) {
    return headHtml + `<div class="graph-empty">활성 채널 없음 — 에이전트들이 조용히 대기 중</div>`;
  }

  const legend = `<div class="graph-legend">
    <div class="item"><span class="swatch" style="background:var(--accent)"></span>DM</div>
    <div class="item"><span class="swatch" style="background:var(--ok)"></span>Group</div>
    <div class="item"><span class="swatch" style="background:var(--cmd)"></span>Internal DM</div>
    <div class="item"><span class="swatch" style="background:var(--creator)"></span>Internal Group</div>
    <div class="item"><span class="swatch" style="background:var(--mgr)"></span>Manager</div>
    ${SHOW_SUP ? `<div class="item"><span class="swatch" style="background:var(--warn)"></span>Supervisor</div>` : ''}
    <div class="item" style="margin-left:auto"><span style="color:var(--text)">━━</span> 활성  <span style="color:var(--text-dim);margin-left:4px">┄┄</span> 대기</div>
  </div>`;

  return headHtml +
    `<div class="graph-stage"><div id="cy-graph" style="width:100%;height:100%"></div></div>` +
    legend;
}

// renderConnectionGraph 후 호출 — innerHTML 으로 들어간 #cy-graph 에 cytoscape 인스턴스 마운트
function mountCytoscapeGraph(snap) {
  destroyCyGraph();
  const container = document.getElementById('cy-graph');
  if (!container || typeof cytoscape === 'undefined') return;

  const { nodes, edges } = buildGraphElements(snap);
  if (nodes.length === 0) return;

  const fullscreen = document.body.classList.contains('graph-fullscreen');

  // CSS variable → 실제 색상값 (cytoscape style 은 var() 못 읽음)
  const cs = getComputedStyle(document.body);
  const tok = (n) => (cs.getPropertyValue(n) || '').trim();
  const C = {
    text: tok('--text') || '#222',
    textDim: tok('--text-dim') || '#888',
    panel: tok('--panel') || '#fff',
    border: tok('--border') || '#ddd',
    accent: tok('--accent') || '#4b8',
    ok: tok('--ok') || '#5c5',
    warn: tok('--warn') || '#c93',
    err: tok('--err') || '#c33',
    mgr: tok('--mgr') || '#a6f',
    creator: tok('--creator') || '#fa3',
    persona: tok('--persona') || '#48f',
    user: tok('--user') || '#fb6',
    cmd: tok('--cmd') || '#d6f',
    thinking: tok('--thinking') || '#fc6',
    speaking: tok('--speaking') || '#6cf',
  };

  // 노드 크기 — overview 에서도 충분히 크게 (사용자: "원이 멀리있다 = 작다")
  const nodeSize = fullscreen ? 70 : 64;
  const ownerSize = fullscreen ? 66 : 60;
  const supSize = fullscreen ? 54 : 48;
  const fontSize = fullscreen ? 12 : 11.5;

  cyInstance = cytoscape({
    container,
    elements: { nodes, edges },
    minZoom: 0.5,
    maxZoom: 2.5,
    boxSelectionEnabled: false,
    autounselectify: true,
    // overview 모드 (default): 그래프 내부 휠/드래그 비활성
    //   → 페이지 전체 스크롤이 그래프 위에서도 자연스럽게 동작
    // fullscreen 모드: 줌/팬 가능
    userZoomingEnabled: fullscreen,
    userPanningEnabled: fullscreen,
    style: [
      // ===== Agent nodes (avatar 원) =====
      {
        selector: 'node.agent',
        style: {
          'shape': 'ellipse',
          'width': nodeSize,
          'height': nodeSize,
          'background-image': 'data(avatar)',
          'background-fit': 'cover cover',
          'background-color': C.panel,
          'border-width': 3,
          'border-color': C.border,
          'label': 'data(label)',
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-margin-y': 6,
          'color': C.text,
          'font-size': fontSize,
          'font-weight': 600,
          'text-background-color': C.panel,
          'text-background-opacity': 0.85,
          'text-background-padding': 3,
          'text-background-shape': 'roundrectangle',
          'text-border-color': C.border,
          'text-border-width': 0,
        },
      },
      { selector: 'node.agent.mgr', style: { 'border-color': C.mgr } },
      { selector: 'node.agent.creator', style: { 'border-color': C.creator } },
      { selector: 'node.agent.persona', style: { 'border-color': C.persona } },
      {
        selector: 'node.agent.thinking',
        style: { 'border-color': C.accent, 'border-width': 4 },
      },
      {
        selector: 'node.agent.speaking',
        style: { 'border-color': C.speaking, 'border-width': 4 },
      },
      // ===== Owner node — Material person SVG, viewBox 큼 + figure 가운데에 작게 =====
      //   shape:ellipse + bg-clip 으로 잘리는 문제 방지를 위해 figure 를 inscribed circle 안에 배치
      //   viewBox 200x200, figure 는 가운데 ~80x100 영역 (충분한 padding)
      {
        selector: 'node.owner',
        style: {
          'shape': 'ellipse',
          'width': ownerSize,
          'height': ownerSize,
          'background-color': '#fff5e6',
          'background-image': 'data:image/svg+xml;utf8,' + encodeURIComponent(
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">' +
              '<circle cx="100" cy="80" r="26" fill="' + C.user + '"/>' +
              '<path d="M50 160 Q 50 116 100 116 Q 150 116 150 160 Z" fill="' + C.user + '"/>' +
            '</svg>'
          ),
          'background-fit': 'contain',
          'background-image-opacity': 1,
          'background-image-containment': 'inside',
          'border-width': 3,
          'border-color': C.user,
          'label': (snap.meta?.user_name || 'Owner'),
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-margin-y': 6,
          'color': C.text,
          'font-size': fontSize,
          'font-weight': 700,
          'text-background-color': C.panel,
          'text-background-opacity': 0.85,
          'text-background-padding': 3,
          'text-background-shape': 'roundrectangle',
        },
      },
      // ===== Supervisor nodes (다이아몬드, dashed border, 아이콘 이미지) =====
      {
        selector: 'node.sup',
        style: {
          'shape': 'diamond',
          'width': supSize,
          'height': supSize,
          'background-color': C.panel,
          'background-image': 'data(iconSvg)',
          'background-fit': 'contain',
          'background-image-opacity': 1,
          'background-image-containment': 'inside',
          'border-width': 2,
          'border-style': 'dashed',
          'border-color': C.warn,
          'label': 'data(label)',
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-margin-y': 6,
          'color': C.textDim,
          'font-size': 10,
          'font-weight': 600,
          'text-background-color': C.panel,
          'text-background-opacity': 0.85,
          'text-background-padding': 2,
          'text-background-shape': 'roundrectangle',
        },
      },
      { selector: 'node.sup.active', style: { 'border-style': 'solid' } },
      {
        selector: 'node.sup.intervening',
        style: {
          'border-style': 'solid',
          'border-color': C.warn,
          'border-width': 4,
        },
      },
      // ===== Edges =====
      //   기본 (대기): dashed + 흐릿 → 범례의 "┄┄ 대기" 와 매칭
      //   live (활성): solid + 굵게 + 펄스 글로우 → "━━ 활성"
      {
        selector: 'edge',
        style: {
          'curve-style': 'unbundled-bezier',
          'control-point-distances': 'data(cpd)',
          'control-point-weights': 'data(cpw)',
          'width': 1.4,
          'line-color': C.textDim,
          'line-style': 'dashed',
          'line-dash-pattern': [4, 6],
          'target-arrow-shape': 'none',
          'opacity': 0.35,
          // 기본 라벨 숨김 — hover 시에만 보임 (라벨 떡짐 회피)
          //   midpoint label (target-label 대신 label) → 엣지 가운데에 깔끔히 배치
          'label': 'data(label)',
          'text-opacity': 0,
          'font-size': 11,
          'color': C.text,
          'text-background-color': C.panel,
          'text-background-opacity': 0.95,
          'text-background-padding': 2,
          'text-background-shape': 'roundrectangle',
          'text-border-color': C.border,
          'text-border-width': 1,
          'text-border-opacity': 0.6,
          'text-events': 'yes',
        },
      },
      // 채널 종류별 색상은 hover label 정도로만 활용. 기본 라인은 중성톤으로 통일해
      // 노드 컬러와 충돌하지 않게 (사용자 피드백: "엣지가 너무 튀어서 미감 망침")
      {
        selector: 'edge.live',
        style: {
          'line-style': 'solid',
          'opacity': 0.85,
          'width': 2.0,
          'line-color': C.accent,
        },
      },
      {
        selector: 'edge.sup-edge',
        style: {
          'line-style': 'dashed',
          'line-dash-pattern': [5, 4],
          'line-color': C.warn,
          'opacity': 0.65,
          'width': 1.6,
          'label': '',
        },
      },
      { selector: 'edge.sup-edge.active', style: { 'opacity': 0.95, 'width': 2 } },
      {
        selector: 'edge.sup-edge.intervening',
        style: { 'opacity': 1, 'width': 2.5, 'line-dash-pattern': [4, 3] },
      },
      // Hover — 엣지 직접 hover 또는 연결된 노드 hover 시 라벨/엣지 강조
      { selector: 'edge.hl', style: {
        'text-opacity': 1,
        'opacity': 1,
        'width': 3,
        'z-index': 999,
      }},
      { selector: 'node.hl', style: {
        'border-width': 5,
        'z-index': 999,
      }},
      {
        selector: 'node:active, edge:active',
        style: { 'overlay-opacity': 0.1 },
      },
    ],
    layout: pickGraphLayout(nodes.length, fullscreen),
  });

  // ===== Interactivity =====
  cyInstance.on('tap', 'node.agent', (evt) => openAgent(evt.target.id()));
  cyInstance.on('tap', 'node.sup', (evt) => openAgent(evt.target.id()));
  cyInstance.on('tap', 'edge', (evt) => {
    const ch = evt.target.data('channel');
    if (ch) openChannel(ch);
  });
  // Hover 강조 — 노드 hover → 연결된 엣지 라벨 표시 / 엣지 hover → 본인 라벨 표시
  cyInstance.on('mouseover', 'node', (evt) => {
    container.style.cursor = 'pointer';
    const n = evt.target;
    n.addClass('hl');
    n.connectedEdges().addClass('hl');
  });
  cyInstance.on('mouseout', 'node', (evt) => {
    container.style.cursor = 'default';
    cyInstance.elements('.hl').removeClass('hl');
  });
  cyInstance.on('mouseover', 'edge', (evt) => {
    container.style.cursor = 'pointer';
    evt.target.addClass('hl');
  });
  cyInstance.on('mouseout', 'edge', (evt) => {
    container.style.cursor = 'default';
    evt.target.removeClass('hl');
  });

  // 레이아웃 끝나고 명시적으로 fit (concentric 의 fit:true 가 spacingFactor 큰 경우 overflow)
  cyInstance.ready(() => {
    cyInstance.fit(undefined, fullscreen ? 140 : 25);
  });

  // 노드 펄스용 색상 stash. thinking 머스타드 노랑은 따뜻한 아바타 위에 더러워보여서
  // 차분한 accent (indigo)로 통일. speaking 만 cyan 유지 (대비)
  cyInstance.scratch('_thinkingColor', C.accent);
  cyInstance.scratch('_speakingColor', C.speaking);

  // ===== 라이브 엣지 + 노드 펄스 애니메이션 시작 =====
  startLiveEdgeAnimation();
  startNodePulseAnimation();

  // ===== Note (n connections · m nodes · k supervisors) =====
  const noteEl = document.getElementById('graph-note');
  if (noteEl) {
    const supNodeCount = nodes.filter(n => n.classes && n.classes.indexOf('sup') === 0).length;
    const agentNodeCount = nodes.length - supNodeCount;
    const supEdgeCount = edges.filter(e => e.classes && e.classes.indexOf('sup-edge') === 0).length;
    const channelEdgeCount = edges.length - supEdgeCount;
    let txt = `${channelEdgeCount} connection${channelEdgeCount === 1 ? '' : 's'} · ${agentNodeCount} node${agentNodeCount === 1 ? '' : 's'}`;
    if (supNodeCount) txt += ` · ${supNodeCount} supervisor${supNodeCount === 1 ? '' : 's'}`;
    noteEl.textContent = txt;
  }
}

function toggleGraphFullscreen() {
  document.body.classList.toggle('graph-fullscreen');
  lastGraphSig = null;  // 재렌더 강제
  tick();
}
// ESC로 fullscreen 빠져나오기
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && document.body.classList.contains('graph-fullscreen')) {
    document.body.classList.remove('graph-fullscreen');
    tick();
  }
});

// 창 크기 / 패널 크기 변할 때 그래프 재렌더
//   - window resize: 창 크기 바뀜 (기본)
//   - ResizeObserver: 사이드바 토글 등 창 크기 안 변해도 패널 width 변할 때 감지
//   - debounce 로 과도 호출 방지, 같은 크기면 skip
(function() {
  let _resizeTimer = null;
  let _lastStageSize = null;
  function _measureAndMaybeRerender() {
    const panel = document.getElementById('graph-panel');
    if (!panel) return;
    const rect = panel.getBoundingClientRect();
    const fs = document.body.classList.contains('graph-fullscreen');
    const key = `${Math.round(rect.width)}x${fs ? 'fs' : 'n'}x${window.innerHeight}`;
    if (key === _lastStageSize) return;
    _lastStageSize = key;
    lastGraphSig = null;
    if (typeof tick === 'function') tick();
  }
  function _schedule() {
    clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(_measureAndMaybeRerender, 180);
  }
  window.addEventListener('resize', _schedule);
  // ResizeObserver — 패널 자체 크기 변경 감지 (브라우저 zoom, sidebar 등)
  if (typeof ResizeObserver !== 'undefined') {
    const ro = new ResizeObserver(_schedule);
    // panel 은 초기 렌더 후 DOM 에 있음
    document.addEventListener('DOMContentLoaded', () => {
      const p = document.getElementById('graph-panel');
      if (p) ro.observe(p);
    });
    // 이미 로드됐을 수 있으므로
    const p0 = document.getElementById('graph-panel');
    if (p0) ro.observe(p0);
  }
})();

function activeScenes(snap) {
  return (snap.scenes || []).filter(s => s.status === 'active');
}

function firstActiveScene(snap) {
  return activeScenes(snap)[0] || null;
}

function fmtDateTime(iso) {
  if (!iso) return '';
  return String(iso).slice(0, 19).replace('T', ' ');
}

function renderSceneCard(s) {
  const statusLabel = {
    active: '진행 중',
    completed: '완료',
    not_started: '시작 전',
  }[s.status] || s.status;
  const badgeStyle = {
    active: 'background:color-mix(in srgb,var(--accent) 15%,transparent);color:var(--accent);border:1px solid color-mix(in srgb,var(--accent) 30%,transparent)',
    completed: 'background:color-mix(in srgb,var(--ok) 15%,transparent);color:var(--ok);border:1px solid color-mix(in srgb,var(--ok) 30%,transparent)',
    not_started: 'background:var(--panel-2);color:var(--text-faint);border:1px solid var(--border)',
  }[s.status] || '';
  const leftBorder = {
    active: 'var(--accent)',
    completed: 'var(--ok)',
    not_started: 'var(--text-faint)',
  }[s.status] || 'var(--text-faint)';
  const dim = s.status === 'not_started' ? 'opacity:0.6;' : '';
  return `<div style="padding:16px 20px;margin-bottom:10px;background:var(--panel);border:1px solid var(--border-soft);border-left:3px solid ${leftBorder};border-radius:10px;box-shadow:var(--shadow);${dim}">
    <div style="display:flex;align-items:center;gap:10px;margin-bottom:6px">
      <span style="font-size:22px">${s.icon || '🎭'}</span>
      <span style="font-size:15px;font-weight:700;color:var(--text);flex:1">${esc(s.name)}</span>
      <span style="font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.8px;padding:3px 10px;border-radius:999px;${badgeStyle}">${statusLabel}</span>
    </div>
    <div style="color:var(--text-dim);font-size:12px;line-height:1.55;margin-bottom:8px">${esc(s.description)}</div>
    ${s.phase_desc ? `<div style="display:inline-block;padding:3px 8px;background:var(--panel-2);border-radius:5px;font-size:11px;color:var(--text);font-family:'JetBrains Mono',monospace">${esc(s.phase_desc)}</div>` : ''}
    <div style="display:flex;gap:14px;margin-top:8px;font-size:10.5px;color:var(--text-faint)">
      ${s.started_at ? `<span>시작: <b style="color:var(--text-dim);font-weight:500">${esc(fmtDateTime(s.started_at))}</b></span>` : ''}
      ${s.completed_at ? `<span>완료: <b style="color:var(--ok);font-weight:500">${esc(fmtDateTime(s.completed_at))}</b></span>` : ''}
      ${s.status === 'active' ? '<span style="color:var(--accent)">● LIVE</span>' : ''}
    </div>
  </div>`;
}

function renderScenes(scenes) {
  if (!scenes || !scenes.length) {
    return '<div class="empty">씬 정보 없음</div>';
  }
  const active = scenes.filter(s => s.status === 'active');
  const completed = scenes.filter(s => s.status === 'completed');
  const notStarted = scenes.filter(s => s.status === 'not_started');

  const sec = (title, arr, hint) => arr.length
    ? `<div class="detail-section"${title === 'Active' ? ' style="margin-top:0"' : ''}>
         <h4>${esc(title)} · ${arr.length}</h4>
         ${hint ? `<div style="color:var(--text-dim);font-size:11.5px;margin-bottom:10px">${esc(hint)}</div>` : ''}
         ${arr.map(renderSceneCard).join('')}
       </div>`
    : '';

  // 향후 추가 예정 씬 placeholder (정적)
  const futureHint = `<div class="detail-section">
    <h4>Future Scene Types</h4>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px;font-size:12px">
      <div style="padding:10px 14px;background:var(--panel-2);border-radius:8px;opacity:0.5">
        <div style="font-weight:600">🎂 Birthday</div>
        <div style="color:var(--text-dim);font-size:11px">멤버 생일 이벤트 (TBD)</div>
      </div>
      <div style="padding:10px 14px;background:var(--panel-2);border-radius:8px;opacity:0.5">
        <div style="font-weight:600">⚡ Conflict</div>
        <div style="color:var(--text-dim);font-size:11px">멤버간 갈등 씬 (TBD)</div>
      </div>
      <div style="padding:10px 14px;background:var(--panel-2);border-radius:8px;opacity:0.5">
        <div style="font-weight:600">🎉 Party</div>
        <div style="color:var(--text-dim);font-size:11px">단체 모임 씬 (TBD)</div>
      </div>
    </div>
  </div>`;

  return [
    sec('Active', active, '지금 진행 중인 씬'),
    sec('Completed', completed, '이전에 완료된 씬'),
    sec('Not Started', notStarted, '아직 시작 안 된 시나리오'),
    futureHint,
  ].join('');
}

function syntheticTestUserAgent(snap) {
  // QA 커뮤니티에서만 test-user-bot을 가상 에이전트로 표시
  if (snap.community_id !== 'qa') return null;
  const alive = snap.bot.test_user_alive;
  // .thinking-test-user / .speaking-test-user 플래그를 서버에서 받아 반영
  const thinking = !!snap.bot.test_user_thinking;
  const speaking = !!snap.bot.test_user_speaking;
  return {
    id: 'test-user-bot',
    type: 'persona',
    name: (snap.meta.user_name || 'Test User') + ' (QA)',
    status: alive ? 'active' : 'inactive',
    emotion: alive ? '신남' : '평온',
    emoji: alive ? '🤩' : '😌',
    intensity: alive ? 7 : 0,
    mbti: 'ENTP',
    age: 26,
    last_active: new Date().toISOString(),
    thinking: thinking,
    speaking: speaking,
    thinking_seconds: 0,
    speaking_seconds: 0,
    model: 'claude-haiku-4-5',
    provider: 'claude',
    model_override: true,
    _synthetic: true,
  };
}

async function tick() {
  // 5개 엔드포인트 병렬 fetch — 순차 await 대신 Promise.all로 5배 빠름
  const [snap, logs, health, dev, usage] = await Promise.all([
    j(q('/api/snapshot')),
    j(q('/api/logs?tail=200')),
    j(q('/api/health')),
    j(q('/api/dev')),
    j(q('/api/usage')),
  ]);
  if (!snap) return;

  COMMUNITY = snap.community_id;
  const b = snap.bot, m = snap.meta;

  // 서버 언어 설정 반영 (community_meta.language)
  const prevLang = currentLang();
  SERVER_LANG = (snap.community_meta && snap.community_meta.language) || 'ko';
  const newLang = currentLang();
  if (newLang !== prevLang || !I18N_CACHE[newLang]) {
    await loadLang(newLang);
    applyLangLabel();
  }

  // QA에 test-user 가상 에이전트 추가 (맨 앞)
  const testUser = syntheticTestUserAgent(snap);
  if (testUser) {
    snap.agents = [testUser, ...snap.agents];
  }

  // Empty community 체크 — agents 비어있고 conversations 없으면 초기화되지 않은 상태
  const hasData = (snap.agents && snap.agents.length > 0) || snap.total_messages > 0;
  document.body.classList.toggle('community-empty', !hasData);
  const ecid = document.getElementById('empty-cid');
  if (ecid) ecid.textContent = snap.community_id;

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

  // 헤더 pills/meta는 제거됨 — 모든 정보는 KPI 카드에 있음

  document.getElementById('tc-agents').textContent = snap.agents.length;
  document.getElementById('tc-channels').textContent = snap.channels.length;
  document.getElementById('tc-messages').textContent = snap.recent_messages.length;
  document.getElementById('tc-scenes').textContent = (snap.scenes || []).filter(s => s.status === 'active').length;
  document.getElementById('tc-events').textContent = snap.events.length;
  const supActiveCount = (snap.supervisors || []).filter(s => s.active).length;
  const supEl = document.getElementById('tc-supervisors');
  if (supEl) supEl.textContent = supActiveCount;
  // Supervisors 탭 렌더
  const supFull = document.getElementById('supervisors-full');
  if (supFull) supFull.innerHTML = renderSupervisorsTab(snap.supervisors || []);

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
  document.getElementById('kpi-user').innerHTML = esc(m.user_name || '—');
  // Active Scene: 현재 진행 중 씬 (snap.scenes에서 status='active' 첫번째)
  const scene = firstActiveScene(snap);
  const actives = activeScenes(snap);
  document.getElementById('kpi-scene').innerHTML = scene
    ? `<span style="color:var(--accent)">${esc(scene.icon || '')} ${esc(scene.name)}</span><small>${esc(scene.phase_desc || scene.status)}${actives.length > 1 ? ` +${actives.length - 1}` : ''}</small>`
    : `<span style="color:var(--text-faint);font-size:15px">—</span><small>nothing active</small>`;
  document.getElementById('kpi-msgs').innerHTML = `${snap.total_messages}<small>total</small>`;

  // Connection Graph — 구조 변화 있을 때만 재렌더 (깜빡임 방지)
  //   동일 구조면 live 상태만 DOM 레벨로 업데이트
  const graphEl = document.getElementById('graph-panel');
  if (graphEl) {
    const sig = graphSignature(snap);
    if (sig !== lastGraphSig) {
      graphEl.innerHTML = renderConnectionGraph(snap);
      mountCytoscapeGraph(snap);
      lastGraphSig = sig;
    } else {
      // 구조 동일 → 노드 thinking/speaking 클래스만 갱신
      updateGraphLiveState(snap);
    }
  }

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
  // Scenes 탭: 각 씬 카드 (active/completed/not_started 상태별 스타일)
  const scenesEl = document.getElementById('scenes-full');
  if (scenesEl) {
    const scenes = snap.scenes || [];
    scenesEl.innerHTML = renderScenes(scenes);
  }

  // Events 탭: events 테이블 — 발생한 일들의 로그 (멤버간 사건 기록)
  const eventsEl = document.getElementById('events-full');
  if (eventsEl) {
    eventsEl.innerHTML = snap.events.length
      ? `<div style="color:var(--text-dim);font-size:11.5px;margin-bottom:12px">
           커뮤니티에서 발생한 사건 기록 — 관계 변화, 갈등, 화해 등 persona들의 내면 이벤트
         </div>` + snap.events.map(renderEvent).join('')
      : '<div class="empty">기록된 이벤트 없음</div>';
  }

  // Health
  if (health) {
    const diskPct = health.disk_total_bytes ? (health.disk_used_bytes / health.disk_total_bytes * 100).toFixed(1) : 0;
    const memPct = health.sys_mem_pct || 0;
    const glimiMemPct = health.sys_mem_total_bytes ? (health.glimi_mem_bytes / health.sys_mem_total_bytes * 100).toFixed(1) : 0;
    const serverRun = health.bot_alive;
    document.getElementById('health-full').innerHTML = `
      <div style="margin-bottom:18px">
        <div class="section-title" style="margin-top:0">Server Control</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;padding:14px 18px;background:var(--panel);border:1px solid var(--border-soft);border-radius:10px">
          <button class="act-btn success" onclick="runServerControl('start')" ${serverRun ? 'disabled' : ''}>▶ 서버 시작</button>
          <button class="act-btn danger" onclick="runServerControl('stop')" ${!serverRun ? 'disabled' : ''}>⏸ 서버 중단</button>
          <button class="act-btn primary" onclick="runServerControl('restart')">↻ 재시작</button>
          <div style="flex:1"></div>
          <span style="align-self:center;color:var(--text-dim);font-size:11.5px">
            현재 상태: ${serverRun ? '<span style="color:var(--ok)">● Running</span>' : '<span style="color:var(--err)">○ Stopped</span>'}
          </span>
        </div>
      </div>

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
          ${renderGpuCard(health.gpu, health.sys_mem_total_bytes, health.sys_mem_used_bytes)}
          <div class="health-card">
            <h4>Disk</h4>
            <div class="big">${fmtBytes(health.disk_used_bytes)} <small style="font-size:12px;color:var(--text-dim)">/ ${fmtBytes(health.disk_total_bytes)}</small></div>
            <div class="sub">free: ${fmtBytes(health.disk_free_bytes)} · ${diskPct}% used</div>
            <div class="disk-bar"><span style="width:${diskPct}%"></span></div>
          </div>
        </div>
      </div>
    `;
  }

  // Sync tab
  const serverRunning = b.bot_alive;
  const guardNote = serverRunning
    ? `<div style="padding:10px 14px;background:color-mix(in srgb,var(--accent) 10%,var(--panel));border:1px solid color-mix(in srgb,var(--accent) 30%,transparent);border-radius:10px;margin-bottom:16px;font-size:12px;color:var(--text)">ℹ 서버 실행 중 — Sync 버튼 클릭 시 <b>자동으로 서버 중단 → 작업 → 재시작</b> 진행. 취소 버튼 제공됨.</div>`
    : `<div style="padding:10px 14px;background:color-mix(in srgb,var(--ok) 8%,var(--panel));border:1px solid color-mix(in srgb,var(--ok) 25%,transparent);border-radius:10px;margin-bottom:16px;font-size:12px;color:var(--ok)">○ 서버 오프라인 — 모든 sync 작업 즉시 가능.</div>`;

  document.getElementById('sync-full').innerHTML = `
    ${guardNote}
    <div class="detail-section" style="margin-top:0">
      <h4>Sync Actions</h4>
      <div style="color:var(--text-dim);font-size:11.5px;margin-bottom:10px">
        Discord 서버와 DB 사이 상태를 맞추는 작업. 서버 실행 중이면 자동 중단·작업·재시작.
      </div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px">
        <button class="act-btn primary" onclick="runSyncAction('scan')">🔍 Scan Discord</button>
        <button class="act-btn success" onclick="runSyncAction('sync')">▶ Full Sync</button>
        <button class="act-btn" onclick="runSyncAction('restore')">↻ Restore Messages</button>
      </div>
      <div id="sync-output" style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-dim);background:var(--panel-2);padding:10px;border-radius:8px;min-height:60px;max-height:240px;overflow-y:auto;white-space:pre-wrap"></div>
    </div>
    <div class="detail-section">
      <h4>Trash · <span id="trash-count" style="color:var(--text-faint)">...</span></h4>
      <div style="color:var(--text-dim);font-size:11.5px;margin-bottom:10px">
        휴지통 — 채널/메시지 삭제 시 완전 삭제 대신 여기로 옮겨짐. 실수 복구용 안전망.
        <br>Empty Trash 로 영구 삭제, 각 항목별 <b>복구</b> 가능.
      </div>
      <div style="display:flex;gap:8px;margin-bottom:10px">
        <button class="act-btn small" onclick="loadTrash()">새로고침</button>
        <button class="act-btn small danger" onclick="emptyTrash()">Empty Trash</button>
      </div>
      <div id="trash-list"></div>
    </div>
    <div class="detail-section">
      <h4>DB-registered Channels · ${snap.channels.length}</h4>
      ${renderChannelsGrouped(snap.channels)}
    </div>
  `;
  loadTrash();

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

  // Usage — telemetry parsed
  if (usage) {
    if (usage.source !== 'telemetry') {
      document.getElementById('usage-full').innerHTML = `
        <div class="detail-section">
          <h4>Usage</h4>
          <div style="color:var(--text-dim);font-size:13px">
            telemetry 데이터 없음 — ~/.claude/telemetry 파일 찾지 못함.<br>
            로그 기반 근사치: sonnet ${usage.sonnet_calls || 0} · haiku ${usage.haiku_calls || 0} · opus ${usage.opus_calls || 0}
          </div>
        </div>`;
    } else {
      const dayBars = (usage.recent_days || []).slice().reverse();
      const maxDay = Math.max(...dayBars.map(d => d.cost), 0.01);
      const totalTokens = usage.tokens_input + usage.tokens_output + usage.tokens_cache_write + usage.tokens_cache_read;
      const apiMin = (usage.api_duration_ms / 1000 / 60).toFixed(1);
      const modelRows = Object.entries(usage.by_model || {})
        .sort((a,b) => b[1] - a[1])
        .slice(0, 8)
        .map(([m, c]) => {
          const provider = m.startsWith('claude-') ? 'claude' : (m.includes('gpt') ? 'openai' : 'other');
          return `<div class="rel-row"><span class="rname">${esc(m)}</span><span class="model-tag ${provider}">${c} events</span></div>`;
        }).join('');

      document.getElementById('usage-full').innerHTML = `
        <div class="overview-grid">
          <div class="kpi">
            <div class="label">Total Cost</div>
            <div class="value">$${usage.cost_total_usd.toFixed(2)}<small>${usage.sessions_total} sessions</small></div>
          </div>
          <div class="kpi">
            <div class="label">Today</div>
            <div class="value">$${usage.cost_today_usd.toFixed(2)}</div>
          </div>
          <div class="kpi">
            <div class="label">7-day</div>
            <div class="value">$${usage.cost_week_usd.toFixed(2)}</div>
          </div>
          <div class="kpi">
            <div class="label">30-day</div>
            <div class="value">$${usage.cost_month_usd.toFixed(2)}</div>
          </div>
          <div class="kpi">
            <div class="label">Subscription</div>
            <div class="value" style="font-size:15px">${esc(usage.subscription_type)}</div>
          </div>
        </div>

        <div class="detail-section">
          <h4>Recent 7 Days</h4>
          <div style="display:flex;align-items:flex-end;gap:8px;height:120px;padding:10px 0">
            ${dayBars.map(d => {
              const h = maxDay ? Math.max(3, (d.cost / maxDay * 100)) : 3;
              return `<div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:4px">
                <div style="font-size:10px;color:var(--text-dim)">${d.cost > 0 ? '$' + d.cost.toFixed(2) : ''}</div>
                <div style="width:100%;height:${h}%;background:linear-gradient(180deg,var(--accent),var(--accent-2));border-radius:4px 4px 0 0;min-height:2px"></div>
                <div style="font-size:10px;color:var(--text-faint)">${d.date.slice(5)}</div>
                <div style="font-size:9px;color:var(--text-faint)">${d.sessions}s</div>
              </div>`;
            }).join('')}
          </div>
        </div>

        <div class="detail-section">
          <h4>Token Usage (All Time)</h4>
          <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px;margin-top:6px">
            <div><div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px">Input</div><div style="font-size:16px;font-weight:700">${usage.tokens_input.toLocaleString()}</div></div>
            <div><div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px">Output</div><div style="font-size:16px;font-weight:700">${usage.tokens_output.toLocaleString()}</div></div>
            <div><div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px">Cache Write</div><div style="font-size:16px;font-weight:700">${usage.tokens_cache_write.toLocaleString()}</div></div>
            <div><div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px">Cache Read</div><div style="font-size:16px;font-weight:700">${usage.tokens_cache_read.toLocaleString()}</div></div>
            <div><div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px">Total</div><div style="font-size:16px;font-weight:700">${totalTokens.toLocaleString()}</div></div>
            <div><div style="font-size:10px;color:var(--text-dim);text-transform:uppercase;letter-spacing:1px">API Time</div><div style="font-size:16px;font-weight:700">${apiMin} min</div></div>
          </div>
        </div>

        ${modelRows ? `<div class="detail-section"><h4>Models</h4>${modelRows}</div>` : ''}

        <div class="detail-section">
          <h4>Source</h4>
          <div style="color:var(--text-dim);font-size:12px">
            ~/.claude/telemetry/ tengu_exit 이벤트 기반 실시간 집계. Claude Code 세션이 종료될 때마다 업데이트됨.
          </div>
        </div>
      `;
    }
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
  if (activeItem && activeItem.running) btn.classList.remove('stopped');
  else btn.classList.add('stopped');

  // 메뉴 생성 — running 은 초록 테마, stopped 은 dim
  menu.innerHTML = (d.items || []).map(c => {
    const cls = ['ci'];
    if (c.id === d.active) cls.push('active');
    if (!c.running) cls.push('stopped');
    const ageText = c.last_log_age_sec != null
      ? (c.last_log_age_sec < 60 ? `${c.last_log_age_sec}s` : c.last_log_age_sec < 3600 ? `${Math.floor(c.last_log_age_sec/60)}m` : `${Math.floor(c.last_log_age_sec/3600)}h`) + ' ago'
      : '';
    const meta = c.running
      ? `<span class="ci-meta" style="color:var(--ok)">● running${ageText ? ` · ${ageText}` : ''}</span>`
      : `<span class="ci-meta">○ stopped${ageText ? ` · ${ageText}` : ''}</span>`;
    return `<div class="${cls.join(' ')}" data-cid="${esc(c.id)}">
      <span class="ci-dot"></span>
      <div style="flex:1">
        <div class="ci-name">${esc(c.id)}</div>
        ${meta}
      </div>
      <span class="ci-check"></span>
    </div>`;
  }).join('') || '<div class="empty">no communities</div>';

  // 아이템 클릭 → 전환 (즉시 UI 반영 + 로딩 표시)
  menu.querySelectorAll('.ci').forEach(el => {
    el.addEventListener('click', async () => {
      const newCid = el.dataset.cid;
      if (newCid === COMMUNITY) { menu.classList.remove('open'); return; }
      COMMUNITY = newCid;
      menu.classList.remove('open');

      // 즉시 UI 리셋 + 로딩 상태
      document.body.classList.add('switching');
      lastGraphSig = null;  // 그래프 강제 재렌더
      // 커뮤니티 버튼 이름 즉시 교체 (응답 전에도 피드백)
      const btnName = document.getElementById('community-btn-name');
      if (btnName) btnName.textContent = COMMUNITY;

      const url = new URL(location.href);
      url.searchParams.set('community', COMMUNITY);
      history.replaceState(null, '', url);

      try {
        await tick();
        await loadCommunities();
      } finally {
        document.body.classList.remove('switching');
      }
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

// 초기 i18n 프리로드 → 첫 tick → 주기적 갱신
(async () => {
  await loadLang('ko');
  await loadLang('en');
  applyLangLabel();
  await loadCommunities();
  await tick();
  // ?openAgent=ID — auto-open agent modal (used for screenshot capture)
  const _params = new URLSearchParams(location.search);
  const _autoOpen = _params.get('openAgent');
  if (_autoOpen) setTimeout(() => openAgent(_autoOpen), 500);
})();
setInterval(tick, 1500);
setInterval(loadCommunities, 5000);  // 커뮤니티 running 상태 5초마다 갱신
</script>
</body></html>
"""


import threading

# 커뮤니티 전환은 전역 상태 (GLIMI_COMMUNITY env, _comm._current_id, db.DB_PATH)
# 를 건드림 → 동시 요청이 서로 다른 커뮤니티를 지정하면 race로 섞임
# (예: private 요청 중 qa 요청이 env를 덮어쓰면 private이 qa DB를 읽게 됨).
# 모든 커뮤니티-의존 핸들러를 이 lock으로 직렬화.
_COMMUNITY_LOCK = threading.Lock()


def _read_community(path: str) -> Optional[str]:
    q = parse_qs(urlparse(path).query)
    return q.get("community", [None])[0]


def _set_active_community(cid: Optional[str]):
    if cid:
        os.environ["GLIMI_COMMUNITY"] = cid
    from src import community as _comm
    if cid:
        _comm.set_community(cid)
    # DB_PATH 전역 캐시 무효화 — 커뮤니티 전환 시 실제 DB 파일도 바뀌어야 함
    try:
        import src.db as _db
        _db.DB_PATH = None
    except Exception:
        pass


def _with_community(path: str, fn):
    """URL ?community= 파라미터로 커뮤니티 전환 후 fn 호출.
    전역 상태 변경을 lock으로 직렬화 → race condition 방지."""
    cid = _read_community(path)
    with _COMMUNITY_LOCK:
        if cid:
            _set_active_community(cid)
        return fn()


def _read_query(path: str, key: str, default: Optional[str] = None) -> Optional[str]:
    q = parse_qs(urlparse(path).query)
    v = q.get(key, [default])[0]
    return v


def api_snapshot(path):
    def _run():
        from src.core import monitor
        snap = monitor.snapshot()
        for c in snap["channels"]:
            c["last_ago"] = monitor.human_ago(c["last_ts"])
        return snap
    return _with_community(path, _run)


def api_logs(path):
    def _run():
        from src.core import monitor
        tail = int(_read_query(path, "tail", "150") or 150)
        return {"lines": monitor.get_recent_system_logs(tail_lines=tail)}
    return _with_community(path, _run)


def api_agent_activity(path):
    def _run():
        from src.core import monitor
        aid = _read_query(path, "id", "")
        if not aid:
            return {"logs": [], "chat": []}
        return {
            "logs": monitor.get_agent_thinking_logs(aid, n=5),
            "chat": monitor.get_agent_recent_chat(aid, limit=3),
        }
    return _with_community(path, _run)


def api_agent_detail(path):
    def _run():
        from src.core import monitor
        aid = _read_query(path, "id", "")
        if not aid:
            return {"error": "missing id"}
        return monitor.get_agent_detail(aid)
    return _with_community(path, _run)


def api_channel_detail(path):
    def _run():
        from src.core import monitor
        name = _read_query(path, "name", "")
        if not name:
            return {"error": "missing name"}
        return monitor.get_channel_detail(name)
    return _with_community(path, _run)


def api_health(path):
    def _run():
        from src.core import monitor
        return monitor.get_health()
    return _with_community(path, _run)


def api_dev(path):
    def _run():
        from src.core import monitor
        return monitor.get_dev_state()
    return _with_community(path, _run)


def api_usage(path):
    def _run():
        from src.core import monitor
        return monitor.get_usage_stats()
    return _with_community(path, _run)


def _serve_logo(handler):
    """resources/Glimi-logo.png 서빙."""
    fp = ROOT / "resources" / "Glimi-logo.png"
    if not fp.exists():
        handler._send(404, b"not found", "text/plain")
        return
    try:
        with open(fp, "rb") as f:
            data = f.read()
    except Exception as e:
        handler._send(500, str(e).encode(), "text/plain")
        return
    handler.send_response(200)
    handler.send_header("Content-Type", "image/png")
    handler.send_header("Cache-Control", "public, max-age=3600")
    handler.send_header("Content-Length", str(len(data)))
    handler.end_headers()
    handler.wfile.write(data)


def api_i18n(path: str) -> dict:
    """i18n/dashboard.{ko,en}.json 파일 로드."""
    from urllib.parse import parse_qs, urlparse as _u
    q = parse_qs(_u(path).query)
    lang = (q.get("lang", ["ko"])[0] or "ko").lower()
    if lang not in ("ko", "en"):
        lang = "ko"
    fp = ROOT / "i18n" / f"dashboard.{lang}.json"
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e)}


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


# ── Mutation endpoints (POST) ──────────────────────────

def _bot_running_for(community_id: str) -> bool:
    """해당 커뮤니티의 봇이 돌고 있는지 (running 커뮤니티 확인과 동일 로직)."""
    import time as _t
    try:
        log_path = ROOT / "communities" / community_id / "logs" / "system.log"
        if log_path.exists():
            return (_t.time() - log_path.stat().st_mtime) < 120
    except Exception:
        pass
    return False


def _require_server_stopped(community_id: str) -> Optional[dict]:
    """Discord 상호작용 ops 전 실행 중인 봇 가드. 문제 있으면 error dict 반환."""
    if _bot_running_for(community_id):
        return {
            "error": "server_running",
            "message": "커뮤니티 서버가 실행 중이라 이 작업은 할 수 없음. 먼저 서버 중단 후 재시도.",
        }
    return None


def api_action_scan_discord(body: dict, community_id: str) -> dict:
    """Discord에서 채널/메시지 스캔만 하고 DB 변경 없이 diff 보고."""
    guard = _require_server_stopped(community_id)
    if guard:
        return guard
    from src.core.sync import run_sync
    try:
        result = run_sync(dry_run=True)
        return {"ok": True, "result": result}
    except TypeError:
        # run_sync가 dry_run 인자 없으면 진행 불가
        return {"error": "not_supported", "message": "run_sync()에 dry_run 지원 없음 — full sync만 가능"}
    except Exception as e:
        return {"error": "exception", "message": str(e)}


def api_action_run_sync(body: dict, community_id: str) -> dict:
    """full sync 실행 (DB ↔ Discord 양방향)."""
    guard = _require_server_stopped(community_id)
    if guard:
        return guard
    from src.core.sync import run_sync
    try:
        logs: list[str] = []
        def _cb(msg: str):
            logs.append(msg)
        try:
            result = run_sync(on_progress=_cb)
        except TypeError:
            result = run_sync()
        return {"ok": True, "result": result, "logs": logs[-20:]}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": "exception", "message": str(e)}


def api_action_restore(body: dict, community_id: str) -> dict:
    """DB 메시지를 Discord에 재전송."""
    guard = _require_server_stopped(community_id)
    if guard:
        return guard
    from src.core.sync import run_restore
    try:
        logs: list[str] = []
        try:
            result = run_restore(on_progress=lambda m: logs.append(m))
        except TypeError:
            result = run_restore()
        return {"ok": True, "result": result, "logs": logs[-20:]}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"error": "exception", "message": str(e)}


def api_action_channel_clear(body: dict, community_id: str) -> dict:
    """채널의 DB 메시지만 삭제 (Discord 유지). 봇 실행 중에도 안전."""
    from src import db
    channel = (body.get("channel") or "").strip()
    if not channel:
        return {"error": "missing_channel"}
    try:
        result = db.delete_channel_data(channel)
        return {"ok": True, "deleted": result}
    except Exception as e:
        return {"error": "exception", "message": str(e)}


def api_action_channel_delete(body: dict, community_id: str) -> dict:
    """채널 DB + Discord 양쪽 삭제. Discord 쪽은 봇 없으면 스킵."""
    from src import db
    channel = (body.get("channel") or "").strip()
    if not channel:
        return {"error": "missing_channel"}

    # DB 먼저 삭제
    try:
        db_result = db.delete_channel_data(channel)
    except Exception as e:
        return {"error": "db_delete_failed", "message": str(e)}

    # channels 테이블에서도 제거
    try:
        conn = db.get_conn()
        conn.execute("DELETE FROM channels WHERE channel = ?", (channel,))
        conn.commit()
        conn.close()
    except Exception:
        pass

    # Discord 쪽은 봇이 안 돌고 있으면 sync로 대신 정리 (또는 skip)
    # 여기선 간단히 DB만 — Discord 채널 삭제는 봇 or 수동
    discord_msg = "Discord 채널은 남아있음 — 봇 실행 중이면 다음 sync 때 자동 정리됨"
    return {"ok": True, "db": db_result, "note": discord_msg}


def api_action_trash_message(body: dict, community_id: str) -> dict:
    """메시지를 trash로 이동."""
    from src import db
    channel = (body.get("channel") or "").strip()
    message_id = body.get("message_id")
    if not channel:
        return {"error": "missing_channel"}
    try:
        ids = [int(message_id)] if message_id else None
        db.trash_messages(channel, message_ids=ids)
        return {"ok": True}
    except Exception as e:
        return {"error": "exception", "message": str(e)}


def api_action_trash_list(body: dict, community_id: str) -> dict:
    from src import db
    try:
        items = db.trash_list()
        return {"ok": True, "items": items}
    except Exception as e:
        return {"error": "exception", "message": str(e)}


def api_action_trash_restore(body: dict, community_id: str) -> dict:
    from src import db
    trash_id = body.get("trash_id")
    if trash_id is None:
        return {"error": "missing_trash_id"}
    try:
        result = db.trash_restore(int(trash_id))
        return {"ok": True, "result": result}
    except Exception as e:
        return {"error": "exception", "message": str(e)}


def api_action_trash_empty(body: dict, community_id: str) -> dict:
    from src import db
    try:
        db.trash_empty()
        return {"ok": True}
    except Exception as e:
        return {"error": "exception", "message": str(e)}


def _find_bot_pids(community_id: str) -> list[int]:
    """src.discord_bot 프로세스 중 해당 커뮤니티 env를 가진 PID 목록."""
    import subprocess as _sp
    try:
        # ps eww 로 env 포함 (macOS)
        r = _sp.run(["ps", "eaxww", "-o", "pid,command"], capture_output=True, text=True, timeout=5)
        pids = []
        for line in r.stdout.split("\n"):
            if "src.discord_bot" not in line or "grep" in line:
                continue
            # GLIMI_COMMUNITY=xxx 매칭
            if f"GLIMI_COMMUNITY={community_id}" not in line and community_id != "":
                # env 체크 실패 시 fallback: 어쨌든 discord_bot이면 포함
                # 대부분 한 번에 한 커뮤니티만 돌아서 괜찮음
                pass
            parts = line.strip().split(None, 1)
            if parts and parts[0].isdigit():
                pids.append(int(parts[0]))
        return pids
    except Exception:
        return []


def api_action_stop_server(body: dict, community_id: str) -> dict:
    """해당 커뮤니티 Glimi 봇 + 러너 + test-user 봇 모두 종료."""
    import signal as _sig
    import time as _t

    killed = []
    # Glimi bot pids
    pids = _find_bot_pids(community_id)

    # QA runner / test_user_bot도 같이
    try:
        import subprocess as _sp
        r = _sp.run(["ps", "ax", "-o", "pid,command"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.split("\n"):
            if "tests.e2e.runner" in line or "tests.e2e.test_user_bot" in line:
                parts = line.strip().split(None, 1)
                if parts and parts[0].isdigit():
                    pid = int(parts[0])
                    if pid not in pids:
                        pids.append(pid)
    except Exception:
        pass

    for pid in pids:
        try:
            os.kill(pid, _sig.SIGTERM)
            killed.append(pid)
        except ProcessLookupError:
            pass
        except Exception:
            pass

    # 종료 대기 (최대 10초, 0.5초 간격)
    deadline = _t.time() + 10
    while _t.time() < deadline:
        remaining = []
        for pid in killed:
            try:
                os.kill(pid, 0)  # check if alive
                remaining.append(pid)
            except ProcessLookupError:
                pass
        if not remaining:
            break
        _t.sleep(0.5)

    # 아직 살아있으면 SIGKILL
    for pid in killed:
        try:
            os.kill(pid, _sig.SIGKILL)
        except ProcessLookupError:
            pass
        except Exception:
            pass

    # PID 파일 제거
    try:
        pid_file = ROOT / "dev" / ".bot.pid"
        if pid_file.exists():
            pid_file.unlink()
    except Exception:
        pass

    return {"ok": True, "killed_pids": killed, "count": len(killed)}


def api_action_start_server(body: dict, community_id: str) -> dict:
    """scripts/run.sh {community_id}를 백그라운드로 기동."""
    import subprocess as _sp
    # 이미 돌고 있으면 거부
    if _bot_running_for(community_id):
        return {"error": "already_running", "message": "서버가 이미 실행 중"}

    run_sh = ROOT / "scripts" / "run.sh"
    if not run_sh.exists():
        return {"error": "run_sh_missing", "message": f"{run_sh} 없음"}

    try:
        # detached process로 시작 (대시보드 종료돼도 계속)
        env = dict(os.environ)
        env["GLIMI_COMMUNITY"] = community_id
        proc = _sp.Popen(
            ["bash", str(run_sh), community_id],
            cwd=str(ROOT),
            env=env,
            stdout=_sp.DEVNULL,
            stderr=_sp.DEVNULL,
            stdin=_sp.DEVNULL,
            start_new_session=True,  # 부모와 분리
        )
        return {"ok": True, "pid": proc.pid, "message": "서버 시작 중 — 10~20초 후 online"}
    except Exception as e:
        return {"error": "exception", "message": str(e)}


def api_action_restart_server(body: dict, community_id: str) -> dict:
    """stop → 3초 대기 → start."""
    import time as _t
    r1 = api_action_stop_server(body, community_id)
    _t.sleep(3)
    r2 = api_action_start_server(body, community_id)
    return {"ok": r1.get("ok") and r2.get("ok"), "stop": r1, "start": r2}


def _serve_avatar(handler, path):
    """에이전트 아바타 이미지 서빙."""
    cid = _read_community(path)
    agent_id = _read_query(path, "id", "")
    variant = _read_query(path, "variant", "") or ""  # "" or "full"
    if not agent_id:
        handler._send(404, b"missing id", "text/plain")
        return

    # lock 안에서 community 전환 + profile 조회 + avatar path 해석
    # — 다른 커뮤니티 아바타 섞임 방지
    with _COMMUNITY_LOCK:
        if cid:
            _set_active_community(cid)
        from src import community as _comm
        from src.core.profile import load_profile
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
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

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
            elif p == "/api/i18n":
                self._json(api_i18n(self.path))
            elif p == "/api/avatar":
                _serve_avatar(self, self.path)
            elif p == "/logo":
                _serve_logo(self)
            else:
                self._send(404, b"not found", "text/plain")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._json({"error": str(e)})

    def do_POST(self):
        p = urlparse(self.path).path
        cid = _read_community(self.path)

        # body 파싱 (lock 밖에서 먼저 — 읽기는 race 영향 없음)
        body = {}
        try:
            length = int(self.headers.get("Content-Length", 0))
            if length > 0:
                raw = self.rfile.read(length)
                body = json.loads(raw.decode("utf-8"))
        except Exception:
            body = {}

        mutations = {
            "/api/action/scan_discord": api_action_scan_discord,
            "/api/action/run_sync": api_action_run_sync,
            "/api/action/restore": api_action_restore,
            "/api/action/channel_clear": api_action_channel_clear,
            "/api/action/channel_delete": api_action_channel_delete,
            "/api/action/trash_message": api_action_trash_message,
            "/api/action/trash_list": api_action_trash_list,
            "/api/action/trash_restore": api_action_trash_restore,
            "/api/action/trash_empty": api_action_trash_empty,
            "/api/action/stop_server": api_action_stop_server,
            "/api/action/start_server": api_action_start_server,
            "/api/action/restart_server": api_action_restart_server,
        }
        handler = mutations.get(p)
        if handler is None:
            self._send(404, b"not found", "text/plain")
            return
        # 커뮤니티 전환 + 핸들러 호출을 lock으로 직렬화
        try:
            with _COMMUNITY_LOCK:
                if cid:
                    _set_active_community(cid)
                from src import community as _comm
                community_id = cid or _comm.get_community_id()
                result = handler(body, community_id)
            self._json(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._json({"error": "exception", "message": str(e)})


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
