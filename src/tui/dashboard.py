#!/usr/bin/env python3
"""
Project Glimi — Interactive Dashboard TUI (Textual)

커뮤니티 대시보드: 봇 상태, 에이전트, 채널, 로그를 실시간 모니터링.
마우스 + 키보드 모두 지원.

실행:
  python -m src.tui.dashboard [community_id]
"""
import sys
import os
import re as _re
import signal
import subprocess
import asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 다른 모듈 import 전에 커뮤니티 환경변수 설정
# (src.db import 시 community.get_community_id()가 호출됨)
for _a in sys.argv[1:]:
    if not _a.startswith("-"):
        os.environ["GLIMI_COMMUNITY"] = _a
        break

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
from src.core.sync import run_sync, run_restore
from src import log_writer
from src.tui.components import LoadingOverlay, ConfirmDialog, MessageActionDialog, ErrorDialog
from src.i18n import t

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
    "bright_magenta", "bright_cyan", "bright_green",
    "bright_red", "dodger_blue1", "spring_green1", "orchid",
    "salmon1", "turquoise2", "deep_pink1", "gold1",
    "medium_purple1", "dark_orange", "pale_green1", "sky_blue1",
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
    height: auto;
    background: $panel;
    border: round $primary-darken-2;
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

/* ── 에이전트 선택 목록 ── */
.agent-selector {
    height: auto;
    max-height: 80vh;
    margin: 0 2;
    background: $panel;
    border: round $primary-darken-2;
    padding: 0 1;
}

#nav-back {
    margin: 0 2;
    display: none;
}

