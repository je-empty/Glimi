#!/usr/bin/env python3
"""
Project Glimi — Community Wizard (Textual TUI)

커뮤니티 생성/관리/삭제, 봇 토큰 설정, 프로세스 관리,
디스코드 채널 정리, 커뮤니티 내보내기/가져오기를 통합 관리.

실행: python -m src.tui.wizard
"""
import asyncio
import json
import os
import shutil
import signal
import sqlite3
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import discord as discord_lib
from dotenv import set_key
from rich.text import Text
from rich import box
from rich.table import Table as RichTable
from rich.panel import Panel as RichPanel

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import Screen, ModalScreen
from textual.widgets import (
    Static, OptionList, Input, Header, Footer, Label,
    Button, Rule, LoadingIndicator,
)
from textual.widgets.option_list import Option

from src import community
from src.tui.components import LoadingOverlay, ConfirmDialog

PROJECT_ROOT = Path(__file__).parent.parent.parent


def _venv_python() -> str:
    """프로젝트 venv의 Python 경로"""
    venv = PROJECT_ROOT / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


# ══════════════════════════════════════════════════════════
# 유틸리티 (순수 함수 — UI 의존 없음)
# ══════════════════════════════════════════════════════════

def _get_token(community_id: str) -> Optional[str]:
    env_path = community.COMMUNITIES_DIR / community_id / ".env"
    if not env_path.exists():
        return None
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line.startswith("DISCORD_BOT_TOKEN=") and not line.startswith("#"):
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                return val if val and val != "여기에_봇_토큰" else None
    return None


def _mask_token(token: str) -> str:
    if not token or len(token) < 20:
        return "***"
    return token[:6] + "..." + token[-4:]


def _get_db_stats(community_id: str) -> Optional[dict]:
    db_path = community.COMMUNITIES_DIR / community_id / "community.db"
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        stats = {}
        stats["size_mb"] = round(db_path.stat().st_size / 1024 / 1024, 2)
        stats["agents"] = conn.execute("SELECT COUNT(*) as c FROM agents").fetchone()["c"]
        stats["messages"] = conn.execute("SELECT COUNT(*) as c FROM conversations").fetchone()["c"]
        stats["memories"] = conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]
        stats["relationships"] = conn.execute("SELECT COUNT(*) as c FROM relationships").fetchone()["c"]
        stats["events"] = conn.execute("SELECT COUNT(*) as c FROM events").fetchone()["c"]
        last = conn.execute(
            "SELECT timestamp FROM conversations ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        stats["last_activity"] = last["timestamp"][:16] if last else None
        agents = conn.execute("SELECT id, name, type, current_emotion, emotion_intensity FROM agents").fetchall()
        stats["agent_list"] = [dict(a) for a in agents]
        channels = conn.execute("SELECT COUNT(DISTINCT channel) as c FROM conversations").fetchone()
        stats["channels"] = channels["c"] if channels else 0
        try:
            stats["users"] = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
        except sqlite3.OperationalError:
            stats["users"] = 0
        conn.close()
        return stats
    except Exception as e:
        return {"error": str(e)}


def _is_bot_running(community_id: str) -> bool:
    """커뮤니티별 PID 파일로만 판단 (정확한 체크)"""
    pid_file = PROJECT_ROOT / "dev" / f".bot-{community_id}.pid"
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)  # 프로세스 존재 확인
        return True
    except (ProcessLookupError, ValueError):
        pid_file.unlink(missing_ok=True)  # 죽은 PID 정리
        return False
    except PermissionError:
        return True  # 권한 없으면 살아있는 것


def _get_community_ids() -> list[str]:
    if not community.COMMUNITIES_DIR.exists():
        return []
    return sorted([
        d.name for d in community.COMMUNITIES_DIR.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    ])


async def _discord_connect(token: str, timeout: float = 12.0) -> dict:
    intents = discord_lib.Intents.default()
    intents.guilds = True
    client = discord_lib.Client(intents=intents)
    result = {"ok": False}

    @client.event
    async def on_ready():
        guilds = []
        missing_perms = []
        for g in client.guilds:
            me = g.me
            perms = me.guild_permissions if me else None
            if perms:
                if not perms.manage_channels:
                    missing_perms.append("채널 관리 (Manage Channels)")
                if not perms.manage_webhooks:
                    missing_perms.append("웹훅 관리 (Manage Webhooks)")
                if not perms.send_messages:
                    missing_perms.append("메시지 보내기 (Send Messages)")
                if not perms.read_messages:
                    missing_perms.append("메시지 읽기 (Read Messages)")
                if not perms.manage_messages:
                    missing_perms.append("메시지 관리 (Manage Messages)")

            glimi_cats = [c for c in g.categories if c.name.startswith("glimi")]
            glimi_channels = []
            for cat in glimi_cats:
                glimi_channels.extend(
                    {"name": ch.name, "id": ch.id}
                    for ch in cat.text_channels
                )
            guilds.append({
                "id": g.id, "name": g.name,
                "member_count": g.member_count,
                "glimi_channels": glimi_channels,
            })
        result.update(ok=True, bot_name=client.user.name,
                      bot_id=client.user.id, guilds=guilds,
                      missing_perms=missing_perms)
        await client.close()

    try:
        await asyncio.wait_for(client.start(token), timeout=timeout)
    except asyncio.TimeoutError:
        result["error"] = "연결 시간 초과"
        await client.close()
    except discord_lib.LoginFailure:
        result["error"] = "유효하지 않은 토큰"
    except asyncio.CancelledError:
        pass
    except Exception as e:
        result["error"] = str(e)
        try:
            await client.close()
        except Exception:
            pass
    return result


async def _discord_delete_channels(token: str, guild_id: int, channel_ids: list[int]) -> list[str]:
    intents = discord_lib.Intents.default()
    intents.guilds = True
    client = discord_lib.Client(intents=intents)
    deleted = []

    @client.event
    async def on_ready():
        guild = client.get_guild(guild_id)
        if guild:
            for cid in channel_ids:
                ch = guild.get_channel(cid)
                if ch:
                    try:
                        await ch.delete(reason="Glimi Wizard")
                        deleted.append(ch.name)
                    except Exception:
                        pass
            glimi_cat = discord_lib.utils.get(guild.categories, name="glimi")
            if glimi_cat and len(glimi_cat.channels) == 0:
                try:
                    await glimi_cat.delete()
                    deleted.append("[category] glimi")
                except Exception:
                    pass
        await client.close()

    try:
        await asyncio.wait_for(client.start(token), timeout=30)
    except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
        pass
    return deleted


# ══════════════════════════════════════════════════════════
# CSS
# ══════════════════════════════════════════════════════════

WIZARD_CSS = """
Screen {
    background: $surface;
}


#banner {
    width: 100%;
    content-align: center middle;
    text-align: center;
    padding: 1 0;
    color: $primary;
}

.screen-title {
    width: 100%;
    text-align: center;
    padding: 1 0;
    color: $text;
}

.overview-panel {
    margin: 1 4 0 4;
    padding: 0 1;
    height: auto;
}

.server-wrapper {
    margin: 1 4;
    padding: 1 1;
    height: auto;
    background: $panel;
    border: round $primary-lighten-2;
    border-title-color: $accent;
    border-title-style: bold;
}

#server-cards {
    height: auto;
}

.server-card {
    padding: 1 1;
    background: $surface;
    border: round $primary-darken-2;
    border-title-color: $accent;
    border-title-style: bold;
    width: 100%;
    height: auto;
    margin: 0 0 1 0;
}

.server-card:last-of-type {
    margin: 0;
}

.server-card:focus {
    border: round $accent;
    background: $surface-lighten-1;
}

.server-card:hover {
    border: round $accent;
}

.server-card-info {
    width: 1fr;
    height: auto;
    padding: 0 1;
}

.settings-btn {
    width: 14;
    height: auto;
    margin: 1 0 1 1;
}

.menu-list {
    height: auto;
    max-height: 18;
    margin: 1 4;
    background: $panel;
    border: round $primary-lighten-2;
    padding: 1 2;
}

.status-panel {
    margin: 1 4;
    padding: 1 2;
    border: round $accent;
    height: auto;
    background: $panel;
}

.info-panel {
    margin: 0 4 1 4;
    padding: 1 2;
    height: auto;
    background: $panel;
    border: round $primary-darken-2;
}

.log-panel {
    margin: 1 4;
    padding: 1 2;
    height: auto;
    max-height: 20;
    background: $panel;
    border: round $primary-darken-2;
    overflow-y: auto;
}

.input-group {
    margin: 1 4;
    padding: 1 2;
    height: auto;
    background: $panel;
    border: round $accent;
}

.input-group Label {
    padding: 0 0 0 0;
    color: $text;
}

.input-group Input {
    margin: 0 0 1 0;
}

.result-text {
    margin: 0 4;
    padding: 0 2;
}

.action-bar {
    margin: 1 4 0 4;
    height: 3;
}

.action-bar Button {
    margin: 0 1;
}

Button.danger {
    background: $error;
}

Button.success {
    background: $success;
}

ConfirmDialog {
    align: center middle;
}

ConfirmDialog > Vertical {
    width: 60;
    height: auto;
    max-height: 20;
    background: $panel;
    border: round $warning;
    padding: 1 2;
}

InputDialog {
    align: center middle;
}

InputDialog > Vertical {
    width: 70;
    height: auto;
    max-height: 20;
    background: $panel;
    border: round $accent;
    padding: 1 2;
}

TokenSetupDialog {
    align: center middle;
}

TokenSetupDialog > Vertical {
    width: 80;
    height: auto;
    max-height: 36;
    background: $panel;
    border: round $accent;
    padding: 1 2;
    overflow-y: auto;
}
"""


