#!/usr/bin/env python3
"""
Project Chaos — Interactive Dashboard TUI (Textual)

커뮤니티 대시보드: 봇 상태, 에이전트, 채널, 로그를 실시간 모니터링.
마우스 + 키보드 모두 지원.

실행:
  python -m src.tui.dashboard [community_id]
"""
import sys
import os
import signal
import subprocess
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from datetime import datetime
from pathlib import Path

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll, Grid
from textual.screen import Screen
from textual.widgets import (
    Static, Header, Footer, Button, Label, Rule,
    OptionList, ListView, ListItem,
)
from textual.widgets.option_list import Option
from textual.reactive import reactive

from rich.text import Text
from rich.panel import Panel
from rich.table import Table as RichTable
from rich.columns import Columns
from rich.console import Group
from rich import box

from src import db
from src.core.profile import load_profile, get_user_name, get_user_id
from src.core.sync import run_sync
from src import log_writer
from src.tui.components import LoadingOverlay

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PID_FILE = os.path.join(PROJECT_ROOT, "dev", ".bot.pid")

def _venv_python() -> str:
    """프로젝트 venv의 Python 경로 (sys.executable이 conda 등일 수 있음)"""
    venv = os.path.join(PROJECT_ROOT, ".venv", "bin", "python")
    return venv if os.path.exists(venv) else sys.executable


# ══════════════════════════════════════════════════════════
# 공통 유틸리티
# ══════════════════════════════════════════════════════════

_COLOR_POOL = [
    "bright_magenta", "bright_red", "bright_cyan", "yellow", "green",
    "white", "bright_yellow", "bright_green", "magenta", "red",
    "bright_white", "dark_orange", "deep_pink1", "spring_green1",
]
_TYPE_COLORS = {"mgr": "bright_blue", "creator": "bright_yellow"}
_agent_colors: dict[str, str] = {}

E_EMOJI = {
    "기쁨": "😊", "평온": "😌", "서운함": "😢", "화남": "😠",
    "설렘": "💗", "불안": "😰", "신남": "🤩", "슬픔": "😥",
}


def _get_color(agent_id: str) -> str:
    if agent_id in _agent_colors:
        return _agent_colors[agent_id]
    profile = load_profile(agent_id)
    if profile and profile.get("type") in _TYPE_COLORS:
        c = _TYPE_COLORS[profile["type"]]
    else:
        used = set(_agent_colors.values())
        available = [c for c in _COLOR_POOL if c not in used]
        c = available[0] if available else _COLOR_POOL[hash(agent_id) % len(_COLOR_POOL)]
    _agent_colors[agent_id] = c
    return c


def _seconds_since(ts_str):
    if not ts_str:
        return 999999
    try:
        return (datetime.now() - datetime.fromisoformat(ts_str)).total_seconds()
    except Exception:
        return 999999


def _ago(seconds):
    if seconds < 60:
        return "방금"
    if seconds < 3600:
        return f"{int(seconds // 60)}분"
    if seconds < 86400:
        return f"{int(seconds // 3600)}시간"
    return f"{int(seconds // 86400)}일"


def _speaker_name(sid):
    if sid == get_user_id():
        return get_user_name()
    a = db.get_agent(sid)
    return a["name"] if a else sid


def _trunc(s, n):
    return s[:n - 3] + "..." if len(s) > n else s


def _is_bot_running():
    if not os.path.exists(PID_FILE):
        return False
    try:
        with open(PID_FILE) as f:
            pid = int(f.read().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError, FileNotFoundError):
        return False


def _find_mgr_id() -> str:
    for a in db.list_agents("mgr"):
        return a["id"]
    return "agent-mgr-001"


def _classify_channels(channels):
    dm, group, internal, mgr = [], [], [], []
    for ch in channels:
        name = ch["channel"]
        if name.startswith("dm-"):
            dm.append(ch)
        elif name.startswith("group-"):
            group.append(ch)
        elif name.startswith("internal-"):
            internal.append(ch)
        elif name.startswith("mgr"):
            mgr.append(ch)
    return dm, group, internal, mgr


def _channel_is_active(channels, ch_name):
    for c in channels:
        if c["channel"] == ch_name:
            return _seconds_since(c["last_active"]) < 120
    return False


# ══════════════════════════════════════════════════════════
# Data Cache
# ══════════════════════════════════════════════════════════

class DataCache:
    def __init__(self):
        self.all_agents = {}
        self.messages = []
        self.total = 0
        self.channels = []
        self.mgr_id = _find_mgr_id()

    def refresh(self):
        # 모든 에이전트 표시 (active 뿐 아니라 전부)
        agents = db.list_agents()
        agents.sort(key=lambda a: (
            0 if a.get("type") == "mgr" else 1 if a.get("type") == "creator" else 2,
            a["id"],
        ))
        self.all_agents = {a["id"]: a for a in agents}

        conn = db.get_conn()
        rows = conn.execute(
            "SELECT * FROM conversations ORDER BY timestamp DESC LIMIT 20"
        ).fetchall()
        self.total = conn.execute(
            "SELECT COUNT(*) as c FROM conversations"
        ).fetchone()["c"]
        conn.close()
        self.messages = list(reversed(rows))
        self.channels = db.get_channel_overview()


_cache = DataCache()


# ══════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════