#sync-buttons {
    display: none;
    margin: 0 2;
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
        Binding("e", "toggle_edit", "편집"),
        Binding("delete", "go_back", "뒤로"),
        Binding("w", "go_wizard", "Wizard"),
        Binding("backspace", "go_back", "Back"),
    ]

    def __init__(self):
        super().__init__()
        self._bot_proc: subprocess.Popen | None = None
        self._dev_proc: subprocess.Popen | None = None
        self._init_loading: LoadingOverlay | None = None
        self._prev_dev = False
        self._current_view = "overview"  # overview, agent, channel, channels, health, dev, logs, manage

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="main-body", can_focus=False):
            # 상태 바
            yield Static(id="status-bar", classes="status-bar")
            # 네비게이션
            with Horizontal(classes="nav-bar"):
                yield Button("Overview", variant="primary", id="nav-overview")
                yield Button("Agents", id="nav-agents")
                yield Button("Channels", id="nav-channels")
                yield Button("Sync", id="nav-sync")
                yield Button("Health", id="nav-health")
                yield Button("Logs", id="nav-logs")
                yield Button("Dev", id="nav-dev")
                yield Button("Usage", id="nav-usage")
                yield Button("Refresh", variant="primary", id="nav-refresh")
                yield Button("Restart", variant="error", id="nav-restart")
                yield Button("Wizard", variant="warning", id="nav-wizard")
            # Back 버튼 (서브페이지에서만 표시)
            yield Button("← Back", variant="default", id="nav-back")
            # 콘텐츠 영역
            yield Static(id="content", classes="content-area")
            # Sync 전용 버튼 바
            with Horizontal(id="sync-buttons", classes="nav-bar"):
                yield Button("🔍 Scan Discord", variant="primary", id="btn-sync-scan")
                yield Button("▶ Start Sync", variant="success", id="btn-sync-start")
            # Agents 뷰용 에이전트 선택
            yield OptionList(id="agent-list", classes="agent-selector")
            # 공용 리스트 (채널 편집, 싱크 채널 선택 등)
            yield OptionList(id="manage-list", classes="content-area")
        yield Footer()

    def on_mount(self):
        db.init_db()
        log_writer.clear_flags()
        os.makedirs(os.path.join(PROJECT_ROOT, "logs", "agents"), exist_ok=True)
        os.makedirs(os.path.join(PROJECT_ROOT, "logs", "chat"), exist_ok=True)
        os.makedirs(os.path.join(PROJECT_ROOT, "dev"), exist_ok=True)
        # 이전 봇 프로세스 정리 (다른 커뮤니티 봇이 남아있을 수 있음)
        if _is_bot_running():
            try:
                with open(PID_FILE) as f:
                    old_pid = int(f.read().strip())
                os.kill(old_pid, signal.SIGTERM)
            except Exception:
                pass
            try:
                os.remove(PID_FILE)
            except FileNotFoundError:
                pass
        # 이전 로그 정리
        _log_path = os.path.join(log_writer.get_log_dir(), "system.log")
        try:
            open(_log_path, "w").close()
        except OSError:
            pass

        self._check_first_run_cleanup()
        self._start_bot()
        self._init_loading = LoadingOverlay(t("dashboard.loading_discord"))
        self.app.push_screen(self._init_loading)
        self._wait_bot_ready()
        _cache.refresh()
        self._refresh_all()
        self.set_interval(1.0, self._tick)
        self.query_one("#nav-overview", Button).focus()

    def _check_first_run_cleanup(self):
        """첫 실행 판단 — 봇이 기존 디코 채널 유무를 보고 판단"""
        # .clean-channels / .keep-channels 플래그는 봇이 ensure_channels()에서 처리 후 제거함
        # 대시보드에서 미리 제거하면 위저드에서 설정한 플래그가 사라짐
        pass

    # ── Bot / Dev 프로세스 관리 ──────────────────────────

    def _start_bot(self):
        if self._bot_proc and self._bot_proc.poll() is None:
            return
        # 이미 외부에서 봇이 돌고 있으면 새로 시작하지 않음
        if _is_bot_running():
            log_writer.system("Bot already running — connecting")
            return
        log_writer.system("Bot starting")
        env = os.environ.copy()
        cid = os.environ.get("GLIMI_COMMUNITY", "")
        if cid:
            env["GLIMI_COMMUNITY"] = cid
        self._bot_proc = subprocess.Popen(
            [_venv_python(), "-u", "-m", "src.discord_bot"],
            cwd=PROJECT_ROOT, env=env,
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
        log_writer.system("Dev runner started")
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
            log_writer.system(f"Bot exit (dev request, exit={exit_code})")
            self._run_dev_runner()
        elif exit_code == 0:
            log_writer.system("Bot stopped normally")
        else:
            log_writer.system(f"Bot crashed (exit={exit_code}) — restarting in 5s")
            self.set_timer(5.0, self._start_bot)

        if self._dev_proc and self._dev_proc.poll() is not None:
            log_writer.system("Dev runner done — full restart")
            self._dev_proc = None
            self.set_timer(2.0, self._do_full_restart)

    # ── Tick / Refresh ──────────────────────────────────

    @work(thread=True)
    def _wait_bot_ready(self):
        """봇 초기화 + 온보딩 대기 → 단계별 문구 변경 → 완료 시 로딩 해제"""
        import time as _time
        log_path = os.path.join(log_writer.get_log_dir(), "system.log")
        seen_lines = 0
        phase = "discord"  # discord → onboarding → done

        # 봇이 아직 시작도 안 했으면 잠깐 대기
        _time.sleep(1)

        try:
          for _ in range(600):  # 최대 5분 (0.5초 간격)
            # 봇 즉사 체크 (sleep 전에)
            if self._bot_proc and self._bot_proc.poll() is not None:
                exit_code = self._bot_proc.poll()
                if self._init_loading:
                    try:
                        self.app.call_from_thread(self.app.pop_screen)
                    except Exception:
                        pass
                    self._init_loading = None
                err_lines = log_writer.tail(log_path, 10) if os.path.exists(log_path) else []
                log_text = "\n".join(err_lines[-5:])
                if "login failed" in log_text.lower() or "improper token" in log_text.lower():
                    err_msg = (
                        f"Bot login failed (exit code: {exit_code})\n\n"
                        "The bot token may be invalid or expired.\n"
                        "Go to Wizard → Settings → Set Token to update.\n\n"
                        + log_text
                    )
                else:
                    err_msg = f"Bot process crashed (exit code: {exit_code})\n\n" + log_text
                self.app.call_from_thread(
                    self.app.push_screen,
                    ErrorDialog(t("dashboard.error_bot_crash"), err_msg),
                )
                return

            _time.sleep(0.5)

            # 시스템 로그 실시간 표시 (온보딩 단계에서는 숨김)
            is_onboarding = phase in ("onboarding", "wait_onboarding")
            if self._init_loading and os.path.exists(log_path) and not is_onboarding:
                try:
                    lines = log_writer.tail(log_path, 30)
                    for line in lines[seen_lines:]:
                        if "[sup:" in line or "[supervisor]" in line:
                            continue
                        self.app.call_from_thread(self._init_loading.update_detail, line)
                        # 로그 키워드로 모달 타이틀 자동 변경
                        low = line.lower()
                        if "nitializing channel" in line or "채널 초기화" in line:
                            self.app.call_from_thread(self._init_loading.update_message, t("dashboard.loading_channels"))
                        elif "yncing avatar" in line or "아바타 동기화" in line:
                            self.app.call_from_thread(self._init_loading.update_message, t("dashboard.loading_avatars"))
                        elif "ctivating agent" in line or "에이전트" in line:
                            self.app.call_from_thread(self._init_loading.update_message, t("dashboard.loading_agents"))
                        elif "ot ready" in line or "봇 준비" in line:
                            self.app.call_from_thread(self._init_loading.update_message, t("dashboard.loading_almost"))
                    seen_lines = len(lines)
                except Exception:
                    pass

            # 단계 전환
            if phase == "discord" and log_writer.is_bot_ready():
                if log_writer.is_onboarding():
                    phase = "onboarding"
                    self.app.call_from_thread(
                        self._init_loading.update_message,
                        t("dashboard.onboarding_prep")
                    )
                elif log_writer.is_onboarding_done():
                    break
                else:
                    # bot ready + onboarding 안 시작 → 3초 대기 후 탈출
                    phase = "wait_onboarding"
                    _wait_count = 0

            elif phase == "wait_onboarding":
                _wait_count += 1
                if log_writer.is_onboarding():
                    phase = "onboarding"
                    self.app.call_from_thread(
                        self._init_loading.update_message,
                        t("dashboard.onboarding_prep")
                    )
                elif log_writer.is_onboarding_done() or _wait_count > 6:
                    break  # 3초(6 * 0.5) 대기 후 온보딩 없으면 진행

            elif phase == "onboarding":
                if log_writer.is_onboarding_done():
                    break

            if self._bot_proc is None:
                break

        except Exception as e:
            log_writer.system(f"_wait_bot_ready error: {e}")

        # 타임아웃 체크 (5분 루프 다 돌았는데 아직 완료 안 됨)
        if self._init_loading and not log_writer.is_bot_ready():
            try:
                self.app.call_from_thread(self.app.pop_screen)
            except Exception:
                pass
            self._init_loading = None
            err_lines = log_writer.tail(log_path, 10) if os.path.exists(log_path) else []
            err_msg = (
                "Bot initialization did not complete within 5 minutes.\n"
                "This may be a network or token issue.\n"
                "Go to Wizard → Settings → Set Token to verify.\n\n"
                + "\n".join(err_lines[-5:])
            )
            self.app.call_from_thread(
                self.app.push_screen,
                ErrorDialog(t("dashboard.error_timeout"), err_msg),
            )
            return

        # 정상 완료 — 로딩 해제
        if self._init_loading:
            try:
                self.app.call_from_thread(self.app.pop_screen)
            except Exception:
                pass
            self._init_loading = None

    def _tick(self):

        # 모달이 떠있으면 UI 갱신만 스킵 (봇 상태 체크는 계속)
        _cache.refresh()
        self._check_bot_status()

        if self._dev_proc and self._dev_proc.poll() is not None:
            log_writer.system("Dev runner done — full restart")
            self._dev_proc = None
            self.set_timer(2.0, self._do_full_restart)

        dev_active = log_writer.is_dev_active()
        if dev_active and not self._prev_dev:
            self._current_view = "dev"
        elif not dev_active and self._prev_dev and self._current_view == "dev":
            self._current_view = "overview"
        self._prev_dev = dev_active

        # 편집 모드/에이전트 상세에서는 UI 갱신 스킵 (스크롤 위치 유지)
        view = self._current_view
        if view.endswith(":edit") or view.startswith("agent:") or view.startswith("channel:"):
            # 상태바만 갱신
            self._update_status_bar()
            return

        self._refresh_all()

    def _refresh_all(self):
        # 모달 떠있으면 상태바만
        try:
            if len(self.app.screen_stack) > 2:
                self._update_status_bar()
                return
        except Exception:
            pass

        self._update_status_bar()

        content = self.query_one("#content", Static)
        agent_list = self.query_one("#agent-list", OptionList)
        manage_list = self.query_one("#manage-list", OptionList)
        view = self._current_view

        # 기본: 리스트/버튼 숨김
        agent_list.display = False
        manage_list.display = False
        self.query_one("#sync-buttons", Horizontal).display = False

        # Back 버튼: 서브페이지에서만 표시
        back_btn = self.query_one("#nav-back", Button)
        is_subpage = view.startswith("agent:") or view.startswith("channel:") or view.startswith("manage:")
        back_btn.display = is_subpage

        # 탭 Active 표시
        view_base = view.split(":")[0] if ":" in view else view
        _TAB_ALIAS = {"channel": "channels", "agent": "agents", "manage": "channels"}
        view_base = _TAB_ALIAS.get(view_base, view_base)
        for btn_id, tab_view in self._NAV_MAP.items():
            try:
                btn = self.query_one(f"#{btn_id}", Button)
                btn.variant = "primary" if tab_view == view_base else "default"
            except Exception:
                pass

        if view == "sync":
            content.display = True
            manage_list.display = True
            try:
                self.query_one("#sync-buttons", Horizontal).display = True
                scanned = hasattr(self, '_sync_scan_data') and self._sync_scan_data
                self.query_one("#btn-sync-start", Button).disabled = not scanned
            except Exception:
                pass
            content.update(self._render_sync_view())
            self._update_sync_list()
        elif view == "overview":
            content.display = True
            content.update(self._render_overview())
        elif view == "agents":
            agent_list.display = True
            content.display = False
            self._update_agent_list()
        elif view.startswith("agent:"):
            content.display = True
            content.update(self._render_agent_detail(view.split(":", 1)[1]))
        elif view == "channels":
            agent_list.display = True
            content.display = False
            self._update_channel_list()
        elif view.startswith("channel:") and view.endswith(":edit"):
            # 편집 모드 — manage_list로 메시지 삭제
            ch_name = view.split(":")[1]
            content.display = True
            manage_list.display = True
            content.update(self._render_channel_edit_header(ch_name))
            self._update_channel_edit_list(ch_name)
        elif view.startswith("channel:"):
            # 기본 뷰 — 메시지 읽기
            ch_name = view.split(":", 1)[1]
            content.display = True
            content.update(self._render_channel_detail(ch_name))
        elif view == "health":
            content.display = True
            content.update(self._render_health())
        elif view == "dev":
            content.display = True
            content.update(self._render_dev())
        elif view == "logs":
            content.display = True
            content.update(self._render_logs())
        elif view.startswith("manage"):
            # 레거시 manage 뷰 → channels로 리다이렉트
            self._current_view = "channels"
            return self._refresh_all()
        elif view == "usage":
            content.display = True
            content.update(self._render_usage())
        else:
            content.display = True
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
                speaking = log_writer.is_speaking(a["id"])
                em = E_EMOJI.get(a["current_emotion"], "")
                if thinking:
                    icon = "🧠"
                elif speaking:
                    icon = "💬"
                elif a["status"] == "active":
                    icon = "🟢"
                else:
                    icon = "⚪"
                type_map = {"mgr": "MGR", "creator": "CRT", "persona": ""}
                type_str = type_map.get(a.get("type", ""), "")
                type_badge = f" [dim]({type_str})[/dim]" if type_str else ""
                emotion = a.get('current_emotion', '')
                label = f"  {icon} [{c} bold]{a['name']}[/{c} bold]{type_badge}  {em} [dim]{emotion}[/dim]"
                agent_list.add_option(Option(label, id=a["id"]))

    def _update_channel_list(self):
        """채널 OptionList 갱신 (agent-list 재활용)"""
        agent_list = self.query_one("#agent-list", OptionList)
        agent_list.clear_options()

        # DB 채널 + 시스템 채널 + 스캔 데이터 병합
        ch_data = {ch["channel"]: ch for ch in _cache.channels}

        # 시스템 채널 (대화 없어도 표시)
        for a in _cache.all_agents.values():
            if a["type"] == "mgr":
                for sys_ch in ["mgr-dashboard", "mgr-system-log"]:
                    if sys_ch not in ch_data:
                        ch_data[sys_ch] = {"channel": sys_ch, "msg_count": 0, "last_active": None}
            elif a["type"] == "creator":
                if "mgr-creator" not in ch_data:
                    ch_data["mgr-creator"] = {"channel": "mgr-creator", "msg_count": 0, "last_active": None}
            else:
                dm_ch = f"dm-{a['name']}"
                if dm_ch not in ch_data:
                    ch_data[dm_ch] = {"channel": dm_ch, "msg_count": 0, "last_active": None}

        # 관계 기반 internal 채널 (대화 있는 것만 표시)
        conn = db.get_conn()
        rels = [dict(r) for r in conn.execute("SELECT * FROM relationships").fetchall()]
        conn.close()
        for r in rels:
            a_agent = _cache.all_agents.get(r["agent_a"])
            b_agent = _cache.all_agents.get(r["agent_b"])
            if a_agent and b_agent:
                for ch_name in [
                    f"internal-dm-{a_agent['name']}-{b_agent['name']}",
                    f"internal-dm-{b_agent['name']}-{a_agent['name']}",
                ]:
                    if ch_name not in ch_data:
                        cnt = db.get_recent_messages(ch_name, limit=1)
                        if cnt:  # 대화 있는 것만
                            ch_data[ch_name] = {
                                "channel": ch_name,
                                "msg_count": len(cnt),
                                "last_active": cnt[0]["timestamp"] if cnt[0]["timestamp"] else None,
                            }
                            break

        # Sync 스캔 데이터가 있으면 포함 (디코에만 있는 채널)
        scan_data = getattr(self, '_sync_scan_data', None)
        if scan_data:
            for ch_name, count in scan_data.items():
                if ch_name not in ch_data:
                    ch_data[ch_name] = {"channel": ch_name, "msg_count": 0, "last_active": None}

        all_channels = list(ch_data.values())
        dm, group, internal, mgr = _classify_channels(all_channels)
        for label, icon, chs, clr in [
            ("Manager", "📋", mgr, "blue"),
            ("DM", "💬", dm, "cyan"),
            ("Group", "👥", group, "green"),
            ("Internal", "🔒", internal, "yellow"),
        ]:
            if not chs:
                continue
            agent_list.add_option(Option(f"  [{clr} bold]{icon} {label} ({len(chs)})[/{clr} bold]"))
            for ch in chs:
                active = _channel_is_active(_cache.channels, ch["channel"])
                dot = "[green]●[/green]" if active else "[dim]○[/dim]"
                ts = ch["last_active"][11:16] if ch["last_active"] else ""
                cnt = ch["msg_count"]
                # 참가자 표시
                parts = ch.get("participants", [])
                if parts:
                    part_names = []
                    for pid in parts:
                        agent = _cache.all_agents.get(pid)
                        if agent:
                            part_names.append(agent["name"])
                        elif pid == get_user_id():
                            part_names.append(get_user_name())
                    members = ", ".join(part_names) if part_names else ""
                    members_str = f"  [dim]({members})[/dim]" if members else ""
                else:
                    members_str = ""
                agent_list.add_option(Option(
                    f"    {dot} {ch['channel']}{members_str}  [dim]{cnt}건  {ts}[/dim]",
                    id=f"ch:{ch['channel']}",
                ))

    def _update_status_bar(self):
        bot = _is_bot_running()
        dev = log_writer.is_dev_active()
        thinking = [a for a in _cache.all_agents.values()
                    if log_writer.is_thinking(a["id"])]
        speaking_list = [a for a in _cache.all_agents.values()
                        if log_writer.is_speaking(a["id"])]
        total = len(_cache.all_agents)
        now = datetime.now().strftime("%H:%M:%S")

        bot_s = "[green bold]● Running[/green bold]" if bot else "[red bold]● Stopped[/red bold]"
        dev_s = "[bright_yellow bold]🔧 Dev[/bright_yellow bold]" if dev else ""
        think_s = f"[bright_yellow]🧠 {len(thinking)}[/bright_yellow]" if thinking else ""
        speak_s = f"[bright_cyan]💬 {len(speaking_list)}[/bright_cyan]" if speaking_list else ""

        parts = [
            f"[bright_magenta bold]◈ Glimi[/bright_magenta bold]",
            bot_s,
            f"[dim]{now}[/dim]",
            f"Agents: [cyan]{total}[/cyan]",
            f"Messages: [dim]{_cache.total:,}[/dim]",
        ]
        if think_s:
            parts.append(think_s)
        if speak_s:
            parts.append(speak_s)
        if dev_s:
            parts.append(dev_s)

        self.query_one("#status-bar", Static).update(
            Text.from_markup("  │  ".join(parts))
        )

    # ── Render: Overview ────────────────────────────────

    def _render_agent_card(self, agent, expanded=False):
        """에이전트 카드"""
        aid = agent["id"]
        c = _get_color(aid)
        thinking = log_writer.is_thinking(aid)
        speaking = log_writer.is_speaking(aid)
        em = E_EMOJI.get(agent["current_emotion"], "")
        sec = _seconds_since(agent.get("last_active"))
        type_map = {"mgr": "Mgr", "creator": "Cre", "persona": "Per"}
        type_str = type_map.get(agent.get("type", ""), "")
        agent_type = agent.get("type", "persona")
        ch_name = "mgr-dashboard" if agent_type == "mgr" else f"dm-{agent['name']}"

        if (thinking or speaking) and expanded:
            # ── 확장 카드 (추론/전송 중, 상단 배치) ──
            if thinking:
                active_sec = log_writer.thinking_seconds(aid)
                state_label = "[bright_yellow bold]🧠 THINKING[/bright_yellow bold]"
                border_color = "bright_yellow"
            else:
                active_sec = log_writer.speaking_seconds(aid)
                state_label = "[bright_cyan bold]💬 SPEAKING[/bright_cyan bold]"
                border_color = "bright_cyan"
            elapsed = f"{int(active_sec//60)}:{int(active_sec%60):02d}" if active_sec >= 60 else f"{int(active_sec)}s"
            bar_len = 30
            filled = int(active_sec % bar_len)
            progress = "".join("▓" if i == filled else "░" for i in range(bar_len))

            lines = [
                f"  {state_label}  {elapsed}  {em} {agent['current_emotion']}  {type_str}",
                f"  [{c}]{progress}[/{c}]",
            ]

            # 추론 로그 (thinking일 때만)
            if thinking:
                sys_log_path = os.path.join(log_writer.get_log_dir(), "system.log")
                all_sys = log_writer.tail(sys_log_path, 50)
                t_lines = [l for l in all_sys if f"[{aid}]" in l]
                if t_lines:
                    lines.append(f"  {'─' * 50}")
                    for l in t_lines[-4:]:
                        lines.append(f"  [dim]{_trunc(l, 70)}[/dim]")

            # Recent Chat (CMD/QUERY/ACTION 제외)
            recent = [m for m in db.get_recent_messages(ch_name, limit=10)
                      if not _re.search(r'\[(?:CMD|QUERY|ACTION):', m["message"] or "")][-3:]
            if recent:
                lines.append(f"  {'─' * 50}")
                for r in recent:
                    speaker = get_user_name() if r["speaker"] == get_user_id() else agent["name"]
                    lines.append(f"  [{c}]{speaker}[/{c}]: {_trunc(r['message'], 55)}")

            return Panel(
                "\n".join(lines),
                title=f" [{c} bold]{agent['name']}[/{c} bold] ",
                subtitle=f"[{border_color}] ● {elapsed} [/{border_color}]",
                border_style=border_color, box=box.HEAVY, padding=(0, 1),
            )
        else:
            # ── 컴팩트 카드 (고정 크기) ──
            status = "[green]●[/green]" if agent["status"] == "active" else "[dim]○[/dim]"

            if thinking:
                think_sec = log_writer.thinking_seconds(aid)
                elapsed = f"{int(think_sec)}s"
                line1 = f"  {status} {em}  [bright_yellow]🧠{elapsed}[/bright_yellow]  {type_str}"
            elif speaking:
                speak_sec = log_writer.speaking_seconds(aid)
                elapsed = f"{int(speak_sec)}s"
                line1 = f"  {status} {em}  [bright_cyan]💬{elapsed}[/bright_cyan]  {type_str}"
            else:
                line1 = f"  {status} {em} {agent['current_emotion'][:4]}  {type_str}  [dim]{_ago(sec)}[/dim]"

            # 마지막 메시지
            recent = db.get_recent_messages(ch_name, limit=1)
            if recent:
                r = recent[-1]
                speaker = get_user_name() if r["speaker"] == get_user_id() else agent["name"]
                line2 = f"  [dim]{speaker}: {_trunc(r['message'], 30)}[/dim]"
            else:
                line2 = f"  [dim]No messages[/dim]"

            border = "bright_yellow" if thinking else "bright_cyan" if speaking else (c if agent["status"] == "active" else "dim")
            return Panel(
                f"{line1}\n{line2}",
                title=f" [{c}]{agent['name']}[/{c}] ",
                border_style=border, box=box.ROUNDED, padding=(0, 0),
            )

    def _render_overview(self):
        items = []
        agents = list(_cache.all_agents.values())

        if not agents:
            return Panel(
                "[dim]No agents.\nInitialize DB from Wizard.[/dim]",
                border_style="yellow", box=box.ROUNDED, padding=(1, 2),
            )

        thinking = [a for a in agents if log_writer.is_thinking(a["id"])]
        speaking_agents = [a for a in agents
                          if not log_writer.is_thinking(a["id"]) and log_writer.is_speaking(a["id"])]
        idle = [a for a in agents
                if not log_writer.is_thinking(a["id"]) and not log_writer.is_speaking(a["id"])]

        # 추론 중 — 확장 카드 (2열 분할)
        if thinking:
            if len(thinking) == 1:
                items.append(self._render_agent_card(thinking[0], expanded=True))
            else:
                row = []
                for a in thinking:
                    row.append(self._render_agent_card(a, expanded=True))
                    if len(row) == 2:
                        items.append(Columns(row, equal=True, expand=True))
                        row = []
                if row:
                    items.append(Columns(row, equal=True, expand=True))

        # Speaking 에이전트 — 확장 카드
        if speaking_agents:
            if len(speaking_agents) == 1:
                items.append(self._render_agent_card(speaking_agents[0], expanded=True))
            else:
                row = []
                for a in speaking_agents:
                    row.append(self._render_agent_card(a, expanded=True))
                    if len(row) == 2:
                        items.append(Columns(row, equal=True, expand=True))
                        row = []
                if row:
                    items.append(Columns(row, equal=True, expand=True))

        # 나머지 — 컴팩트 카드 3열
        if idle:
            row = []
            for a in idle:
                row.append(self._render_agent_card(a))
                if len(row) == 3:
                    items.append(Columns(row, equal=True, expand=True))
                    row = []
            if row:
                # 빈 자리 채우기 (균일 크기)
                while len(row) < 3:
                    row.append(Text(""))
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
        ch_summary = "  │  ".join(ch_lines) if ch_lines else "[dim]No channels[/dim]"
        items.append(Panel(ch_summary, border_style="dim", box=box.ROUNDED, padding=(0, 1)))

        # Recent Chat (CMD/QUERY/ACTION 태그 포함 메시지 제외)
        _cmd_re = _re.compile(r'\[(?:CMD|QUERY|ACTION):')
        chat_lines = []
        for r in (_cache.messages[-20:] if _cache.messages else []):
            if _cmd_re.search(r["message"] or ""):
                continue
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
            if len(chat_lines) >= 10:
                break

        chat_content = "\n".join(chat_lines) if chat_lines else "[dim]No messages[/dim]"
        items.append(Panel(
            chat_content, title="[bold]💬 Recent Chat[/bold]",
            border_style="dim", box=box.ROUNDED, padding=(0, 1),
        ))

        # 시스템 로그 (supervisor 로그 제외)
        sys_log = os.path.join(log_writer.get_log_dir(), "system.log")
        log_lines = [l for l in log_writer.tail(sys_log, 15) if "[sup:" not in l][-6:]
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
        speaking = log_writer.is_speaking(agent_id)
        sec = _seconds_since(agent.get("last_active"))
        items = []

        # ── 프로필 정보 ──
        info_lines = []
        type_map = {"mgr": "Manager", "creator": "Creator", "persona": "Persona"}
        if thinking:
            status_str = "[bright_yellow]🧠 Thinking[/bright_yellow]"
        elif speaking:
            status_str = "[bright_cyan]💬 Speaking[/bright_cyan]"
        elif agent["status"] == "active":
            status_str = "[green]● Active[/green]"
        else:
            status_str = f"[dim]{agent['status']}[/dim]"

        info_lines.append(f"{status_str}  │  {em} {agent['current_emotion']} ({agent.get('emotion_intensity', 0)}/10)  │  [dim]{_ago(sec)}[/dim]")
        info_lines.append(f"[dim]{agent_id} · {type_map.get(agent.get('type', ''), '')}[/dim]")

        if profile:
            parts = []
            if profile.get("age"):
                parts.append(f"{profile['age']}y/o")
            if profile.get("mbti"):
                parts.append(profile["mbti"])
            if profile.get("enneagram"):
                parts.append(profile["enneagram"])
            if parts:
                info_lines.append("  ".join(parts))

            traits = profile.get("personality", {}).get("traits", [])
            if traits:
                info_lines.append(f"[bold]Personality:[/bold] {' · '.join(traits[:5])}")

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
                info_lines.append(f"[bold]Relationships:[/bold] {' · '.join(rel_parts)}")

        items.append(Panel(
            "\n".join(info_lines),
            title=f"[{c} bold]{agent['name']}[/{c} bold]",
            border_style=c, box=box.ROUNDED, padding=(1, 2),
        ))

        # ── 추론 로그 (raw) ──
        sys_log_path = os.path.join(log_writer.get_log_dir(), "system.log")
        all_sys = log_writer.tail(sys_log_path, 200)
        thinking_lines = [l for l in all_sys if f"[{agent_id}]" in l]
        thinking_content = "\n".join(thinking_lines[-20:]) if thinking_lines else "[dim]추론 No logs[/dim]"
        thinking_title = "[bold]🧠 추론 로그[/bold]"
        if thinking:
            thinking_title += "  [bright_yellow]● LIVE[/bright_yellow]"
        items.append(Panel(
            thinking_content, title=thinking_title,
            border_style="bright_yellow" if thinking else "dim",
            box=box.ROUNDED, padding=(0, 1),
        ))

        # ── 관계 점수 ──
        rels_db = db.get_all_relationships(agent_id)
        if rels_db:
            rel_lines = []
            for r in rels_db:
                other_id = r["agent_b"] if r["agent_a"] == agent_id else r["agent_a"]
                other = _cache.all_agents.get(other_id)
                other_name = other["name"] if other else other_id
                oc = _get_color(other_id)
                intimacy = r.get("intimacy_score", 50)
                bar = "".join("█" if i < intimacy // 10 else "░" for i in range(10))
                dynamics = r.get("dynamics", "")
                rel_lines.append(
                    f"  [{oc}]{other_name}[/{oc}]  {r.get('type', '?')}  "
                    f"[cyan]{bar}[/cyan] {intimacy}"
                    f"{'  [dim]' + _trunc(dynamics, 30) + '[/dim]' if dynamics else ''}"
                )
            items.append(Panel(
                "\n".join(rel_lines),
                title=f"[bold]💕 관계[/bold]  [dim]({len(rels_db)}items)[/dim]",
                border_style="bright_magenta", box=box.ROUNDED, padding=(0, 1),
            ))

        # ── 메모리 (채널별 전체) ──
        items.append(Text.from_markup("\n[bold magenta]━━ 🧠 Memory ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold magenta]"))
        conn = db.get_conn()
        memories = [dict(r) for r in conn.execute(
            "SELECT * FROM memories WHERE agent_id = ? ORDER BY channel, level DESC, id DESC",
            (agent_id,)
        ).fetchall()]
        conn.close()

        if memories:
            mem_by_channel = {}
            for m in memories:
                ch = m["channel"] or "general"
                if ch not in mem_by_channel:
                    mem_by_channel[ch] = []
                mem_by_channel[ch].append(m)

            for ch, mems in mem_by_channel.items():
                if ch.startswith("dm-"):
                    ch_icon, ch_clr = "💬", "cyan"
                elif ch.startswith("internal-"):
                    ch_icon, ch_clr = "🔒", "yellow"
                elif ch.startswith("group-"):
                    ch_icon, ch_clr = "👥", "green"
                elif ch.startswith("mgr"):
                    ch_icon, ch_clr = "📋", "blue"
                else:
                    ch_icon, ch_clr = "📝", "dim"

                mem_lines = []
                for m in mems:
                    level_tag = f"[magenta]L{m['level']}[/magenta]" if m["level"] == 2 else f"[cyan]L{m['level']}[/cyan]"
                    ts = m["created_at"][:16] if m.get("created_at") else ""
                    mem_lines.append(f"  {level_tag} [dim]{ts}[/dim]")
                    mem_lines.append(f"    {m['content']}")
                    mem_lines.append("")

                items.append(Panel(
                    "\n".join(mem_lines).rstrip(),
                    title=f"[bold]🧠 {ch_icon} {ch}[/bold]  [dim]({len(mems)}items)[/dim]",
                    border_style=ch_clr, box=box.ROUNDED, padding=(0, 1),
                ))
        else:
            items.append(Panel(
                "[dim]No memories[/dim]",
                title="[bold]🧠 메모리[/bold]",
                border_style="dim", box=box.ROUNDED, padding=(0, 1),
            ))

        # ── 채팅 로그 ──
        items.append(Text.from_markup("\n[bold cyan]━━ 💬 Chat Logs ━━━━━━━━━━━━━━━━━━━━━━━━━━━━[/bold cyan]"))
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
            if agent_name in ch_name:
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

        chat_content = "\n".join(chat_lines) if chat_lines else "[dim]No messages[/dim]"
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
            items.append(Panel("[dim]No channels[/dim]", border_style="dim", box=box.ROUNDED))

        return Group(*items)

    # ── Render: Channel Detail ──────────────────────────

    def _get_channel_style(self, ch_name):
        if ch_name.startswith("dm-"):
            return "cyan", "💬"
        elif ch_name.startswith("group-"):
            return "green", "👥"
        elif ch_name.startswith("internal-"):
            return "yellow", "🔒"
        else:
            return "blue", "📋"

    def _render_channel_detail(self, channel_name):
        active = _channel_is_active(_cache.channels, channel_name)
        active_s = "  [green bold]● Active[/green bold]" if active else ""
        color, icon = self._get_channel_style(channel_name)

        # 전체 메시지
        conn = db.get_conn()
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM conversations WHERE channel=? ORDER BY timestamp ASC",
            (channel_name,)
        ).fetchall()]
        conn.close()

        lines = []
        for r in rows:
            sid = r["speaker"]
            c = _get_color(sid) if sid != get_user_id() else "bright_green"
            ts = r["timestamp"][11:16] if r["timestamp"] else ""
            name = _speaker_name(sid)
            lines.append(f"[dim]{ts}[/dim] [{c} bold]{name}[/{c} bold]: {r['message']}")

        content = "\n".join(lines) if lines else "[dim]No messages[/dim]"

        # 참가자 표시
        parts = db.get_channel_participants(channel_name)
        part_names = []
        for pid in parts:
            agent = _cache.all_agents.get(pid)
            if agent:
                part_names.append(agent["name"])
            elif pid == get_user_id():
                part_names.append(get_user_name())
        members_info = f"  [dim]Participants: {', '.join(part_names)}[/dim]" if part_names else ""

        items = []
        items.append(Panel(
            content,
            title=f"[bold]{icon} {channel_name}[/bold]{active_s}{members_info}  [dim]({len(rows)}items)[/dim]",
            subtitle="[dim]ESC 뒤로  │  e 편집모드[/dim]",
            border_style=color, box=box.ROUNDED, padding=(0, 1),
        ))

        return Group(*items)

    def _render_channel_edit_header(self, ch_name):
        """편집 모드 헤더"""
        color, icon = self._get_channel_style(ch_name)
        conn = db.get_conn()
        count = conn.execute("SELECT COUNT(*) FROM conversations WHERE channel=?", (ch_name,)).fetchone()[0]
        conn.close()
        return Panel(
            f"[bold]{icon} {ch_name}[/bold]  │  {count}건  │  [red bold]편집 모드[/red bold]\n\n"
            f"[dim]메시지 선택 → Enter로 삭제 (Trash 보관)[/dim]\n"
            f"[dim]ESC로 뷰 모드 복귀[/dim]",
            border_style="red", box=box.ROUNDED, padding=(1, 2),
        )

    def _update_channel_edit_list(self, ch_name):
        """편집 모드 — 메시지 삭제 목록"""
        manage_list = self.query_one("#manage-list", OptionList)
        manage_list.clear_options()

        color, icon = self._get_channel_style(ch_name)

        # 채널 액션
        manage_list.add_option(Option(
            f"  [red bold]🗑 채널 전체 삭제[/red bold]  [dim](DB + Discord)[/dim]",
            id=f"del_ch:{ch_name}",
        ))
        manage_list.add_option(Option(
            f"  [yellow bold]🧹 메시지 전체 삭제[/yellow bold]  [dim](DB만, 채널 유지)[/dim]",
            id=f"clear_ch:{ch_name}",
        ))
        manage_list.add_option(None)

        # 전체 메시지
        conn = db.get_conn()
        all_msgs = [dict(r) for r in conn.execute(
            "SELECT * FROM conversations WHERE channel=? ORDER BY timestamp ASC",
            (ch_name,)
        ).fetchall()]
        conn.close()

        for r in all_msgs:
            msg_id = r.get("id", "")
            sid = r["speaker"]
            c = _get_color(sid) if sid != get_user_id() else "bright_green"
            name = get_user_name() if sid == get_user_id() else _speaker_name(sid)
            msg = _trunc(r["message"], 50)
            ts = r["timestamp"][11:16] if r["timestamp"] else ""
            manage_list.add_option(Option(
                f"  [dim]#{msg_id}[/dim] [dim]{ts}[/dim] [{c}]{name}[/{c}]: {msg}",
                id=f"del_msg:{ch_name}:{msg_id}",
            ))

        # Trash 바로가기
        trash_count = len(db.trash_list())
        if trash_count:
            manage_list.add_option(None)
            manage_list.add_option(Option(
                f"  [yellow]🗑 Trash[/yellow]  [dim]({trash_count}items)[/dim]",
                id="trash_view",
            ))

        manage_list.add_option(None)
        manage_list.add_option(Option(
            f"  [dim]← 뷰 모드로[/dim]",
            id=f"back_channel_view:{ch_name}",
        ))

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
        log_content = "\n".join(log_lines) if log_lines else "[dim]시스템 No logs[/dim]"
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
        content = "\n".join(dev_lines[-30:]) if dev_lines else "[dim]개발 No logs[/dim]"
        return Panel(
            content,
            title=f"[bold]🔧 Dev Runner (Opus)[/bold]  │  {status}",
            border_style="bright_yellow" if active else "dim",
            box=box.ROUNDED, padding=(1, 2),
        )

    # ── Render: Logs ────────────────────────────────────

    # ── Render: Usage ─────────────────────────────────

    def _render_usage(self):
        """AI 사용량 대시보드"""
        from datetime import timedelta
        from src.core.runtime import CLAUDE_AVAILABLE, AGENT_MODELS
        items = []

        # ── Claude 상태 ──
        status = "[green]● Connected[/green]" if CLAUDE_AVAILABLE else "[red]● Disconnected[/red]"
        model = AGENT_MODELS.get("persona", "?")

        # 추론 통계 (system.log 기반)
        sys_log = os.path.join(log_writer.get_log_dir(), "system.log")
        all_lines = log_writer.tail(sys_log, 1000)

        today_str = datetime.now().strftime("%Y-%m-%d")
        today_inferences = sum(1 for l in all_lines if "응답" in l)
        thinking_logs = [l for l in all_lines if "추론" in l or "응답" in l]

        # DB 통계
        conn = db.get_conn()
        total_msgs = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        today_msgs = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE timestamp LIKE ?", (f"{today_str}%",)
        ).fetchone()[0]
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        week_msgs = conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE timestamp >= ?", (week_ago,)
        ).fetchone()[0]

        # 에이전트별 오늘 추론 수
        today_agent = conn.execute("""
            SELECT speaker, COUNT(*) as cnt FROM conversations
            WHERE speaker LIKE 'agent-%' AND timestamp LIKE ?
            GROUP BY speaker ORDER BY cnt DESC
        """, (f"{today_str}%",)).fetchall()
        conn.close()

        # 세션 사용량 (현재 실행 이후)
        # Claude Code Max: 세션 45분, 주간 한도
        claude_lines = [
            f"  {status}  │  모델: [cyan]{model}[/cyan]  │  플랜: Claude Code Max",
            "",
            f"  [bold]현재 세션[/bold]",
            f"    추론 요청: [cyan]{today_inferences}[/cyan]건",
            f"    [dim]세션 한도는 Claude Code에서 확인[/dim]",
            "",
            f"  [bold]메시지 통계[/bold]",
            f"    오늘: [cyan]{today_msgs}[/cyan]건  │  주간: [cyan]{week_msgs}[/cyan]건  │  전체: [dim]{total_msgs:,}[/dim]건",
        ]

        if today_agent:
            claude_lines.append("")
            claude_lines.append(f"  [bold]Today by agent[/bold]")
            for row in today_agent[:5]:
                aid = row[0]
                cnt = row[1]
                agent = _cache.all_agents.get(aid)
                name = agent["name"] if agent else aid
                c = _get_color(aid)
                bar = "█" * min(cnt, 20) + "░" * max(0, 20 - cnt)
                claude_lines.append(f"    [{c}]{name:<8}[/{c}] {bar} {cnt}")

        items.append(Panel(
            "\n".join(claude_lines),
            title="[bold blue]☁ Claude[/bold blue]",
            border_style="blue", box=box.ROUNDED, padding=(1, 2),
        ))

        # ── 다른 AI (향후) ──
        other_lines = [
            "  [dim]GPT-4o[/dim]      [dim]미연결  │  연동 예정[/dim]",
            "  [dim]Gemini[/dim]      [dim]미연결  │  연동 예정[/dim]",
            "  [dim]Local LLM[/dim]   [dim]미연결  │  Ollama 등 연동 예정[/dim]",
        ]
        items.append(Panel(
            "\n".join(other_lines),
            title="[dim]Other AI Providers[/dim]",
            border_style="dim", box=box.ROUNDED, padding=(0, 1),
        ))

        return Group(*items)

    def _render_logs(self):
        sys_log = os.path.join(log_writer.get_log_dir(), "system.log")
        log_lines = log_writer.tail(sys_log, 40)
        content = "\n".join(log_lines) if log_lines else "[dim]No logs[/dim]"
        return Panel(
            content,
            title="[bold]📋 System Logs[/bold]",
            border_style="dim", box=box.ROUNDED, padding=(1, 2),
        )

    # ── Render: Manage (DB 관리) ──────────────────────────

    def _render_manage(self):
        view = self._current_view
        items = []

        trash_count = len(db.trash_list())
        trash_str = f"  [dim]({trash_count}items)[/dim]" if trash_count else ""

        if view == "manage":
            items.append(Panel(
                "[bold]DB 관리[/bold]\n\n"
                "채널 목록에서 선택 → Enter로 메시지 관리\n"
                f"[dim]삭제 데이터는 Trash에 보관됩니다{trash_str}[/dim]",
                border_style="cyan", box=box.ROUNDED, padding=(1, 2),
            ))
        elif view.startswith("manage:channel:"):
            ch_name = view.split(":", 2)[2]
            items.append(self._render_manage_channel(ch_name))
        elif view == "manage:trash":
            items.append(self._render_trash())

        return Group(*items) if items else Text("[dim]관리 메뉴[/dim]")

    def _render_manage_channel(self, ch_name):
        """채널 관리 — 안내만 (메시지는 manage-list에서 조작)"""
        conn = db.get_conn()
        count = conn.execute("SELECT COUNT(*) FROM conversations WHERE channel=?", (ch_name,)).fetchone()[0]
        conn.close()

        if ch_name.startswith("dm-"):
            color, icon = "cyan", "💬"
        elif ch_name.startswith("group-"):
            color, icon = "green", "👥"
        elif ch_name.startswith("internal-"):
            color, icon = "yellow", "🔒"
        else:
            color, icon = "blue", "📋"

        return Panel(
            f"[bold]{icon} {ch_name}[/bold]  │  {count}건\n\n"
            f"[dim]아래 목록에서 메시지를 선택하여 삭제 (Enter)[/dim]\n"
            f"[dim]삭제된 데이터는 Trash에 보관됩니다[/dim]",
            border_style=color, box=box.ROUNDED, padding=(1, 2),
        )

    def _render_trash(self):
        """Trash 뷰"""
        items = db.trash_list()
        if not items:
            return Panel("[dim]Trash is empty.[/dim]", title="[bold]🗑 Trash[/bold]",
                         border_style="dim", box=box.ROUNDED, padding=(1, 2))
        lines = []
        for t in items:
            lines.append(
                f"[dim]#{t['id']}[/dim]  [{t['item_type']}]  "
                f"{t.get('channel', '?')}  "
                f"[dim]{t['deleted_at'][:16]}[/dim]"
            )
        return Panel(
            "\n".join(lines),
            title=f"[bold]🗑 Trash[/bold]  [dim]({len(items)}items)[/dim]",
            border_style="yellow", box=box.ROUNDED, padding=(1, 2),
        )

    def _update_manage_list(self):
        """Manage 뷰의 OptionList 갱신"""
        manage_list = self.query_one("#manage-list", OptionList)
        view = self._current_view

        if view == "manage":
            channels = db.get_channel_overview()
            manage_list.clear_options()

            # Trash 바로가기
            trash_count = len(db.trash_list())
            if trash_count:
                manage_list.add_option(Option(
                    f"  [yellow]🗑 Trash[/yellow]  [dim]({trash_count}items)[/dim]",
                    id="trash_view",
                ))
                manage_list.add_option(None)

            for ch in channels:
                name = ch["channel"]
                cnt = ch["msg_count"]
                if name.startswith("dm-"):
                    icon = "💬"
                elif name.startswith("group-"):
                    icon = "👥"
                elif name.startswith("internal-"):
                    icon = "🔒"
                else:
                    icon = "📋"
                manage_list.add_option(Option(
                    f"  {icon} {name}  [dim]({cnt}items)[/dim]",
                    id=f"ch:{name}",
                ))
        elif view.startswith("manage:channel:"):
            ch_name = view.split(":", 2)[2]
            manage_list.clear_options()

            # 채널 액션
            manage_list.add_option(Option(
                "  [red bold]🗑 채널 전체 삭제[/red bold]  [dim](DB + Discord)[/dim]",
                id=f"del_ch:{ch_name}",
            ))
            manage_list.add_option(Option(
                "  [yellow bold]🧹 메시지 전체 삭제[/yellow bold]  [dim](DB만, 채널 유지)[/dim]",
                id=f"clear_ch:{ch_name}",
            ))
            manage_list.add_option(None)

            # 전체 메시지 (limit 늘림)
            conn = db.get_conn()
            all_msgs = conn.execute(
                "SELECT * FROM conversations WHERE channel=? ORDER BY timestamp ASC",
                (ch_name,)
            ).fetchall()
            conn.close()

            for r in all_msgs:
                r = dict(r)
                msg_id = r.get("id", "")
                sid = r["speaker"]
                c = _get_color(sid) if sid != get_user_id() else "bright_green"
                name = get_user_name() if sid == get_user_id() else _speaker_name(sid)
                msg = _trunc(r["message"], 50)
                ts = r["timestamp"][11:16] if r["timestamp"] else ""
                manage_list.add_option(Option(
                    f"  [dim]#{msg_id}[/dim] [dim]{ts}[/dim] [{c}]{name}[/{c}]: {msg}",
                    id=f"del_msg:{ch_name}:{msg_id}",
                ))

            manage_list.add_option(None)
            manage_list.add_option(Option(
                "  [dim]← 채널 목록으로[/dim]",
                id="back_manage",
            ))
        elif view == "manage:trash":
            manage_list.clear_options()
            items = db.trash_list()
            for t in items:
                manage_list.add_option(Option(
                    f"  [green]↩ 복원[/green]  #{t['id']}  [{t['item_type']}] {t.get('channel', '?')}  [dim]{t['deleted_at'][:16]}[/dim]",
                    id=f"trash_restore:{t['id']}",
                ))
            if items:
                manage_list.add_option(None)
                manage_list.add_option(Option(
                    "  [red]🗑 Trash 비우기[/red]",
                    id="trash_empty",
                ))
            manage_list.add_option(None)
            manage_list.add_option(Option(
                "  [dim]← DB 관리로[/dim]",
                id="back_manage",
            ))

    @on(OptionList.OptionSelected, "#manage-list")
    def on_manage_selected(self, event: OptionList.OptionSelected):
        oid = event.option_id
        if not oid:
            return

        if oid.startswith("back_channel_view:"):
            ch_name = oid.split(":", 1)[1]
            self._current_view = f"channel:{ch_name}"
            self._refresh_all()
        elif oid == "back_manage":
            self._current_view = "channels"
            self._refresh_all()
        elif oid.startswith("del_ch:"):
            ch_name = oid.split(":", 1)[1]
            self.app.push_screen(
                ConfirmDialog(f"[red bold]Channels deleted: {ch_name}[/red bold]\n\nDB + Discord에서 삭제됩니다.\nTrashbacked up.", danger=True),
                lambda yes, c=ch_name: self._do_delete_channel(c) if yes else None,
            )
        elif oid.startswith("clear_ch:"):
            ch_name = oid.split(":", 1)[1]
            self.app.push_screen(
                ConfirmDialog(f"[yellow bold]Delete all messages: {ch_name}[/yellow bold]\n\nChannel preserved, messages+memory deleted.\nTrashbacked up.", danger=True),
                lambda yes, c=ch_name: self._do_clear_channel(c) if yes else None,
            )
        elif oid.startswith("del_msg:"):
            parts = oid.split(":", 2)
            ch_name = parts[1]
            msg_id = parts[2]
            # 메시지 내용 가져오기
            conn = db.get_conn()
            row = conn.execute("SELECT * FROM conversations WHERE id=?", (msg_id,)).fetchone()
            conn.close()
            if row:
                row = dict(row)
                sid = row["speaker"]
                speaker = get_user_name() if sid == get_user_id() else _speaker_name(sid)
                self.app.push_screen(
                    MessageActionDialog(speaker, row["message"], msg_id, ch_name),
                    lambda action, c=ch_name, m=msg_id: self._handle_msg_action(action, c, m),
                )
        elif oid == "trash_view":
            self._current_view = "manage:trash"
            self._refresh_all()
        elif oid.startswith("trash_restore:"):
            trash_id = int(oid.split(":", 1)[1])
            result = db.trash_restore(trash_id)
            if result["ok"]:
                log_writer.system(f"[DB] Restored: {result['channel']} ({result['restored']}items)")
            _cache.refresh()
            self._current_view = "manage:trash"
            self._refresh_all()
        elif oid == "trash_empty":
            self.app.push_screen(
                ConfirmDialog("[red bold]Trash 비우기[/red bold]\n\n복원 불가능합니다.", danger=True),
                lambda yes: self._do_empty_trash() if yes else None,
            )
        elif oid == "sync_toggle_all":
            overview = db.get_channel_overview()
            all_chs = {ch["channel"] for ch in overview}
            if all_chs == self._sync_selected_channels:
                self._sync_selected_channels = set()
            else:
                self._sync_selected_channels = all_chs
            self._update_sync_list()
        elif oid.startswith("sync_ch:"):
            ch_name = oid.split(":", 1)[1]
            if ch_name in self._sync_selected_channels:
                self._sync_selected_channels.discard(ch_name)
            else:
                self._sync_selected_channels.add(ch_name)
            self._update_sync_list()

    @work(thread=True)
    def _do_delete_channel(self, ch_name):
        """채널 전체 삭제 — Trash → DB → Discord"""
        from src.core.sync import _get_token
        import time

        self.app.call_from_thread(
            lambda: self.app.push_screen(LoadingOverlay(f"Channels deleted: {ch_name}"))
        )

        # Trash으로 이동 (DB)
        count = db.trash_messages(ch_name)
        log_writer.system(f"[DB] Trash: {ch_name} ({count}items)")

        # Discord 채널 삭제
        token = _get_token()
        if token:
            import asyncio
            import discord as discord_lib

            async def _delete():
                intents = discord_lib.Intents.default()
                intents.guilds = True
                client = discord_lib.Client(intents=intents)

                @client.event
                async def on_ready():
                    for guild in client.guilds:
                        for cat in guild.categories:
                            if cat.name.startswith("glimi"):
                                for ch in cat.text_channels:
                                    if ch.name == ch_name:
                                        await ch.delete(reason="Glimi DB")
                    await client.close()

                bot_was_running = self._bot_proc and self._bot_proc.poll() is None
                if bot_was_running:
                    self._stop_bot()
                    time.sleep(2)
                try:
                    await asyncio.wait_for(client.start(token), timeout=30)
                except Exception:
                    pass
                if bot_was_running:
                    self.app.call_from_thread(self._start_bot)

            loop = asyncio.new_event_loop()
            loop.run_until_complete(_delete())
            loop.close()

        _cache.refresh()
        self.app.call_from_thread(self.app.pop_screen)
        self.app.call_from_thread(self._set_view, "channels")

    @work(thread=True)
    def _do_clear_channel(self, ch_name):
        """채널 메시지만 삭제 — Trash → DB"""
        self.app.call_from_thread(
            lambda: self.app.push_screen(LoadingOverlay(f"메시지 삭제: {ch_name}"))
        )

        count = db.trash_messages(ch_name)
        log_writer.system(f"[DB] Trash: {ch_name} 메시지 {count}건")

        _cache.refresh()
        self.app.call_from_thread(self.app.pop_screen)
        self.app.call_from_thread(self._set_view, f"channel:{ch_name}:edit")

    def _handle_msg_action(self, action: str, ch_name: str, msg_id: str):
        if action == "delete":
            self._do_delete_message(ch_name, msg_id)

    def _do_delete_message(self, ch_name, msg_id):
        """개별 메시지 삭제 — Trash"""
        db.trash_messages(ch_name, [int(msg_id)])
        log_writer.system(f"[DB] Trash: #{msg_id} ({ch_name})")
        _cache.refresh()
        self._current_view = f"channel:{ch_name}:edit"
        self._refresh_all()

    def _do_empty_trash(self):
        count = db.trash_empty()
        log_writer.system(f"[DB] Trash emptied: {count}건")
        _cache.refresh()
        self._current_view = "manage:trash"
        self._refresh_all()

    def _set_view(self, view: str):
        self._current_view = view
        self._refresh_all()

    # ── 네비게이션 액션 ─────────────────────────────────

    _NAV_MAP = {
        "nav-overview": "overview",
        "nav-agents": "agents",
        "nav-channels": "channels",
        "nav-health": "health",
        "nav-dev": "dev",
        "nav-logs": "logs",
        "nav-sync": "sync",
        "nav-usage": "usage",
    }

    def on_button_pressed(self, event: Button.Pressed):
        """클릭 또는 Enter — 모든 버튼 처리"""
        if event.button.id == "btn-sync-scan":
            self._run_sync_scan()
            return
        elif event.button.id == "btn-sync-start":
            self._start_sync()
            return
        self._handle_nav(event.button)

    @on(OptionList.OptionSelected, "#agent-list")
    def on_agent_selected(self, event: OptionList.OptionSelected):
        if not event.option_id:
            return
        oid = event.option_id
        if oid.startswith("ch:"):
            # 채널 상세
            ch_name = oid.split(":", 1)[1]
            self._current_view = f"channel:{ch_name}"
            self._refresh_all()
        else:
            # 에이전트 상세
            self._current_view = f"agent:{oid}"
            self._refresh_all()

    def action_go_back(self):
        view = self._current_view
        if view.startswith("channel:") and view.endswith(":edit"):
            # 편집 → 뷰
            ch_name = view.split(":")[1]
            self._current_view = f"channel:{ch_name}"
        elif view.startswith("channel:"):
            self._current_view = "channels"
        elif view.startswith("agent:"):
            self._current_view = "agents"
            self._refresh_all()
            self.query_one("#agent-list", OptionList).focus()
            return
        elif view.startswith("manage"):
            self._current_view = "channels"
        elif view != "overview":
            self._current_view = "overview"
        self._refresh_all()

    def action_refresh(self):
        _cache.refresh()
        self._refresh_all()

    def action_toggle_edit(self):
        """채널 뷰 ↔ 편집 모드 전환"""
        view = self._current_view
        if view.startswith("channel:") and view.endswith(":edit"):
            # 편집 → 뷰
            ch_name = view.split(":")[1]
            self._current_view = f"channel:{ch_name}"
        elif view.startswith("channel:"):
            # 뷰 → 편집
            ch_name = view.split(":", 1)[1]
            self._current_view = f"channel:{ch_name}:edit"
        self._refresh_all()

    # ── Sync ─────────────────────────────────────────────

    def _run_sync_scan(self):
        """Discord 메시지 수 스캔"""
        self._loading = LoadingOverlay("Discord 스캔 중...")
        self.app.push_screen(self._loading)
        self._do_sync_scan()

    @work(thread=True)
    def _do_sync_scan(self):
        import time
        import asyncio as _aio

        def on_progress(msg):
            try:
                self.app.call_from_thread(self._loading.update_detail, msg)
            except Exception:
                pass

        bot_was_running = self._bot_proc and self._bot_proc.poll() is None

        try:
            on_progress("봇 일시 중지...")
            if bot_was_running:
                self._stop_bot()
                time.sleep(2)

            from src.core.sync import _get_token, _fetch_all_messages
            import discord as discord_lib

            token = _get_token()
            scan_result = {}

            async def _scan():
                intents = discord_lib.Intents.default()
                intents.guilds = True
                intents.message_content = True
                client = discord_lib.Client(intents=intents)

                @client.event
                async def on_ready():
                    guild = client.guilds[0]
                    on_progress(f"서버: {guild.name}")
                    for cat in guild.categories:
                        if cat.name.startswith("glimi"):
                            for ch in cat.text_channels:
                                count = 0
                                try:
                                    async for _ in ch.history(limit=None):
                                        count += 1
                                except Exception:
                                    pass
                                scan_result[ch.name] = count
                                on_progress(f"  {ch.name}: {count}건")
                    await client.close()

                await _aio.wait_for(client.start(token), timeout=120)

            loop = _aio.new_event_loop()
            loop.run_until_complete(_scan())
            loop.close()

            self._sync_scan_data = scan_result
            on_progress(f"스캔 완료: {sum(scan_result.values())}건")

        except Exception as e:
            log_writer.error(f"[Sync Scan] {e}", e)
        finally:
            if bot_was_running:
                self.app.call_from_thread(self._start_bot)
                time.sleep(2)
            try:
                self.app.call_from_thread(self.app.pop_screen)
            except Exception:
                pass
            self.app.call_from_thread(self._set_view, "sync")

    def _start_sync(self):
        """Sync 탭에서 Start 누르면 실행 (스캔 후 + 채널 선택 필수)"""
        if not hasattr(self, '_sync_scan_data') or not self._sync_scan_data:
            return  # 스캔 안 됨

        if not self._sync_selected_channels:
            content = self.query_one("#content", Static)
            content.update(Panel(
                "[yellow]싱크할 채널을 선택하세요.[/yellow]\n[dim]전체 선택은 상단 체크박스 사용[/dim]",
                border_style="yellow", box=box.ROUNDED, padding=(1, 2),
            ))
            return

        thinking = [a for a in _cache.all_agents.values() if log_writer.is_thinking(a["id"])]
        if thinking:
            names = ", ".join(a["name"] for a in thinking)
            content = self.query_one("#content", Static)
            content.update(Panel(
                f"[yellow]추론 중: {names}[/yellow]\n[dim]추론 완료 후 시도[/dim]",
                border_style="yellow", box=box.ROUNDED, padding=(1, 2),
            ))
            return

        self._loading = LoadingOverlay("동기화 진행 중...")
        self.app.push_screen(self._loading)
        self._run_sync(self._sync_selected_channels)

    @work(thread=True)
    def _run_sync(self, channels_filter=None):
        import time
        import traceback as _tb

        def on_progress(msg):
            try:
                self.app.call_from_thread(self._loading.update_detail, msg)
            except Exception:
                pass

        bot_was_running = self._bot_proc and self._bot_proc.poll() is None
        error_msg = None
        error_detail = ""
        result = None

        try:
            on_progress("봇 일시 중지...")
            if bot_was_running:
                self._stop_bot()
                time.sleep(2)

            result = run_sync(on_progress=on_progress, channels_filter=channels_filter)

        except Exception as e:
            error_msg = str(e)
            error_detail = _tb.format_exc()
            log_writer.error(f"[Sync] 크래시: {e}", e)

        finally:
            # 항상 봇 재시작
            if bot_was_running:
                try:
                    on_progress("봇 재시작...")
                    self.app.call_from_thread(self._start_bot)
                    time.sleep(3)
                except Exception:
                    pass

            # 항상 로딩 닫기
            try:
                self.app.call_from_thread(self.app.pop_screen)
            except Exception:
                pass

        # 결과 표시
        if error_msg:
            self.app.call_from_thread(
                self._show_error_dialog, "동기화 크래시", error_msg, error_detail, "sync"
            )
        elif result and not result["ok"]:
            err = result.get("error", "알 수 없는 오류")
            detail = "\n".join(result.get("errors", [])[:10])
            self.app.call_from_thread(
                self._show_error_dialog, "동기화 실패", err, detail, "sync"
            )
        elif result:
            lines = ["[green bold]동기화 완료[/green bold]\n"]
            if result["channels_created"]:
                lines.append(f"[green]Channels created:[/green] {', '.join(result['channels_created'])}")
            if result["channels_deleted"]:
                lines.append(f"[yellow]Channels deleted:[/yellow] {', '.join(result['channels_deleted'])}")
            if result.get("categories_deleted"):
                lines.append(f"[yellow]Categories deleted:[/yellow] {', '.join(result['categories_deleted'])}")
            if result.get("messages_deleted_from_discord"):
                lines.append(f"[red]Discord messages deleted:[/red] {result['messages_deleted_from_discord']}건")
            if result.get("messages_restored"):
                lines.append(f"[green]DB→Discord Restored:[/green] +{result['messages_restored']}건")
            lines.append(f"[dim]{result.get('channels_scanned', 0)}개 채널 스캔[/dim]")
            if result.get("errors"):
                lines.append(f"\n[yellow]경고 {len(result['errors'])}건:[/yellow]")
                for e in result["errors"][:5]:
                    lines.append(f"  [dim]{e}[/dim]")
            no_change = (not result["channels_created"] and not result["channels_deleted"]
                         and not result.get("messages_deleted_from_discord")
                         and not result.get("messages_restored") and not result.get("errors"))
            if no_change:
                lines.append("\n[dim]변경 없음 — 이미 동기화 상태[/dim]")
            self.app.call_from_thread(self._show_sync_result, "\n".join(lines))

    def _show_error_dialog(self, title: str, error_msg: str, detail: str, context: str):
        """에러 다이얼로그 표시 — Auto Fix 선택 시 개발봇에 요청"""
        full_msg = f"[red]{error_msg}[/red]"
        if detail:
            full_msg += f"\n\n[yellow]상세:[/yellow]\n[dim]{detail[:1000]}[/dim]"

        def on_result(action: str):
            if action == "fix":
                self._request_auto_fix(context, error_msg, detail)

        try:
            self.app.push_screen(
                ErrorDialog(title, full_msg, f"context: {context}"),
                on_result,
            )
        except Exception:
            # 다이얼로그 실패 시 content에 직접 표시
            self._current_view = "overview"
            self._refresh_all()
            content = self.query_one("#content", Static)
            content.update(Panel(
                f"[red bold]❌ {title}[/red bold]\n\n{full_msg}",
                border_style="red", box=box.ROUNDED, padding=(1, 2),
            ))

    def _request_auto_fix(self, context: str, error_msg: str, detail: str):
        """개발봇에 자동 수정 요청"""
        import json
        from pathlib import Path

        # runtime_error.log 내용 읽기
        error_log_path = os.path.join(log_writer.get_log_dir(), "runtime_error.log")
        error_log = ""
        if os.path.exists(error_log_path):
            with open(error_log_path, "r") as f:
                error_log = f.read()[-3000:]  # 마지막 3000자

        # 개발 요청 생성
        dev_dir = os.path.join(PROJECT_ROOT, "dev")
        os.makedirs(dev_dir, exist_ok=True)
        request = {
            "description": (
                f"[자동 수정 요청] {context} 에러 수정\n\n"
                f"에러: {error_msg}\n\n"
                f"상세:\n{detail[:2000]}\n\n"
                f"runtime_error.log:\n{error_log}"
            ),
            "requested_by": "dashboard-auto-fix",
            "timestamp": datetime.now().isoformat(),
        }
        pending_path = os.path.join(dev_dir, "pending.json")
        with open(pending_path, "w", encoding="utf-8") as f:
            json.dump(request, f, ensure_ascii=False, indent=2)

        log_writer.system(f"[AutoFix] 개발 요청 생성: {context}")

        # 봇 종료 → exit(42) 시뮬레이션 → dev_runner 실행
        self._stop_bot()
        self._run_dev_runner_for_fix()

    @work(thread=True)
    def _run_dev_runner_for_fix(self):
        """개발봇 실행 후 전체 재시작"""
        import time
        log_writer.system("[AutoFix] 개발봇 실행 중...")
        self._dev_proc = subprocess.Popen(
            [_venv_python(), "-u", "-m", "src.tools.dev_runner"],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        self._dev_proc.wait()  # 완료 대기
        log_writer.system("[AutoFix] 개발봇 완료 — 재시작")
        self._dev_proc = None
        time.sleep(1)
        self.app.call_from_thread(self._do_full_restart)

    def _render_sync_view(self):
        """Sync 탭 메인 뷰"""
        if not hasattr(self, '_sync_selected_channels'):
            self._sync_selected_channels = set()

        selected = len(self._sync_selected_channels)
        scan_data = getattr(self, '_sync_scan_data', None)

        overview = db.get_channel_overview()
        total_db = sum(ch["msg_count"] for ch in overview)

        items = []

        # 상태 요약
        status_lines = [f"[bold]🔄 Discord ↔ DB Sync[/bold]", ""]

        if scan_data:
            total_discord = sum(scan_data.values())
            db_only = 0  # DB에만 있는 (Discord 누락)
            dc_only = 0  # Discord에만 있는 (DB 누락)
            synced_ch = 0

            for ch in overview:
                ch_name = ch["channel"]
                dc = scan_data.get(ch_name, 0)
                diff = ch["msg_count"] - dc
                if diff > 0:
                    db_only += diff
                elif diff < 0:
                    dc_only += -diff
                else:
                    synced_ch += 1

            status_lines.append(f"  DB: [cyan]{total_db:,}[/cyan]건  │  Discord: [cyan]{total_discord:,}[/cyan]건")
            status_lines.append("")
            if db_only > 0:
                status_lines.append(f"  [yellow]⬆ {db_only:,}건 Discord 누락[/yellow] → 싱크 시 복원")
            if dc_only > 0:
                status_lines.append(f"  [red]⬇ {dc_only:,}건 Discord 초과[/red] → 싱크 시 삭제 (DB 기준)")
            if db_only == 0 and dc_only == 0:
                status_lines.append(f"  [green]✓ 완전 동기화 상태[/green]")
            status_lines.append(f"  [dim]동기화 완료: {synced_ch}개 채널[/dim]")
        else:
            status_lines.append(f"  DB: [cyan]{total_db:,}[/cyan]건 ({len(overview)}개 채널)")
            status_lines.append(f"  Discord: [dim]? (🔍 Scan으로 확인)[/dim]")

        if selected:
            status_lines.append(f"\n  [cyan bold]선택: {selected}개 채널[/cyan bold]")

        items.append(Panel("\n".join(status_lines), border_style="cyan", box=box.ROUNDED, padding=(1, 2)))

        return Group(*items)

    def _update_sync_list(self):
        """Sync 탭 채널 목록"""
        manage_list = self.query_one("#manage-list", OptionList)
        manage_list.clear_options()

        if not hasattr(self, '_sync_selected_channels'):
            self._sync_selected_channels = set()

        scan_data = getattr(self, '_sync_scan_data', None)
        selected_count = len(self._sync_selected_channels)
        overview = db.get_channel_overview()

        # 전체 선택/해제
        all_channels = {ch["channel"] for ch in overview}
        all_selected = all_channels and all_channels == self._sync_selected_channels
        manage_list.add_option(Option(
            f"  {'[green]✓[/green]' if all_selected else '[dim]○[/dim]'}  [bold]전체 선택/해제[/bold]",
            id="sync_toggle_all",
        ))
        manage_list.add_option(None)

        overview = db.get_channel_overview()

        # 싱크 필요한 채널 먼저, 그 다음 완료
        def sort_key(ch):
            if scan_data and ch["channel"] in scan_data:
                diff = abs(ch["msg_count"] - scan_data[ch["channel"]])
                return (0 if diff > 0 else 1, -diff)
            return (0, -ch["msg_count"])

        overview.sort(key=sort_key)

        for ch in overview:
            ch_name = ch["channel"]
            db_count = ch["msg_count"]
            selected = ch_name in self._sync_selected_channels
            check = "[green]✓[/green]" if selected else "[dim]○[/dim]"

            if ch_name.startswith("dm-"):
                icon = "💬"
            elif ch_name.startswith("group-"):
                icon = "👥"
            elif ch_name.startswith("internal-"):
                icon = "🔒"
            else:
                icon = "📋"

            if scan_data and ch_name in scan_data:
                dc_count = scan_data[ch_name]
                diff = db_count - dc_count

                if diff > 0:
                    status = f"  [yellow bold]⬆{diff}건 Discord 누락[/yellow bold] → 복원"
                elif diff < 0:
                    status = f"  [red bold]⬇{-diff}건 Discord 초과[/red bold] → 삭제"
                else:
                    status = f"  [green]✓[/green]"

                count_str = f"DB:{db_count} DC:{dc_count}{status}"
            else:
                count_str = f"DB:{db_count}  [dim]DC:?[/dim]"

            manage_list.add_option(Option(
                f"  {check}  {icon} {ch_name}  {count_str}",
                id=f"sync_ch:{ch_name}",
            ))

    def _show_sync_result(self, msg: str):
        self._current_view = "sync"
        _cache.refresh()
        self._refresh_all()
        content = self.query_one("#content", Static)
        content.update(Panel(
            msg,
            title="[bold]🔄 Sync Result[/bold]",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        ))
        # 검증용 자동 재스캔
        self._run_sync_scan()

    # ── Restart / Navigation ────────────────────────────

    def _do_full_restart(self):
        """개발 완료 후 자동 전체 재시작"""
        self.action_restart()

    def action_restart(self):
        """이 커뮤니티 재시작 — 봇 + 대시보드를 재실행 (코드 변경 반영)"""
        self._stop_bot()
        if self._dev_proc and self._dev_proc.poll() is None:
            self._dev_proc.terminate()
        log_writer.system("Dashboard restart")
        cid = os.environ.get("GLIMI_COMMUNITY", "")
        py = _venv_python()
        args = [py, "-m", "src.tui.dashboard"]
        if cid:
            args.append(cid)
        os.execvp(py, args)

    def action_go_wizard(self):
        """대시보드 종료 → Switching to Wizard (봇은 유지)"""
        # 봇 프로세스는 detach — 종료하지 않음
        # start_new_session=True + DEVNULL이라 대시보드 종료해도 안 죽음
        self._bot_proc = None
        self._dev_proc = None
        log_writer.system("Switching to Wizard")
        self.app.exit(result="wizard")

    def _handle_nav(self, button: Button):
        view = self._NAV_MAP.get(button.id or "")
        if view:
            self._current_view = view
            self._refresh_all()
            # 리스트 뷰는 리스트에 포커스
            if view in ("agents", "channels"):
                self.query_one("#agent-list", OptionList).focus()
        elif button.id == "nav-back":
            self.action_go_back()
        elif button.id == "nav-refresh":
            self.action_refresh()
        elif button.id == "nav-restart":
            self.action_restart()
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

class GlimiDashboard(App):
    CSS = DASHBOARD_CSS
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
    ]

    def on_mount(self):
        cid = os.environ.get("GLIMI_COMMUNITY", "default")
        self.title = f"Project Glimi — {cid}"
        self.sub_title = ""
        self.push_screen(DashboardScreen())


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Glimi Dashboard")
    parser.add_argument("community_id", nargs="?", help="커뮤니티 ID")
    args = parser.parse_args()

    # 환경변수를 먼저 설정 (다른 모듈이 import 시 참조)
    if args.community_id:
        os.environ["GLIMI_COMMUNITY"] = args.community_id

    # community 모듈의 캐시된 값 강제 갱신
    from src import community
    if args.community_id:
        community.set_community(args.community_id)

    try:
        result = GlimiDashboard().run()
    except KeyboardInterrupt:
        print("\nDashboard interrupted.")
        sys.exit(0)
    except Exception as e:
        import traceback
        try:
            log_writer.error(f"[Dashboard] crash: {e}", e)
        except Exception:
            pass
        traceback.print_exc()
        sys.exit(1)

    if result == "wizard":
        py = _venv_python()
        os.execvp(py, [py, "-m", "src.tui.wizard"])


if __name__ == "__main__":
    main()