# ══════════════════════════════════════════════════════════
# 공통 모달 다이얼로그
# ══════════════════════════════════════════════════════════

class InputDialog(ModalScreen[str]):
    """텍스트 입력 다이얼로그"""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, label: str, placeholder: str = "", password: bool = False):
        super().__init__()
        self._label = label
        self._placeholder = placeholder
        self._password = password

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._label)
            yield Input(placeholder=self._placeholder, password=self._password, id="dialog-input")
            yield Static("[dim]Enter 확인 / Escape 취소[/dim]", markup=True)

    def on_mount(self):
        self.query_one("#dialog-input", Input).focus()

    @on(Input.Submitted, "#dialog-input")
    def on_submit(self, event: Input.Submitted):
        self.dismiss(event.value)

    def action_cancel(self):
        self.dismiss("")


DISCORD_SETUP_GUIDE = """\
[bold cyan]Discord Bot 설정 가이드[/bold cyan]

[bold]1.[/bold] discord.com/developers/applications 접속
[bold]2.[/bold] [bold]New Application[/bold] → 이름 입력 → Create
[bold]3.[/bold] [bold]Bot[/bold] 메뉴 → [bold]Reset Token[/bold] → 토큰 복사

[bold]4.[/bold] [yellow]Privileged Gateway Intents[/yellow] 전부 켜기:
   [green]✓[/green] MESSAGE CONTENT INTENT
   [green]✓[/green] SERVER MEMBERS INTENT
   [green]✓[/green] PRESENCE INTENT

[bold]5.[/bold] [bold]OAuth2 → URL Generator[/bold]:
   Scopes: [cyan]bot[/cyan]
   Permissions: [cyan]Administrator[/cyan] (개인 서버용)

[bold]6.[/bold] 생성된 URL로 봇을 서버에 초대

[dim]아래에 복사한 Bot Token을 붙여넣으세요.[/dim]\
"""


class TokenSetupDialog(ModalScreen[str]):
    """디스코드 셋업 가이드 + 토큰 입력 다이얼로그"""
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(DISCORD_SETUP_GUIDE, markup=True)
            yield Static("")
            yield Label("Bot Token")
            yield Input(placeholder="MTIzNDU2...", password=True, id="dialog-input")
            yield Static("[dim]Enter 확인 / Escape 취소[/dim]", markup=True)

    def on_mount(self):
        self.query_one("#dialog-input", Input).focus()

    @on(Input.Submitted, "#dialog-input")
    def on_submit(self, event: Input.Submitted):
        self.dismiss(event.value)

    def action_cancel(self):
        self.dismiss("")


# ══════════════════════════════════════════════════════════
# 메인 화면
# ══════════════════════════════════════════════════════════

BANNER_ART = """\
 ██████╗ ██╗     ██╗███╗   ███╗██╗
██╔════╝ ██║     ██║████╗ ████║██║
██║  ███╗██║     ██║██╔████╔██║██║
██║   ██║██║     ██║██║╚██╔╝██║██║
╚██████╔╝███████╗██║██║ ╚═╝ ██║██║
 ╚═════╝ ╚══════╝╚═╝╚═╝     ╚═╝╚═╝"""


class _ServerCard(Horizontal, can_focus=True):
    """서버 카드 — 클릭하면 대시보드 진입, 내부에 Settings 버튼 포함"""

    def __init__(self, cid: str, info_text: str):
        super().__init__()
        self.cid = cid
        self._info_text = info_text
        self.add_class("server-card")

    def compose(self) -> ComposeResult:
        yield Static(self._info_text, markup=True, classes="server-card-info")
        yield Button("Settings", variant="warning", id=f"settings-{self.cid}", classes="settings-btn")

    def on_click(self, event):
        # Settings 버튼 클릭은 제외
        if not isinstance(event._sender, Button):
            self.screen.app.exit(result=("dashboard", self.cid))