DASHBOARD_CSS = """
Screen {
    background: $surface;
}


#main-body {
    height: 1fr;
}

/* ── 상태 바 ── */
.status-bar {
    height: auto;
    margin: 0 2;
    padding: 0 2;
    background: $panel;
    border: round $primary-darken-2;
}

/* ── 네비게이션 탭 ── */
.nav-bar {
    height: 3;
    margin: 0 2;
    padding: 0 1;
}
.nav-bar Button {
    margin: 0 0 0 1;
    min-width: 12;
}

/* ── 메인 콘텐츠 ── */
.content-area {
    margin: 0 2;
    padding: 1 2;
    height: 1fr;
    background: $panel;
    border: round $primary-darken-2;
    overflow-y: auto;
}

/* ── 에이전트 그리드 ── */
.agent-grid {
    height: auto;
    grid-size: 3;
    grid-gutter: 1;
    margin: 0 2;
    padding: 0;
}
.agent-card {
    height: auto;
    min-height: 5;
    padding: 1 2;
    background: $panel;
    border: round $primary-darken-2;
}
.agent-card:hover {
    border: round $accent;
}
.agent-card.thinking {
    border: round $warning;
}
.agent-card.mgr {
    border: round blue;
}
.agent-card.creator {
    border: round $warning-darken-1;
}

/* ── 하단 3패널 ── */
.bottom-panels {
    height: auto;
    max-height: 18;
    margin: 0 2;
}
.bottom-panel {
    height: auto;
    max-height: 16;
    padding: 1 2;
    background: $panel;
    border: round $primary-darken-2;
    overflow-y: auto;
}

/* ── 채널 목록 ── */
.channel-list {
    height: auto;
    max-height: 20;
    margin: 0 2;
    background: $panel;
    border: round $primary-darken-2;
    padding: 1 2;
}

/* ── 상세 뷰 ── */
.detail-panel {
    margin: 0 2 1 2;
    padding: 1 2;
    height: auto;
    background: $panel;
    border: round $accent;
}

.chat-panel {
    margin: 0 2;
    padding: 1 2;
    height: 1fr;
    background: $panel;
    border: round $primary-darken-2;
    overflow-y: auto;
}

.log-panel {
    margin: 0 2;
    padding: 1 2;
    height: 1fr;
    max-height: 25;
    background: $panel;
    border: round $primary-darken-2;
    overflow-y: auto;
}

/* ── 기타 ── */
.section-title {
    padding: 0 2;
    margin: 0 2;
    color: $text-muted;
}
"""


# ══════════════════════════════════════════════════════════
# 메인 대시보드 화면
# ══════════════════════════════════════════════════════════