class MainScreen(Screen):
    BINDINGS = [
        Binding("q", "quit_app", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("enter", "open_dashboard", "Dashboard", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(id="main-scroll", can_focus=False):
            yield Static(BANNER_ART, id="banner")
            yield Static("", id="no-community", classes="overview-panel")
            with Vertical(id="server-wrapper", classes="server-wrapper"):
                yield Vertical(id="server-cards")
            yield OptionList(id="action-menu", classes="menu-list")
        yield Footer()

    def on_mount(self):
        self._refresh_view()

    def action_refresh(self):
        self._refresh_view()

    def action_quit_app(self):
        self.app.exit()

    def action_open_dashboard(self):
        """Enter: 포커스된 카드로 대시보드 진입"""
        focused = self.app.focused
        if isinstance(focused, _ServerCard):
            self.app.exit(result=("dashboard", focused.cid))

    def _refresh_view(self):
        cards_container = self.query_one("#server-cards", Vertical)
        action_menu = self.query_one("#action-menu", OptionList)
        no_community = self.query_one("#no-community", Static)
        action_menu.clear_options()

        # 기존 카드 제거
        for child in list(cards_container.children):
            child.remove()

        cids = _get_community_ids()

        wrapper = self.query_one("#server-wrapper", Vertical)
        wrapper.border_title = "Communities"

        if cids:
            no_community.display = False
            wrapper.display = True
            for cid in cids:
                running = _is_bot_running(cid)
                token = _get_token(cid)
                stats = _get_db_stats(cid) or {}

                status_icon = "[green]●[/green]" if running else "[dim]○[/dim]"
                status_text = "[green bold]Running[/green bold]" if running else "[dim]Stopped[/dim]"
                tk = "[green]Set[/green]" if token else "[red]None[/red]"
                agents = stats.get("agents", 0)
                msgs = stats.get("messages", 0)
                memories = stats.get("memories", 0)
                channels = stats.get("channels", 0)
                last = stats.get("last_activity") or "-"
                size = stats.get("size_mb", 0)

                card_text = (
                    f"{status_icon} {status_text}    "
                    f"[dim]Token:[/dim] {tk}    "
                    f"[dim]DB:[/dim] {size}MB\n"
                    f"\n"
                    f"[dim]Agents[/dim] [bold]{agents}[/bold]    "
                    f"[dim]Messages[/dim] [bold]{msgs:,}[/bold]    "
                    f"[dim]Memories[/dim] {memories:,}    "
                    f"[dim]Channels[/dim] {channels}\n"
                    f"[dim]Last Activity  {last}[/dim]"
                )

                card = _ServerCard(cid, card_text)
                card.border_title = f" {cid} "
                cards_container.mount(card)
            # 첫 번째 카드에 포커스
            cards = self.query(_ServerCard)
            if cards:
                cards.first().focus()
        else:
            no_community.display = True
            no_community.update(RichPanel(
                "[dim]커뮤니티가 없습니다. 아래에서 새로 만들어보세요.[/dim]",
                border_style="yellow", padding=(1, 2), title="[bold]Communities[/bold]",
            ))
            wrapper.display = False
            action_menu.focus()

        # 액션 메뉴
        action_menu.add_option(Option("  New Community          새 커뮤니티 생성", id="create"))
        action_menu.add_option(Option("  Export / Import        내보내기 · 가져오기", id="export_import"))
        action_menu.add_option(None)
        action_menu.add_option(Option("  Quit                   종료", id="quit"))

    @on(Button.Pressed)
    def on_settings_pressed(self, event: Button.Pressed):
        bid = event.button.id or ""
        if bid.startswith("settings-"):
            cid = bid.split("-", 1)[1]
            self.app.push_screen(ManageScreen(cid))

    @on(OptionList.OptionSelected, "#action-menu")
    def on_action_select(self, event: OptionList.OptionSelected):
        oid = event.option_id
        if oid == "quit":
            self.app.exit()
        elif oid == "create":
            self.app.push_screen(CreateScreen())
        elif oid == "export_import":
            self.app.push_screen(ExportImportScreen())

    def on_key(self, event):
        # 카드 ↔ 액션 메뉴 방향키 전환
        if event.key == "down":
            focused = self.app.focused
            if isinstance(focused, _ServerCard):
                # 다음 카드가 있으면 이동, 없으면 액션 메뉴로
                cards = list(self.query(_ServerCard))
                idx = cards.index(focused) if focused in cards else -1
                if idx == len(cards) - 1:
                    am = self.query_one("#action-menu", OptionList)
                    am.highlighted = 0
                    am.focus()
                    event.prevent_default()
                    return
                elif idx >= 0:
                    cards[idx + 1].focus()
                    event.prevent_default()
                    return
        if event.key == "up":
            focused = self.app.focused
            if isinstance(focused, _ServerCard):
                cards = list(self.query(_ServerCard))
                idx = cards.index(focused) if focused in cards else -1
                if idx > 0:
                    cards[idx - 1].focus()
                    event.prevent_default()
                    return
            am = self.query_one("#action-menu", OptionList)
            if am.has_focus and am.highlighted == 0:
                cards = list(self.query(_ServerCard))
                if cards:
                    cards[-1].focus()
                    event.prevent_default()
                    return

    def on_screen_resume(self):
        self._refresh_view()


# ══════════════════════════════════════════════════════════
# 커뮤니티 생성 화면
# ══════════════════════════════════════════════════════════

class CreateScreen(Screen):
    BINDINGS = [Binding("escape", "go_back", "Back")]

    def __init__(self):
        super().__init__()
        self._community_id = ""
        self._page = 1
        self._gender = ""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(can_focus=False):
            yield Static(BANNER_ART, id="banner")
            yield Static("[bold]New Community[/bold]", id="screen-title", classes="screen-title")

            # Page 1: 커뮤니티 정보
            with Container(id="page-1", classes="input-group"):
                yield Label("Community ID [dim](영문, 하이픈 가능)[/dim]")
                yield Input(placeholder="my-server", id="cid-input")
                yield Static("")
                yield Label("Description [dim](선택)[/dim]")
                yield Input(placeholder="내 디스코드 서버", id="desc-input")
                yield Static("")
                yield Button("Next →", variant="primary", id="btn-next")

            # Page 2: 사용자 정보
            with Container(id="page-2", classes="input-group"):
                yield Label("[bold]사용자 정보[/bold]")
                yield Label("[dim]에이전트가 이 정보를 기반으로 대화합니다[/dim]")
                yield Static("")
                yield Label("이름 [dim](필수)[/dim]")
                yield Input(placeholder="홍길동", id="owner-name-input")
                yield Static("")
                yield Label("별칭 [dim](희망 호칭 — 에이전트별로 다르게 부를 수 있음)[/dim]")
                yield Input(placeholder="비워두면 이름으로 불러요", id="owner-nickname-input")
                yield Static("")
                yield Label("생년월일 [dim](YYYY-MM-DD)[/dim]")
                yield Input(placeholder="2001-01-01", id="owner-birth-input")
                yield Static("")
                yield Label("성별")
                with Horizontal(classes="action-bar"):
                    yield Button("남", id="gender-m")
                    yield Button("여", id="gender-f")
                yield Static("", id="gender-display")
                yield Static("")
                with Horizontal(classes="action-bar"):
                    yield Button("← Back", id="btn-prev")
                    yield Button("Next →", variant="primary", id="btn-next2")

            # Page 3: Discord 봇 토큰
            with Container(id="page-3", classes="input-group"):
                yield Static(DISCORD_SETUP_GUIDE, markup=True)
                yield Static("")
                yield Label("Bot Token [dim](필수)[/dim]")
                yield Input(placeholder="MTIzNDU2...", password=True, id="token-input")
                yield Static("", id="token-error", classes="result-text")
                yield Static("")
                with Horizontal(classes="action-bar"):
                    yield Button("← Back", id="btn-prev2")
                    yield Button("Verify →", variant="primary", id="btn-verify")

            # Page 4: 검증 결과 + 생성
            with Container(id="page-4", classes="input-group"):
                yield Static("", id="verify-result", classes="result-text")
                yield Static("")
                with Horizontal(classes="action-bar"):
                    yield Button("← Back", id="btn-prev3")
                    yield Button("Create", variant="success", id="btn-create")

            yield Static("", id="create-result", classes="result-text")
        yield Footer()

    def on_mount(self):
        self._show_page(1)
        self.query_one("#cid-input", Input).focus()

    def _show_page(self, page: int):
        self._page = page
        for i in range(1, 5):
            self.query_one(f"#page-{i}").display = (page == i)

    @on(Button.Pressed, "#btn-next")
    def on_next(self):
        cid = self.query_one("#cid-input", Input).value.strip()
        result = self.query_one("#create-result", Static)
        if not cid or not cid.replace("-", "").replace("_", "").isalnum():
            result.update("[red]유효하지 않은 Community ID입니다.[/red]")
            return
        if (community.COMMUNITIES_DIR / cid).exists():
            result.update(f"[red]이미 존재: {cid}[/red]")
            return
        result.update("")
        self._show_page(2)
        self.query_one("#owner-name-input", Input).focus()

    @on(Button.Pressed, "#btn-prev")
    def on_prev(self):
        self._show_page(1)
        self.query_one("#cid-input", Input).focus()

    @on(Button.Pressed, "#gender-m")
    def on_gender_m(self):
        self._gender = "남"
        self.query_one("#gender-display", Static).update("[cyan bold]남[/cyan bold] 선택됨")
        self.query_one("#gender-m", Button).variant = "primary"
        self.query_one("#gender-f", Button).variant = "default"

    @on(Button.Pressed, "#gender-f")
    def on_gender_f(self):
        self._gender = "여"
        self.query_one("#gender-display", Static).update("[magenta bold]여[/magenta bold] 선택됨")
        self.query_one("#gender-f", Button).variant = "primary"
        self.query_one("#gender-m", Button).variant = "default"

    @on(Button.Pressed, "#btn-next2")
    def on_next2(self):
        owner_name = self.query_one("#owner-name-input", Input).value.strip()
        result = self.query_one("#create-result", Static)
        if not owner_name:
            result.update("[red]이름은 필수입니다.[/red]")
            return
        result.update("")
        self._show_page(3)
        self.query_one("#token-input", Input).focus()

    @on(Button.Pressed, "#btn-prev2")
    def on_prev2(self):
        self._show_page(2)
        self.query_one("#owner-name-input", Input).focus()

    @on(Button.Pressed, "#btn-verify")
    def on_verify(self):
        self._do_verify()

    @on(Button.Pressed, "#btn-prev3")
    def on_prev3(self):
        self._show_page(3)
        self.query_one("#token-input", Input).focus()

    @on(Button.Pressed, "#btn-create")
    def on_create(self):
        self._do_create()

    @on(Input.Submitted, "#cid-input")
    def on_cid_submit(self):
        self.query_one("#desc-input", Input).focus()

    @on(Input.Submitted, "#desc-input")
    def on_desc_submit(self):
        self.on_next()

    @on(Input.Submitted, "#token-input")
    def on_token_submit(self):
        self._do_verify()

    def _do_verify(self):
        token = self.query_one("#token-input", Input).value.strip()
        err = self.query_one("#token-error", Static)
        if not token:
            err.update("[red]봇 토큰은 필수입니다.[/red]")
            return
        err.update("")
        self._loading = LoadingOverlay("봇 토큰 검증 중...")
        self.app.push_screen(self._loading)
        self._run_verify(token)

    @work(thread=True)
    def _run_verify(self, token: str):
        """토큰 검증 → 결과 페이지로"""
        loop = asyncio.new_event_loop()
        info = loop.run_until_complete(_discord_connect(token, timeout=15))
        loop.close()

        # 로딩 닫기
        try:
            self.app.call_from_thread(self.app.pop_screen)
        except Exception:
            pass

        err_widget = self.query_one("#token-error", Static)

        if not info.get("ok"):
            err = info.get("error", "알 수 없는 오류")
            self.app.call_from_thread(err_widget.update, f"[red]검증 실패: {err}. 토큰을 다시 확인하세요.[/red]")
            return

        missing = info.get("missing_perms", [])
        if missing:
            perm_list = ", ".join(missing)
            self.app.call_from_thread(
                err_widget.update,
                f"[red]봇 권한 부족: {perm_list}[/red]\n"
                "[dim]디스코드 서버 설정 → 역할에서 권한 부여 후 다시 시도하세요.[/dim]"
            )
            return

        if not info.get("guilds"):
            self.app.call_from_thread(
                err_widget.update,
                "[red]봇이 참여한 서버가 없습니다. 봇을 서버에 초대 후 다시 시도하세요.[/red]"
            )
            return

        # 검증 통과 → 결과 저장 + Page 4
        self._verified_info = info
        bot_name = info.get("bot_name", "?")
        guild = info["guilds"][0]
        guild_name = guild["name"]
        member_count = guild.get("member_count", "?")
        verify_text = (
            f"[green bold]검증 완료[/green bold]\n\n"
            f"  봇: [cyan]{bot_name}[/cyan]\n"
            f"  서버: [cyan]{guild_name}[/cyan] ({member_count}명)\n"
            f"  토큰: {_mask_token(self.query_one('#token-input', Input).value.strip())}\n"
        )
        self.app.call_from_thread(self.query_one("#verify-result", Static).update, verify_text)
        self.app.call_from_thread(self._show_page, 4)

    def _do_create(self):
        cid = self.query_one("#cid-input", Input).value.strip()
        token = self.query_one("#token-input", Input).value.strip()
        desc = self.query_one("#desc-input", Input).value.strip()
        owner_name = self.query_one("#owner-name-input", Input).value.strip()
        owner_nickname = self.query_one("#owner-nickname-input", Input).value.strip()
        owner_birth = self.query_one("#owner-birth-input", Input).value.strip()
        owner_gender = getattr(self, '_gender', '')
        result = self.query_one("#create-result", Static)

        if (community.COMMUNITIES_DIR / cid).exists():
            result.update(f"[red]이미 존재: {cid}[/red]")
            return

        self._community_id = cid
        community.init_community(cid)

        if desc:
            reg = community.REGISTRY_PATH
            if reg.exists():
                content = reg.read_text()
                content = content.replace(
                    f'[community.{cid}]\nname = "{cid}"\ndescription = ""',
                    f'[community.{cid}]\nname = "{cid}"\ndescription = "{desc}"',
                )
                reg.write_text(content)

        self._save_owner_profile(cid, owner_name, owner_nickname, owner_birth, owner_gender)

        env_path = community.COMMUNITIES_DIR / cid / ".env"
        set_key(str(env_path), "DISCORD_BOT_TOKEN", token)

        info = getattr(self, '_verified_info', {})
        bot_name = info.get("bot_name", "?")
        guild_name = info["guilds"][0]["name"] if info.get("guilds") else "?"
        result.update(
            f"[green]커뮤니티 '{cid}' 생성 완료![/green]\n\n"
            f"봇: {bot_name} → 서버: {guild_name}\n"
            f"사용자: {owner_name}"
            f"{f' ({owner_nickname})' if owner_nickname else ''}\n\n"
            "[dim]ESC로 돌아가세요.[/dim]"
        )

        self._ask_init_db(cid)

    def _save_owner_profile(self, cid, name, nickname, birth, gender):
        """오너 프로필을 커뮤니티 DB에 저장"""
        import json as _json
        import sqlite3

        db_path = community.COMMUNITIES_DIR / cid / "community.db"
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row

        # DB 초기화 (테이블 없으면)
        from src import db as _db
        old_community = os.environ.get("GLIMI_COMMUNITY", "")
        os.environ["GLIMI_COMMUNITY"] = cid
        community.set_community(cid)
        _db.init_db()

        # 나이 계산
        age = None
        birth_year = None
        if birth:
            try:
                from datetime import datetime
                birth_date = datetime.strptime(birth, "%Y-%m-%d")
                birth_year = birth_date.year
                today = datetime.now()
                age = today.year - birth_year
                # 한국 나이 (만 나이 + 1은 유나가 나중에 물어볼 것)
            except ValueError:
                pass

        # 오너 데이터
        owner_id = name.lower().replace(" ", "_")
        user_data = {
            "id": owner_id,
            "name": name,
            "birth_year": birth_year,
            "age": age,
            "personality": _json.dumps({"nickname": nickname, "gender": gender}, ensure_ascii=False) if nickname or gender else None,
        }

        conn.execute(
            "INSERT OR REPLACE INTO users (id, name, birth_year, age, personality) VALUES (?, ?, ?, ?, ?)",
            (user_data["id"], user_data["name"], user_data["birth_year"], user_data["age"], user_data["personality"]),
        )
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('active_user_id', ?)", (owner_id,))
        conn.commit()
        conn.close()

        # 환경변수 복원
        if old_community:
            os.environ["GLIMI_COMMUNITY"] = old_community
            community.set_community(old_community)


    def _ask_init_db(self, cid: str):
        self._run_db_init(cid)

    @work(thread=True)
    def _run_db_init(self, cid: str):
        env = os.environ.copy()
        env["GLIMI_COMMUNITY"] = cid
        result = subprocess.run(
            [_venv_python(), "-c",
             f"from src import community, db; "
             f"community.set_community('{cid}'); "
             f"db.init_db(); "
             f"from src.tools.migrate import migrate_json_to_db; "
             f"migrate_json_to_db()"],
            capture_output=True, text=True, env=env,
            cwd=str(PROJECT_ROOT),
        )
        # 생성 완료 → 바로 대시보드 진입
        self.app.call_from_thread(lambda: self.app.exit(result=("dashboard", cid)))

    def action_go_back(self):
        self.app.pop_screen()


# ══════════════════════════════════════════════════════════
# 커뮤니티 관리 화면
# ══════════════════════════════════════════════════════════

class ManageScreen(Screen):
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, community_id: str):
        super().__init__()
        self._cid = community_id

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(can_focus=False):
            yield Static(id="manage-info", classes="status-panel")
            yield Static(id="manage-agents", classes="info-panel")
            yield OptionList(id="manage-menu", classes="menu-list")
            yield Static("", id="manage-result", classes="result-text")
        yield Footer()

    def on_mount(self):
        self._refresh_view()
        self.query_one("#manage-menu", OptionList).focus()

    def action_refresh(self):
        self._refresh_view()

    def on_screen_resume(self):
        self._refresh_view()
        self.query_one("#manage-menu", OptionList).focus()

    def _refresh_view(self):
        cid = self._cid
        running = _is_bot_running(cid)
        token = _get_token(cid)
        stats = _get_db_stats(cid) or {}

        # 정보 패널
        lines = []
        lines.append(f"[bold cyan]{cid}[/bold cyan]")
        lines.append("")
        lines.append(f"Status    {'[bold green]● Running[/bold green]' if running else '[dim]○ Stopped[/dim]'}")
        lines.append(f"Token     {'[green]' + _mask_token(token) + '[/green]' if token else '[red]Not set[/red]'}")
        lines.append(f"DB        {'[green]OK[/green]' if (community.COMMUNITIES_DIR / cid / 'community.db').exists() else '[yellow]None[/yellow]'}")

        if stats and "error" not in stats:
            lines.append("")
            lines.append(f"Agents    [bold]{stats.get('agents', 0)}[/bold]")
            lines.append(f"Messages  [bold]{stats.get('messages', 0):,}[/bold]")
            lines.append(f"Memories  {stats.get('memories', 0):,}")
            lines.append(f"Channels  {stats.get('channels', 0)}")
            lines.append(f"DB Size   {stats.get('size_mb', 0)} MB")
            if stats.get("last_activity"):
                lines.append(f"Last      {stats['last_activity']}")

        self.query_one("#manage-info", Static).update("\n".join(lines))

        # 에이전트 테이블
        if stats and stats.get("agent_list"):
            table = RichTable(box=box.SIMPLE, show_header=True, padding=(0, 1), expand=True)
            table.add_column("ID", style="dim", ratio=2)
            table.add_column("Name", style="bold", ratio=1)
            table.add_column("Type", ratio=1)
            table.add_column("Emotion", ratio=1)
            for a in stats["agent_list"]:
                emo = a.get("current_emotion", "-")
                intensity = a.get("emotion_intensity", "")
                emo_display = f"{emo} ({intensity})" if intensity else emo
                table.add_row(a["id"], a["name"], a["type"], emo_display)
            self.query_one("#manage-agents", Static).update(table)
        else:
            self.query_one("#manage-agents", Static).update("[dim]에이전트 없음[/dim]")

        # 메뉴
        menu = self.query_one("#manage-menu", OptionList)
        menu.clear_options()

        if running:
            menu.add_option(Option("  Open Dashboard         실시간 대시보드", id="dashboard"))
            menu.add_option(None)
            menu.add_option(Option("  Stop Server            서버 중지", id="stop"))
            menu.add_option(Option("  Restart Server         서버 재시작", id="restart"))
        else:
            menu.add_option(Option("  Start Server           서버 시작", id="start"))
        menu.add_option(None)

        menu.add_option(Option("  Set Token              봇 토큰 설정", id="token"))
        menu.add_option(Option("  Health Check           연결 상태 확인", id="health"))
        menu.add_option(None)

        menu.add_option(Option("  Init DB                DB 초기화 + 마이그레이션", id="initdb"))
        menu.add_option(Option("  Discord Channels       디스코드 채널 관리", id="discord"))
        menu.add_option(Option("  View Logs              로그 보기", id="logs"))
        menu.add_option(None)
        menu.add_option(Option("  Delete Community       커뮤니티 삭제", id="delete"))

        self.query_one("#manage-result", Static).update("")

    @on(OptionList.OptionSelected, "#manage-menu")
    def on_action(self, event: OptionList.OptionSelected):
        oid = event.option_id
        if oid == "dashboard":
            self._do_open_dashboard()
        elif oid == "token":
            self._do_set_token()
        elif oid == "health":
            self._do_health_check()
        elif oid == "start":
            self._do_start_bot()
        elif oid == "stop":
            self._do_stop_bot()
        elif oid == "restart":
            self._do_restart_bot()
        elif oid == "initdb":
            self._do_init_db()
        elif oid == "discord":
            self.app.push_screen(DiscordScreen(self._cid))
        elif oid == "logs":
            self.app.push_screen(LogScreen(self._cid))
        elif oid == "delete":
            self._do_delete()

    def _do_open_dashboard(self):
        """wizard 종료 후 대시보드 실행"""
        cid = self._cid
        self.app.exit(result=("dashboard", cid))

    def _result(self, msg: str):
        self.query_one("#manage-result", Static).update(msg)

    # ── 토큰 ──

    def _do_set_token(self):
        def on_token(token: str):
            if not token:
                return
            # 바로 검증
            self._loading = LoadingOverlay("봇 토큰 검증 중...")
            self.app.push_screen(self._loading)
            self._verify_and_save_token(token)

        self.app.push_screen(
            InputDialog("Discord Bot Token", placeholder="MTIzNDU2...", password=True),
            on_token,
        )

    @work(thread=True)
    def _verify_and_save_token(self, token: str):
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(_discord_connect(token, timeout=15))
        loop.close()

        # 로딩 닫기
        try:
            self.app.call_from_thread(self.app.pop_screen)
        except Exception:
            pass

        if not result.get("ok"):
            err = result.get("error", "알 수 없는 오류")
            self.app.call_from_thread(
                self.app.push_screen,
                ConfirmDialog(f"[red]검증 실패: {err}[/red]\n\n토큰을 다시 확인하세요.", danger=True),
            )
            return

        # 권한 체크
        missing = result.get("missing_perms", [])
        if missing:
            perm_list = "\n".join(f"  - {p}" for p in missing)
            self.app.call_from_thread(
                self.app.push_screen,
                ConfirmDialog(
                    f"[red]봇 권한이 부족합니다:[/red]\n{perm_list}\n\n"
                    "디스코드 서버 설정 → 역할에서 권한을 부여하세요.",
                    danger=True,
                ),
            )
            return

        if not result.get("guilds"):
            self.app.call_from_thread(
                self.app.push_screen,
                ConfirmDialog("[red]봇이 참여한 서버가 없습니다.[/red]\n\n봇을 서버에 초대 후 다시 시도하세요.", danger=True),
            )
            return

        # 검증 통과 → 저장
        env_path = community.COMMUNITIES_DIR / self._cid / ".env"
        set_key(str(env_path), "DISCORD_BOT_TOKEN", token)

        bot_name = result.get("bot_name", "?")
        guilds = result.get("guilds", [])
        guild_lines = []
        for g in guilds:
            ch_count = len(g.get("glimi_channels", []))
            guild_lines.append(f"  {g['name']} ({g['member_count']}명, glimi채널 {ch_count}개)")

        msg = (
            f"[green bold]검증 완료 — 토큰 저장됨[/green bold]\n\n"
            f"Bot: [cyan]{bot_name}[/cyan]\n"
            f"Token: {_mask_token(token)}\n\n"
            f"서버:\n" + "\n".join(guild_lines)
        )
        self.app.call_from_thread(self.app.push_screen, ConfirmDialog(msg))
        self.app.call_from_thread(self._refresh_view)

    # ── 헬스체크 ──

    @work(thread=True)
    def _do_health_check(self):
        cid = self._cid
        lines = []

        running = _is_bot_running(cid)
        lines.append(f"Process   {'[green]● Running[/green]' if running else '[dim]○ Stopped[/dim]'}")

        stats = _get_db_stats(cid)
        if stats and "error" not in stats:
            lines.append(f"DB        [green]OK[/green] ({stats['agents']}명, {stats['messages']:,}건, {stats['size_mb']}MB)")
        elif stats:
            lines.append(f"DB        [red]{stats['error']}[/red]")
        else:
            lines.append("DB        [yellow]파일 없음[/yellow]")

        token = _get_token(cid)
        if token:
            lines.append("Discord   [dim]연결 중...[/dim]")
            self.app.call_from_thread(self._result, "\n".join(lines))

            loop = asyncio.new_event_loop()
            result = loop.run_until_complete(_discord_connect(token))
            loop.close()
            lines.pop()  # "연결 중..." 제거
            if result.get("ok"):
                for g in result.get("guilds", []):
                    ch = len(g.get("glimi_channels", []))
                    lines.append(f"Discord   [green]OK[/green] — {g['name']} (glimi {ch}ch)")
            else:
                lines.append(f"Discord   [red]{result.get('error', '?')}[/red]")
        else:
            lines.append("Discord   [yellow]토큰 미설정[/yellow]")

        self.app.call_from_thread(self._result, "\n".join(lines))

    # ── 시작/중지/재시작 ──

    def _do_start_bot(self):
        token = _get_token(self._cid)
        if not token:
            self._result("[red]토큰이 설정되지 않았습니다.[/red]")
            return
        self._loading = LoadingOverlay("서버 시작 중..."); self.app.push_screen(self._loading)
        self._start_bot_process()

    @work(thread=True)
    def _start_bot_process(self):
        cid = self._cid
        # 기존 프로세스 정리
        subprocess.run(["pkill", "-f", f"GLIMI_COMMUNITY={cid}.*src.discord_bot"], capture_output=True)
        for pf in [PROJECT_ROOT / "dev" / f".bot-{cid}.pid", PROJECT_ROOT / "dev" / ".bot.pid"]:
            if pf.exists():
                try:
                    pid = int(pf.read_text().strip())
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, ValueError):
                    pass
                pf.unlink(missing_ok=True)
        time.sleep(1)
        # 새 프로세스 시작
        env = os.environ.copy()
        env["GLIMI_COMMUNITY"] = cid
        proc = subprocess.Popen(
            ["bash", str(PROJECT_ROOT / "scripts" / "run.sh"), cid],
            cwd=str(PROJECT_ROOT), env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        pid_file = PROJECT_ROOT / "dev" / f".bot-{cid}.pid"
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(proc.pid))
        time.sleep(3)
        running = _is_bot_running(cid)
        msg = f"[green]서버 시작됨 (PID: {proc.pid})[/green]" if running else "[yellow]프로세스 시작됨 (연결 대기 중...)[/yellow]"
        self.app.call_from_thread(self.app.pop_screen)  # 로딩 닫기
        self.app.call_from_thread(self._result, msg)
        self.app.call_from_thread(self._refresh_view)
        self.query_one("#manage-menu", OptionList).focus()

    def _do_stop_bot(self):
        def on_confirm(yes: bool):
            if yes:
                self._loading = LoadingOverlay("서버 중지 중..."); self.app.push_screen(self._loading)
                self._stop_bot_process()
        self.app.push_screen(ConfirmDialog(f"'{self._cid}' 서버를 중지할까요?"), on_confirm)

    @work(thread=True)
    def _stop_bot_process(self):
        cid = self._cid
        subprocess.run(["pkill", "-f", f"GLIMI_COMMUNITY={cid}.*src.discord_bot"], capture_output=True)
        for pf in [PROJECT_ROOT / "dev" / f".bot-{cid}.pid", PROJECT_ROOT / "dev" / ".bot.pid"]:
            if pf.exists():
                try:
                    pid = int(pf.read_text().strip())
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, ValueError):
                    pass
                pf.unlink(missing_ok=True)
        time.sleep(2)
        if not _is_bot_running(cid):
            self.app.call_from_thread(self.app.pop_screen)
            self.app.call_from_thread(self._result, "[green]서버가 중지되었습니다.[/green]")
        else:
            subprocess.run(["pkill", "-9", "-f", f"GLIMI_COMMUNITY={cid}"], capture_output=True)
            self.app.call_from_thread(self.app.pop_screen)
            self.app.call_from_thread(self._result, "[yellow]강제 종료됨[/yellow]")
        self.app.call_from_thread(self._refresh_view)

    def _do_restart_bot(self):
        def on_confirm(yes: bool):
            if yes:
                self._loading = LoadingOverlay("서버 재시작 중..."); self.app.push_screen(self._loading)
                self._restart_bot_process()
        self.app.push_screen(ConfirmDialog(f"'{self._cid}' 서버를 재시작할까요?"), on_confirm)

    @work(thread=True)
    def _restart_bot_process(self):
        cid = self._cid
        self.app.call_from_thread(self._result, "[yellow]서버 중지 중...[/yellow]")
        subprocess.run(["pkill", "-f", f"GLIMI_COMMUNITY={cid}.*src.discord_bot"], capture_output=True)
        for pf in [PROJECT_ROOT / "dev" / f".bot-{cid}.pid", PROJECT_ROOT / "dev" / ".bot.pid"]:
            if pf.exists():
                try:
                    pid = int(pf.read_text().strip())
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, ValueError):
                    pass
                pf.unlink(missing_ok=True)
        time.sleep(3)
        self.app.call_from_thread(self._loading.update_detail, "새 프로세스 시작 중...")
        env = os.environ.copy()
        env["GLIMI_COMMUNITY"] = cid
        proc = subprocess.Popen(
            ["bash", str(PROJECT_ROOT / "scripts" / "run.sh"), cid],
            cwd=str(PROJECT_ROOT), env=env,
            start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        pid_file = PROJECT_ROOT / "dev" / f".bot-{cid}.pid"
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(str(proc.pid))
        time.sleep(3)
        self.app.call_from_thread(self.app.pop_screen)  # 로딩 닫기
        self.app.call_from_thread(self._result, f"[green]서버 재시작 완료 (PID: {proc.pid})[/green]")
        self.app.call_from_thread(self._refresh_view)

    # ── DB 초기화 ──

    def _do_init_db(self):
        self._run_init_db()

    @work(thread=True)
    def _run_init_db(self):
        cid = self._cid
        self.app.call_from_thread(self._result, "[dim]DB 초기화 중...[/dim]")
        env = os.environ.copy()
        env["GLIMI_COMMUNITY"] = cid
        result = subprocess.run(
            [_venv_python(), "-c",
             f"from src import community, db; "
             f"community.set_community('{cid}'); "
             f"db.init_db(); "
             f"from src.tools.migrate import migrate_json_to_db; "
             f"migrate_json_to_db()"],
            capture_output=True, text=True, env=env,
            cwd=str(PROJECT_ROOT),
        )
        output = (result.stdout or "").strip()
        lines = [l for l in output.split("\n") if l.strip()][-8:]
        msg = "\n".join(lines) if lines else "완료"
        status = "[green]완료![/green]" if result.returncode == 0 else "[red]오류 발생[/red]"
        self.app.call_from_thread(self._result, f"{status}\n\n{msg}")
        self.app.call_from_thread(self._refresh_view)

    # ── 삭제 ──

    def _do_delete(self):
        def on_confirm(yes: bool):
            if not yes:
                return
            # 봇 먼저 중지
            if _is_bot_running(self._cid):
                subprocess.run(["pkill", "-f", f"GLIMI_COMMUNITY={self._cid}"], capture_output=True)
                time.sleep(1)

            token = _get_token(self._cid)
            if token:
                def on_discord(clean_discord: bool):
                    if clean_discord:
                        # 한 번 더 확인
                        def on_double_confirm(really: bool):
                            if really:
                                self._delete_with_discord_cleanup(token)
                            else:
                                self._finalize_delete()
                        self.app.push_screen(
                            ConfirmDialog(
                                "[red bold]정말 디스코드 서버의 채널을 삭제하시겠습니까?[/red bold]\n"
                                "삭제된 채널의 메시지는 복구할 수 없습니다.",
                                danger=True,
                            ),
                            on_double_confirm,
                        )
                    else:
                        self._finalize_delete()
                self.app.push_screen(
                    ConfirmDialog("디스코드 서버의 glimi 채널도 삭제할까요?", danger=True, default_no=True),
                    on_discord,
                )
            else:
                # ID 입력 최종 확인
                def on_id(typed: str):
                    if typed == self._cid:
                        self._finalize_delete()
                    else:
                        self._result("[dim]취소됨[/dim]")
                self.app.push_screen(
                    InputDialog(f"삭제 확인: '{self._cid}'를 입력하세요"),
                    on_id,
                )

        self.app.push_screen(
            ConfirmDialog(
                f"[red bold]커뮤니티 '{self._cid}' 삭제[/red bold]\n\n"
                "DB, 아바타, 로그, .env 모두 삭제됩니다.\n"
                "이 작업은 되돌릴 수 없습니다.",
                danger=True,
            ),
            on_confirm,
        )

    @work(thread=True)
    def _delete_with_discord_cleanup(self, token: str):
        self.app.call_from_thread(self._result, "[dim]디스코드 채널 삭제 중...[/dim]")
        loop = asyncio.new_event_loop()
        info = loop.run_until_complete(_discord_connect(token))
        if info.get("ok"):
            for g in info.get("guilds", []):
                channels = g.get("glimi_channels", [])
                if channels:
                    ids = [ch["id"] for ch in channels]
                    deleted = loop.run_until_complete(_discord_delete_channels(token, g["id"], ids))
                    self.app.call_from_thread(
                        self._result,
                        f"[green]디스코드 채널 {len(deleted)}개 삭제됨[/green]"
                    )
        loop.close()

        # ID 입력 최종 확인
        def on_id(typed: str):
            if typed == self._cid:
                self._finalize_delete()
            else:
                self._result("[dim]취소됨[/dim]")
        self.app.call_from_thread(
            self.app.push_screen,
            InputDialog(f"삭제 확인: '{self._cid}'를 입력하세요"),
            on_id,
        )

    def _finalize_delete(self):
        cdir = community.COMMUNITIES_DIR / self._cid
        if cdir.exists():
            shutil.rmtree(cdir)
        # registry 정리
        if community.REGISTRY_PATH.exists():
            content = community.REGISTRY_PATH.read_text()
            lines = content.split("\n")
            new_lines = []
            skip = False
            for line in lines:
                if line.strip() == f"[community.{self._cid}]":
                    skip = True
                    continue
                if skip and line.strip().startswith("["):
                    skip = False
                if skip:
                    continue
                if line.strip() == f'default = "{self._cid}"':
                    remaining = [c for c in _get_community_ids() if c != self._cid]
                    line = f'default = "{remaining[0]}"' if remaining else '# default = ""'
                new_lines.append(line)
            community.REGISTRY_PATH.write_text("\n".join(new_lines))
        self.app.pop_screen()  # ManageScreen 닫기

    def action_go_back(self):
        self.app.pop_screen()


# ══════════════════════════════════════════════════════════
# 디스코드 채널 관리
# ══════════════════════════════════════════════════════════

class DiscordScreen(Screen):
    BINDINGS = [Binding("escape", "go_back", "Back")]

    def __init__(self, community_id: str):
        super().__init__()
        self._cid = community_id
        self._guilds: list = []

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(can_focus=False):
            yield Static(f"[bold]Discord Channels — {self._cid}[/bold]", id="screen-title", classes="screen-title")
            yield Static("[dim]서버 정보 조회 중...[/dim]", id="discord-info", classes="status-panel")
            yield OptionList(id="discord-menu", classes="menu-list")
            yield Static("", id="discord-result", classes="result-text")
        yield Footer()

    def on_mount(self):
        self._load_discord_info()

    @work(thread=True)
    def _load_discord_info(self):
        token = _get_token(self._cid)
        if not token:
            self.app.call_from_thread(
                self.query_one("#discord-info", Static).update,
                "[red]토큰이 설정되지 않았습니다.[/red]"
            )
            return

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(_discord_connect(token))
        loop.close()

        if not result.get("ok"):
            self.app.call_from_thread(
                self.query_one("#discord-info", Static).update,
                f"[red]연결 실패: {result.get('error', '?')}[/red]"
            )
            return

        self._guilds = result.get("guilds", [])

        lines = [f"[green]Bot: {result['bot_name']}[/green]", ""]
        for g in self._guilds:
            channels = g.get("glimi_channels", [])
            lines.append(f"[bold]{g['name']}[/bold] ({g['member_count']}명)")
            if channels:
                for ch in channels:
                    lines.append(f"  #{ch['name']}")
            else:
                lines.append("  [dim]glimi 채널 없음[/dim]")
            lines.append("")

        self.app.call_from_thread(
            self.query_one("#discord-info", Static).update,
            "\n".join(lines)
        )

        # 메뉴
        def build_menu():
            menu = self.query_one("#discord-menu", OptionList)
            menu.clear_options()
            for g in self._guilds:
                channels = g.get("glimi_channels", [])
                if channels:
                    menu.add_option(Option(
                        f"  Delete All ({g['name']})    glimi 채널 전체 삭제",
                        id=f"deleteall:{g['id']}",
                    ))
                    for ch in channels:
                        menu.add_option(Option(
                            f"    #{ch['name']}",
                            id=f"deletech:{g['id']}:{ch['id']}:{ch['name']}",
                        ))
                    menu.add_option(None)

        self.app.call_from_thread(build_menu)

    @on(OptionList.OptionSelected, "#discord-menu")
    def on_discord_action(self, event: OptionList.OptionSelected):
        oid = event.option_id or ""
        if oid.startswith("deleteall:"):
            guild_id = int(oid.split(":")[1])
            guild = next((g for g in self._guilds if g["id"] == guild_id), None)
            if guild:
                channels = guild.get("glimi_channels", [])
                def on_confirm(yes: bool):
                    if yes:
                        self._delete_channels(guild_id, [ch["id"] for ch in channels])
                self.app.push_screen(
                    ConfirmDialog(
                        f"[red]{guild['name']}의 glimi 채널 {len(channels)}개를 모두 삭제할까요?[/red]",
                        danger=True,
                    ),
                    on_confirm,
                )
        elif oid.startswith("deletech:"):
            parts = oid.split(":")
            guild_id, ch_id, ch_name = int(parts[1]), int(parts[2]), parts[3]
            def on_confirm(yes: bool):
                if yes:
                    self._delete_channels(guild_id, [ch_id])
            self.app.push_screen(
                ConfirmDialog(f"[red]#{ch_name} 채널을 삭제할까요?[/red]", danger=True),
                on_confirm,
            )

    @work(thread=True)
    def _delete_channels(self, guild_id: int, channel_ids: list[int]):
        self.app.call_from_thread(
            self.query_one("#discord-result", Static).update,
            "[dim]삭제 중...[/dim]"
        )
        token = _get_token(self._cid)
        loop = asyncio.new_event_loop()
        deleted = loop.run_until_complete(_discord_delete_channels(token, guild_id, channel_ids))
        loop.close()
        msg = f"[green]{len(deleted)}개 삭제됨: {', '.join(deleted)}[/green]" if deleted else "[yellow]삭제된 채널 없음[/yellow]"
        self.app.call_from_thread(
            self.query_one("#discord-result", Static).update, msg
        )
        # 새로고침
        self._load_discord_info()

    def action_go_back(self):
        self.app.pop_screen()


# ══════════════════════════════════════════════════════════
# 로그 화면
# ══════════════════════════════════════════════════════════

class LogScreen(Screen):
    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, community_id: str):
        super().__init__()
        self._cid = community_id

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(can_focus=False):
            yield Static(f"[bold]Logs — {self._cid}[/bold]", id="screen-title", classes="screen-title")
            yield Static("", id="log-content", classes="log-panel")
        yield Footer()

    def on_mount(self):
        self._refresh_logs()

    def action_refresh(self):
        self._refresh_logs()

    def _refresh_logs(self):
        log_path = community.COMMUNITIES_DIR / self._cid / "logs" / "system.log"
        if not log_path.exists():
            self.query_one("#log-content", Static).update("[dim]로그 파일 없음[/dim]")
            return
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            display = "".join(lines[-50:])  # 마지막 50줄
            self.query_one("#log-content", Static).update(display or "[dim]비어있음[/dim]")
        except Exception as e:
            self.query_one("#log-content", Static).update(f"[red]{e}[/red]")

    def action_go_back(self):
        self.app.pop_screen()