class DashboardScreen(Screen):
    BINDINGS = [
        Binding("q", "quit_app", "종료"),
        Binding("r", "refresh", "새로고침"),
        Binding("ctrl+r", "restart", "재시작"),
        Binding("s", "sync", "동기화"),
        Binding("w", "go_wizard", "Wizard"),
        Binding("escape", "go_back", "복귀"),
    ]

    def __init__(self):
        super().__init__()
        self._bot_proc: subprocess.Popen | None = None
        self._dev_proc: subprocess.Popen | None = None
        self._prev_dev = False
        self._current_view = "overview"  # overview, agent, channel, channels, health, dev, logs

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="main-body", can_focus=False):
            # 상태 바
            yield Static(id="status-bar", classes="status-bar")
            # 네비게이션
            with Horizontal(classes="nav-bar"):
                yield Button("Overview", variant="primary", id="nav-overview")
                yield Button("Channels", id="nav-channels")
                yield Button("Health", id="nav-health")
                yield Button("Dev", id="nav-dev")
                yield Button("Logs", id="nav-logs")
                yield Button("Refresh", variant="primary", id="nav-refresh")
                yield Button("Restart", variant="error", id="nav-restart")
                yield Button("Sync", variant="success", id="nav-sync")
                yield Button("Wizard", variant="warning", id="nav-wizard")
            # 에이전트 선택 목록
            yield OptionList(id="agent-list", classes="content-area")
            # 콘텐츠 영역
            yield Static(id="content", classes="content-area")
        yield Footer()

    def on_mount(self):
        db.init_db()
        log_writer.clear_flags()
        os.makedirs(os.path.join(PROJECT_ROOT, "logs", "agents"), exist_ok=True)
        os.makedirs(os.path.join(PROJECT_ROOT, "logs", "chat"), exist_ok=True)
        os.makedirs(os.path.join(PROJECT_ROOT, "dev"), exist_ok=True)
        self._start_bot()
        _cache.refresh()
        self._refresh_all()
        self.set_interval(1.0, self._tick)
        self.query_one("#agent-list", OptionList).focus()

    # ── Bot / Dev 프로세스 관리 ──────────────────────────

    def _start_bot(self):
        if self._bot_proc and self._bot_proc.poll() is None:
            return
        # 이미 외부에서 봇이 돌고 있으면 새로 시작하지 않음
        if _is_bot_running():
            log_writer.system("봇 이미 실행 중 — 연결")
            return
        log_writer.system("봇 시작")
        # stdout/stderr를 DEVNULL로 — 로그는 봇이 log_writer로 자체 기록
        # DEVNULL이면 대시보드 종료 시 SIGPIPE 문제 없음
        self._bot_proc = subprocess.Popen(
            [_venv_python(), "-u", "-m", "src.discord_bot"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            with open(PID_FILE, "w") as f:
                f.write(str(self._bot_proc.pid))
        except OSError:
            pass

    def _stop_bot(self):
        if self._bot_proc and self._bot_proc.poll() is None:
            self._bot_proc.terminate()
            try:
                self._bot_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._bot_proc.kill()
        self._bot_proc = None
        try:
            os.remove(PID_FILE)
        except FileNotFoundError:
            pass

    def _run_dev_runner(self):
        log_writer.system("개발자 에이전트 실행")
        dev_log = open(os.path.join(PROJECT_ROOT, "logs", "dev_stdout.log"), "a")
        self._dev_log_file = dev_log
        self._dev_proc = subprocess.Popen(
            [_venv_python(), "-u", "-m", "src.tools.dev_runner"],
            cwd=PROJECT_ROOT,
            stdout=dev_log, stderr=dev_log,
        )

    def _check_bot_status(self):
        if self._bot_proc is None:
            return
        exit_code = self._bot_proc.poll()
        if exit_code is None:
            return

        self._bot_proc = None
        try:
            os.remove(PID_FILE)
        except FileNotFoundError:
            pass

        if exit_code == 42:
            log_writer.system(f"봇 종료 (개발 요청, exit={exit_code})")
            self._run_dev_runner()
        elif exit_code == 0:
            log_writer.system("봇 정상 종료")
        else:
            log_writer.system(f"봇 비정상 종료 (exit={exit_code}) — 5초 후 재시작")
            self.set_timer(5.0, self._start_bot)

        if self._dev_proc and self._dev_proc.poll() is not None:
            log_writer.system("개발자 에이전트 완료 — 전체 재시작")
            self._dev_proc = None
            self.set_timer(2.0, self._do_full_restart)

    # ── Tick / Refresh ──────────────────────────────────

    def _tick(self):
        _cache.refresh()
        self._check_bot_status()

        if self._dev_proc and self._dev_proc.poll() is not None:
            log_writer.system("개발자 에이전트 완료 — 전체 재시작")
            self._dev_proc = None
            self.set_timer(2.0, self._do_full_restart)

        dev_active = log_writer.is_dev_active()
        if dev_active and not self._prev_dev:
            self._current_view = "dev"
        elif not dev_active and self._prev_dev and self._current_view == "dev":
            self._current_view = "overview"
        self._prev_dev = dev_active

        self._refresh_all()

    def _refresh_all(self):
        # 상태 바 업데이트
        self._update_status_bar()

        content = self.query_one("#content", Static)
        agent_list = self.query_one("#agent-list", OptionList)
        view = self._current_view

        # overview에서만 에이전트 목록 표시
        if view == "overview":
            agent_list.display = True
            content.display = True
            self._update_agent_list()
            content.update(self._render_overview())
        else:
            agent_list.display = False
            content.display = True
            if view.startswith("agent:"):
                content.update(self._render_agent_detail(view.split(":", 1)[1]))
            elif view == "channels":
                content.update(self._render_channels())
            elif view.startswith("channel:"):
                content.update(self._render_channel_detail(view.split(":", 1)[1]))
            elif view == "health":
                content.update(self._render_health())
            elif view == "dev":
                content.update(self._render_dev())
            elif view == "logs":
                content.update(self._render_logs())
            else:
                content.update(self._render_overview())

    def _update_agent_list(self):
        """에이전트 OptionList 갱신"""
        agent_list = self.query_one("#agent-list", OptionList)
        agents = list(_cache.all_agents.values())

        # 현재 옵션 ID 목록
        current_ids = set()
        try:
            for i in range(agent_list.option_count):
                opt = agent_list.get_option_at_index(i)
                if opt.id:
                    current_ids.add(opt.id)
        except Exception:
            current_ids = set()

        expected_ids = {a["id"] for a in agents}

        # 변경 있을 때만 갱신 (포커스 유지)
        if current_ids != expected_ids:
            agent_list.clear_options()
            for a in agents:
                c = _get_color(a["id"])
                thinking = log_writer.is_thinking(a["id"])
                em = E_EMOJI.get(a["current_emotion"], "")
                icon = "🧠" if thinking else "🟢" if a["status"] == "active" else "⚪"
                type_map = {"mgr": "Manager", "creator": "Creator", "persona": "Persona"}
                type_str = type_map.get(a.get("type", ""), a.get("type", ""))
                label = f"  {icon} [{c}]{a['name']}[/{c}]  {type_str}  {em} {a.get('current_emotion', '')}"
                agent_list.add_option(Option(label, id=a["id"]))

    def _update_status_bar(self):
        bot = _is_bot_running()
        dev = log_writer.is_dev_active()
        thinking = [a for a in _cache.all_agents.values()
                    if log_writer.is_thinking(a["id"])]
        total = len(_cache.all_agents)
        now = datetime.now().strftime("%H:%M:%S")

        bot_s = "[green bold]● Running[/green bold]" if bot else "[red bold]● Stopped[/red bold]"
        dev_s = "[bright_yellow bold]🔧 Dev[/bright_yellow bold]" if dev else ""
        think_s = f"[bright_yellow]🧠 {len(thinking)}[/bright_yellow]" if thinking else ""

        parts = [
            f"[bright_magenta bold]◈ Chaos[/bright_magenta bold]",
            bot_s,
            f"[dim]{now}[/dim]",
            f"Agents: [cyan]{total}[/cyan]",
            f"Messages: [dim]{_cache.total:,}[/dim]",
        ]
        if think_s:
            parts.append(think_s)
        if dev_s:
            parts.append(dev_s)

        self.query_one("#status-bar", Static).update(
            Text.from_markup("  │  ".join(parts))
        )

    # ── Render: Overview ────────────────────────────────

    def _render_agent_card(self, agent):
        """에이전트 카드 — 추론 중이면 확장, 아니면 컴팩트"""
        aid = agent["id"]
        c = _get_color(aid)
        thinking = log_writer.is_thinking(aid)
        em = E_EMOJI.get(agent["current_emotion"], "")
        intensity = agent.get("emotion_intensity", 0)
        sec = _seconds_since(agent.get("last_active"))
        type_map = {"mgr": "Manager", "creator": "Creator", "persona": "Persona"}
        type_str = type_map.get(agent.get("type", ""), "")

        if thinking:
            # ── 확장 카드: 추론 로그 + 최근 대화 ──
            lines = []
            lines.append(f"[bright_yellow bold]🧠 추론중[/bright_yellow bold]  {em} {agent['current_emotion']} ({intensity}/10)")
            lines.append(f"[dim]{type_str} · {_ago(sec)}[/dim]")
            lines.append("")

            # 추론 로그
            sys_log_path = os.path.join(log_writer.get_log_dir(), "system.log")
            all_sys = log_writer.tail(sys_log_path, 50)
            thinking_lines = [l for l in all_sys if f"[{aid}]" in l]
            if thinking_lines:
                lines.append("[bold]추론 로그:[/bold]")
                for l in thinking_lines[-5:]:
                    lines.append(f"  [dim]{l}[/dim]")
                lines.append("")

            # 최근 대화
            agent_type = agent.get("type", "persona")
            ch_name = "mgr-dashboard" if agent_type == "mgr" else f"dm-{agent['name']}"
            recent = db.get_recent_messages(ch_name, limit=4)
            if recent:
                lines.append("[bold]최근 대화:[/bold]")
                for r in recent[-4:]:
                    speaker = get_user_name() if r["speaker"] == get_user_id() else agent["name"]
                    lines.append(f"  [{c}]{speaker}[/{c}]: {_trunc(r['message'], 60)}")

            return Panel(
                "\n".join(lines),
                title=f"[{c} bold]{agent['name']}[/{c} bold]  [bright_yellow]● ACTIVE[/bright_yellow]",
                border_style="bright_yellow", box=box.ROUNDED, padding=(1, 2),
            )
        else:
            # ── 컴팩트 카드 ──
            bar = "●" * (intensity // 2) + "○" * (5 - intensity // 2)
            status = "[green]활성[/green]" if agent["status"] == "active" else f"[dim]{agent['status']}[/dim]"

            line1 = f"{em} {agent['current_emotion']}  [{bar}]  {status}"
            line2 = f"[dim]{type_str} · {_ago(sec)}[/dim]"

            # 마지막 메시지 한 줄
            agent_type = agent.get("type", "persona")
            ch_name = "mgr-dashboard" if agent_type == "mgr" else f"dm-{agent['name']}"
            recent = db.get_recent_messages(ch_name, limit=1)
            line3 = ""
            if recent:
                r = recent[-1]
                speaker = get_user_name() if r["speaker"] == get_user_id() else agent["name"]
                line3 = f"[dim]{speaker}: {_trunc(r['message'], 50)}[/dim]"

            content = f"{line1}\n{line2}"
            if line3:
                content += f"\n{line3}"

            return Panel(
                content,
                title=f"[{c} bold]{agent['name']}[/{c} bold]",
                border_style=c if agent["status"] == "active" else "dim",
                box=box.ROUNDED, padding=(0, 1),
            )

    def _render_overview(self):
        items = []
        agents = list(_cache.all_agents.values())

        if not agents:
            return Panel(
                "[dim]에이전트가 없습니다.\n관리자(Wizard)에서 DB를 초기화하세요.[/dim]",
                border_style="yellow", box=box.ROUNDED, padding=(1, 2),
            )

        # 추론 중 에이전트 먼저 (확장 카드)
        thinking = [a for a in agents if log_writer.is_thinking(a["id"])]
        idle = [a for a in agents if not log_writer.is_thinking(a["id"])]

        for a in thinking:
            items.append(self._render_agent_card(a))

        # 비활성 에이전트 (컴팩트 카드, 3열 그리드)
        if idle:
            row = []
            for a in idle:
                row.append(self._render_agent_card(a))
                if len(row) == 3:
                    items.append(Columns(row, equal=True, expand=True))
                    row = []
            if row:
                items.append(Columns(row, equal=True, expand=True))

        # 채널 요약
        items.append(Text(""))
        dm, group, internal, mgr = _classify_channels(_cache.channels)
        ch_lines = []
        for label, icon, chs, clr in [
            ("DM", "💬", dm, "cyan"), ("Group", "👥", group, "green"),
            ("Internal", "🔒", internal, "yellow"), ("Mgr", "📋", mgr, "blue"),
        ]:
            if chs:
                active = sum(1 for c in chs if _channel_is_active(_cache.channels, c["channel"]))
                active_s = f" [green]({active} active)[/green]" if active else ""
                ch_lines.append(f"[{clr} bold]{icon} {label}[/{clr} bold] {len(chs)}{active_s}")
        ch_summary = "  │  ".join(ch_lines) if ch_lines else "[dim]채널 없음[/dim]"
        items.append(Panel(ch_summary, border_style="dim", box=box.ROUNDED, padding=(0, 1)))

        # 최근 대화
        chat_lines = []
        for r in (_cache.messages[-10:] if _cache.messages else []):
            sid = r["speaker"]
            c = _get_color(sid) if sid != get_user_id() else "bright_green"
            ts = r["timestamp"][11:16] if r["timestamp"] else ""
            ch = r["channel"]
            tag = "DM" if ch.startswith("dm-") else \
                  "🔒" if ch.startswith("internal-") else \
                  "👥" if ch.startswith("group-") else \
                  "📋" if ch.startswith("mgr") else ch[:6]
            msg = _trunc(r["message"], 60)
            name = _speaker_name(sid)
            chat_lines.append(f"[dim]{ts} {tag}[/dim] [{c}]{name}[/{c}] {msg}")

        chat_content = "\n".join(chat_lines) if chat_lines else "[dim]대화 없음[/dim]"
        items.append(Panel(
            chat_content, title="[bold]💬 최근 대화[/bold]",
            border_style="dim", box=box.ROUNDED, padding=(0, 1),
        ))

        # 시스템 로그
        sys_log = os.path.join(log_writer.get_log_dir(), "system.log")
        log_lines = log_writer.tail(sys_log, 6)
        if log_lines:
            items.append(Panel(
                "\n".join(log_lines),
                title="[bold]⚙ System[/bold]",
                border_style="dim", box=box.ROUNDED, padding=(0, 1),
            ))

        return Group(*items)

    # ── Render: Agent Detail ────────────────────────────

    def _render_agent_detail(self, agent_id):
        agent = _cache.all_agents.get(agent_id) or db.get_agent(agent_id)
        profile = load_profile(agent_id)
        if not agent:
            return Text(f"에이전트 없음: {agent_id}")

        c = _get_color(agent_id)
        em = E_EMOJI.get(agent["current_emotion"], "")
        thinking = log_writer.is_thinking(agent_id)
        sec = _seconds_since(agent.get("last_active"))
        items = []

        # ── 프로필 정보 ──
        info_lines = []
        type_map = {"mgr": "Manager", "creator": "Creator", "persona": "Persona"}
        status_str = "[bright_yellow]🧠 추론중[/bright_yellow]" if thinking else \
                     "[green]● 활성[/green]" if agent["status"] == "active" else f"[dim]{agent['status']}[/dim]"

        info_lines.append(f"{status_str}  │  {em} {agent['current_emotion']} ({agent.get('emotion_intensity', 0)}/10)  │  [dim]{_ago(sec)}[/dim]")
        info_lines.append(f"[dim]{agent_id} · {type_map.get(agent.get('type', ''), '')}[/dim]")

        if profile:
            parts = []
            if profile.get("age"):
                parts.append(f"{profile['age']}살")
            if profile.get("mbti"):
                parts.append(profile["mbti"])
            if profile.get("enneagram"):
                parts.append(profile["enneagram"])
            if parts:
                info_lines.append("  ".join(parts))

            traits = profile.get("personality", {}).get("traits", [])
            if traits:
                info_lines.append(f"[bold]성격:[/bold] {' · '.join(traits[:5])}")

            rel = profile.get("relationship_to_owner", {})
            if rel.get("type"):
                rel_str = f"[bold]Owner:[/bold] {rel['type']}"
                if rel.get("pet_name"):
                    rel_str += f" ({rel['pet_name']})"
                if rel.get("duration"):
                    rel_str += f" · {rel['duration']}"
                info_lines.append(rel_str)

            # 다른 에이전트와의 관계
            rels = profile.get("relationships", {})
            if rels:
                rel_parts = []
                for target_id, rel_info in list(rels.items())[:5]:
                    target = _cache.all_agents.get(target_id)
                    target_name = target["name"] if target else target_id
                    tc = _get_color(target_id)
                    rel_type = rel_info.get("type", "?")
                    rel_parts.append(f"[{tc}]{target_name}[/{tc}]({rel_type})")
                info_lines.append(f"[bold]관계:[/bold] {' · '.join(rel_parts)}")

        items.append(Panel(
            "\n".join(info_lines),
            title=f"[{c} bold]{agent['name']}[/{c} bold]",
            border_style=c, box=box.ROUNDED, padding=(1, 2),
        ))

        # ── 추론 로그 (raw) ──
        sys_log_path = os.path.join(log_writer.get_log_dir(), "system.log")
        all_sys = log_writer.tail(sys_log_path, 200)
        thinking_lines = [l for l in all_sys if f"[{agent_id}]" in l]
        thinking_content = "\n".join(thinking_lines[-20:]) if thinking_lines else "[dim]추론 로그 없음[/dim]"
        thinking_title = "[bold]🧠 추론 로그[/bold]"
        if thinking:
            thinking_title += "  [bright_yellow]● LIVE[/bright_yellow]"
        items.append(Panel(
            thinking_content, title=thinking_title,
            border_style="bright_yellow" if thinking else "dim",
            box=box.ROUNDED, padding=(0, 1),
        ))

        # ── 채팅 로그 (이 에이전트 관련 모든 채널) ──
        agent_type = agent.get("type", "persona")
        agent_name = agent["name"]

        # 주 채널
        if agent_type == "mgr":
            primary_ch = "mgr-dashboard"
        else:
            primary_ch = f"dm-{agent_name}"

        # 관련 채널 찾기 (이 에이전트가 참여한 채널들)
        related_channels = []
        for ch in _cache.channels:
            ch_name = ch["channel"]
            if ch_name == primary_ch:
                continue
            if agent_name in ch_name or ch_name.startswith("mgr"):
                related_channels.append(ch)

        # 주 채널 대화
        recent = db.get_recent_messages(primary_ch, limit=20)
        chat_lines = []
        for r in recent:
            sid = r["speaker"]
            sc = _get_color(sid) if sid != get_user_id() else "bright_green"
            name = get_user_name() if sid == get_user_id() else _speaker_name(sid)
            ts = r["timestamp"][11:16] if r["timestamp"] else ""
            chat_lines.append(f"[dim]{ts}[/dim] [{sc} bold]{name}[/{sc} bold]: {r['message']}")

        chat_content = "\n".join(chat_lines) if chat_lines else "[dim]대화 없음[/dim]"
        items.append(Panel(
            chat_content, title=f"[bold]💬 {primary_ch}[/bold]",
            border_style="cyan", box=box.ROUNDED, padding=(0, 1),
        ))

        # 관련 채널 대화
        for ch in related_channels[:3]:
            ch_name = ch["channel"]
            recent = db.get_recent_messages(ch_name, limit=10)
            if not recent:
                continue
            lines = []
            for r in recent:
                sid = r["speaker"]
                sc = _get_color(sid) if sid != get_user_id() else "bright_green"
                name = get_user_name() if sid == get_user_id() else _speaker_name(sid)
                ts = r["timestamp"][11:16] if r["timestamp"] else ""
                lines.append(f"[dim]{ts}[/dim] [{sc} bold]{name}[/{sc} bold]: {r['message']}")

            if ch_name.startswith("internal-"):
                color, icon = "yellow", "🔒"
            elif ch_name.startswith("group-"):
                color, icon = "green", "👥"
            else:
                color, icon = "dim", "💬"

            items.append(Panel(
                "\n".join(lines),
                title=f"[bold]{icon} {ch_name}[/bold]",
                border_style=color, box=box.ROUNDED, padding=(0, 1),
            ))

        return Group(*items)

    # ── Render: Channels ────────────────────────────────

    def _render_channels(self):
        dm, group, internal, mgr = _classify_channels(_cache.channels)
        items = []

        for label, icon, chs, clr in [
            ("DM", "💬", dm, "cyan"),
            ("Group", "👥", group, "green"),
            ("Internal", "🔒", internal, "yellow"),
            ("Manager", "📋", mgr, "blue"),
        ]:
            if not chs:
                continue

            table = RichTable(
                box=box.SIMPLE, show_header=True, padding=(0, 1),
                expand=True,
            )
            table.add_column("", width=2)  # active indicator
            table.add_column("Channel", style=clr, ratio=3)
            table.add_column("Messages", justify="right", ratio=1)
            table.add_column("Last Active", justify="right", ratio=1)

            for ch in chs:
                active = _channel_is_active(_cache.channels, ch["channel"])
                dot = "[green bold]●[/green bold]" if active else "[dim]○[/dim]"
                ts = ch["last_active"][11:16] if ch["last_active"] else "-"
                table.add_row(dot, ch["channel"], str(ch["msg_count"]), ts)

            items.append(Panel(
                table,
                title=f"[bold]{icon} {label}[/bold]  [dim]({len(chs)})[/dim]",
                border_style=clr, box=box.ROUNDED, padding=(0, 1),
            ))

        if not items:
            items.append(Panel("[dim]채널 없음[/dim]", border_style="dim", box=box.ROUNDED))

        return Group(*items)

    # ── Render: Channel Detail ──────────────────────────

    def _render_channel_detail(self, channel_name):
        active = _channel_is_active(_cache.channels, channel_name)
        active_s = "  [green bold]● 대화중[/green bold]" if active else ""

        rows = db.get_recent_messages(channel_name, limit=30)
        lines = []
        for r in reversed(rows):
            sid = r["speaker"]
            c = _get_color(sid) if sid != get_user_id() else "bright_green"
            ts = r["timestamp"][11:16] if r["timestamp"] else ""
            name = _speaker_name(sid)
            lines.append(f"[dim]{ts}[/dim] [{c} bold]{name}[/{c} bold]: {r['message']}")

        content = "\n".join(lines) if lines else "[dim]메시지 없음[/dim]"

        if channel_name.startswith("dm-"):
            color, icon = "cyan", "💬"
        elif channel_name.startswith("group-"):
            color, icon = "green", "👥"
        elif channel_name.startswith("internal-"):
            color, icon = "yellow", "🔒"
        else:
            color, icon = "blue", "📋"

        return Panel(
            content,
            title=f"[bold]{icon} {channel_name}[/bold]{active_s}",
            border_style=color, box=box.ROUNDED, padding=(1, 2),
        )

    # ── Render: Health ──────────────────────────────────

    def _render_health(self):
        bot = _is_bot_running()
        dev = log_writer.is_dev_active()
        items = []

        # 프로세스 상태
        lines = []
        if bot:
            try:
                with open(PID_FILE) as f:
                    pid = f.read().strip()
                lines.append(f"[green bold]● Server Running[/green bold]  PID: {pid}")
            except Exception:
                lines.append("[green bold]● Server Running[/green bold]")
        else:
            lines.append("[red bold]● Server Stopped[/red bold]")

        if dev:
            lines.append("[bright_yellow bold]🔧 Dev Mode Active[/bright_yellow bold]")
        else:
            lines.append("[dim]Dev Mode: Idle[/dim]")

        lines.append("")

        # 에이전트 요약
        thinking = [a for a in _cache.all_agents.values() if log_writer.is_thinking(a["id"])]
        active = [a for a in _cache.all_agents.values() if a["status"] == "active"]
        lines.append(f"[bold]Agents[/bold]")
        lines.append(f"  Active: [cyan]{len(active)}[/cyan]  Total: {len(_cache.all_agents)}  Thinking: {len(thinking)}")
        if thinking:
            lines.append(f"  🧠 {', '.join(a['name'] for a in thinking)}")

        lines.append("")

        # 채널 요약
        dm, group, internal, mgr = _classify_channels(_cache.channels)
        lines.append(f"[bold]Channels[/bold]")
        lines.append(f"  DM: {len(dm)}  Group: {len(group)}  Internal: {len(internal)}  Manager: {len(mgr)}")
        lines.append(f"  Total Messages: {_cache.total:,}")

        items.append(Panel(
            "\n".join(lines),
            title="[bold]🏥 Health Check[/bold]",
            border_style="green" if bot else "red",
            box=box.ROUNDED, padding=(1, 2),
        ))

        # 시스템 로그
        sys_log = os.path.join(log_writer.get_log_dir(), "system.log")
        log_lines = log_writer.tail(sys_log, 15)
        log_content = "\n".join(log_lines) if log_lines else "[dim]시스템 로그 없음[/dim]"
        items.append(Panel(
            log_content,
            title="[bold]⚙ System Log[/bold]",
            border_style="dim", box=box.ROUNDED, padding=(0, 1),
        ))

        return Group(*items)

    # ── Render: Dev ─────────────────────────────────────

    def _render_dev(self):
        active = log_writer.is_dev_active()
        status = "[bright_yellow bold]🔧 Running[/bright_yellow bold]" if active else "[dim]Idle[/dim]"
        sys_log = os.path.join(log_writer.get_log_dir(), "system.log")
        all_lines = log_writer.tail(sys_log, 200)
        dev_lines = [l for l in all_lines if "🔧" in l]
        content = "\n".join(dev_lines[-30:]) if dev_lines else "[dim]개발 로그 없음[/dim]"
        return Panel(
            content,
            title=f"[bold]🔧 Dev Runner (Opus)[/bold]  │  {status}",
            border_style="bright_yellow" if active else "dim",
            box=box.ROUNDED, padding=(1, 2),
        )

    # ── Render: Logs ────────────────────────────────────

    def _render_logs(self):
        sys_log = os.path.join(log_writer.get_log_dir(), "system.log")
        log_lines = log_writer.tail(sys_log, 40)
        content = "\n".join(log_lines) if log_lines else "[dim]로그 없음[/dim]"
        return Panel(
            content,
            title="[bold]📋 System Logs[/bold]",
            border_style="dim", box=box.ROUNDED, padding=(1, 2),
        )

    # ── 네비게이션 액션 ─────────────────────────────────

    _NAV_MAP = {
        "nav-overview": "overview",
        "nav-channels": "channels",
        "nav-health": "health",
        "nav-dev": "dev",
        "nav-logs": "logs",
    }

    # Sync, Wizard는 액션 버튼 — Enter/클릭으로만 실행
    _ACTION_BUTTONS = {"nav-refresh", "nav-restart", "nav-sync", "nav-wizard"}

    def on_button_pressed(self, event: Button.Pressed):
        """클릭 또는 Enter — 모든 버튼 처리"""
        self._handle_nav(event.button)

    def on_descendant_focus(self, event):
        """Tab 포커스 시 뷰 탭만 즉시 전환 (액션 버튼은 제외)"""
        if isinstance(event.widget, Button):
            if event.widget.id not in self._ACTION_BUTTONS:
                self._handle_nav(event.widget)

    @on(OptionList.OptionSelected, "#agent-list")
    def on_agent_selected(self, event: OptionList.OptionSelected):
        if event.option_id:
            self._current_view = f"agent:{event.option_id}"
            self._refresh_all()

    def action_go_back(self):
        if self._current_view.startswith("channel:"):
            self._current_view = "channels"
        elif self._current_view.startswith("agent:"):
            self._current_view = "overview"
            self._refresh_all()
            self.query_one("#agent-list", OptionList).focus()
            return
        elif self._current_view != "overview":
            self._current_view = "overview"
        self._refresh_all()

    def action_refresh(self):
        _cache.refresh()
        self._refresh_all()

    # ── Sync ─────────────────────────────────────────────

    def action_sync(self):
        # 추론 중인 에이전트가 있으면 차단
        thinking = [a for a in _cache.all_agents.values() if log_writer.is_thinking(a["id"])]
        if thinking:
            names = ", ".join(a["name"] for a in thinking)
            self._current_view = "overview"
            self._refresh_all()
            content = self.query_one("#content", Static)
            content.update(Panel(
                f"[yellow]추론 중인 에이전트가 있어 동기화할 수 없습니다.[/yellow]\n\n"
                f"🧠 {names}\n\n"
                f"[dim]추론 완료 후 다시 시도하세요.[/dim]",
                title="[bold]🔄 Sync[/bold]",
                border_style="yellow", box=box.ROUNDED, padding=(1, 2),
            ))
            return
        self._loading = LoadingOverlay("Discord ↔ DB 동기화 중...")
        self.app.push_screen(self._loading)
        self._run_sync()

    @work(thread=True)
    def _run_sync(self):
        import time

        def on_progress(msg):
            self.app.call_from_thread(self._loading.update_detail, msg)

        # 봇 중지 (같은 토큰 동시 접속 불가)
        on_progress("봇 일시 중지...")
        bot_was_running = self._bot_proc and self._bot_proc.poll() is None
        if bot_was_running:
            self._stop_bot()
            time.sleep(2)

        result = run_sync(on_progress=on_progress)

        # 봇 재시작
        if bot_was_running:
            on_progress("봇 재시작...")
            self.app.call_from_thread(self._start_bot)
            time.sleep(3)

        # 결과 표시
        if result["ok"]:
            lines = ["[green bold]동기화 완료[/green bold]\n"]
            if result["channels_created"]:
                lines.append(f"[green]채널 생성:[/green] {', '.join(result['channels_created'])}")
            if result["channels_deleted"]:
                lines.append(f"[yellow]채널 삭제:[/yellow] {', '.join(result['channels_deleted'])}")
            lines.append(f"[cyan]메시지 동기화:[/cyan] {result['messages_synced']}건")
            if result.get("errors"):
                lines.append(f"\n[yellow]경고 {len(result['errors'])}건:[/yellow]")
                for e in result["errors"][:5]:
                    lines.append(f"  [dim]{e}[/dim]")
            if not result["channels_created"] and not result["channels_deleted"] and result["messages_synced"] == 0 and not result.get("errors"):
                lines.append("\n[dim]변경 없음 — 이미 동기화 상태[/dim]")
            msg = "\n".join(lines)
        else:
            msg = f"[red]동기화 실패: {result.get('error', '?')}[/red]"
            if result.get("errors"):
                msg += "\n\n[yellow]상세:[/yellow]\n" + "\n".join(f"  [dim]{e}[/dim]" for e in result["errors"][:5])

        self.app.call_from_thread(self.app.pop_screen)
        self.app.call_from_thread(self._show_sync_result, msg)

    def _show_sync_result(self, msg: str):
        self._current_view = "overview"
        _cache.refresh()
        self._refresh_all()
        # 결과를 content에 표시
        content = self.query_one("#content", Static)
        content.update(Panel(
            msg,
            title="[bold]🔄 Sync Result[/bold]",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        ))

    # ── Restart / Navigation ────────────────────────────

    def _do_full_restart(self):
        """개발 완료 후 자동 전체 재시작"""
        self.action_restart()

    def action_restart(self):
        """이 커뮤니티 재시작 — 봇 + 대시보드를 재실행 (코드 변경 반영)"""
        self._stop_bot()
        if self._dev_proc and self._dev_proc.poll() is None:
            self._dev_proc.terminate()
        log_writer.system("대시보드 재시작")
        cid = os.environ.get("CHAOS_COMMUNITY", "")
        py = _venv_python()
        args = [py, "-m", "src.tui.dashboard"]
        if cid:
            args.append(cid)
        os.execvp(py, args)

    def action_go_wizard(self):
        """대시보드 종료 → Wizard 전환 (봇은 유지)"""
        # 봇 프로세스는 detach — 종료하지 않음
        # start_new_session=True + DEVNULL이라 대시보드 종료해도 안 죽음
        self._bot_proc = None
        self._dev_proc = None
        log_writer.system("Wizard 전환")
        self.app.exit(result="wizard")

    def _handle_nav(self, button: Button):
        view = self._NAV_MAP.get(button.id or "")
        if view:
            self._current_view = view
            self._refresh_all()
        elif button.id == "nav-refresh":
            self.action_refresh()
        elif button.id == "nav-restart":
            self.action_restart()
        elif button.id == "nav-sync":
            self.action_sync()
        elif button.id == "nav-wizard":
            self.action_go_wizard()

    def action_quit_app(self):
        self._stop_bot()
        if self._dev_proc and self._dev_proc.poll() is None:
            self._dev_proc.terminate()
        log_writer.system("대시보드 종료")
        self.app.exit()


# ══════════════════════════════════════════════════════════
# App
# ══════════════════════════════════════════════════════════

class ChaosDashboard(App):
    TITLE = "Project Chaos"
    SUB_TITLE = "Dashboard"
    CSS = DASHBOARD_CSS
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
    ]

    def on_mount(self):
        self.push_screen(DashboardScreen())


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Chaos Dashboard")
    parser.add_argument("community_id", nargs="?", help="커뮤니티 ID")
    args = parser.parse_args()

    if args.community_id:
        os.environ["CHAOS_COMMUNITY"] = args.community_id
        from src import community
        community.set_community(args.community_id)

    result = ChaosDashboard().run()

    if result == "wizard":
        py = _venv_python()
        os.execvp(py, [py, "-m", "src.tui.wizard"])


if __name__ == "__main__":
    main()