# ══════════════════════════════════════════════════════════
# 내보내기 / 가져오기
# ══════════════════════════════════════════════════════════

class ExportImportScreen(Screen):
    BINDINGS = [Binding("escape", "go_back", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with VerticalScroll(can_focus=False):
            yield Static(BANNER_ART, id="banner")
            yield Static("[bold]Export / Import[/bold]", id="screen-title", classes="screen-title", markup=True)
            yield OptionList(
                Option("  Export Community        커뮤니티를 .glimi.zip으로 내보내기", id="export"),
                Option("  Import Community        .glimi.zip에서 가져오기", id="import"),
                None,
                Option("  Apply External DB      외부 DB 파일 적용", id="apply_db"),
                id="ei-menu",
                classes="menu-list",
            )
            yield Static("", id="ei-result", classes="result-text")
        yield Footer()

    @on(OptionList.OptionSelected, "#ei-menu")
    def on_select(self, event: OptionList.OptionSelected):
        oid = event.option_id
        if oid == "export":
            self._do_export()
        elif oid == "import":
            self._do_import()
        elif oid == "apply_db":
            self._do_apply_db()

    def _result(self, msg: str):
        self.query_one("#ei-result", Static).update(msg)

    # ── Export ──

    def _do_export(self):
        cids = _get_community_ids()
        if not cids:
            self._result("[yellow]내보낼 커뮤니티가 없습니다.[/yellow]")
            return

        # 커뮤니티 선택 메뉴를 만든다
        class SelectCommunityScreen(ModalScreen[str]):
            BINDINGS = [Binding("escape", "cancel", "Cancel")]

            def compose(self_inner) -> ComposeResult:
                with Vertical():
                    yield Label("내보낼 커뮤니티 선택")
                    opts = OptionList(id="select-list")
                    for c in cids:
                        opts.add_option(Option(f"  {c}", id=c))
                    yield opts

            @on(OptionList.OptionSelected, "#select-list")
            def on_selected(self_inner, event):
                self_inner.dismiss(event.option_id)

            def action_cancel(self_inner):
                self_inner.dismiss("")

        def on_community(cid: str):
            if cid:
                def on_path(out_path: str):
                    if out_path:
                        self._run_export(cid, out_path)
                self.app.push_screen(
                    InputDialog("저장 경로", placeholder=str(PROJECT_ROOT / f"{cid}.glimi.zip")),
                    on_path,
                )

        self.app.push_screen(SelectCommunityScreen(), on_community)

    @work(thread=True)
    def _run_export(self, cid: str, out_path: str):
        if not out_path.endswith(".zip"):
            out_path += ".glimi.zip"

        self.app.call_from_thread(self._result, "[dim]압축 중...[/dim]")
        cdir = community.COMMUNITIES_DIR / cid
        stats = _get_db_stats(cid) or {}

        manifest = {
            "community_id": cid,
            "exported_at": datetime.now().isoformat(),
            "agents": stats.get("agents", 0),
            "messages": stats.get("messages", 0),
            "memories": stats.get("memories", 0),
        }
        if stats.get("agent_list"):
            manifest["agent_names"] = [a["name"] for a in stats["agent_list"]]

        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            db_path = cdir / "community.db"
            if db_path.exists():
                zf.write(db_path, "community.db")
            avatars_dir = cdir / "avatars"
            if avatars_dir.exists():
                for img in avatars_dir.iterdir():
                    if img.is_file():
                        zf.write(img, f"avatars/{img.name}")

        size_mb = os.path.getsize(out_path) / 1024 / 1024
        names = ", ".join(manifest.get("agent_names", []))
        self.app.call_from_thread(
            self._result,
            f"[green]Export 완료![/green]\n\n"
            f"  파일: {out_path}\n"
            f"  크기: {size_mb:.1f} MB\n"
            f"  에이전트: {manifest['agents']}명 ({names})\n"
            f"  메시지: {manifest['messages']:,}건"
        )

    # ── Import ──

    def _do_import(self):
        def on_path(zip_path: str):
            if not zip_path or not os.path.exists(zip_path):
                self._result("[red]파일 없음[/red]" if zip_path else "")
                return
            self._preview_and_import(zip_path)
        self.app.push_screen(
            InputDialog("가져올 .glimi.zip 파일 경로", placeholder="/path/to/community.glimi.zip"),
            on_path,
        )

    def _preview_and_import(self, zip_path: str):
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = zf.namelist()
                has_db = "community.db" in names
                avatars = [n for n in names if n.startswith("avatars/")]
                manifest = {}
                if "manifest.json" in names:
                    manifest = json.loads(zf.read("manifest.json"))
        except Exception as e:
            self._result(f"[red]zip 읽기 실패: {e}[/red]")
            return

        if not has_db:
            self._result("[red]DB가 없는 패키지[/red]")
            return

        preview = "[bold]패키지 내용[/bold]\n"
        if manifest:
            preview += f"  원본: {manifest.get('community_id', '?')}\n"
            preview += f"  에이전트: {manifest.get('agents', '?')}명\n"
            preview += f"  메시지: {manifest.get('messages', 0):,}건\n"
            if manifest.get("agent_names"):
                preview += f"  이름: {', '.join(manifest['agent_names'])}\n"
        preview += f"  아바타: {len(avatars)}개\n"
        self._result(preview)

        default_id = manifest.get("community_id", "imported")

        def on_id(cid: str):
            if not cid:
                return
            if (community.COMMUNITIES_DIR / cid).exists():
                def on_overwrite(yes: bool):
                    if yes:
                        self._run_import(zip_path, cid)
                self.app.push_screen(
                    ConfirmDialog(f"[yellow]'{cid}'가 이미 존재합니다. 덮어쓸까요?[/yellow]"),
                    on_overwrite,
                )
            else:
                self._run_import(zip_path, cid)

        self.app.push_screen(
            InputDialog("커뮤니티 ID", placeholder=default_id),
            on_id,
        )

    @work(thread=True)
    def _run_import(self, zip_path: str, cid: str):
        self.app.call_from_thread(self._result, "[dim]가져오는 중...[/dim]")
        community.init_community(cid, copy_assets=False)
        cdir = community.COMMUNITIES_DIR / cid

        with zipfile.ZipFile(zip_path, "r") as zf:
            if "community.db" in zf.namelist():
                zf.extract("community.db", str(cdir))
            for name in zf.namelist():
                if name.startswith("avatars/"):
                    zf.extract(name, str(cdir))

        stats = _get_db_stats(cid) or {}
        self.app.call_from_thread(
            self._result,
            f"[green]Import 완료![/green]\n\n"
            f"  커뮤니티: {cid}\n"
            f"  에이전트: {stats.get('agents', 0)}명\n"
            f"  메시지: {stats.get('messages', 0):,}건\n\n"
            f"  [dim]토큰 설정: 관리 메뉴에서 설정하세요.[/dim]"
        )

    # ── Apply External DB ──

    def _do_apply_db(self):
        def on_path(db_path: str):
            if not db_path or not os.path.exists(db_path):
                self._result("[red]파일 없음[/red]" if db_path else "")
                return
            self._preview_and_apply_db(db_path)
        self.app.push_screen(
            InputDialog("DB 파일 경로", placeholder="/path/to/community.db"),
            on_path,
        )

    def _preview_and_apply_db(self, db_path: str):
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            tables = [r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()]
            agents = []
            if "agents" in tables:
                agents = [dict(r) for r in conn.execute("SELECT id, name, type FROM agents").fetchall()]
            msg_count = 0
            if "conversations" in tables:
                msg_count = conn.execute("SELECT COUNT(*) as c FROM conversations").fetchone()["c"]
            conn.close()
        except Exception as e:
            self._result(f"[red]DB 읽기 실패: {e}[/red]")
            return

        is_old = "agent_personality" not in tables
        preview = f"[bold]DB 미리보기[/bold]\n"
        preview += f"  테이블: {len(tables)}개\n"
        preview += f"  에이전트: {len(agents)}명\n"
        preview += f"  메시지: {msg_count:,}건\n"
        preview += f"  형식: {'[yellow]이전 형식[/yellow]' if is_old else '[green]현재 형식[/green]'}\n"
        for a in agents[:5]:
            preview += f"    {a['name']} ({a['type']})\n"
        if len(agents) > 5:
            preview += f"    ... 외 {len(agents) - 5}명\n"
        self._result(preview)

        def on_id(cid: str):
            if not cid:
                return
            self._run_apply_db(db_path, cid, is_old)

        self.app.push_screen(
            InputDialog("적용할 커뮤니티 ID", placeholder="my-server"),
            on_id,
        )

    @work(thread=True)
    def _run_apply_db(self, db_path: str, cid: str, is_old: bool):
        self.app.call_from_thread(self._result, "[dim]적용 중...[/dim]")

        if not (community.COMMUNITIES_DIR / cid).exists():
            community.init_community(cid)

        target = community.COMMUNITIES_DIR / cid / "community.db"
        if target.exists():
            backup = str(target) + f".backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            shutil.copy2(target, backup)

        shutil.copy2(db_path, target)

        if is_old:
            env = os.environ.copy()
            env["GLIMI_COMMUNITY"] = cid
            result = subprocess.run(
                [_venv_python(), "-m", "src.tools.migrate", "--upgrade-db", str(target)],
                capture_output=True, text=True, env=env,
                cwd=str(PROJECT_ROOT),
            )
            output = (result.stdout or "").strip()
            lines = [l for l in output.split("\n") if l.strip()][-8:]
            msg = "\n".join(lines)
        else:
            msg = "현재 형식 DB — 그대로 적용됨"

        stats = _get_db_stats(cid) or {}
        self.app.call_from_thread(
            self._result,
            f"[green]적용 완료![/green]\n\n"
            f"  커뮤니티: {cid}\n"
            f"  에이전트: {stats.get('agents', 0)}명\n"
            f"  메시지: {stats.get('messages', 0):,}건\n\n"
            f"{msg}"
        )

    def action_go_back(self):
        self.app.pop_screen()


# ══════════════════════════════════════════════════════════
# Wizard App
# ══════════════════════════════════════════════════════════

class GlimiWizard(App):
    TITLE = "Project Glimi"
    SUB_TITLE = "Community Wizard"
    CSS = WIZARD_CSS
    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
    ]

    def on_mount(self):
        self.push_screen(MainScreen())


# ══════════════════════════════════════════════════════════

def main():
    try:
        app = GlimiWizard()
        result = app.run()
    except Exception as e:
        import traceback
        from src import log_writer
        try:
            log_writer.error(f"[Wizard] 크래시: {e}", e)
        except Exception:
            pass
        traceback.print_exc()
        sys.exit(1)

    # wizard에서 대시보드 전환 요청 시 대시보드 실행
    if isinstance(result, tuple) and result[0] == "dashboard":
        community_id = result[1]
        py = _venv_python()
        os.execvp(py, [py, "-m", "src.tui.dashboard", community_id])


if __name__ == "__main__":
    main()
