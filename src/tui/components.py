"""
Project Chaos — 공통 TUI 컴포넌트
"""
from textual import on
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Static, Button, RichLog


class LoadingOverlay(ModalScreen):
    """로딩 + 실시간 로그 오버레이"""

    DEFAULT_CSS = """
    LoadingOverlay {
        align: center middle;
        background: rgba(0, 0, 0, 0.7);
    }
    LoadingOverlay > Vertical {
        width: 50;
        height: auto;
        background: $panel;
        border: round $accent;
        padding: 1 2;
        content-align: center middle;
    }
    LoadingOverlay > Vertical.has-log {
        width: 75;
        max-height: 35;
    }
    LoadingOverlay #loading-title {
        text-align: center;
        padding: 1 0;
        text-style: bold;
    }
    LoadingOverlay RichLog {
        height: auto;
        max-height: 25;
        border: round $primary-darken-2;
        padding: 0 1;
        margin: 1 0;
        display: none;
    }
    """

    def __init__(self, message: str = "로딩 중..."):
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"⏳ {self._message}", id="loading-title", markup=True)
            yield RichLog(id="loading-log", markup=True, wrap=True)

    def update_message(self, message: str):
        try:
            self.query_one("#loading-title", Static).update(f"⏳ {message}")
        except Exception:
            pass

    def update_detail(self, detail: str):
        """실시간 로그 추가 (첫 줄부터 자동 표시)"""
        try:
            log = self.query_one("#loading-log", RichLog)
            if not log.display:
                log.display = True
                self.query_one("Vertical").add_class("has-log")
            log.write(f"[dim]{detail}[/dim]")
        except Exception:
            pass


class ConfirmDialog(ModalScreen[bool]):
    """확인/취소 다이얼로그"""

    DEFAULT_CSS = """
    ConfirmDialog {
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }
    ConfirmDialog > Vertical {
        width: 60;
        height: auto;
        max-height: 20;
        background: $panel;
        border: round $warning;
        padding: 1 2;
    }
    ConfirmDialog .action-bar {
        height: 3;
        margin: 1 0 0 0;
    }
    ConfirmDialog .action-bar Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel", "No"),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, message: str, danger: bool = False):
        super().__init__()
        self._message = message
        self._danger = danger

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(self._message, markup=True)
            yield Static("")
            with Horizontal(classes="action-bar"):
                if self._danger:
                    yield Button("Yes", variant="error", id="yes")
                else:
                    yield Button("Yes", variant="primary", id="yes")
                yield Button("No", variant="default", id="no")
            yield Static("[dim]Y / N[/dim]", markup=True)

    @on(Button.Pressed, "#yes")
    def on_yes(self):
        self.dismiss(True)

    @on(Button.Pressed, "#no")
    def on_no(self):
        self.dismiss(False)

    def action_confirm(self):
        self.dismiss(True)

    def action_cancel(self):
        self.dismiss(False)


class MessageActionDialog(ModalScreen[str]):
    """메시지 액션 선택 다이얼로그"""

    DEFAULT_CSS = """
    MessageActionDialog {
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }
    MessageActionDialog > Vertical {
        width: 65;
        height: auto;
        max-height: 24;
        background: $panel;
        border: round $accent;
        padding: 1 2;
    }
    MessageActionDialog .action-bar {
        height: 3;
        margin: 1 0 0 0;
    }
    MessageActionDialog .action-bar Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("d", "delete", "Delete"),
    ]

    def __init__(self, speaker: str, message: str, msg_id: str, channel: str):
        super().__init__()
        self._speaker = speaker
        self._message = message
        self._msg_id = msg_id
        self._channel = channel

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(
                f"[bold]{self._speaker}[/bold]\n"
                f"{self._message}\n\n"
                f"[dim]#{self._msg_id} · {self._channel}[/dim]",
                markup=True,
            )
            yield Static("")
            with Horizontal(classes="action-bar"):
                yield Button("Delete", variant="error", id="act-delete")
                yield Button("Cancel", variant="default", id="act-cancel")
            yield Static("[dim]D 삭제 / ESC 취소[/dim]", markup=True)

    @on(Button.Pressed, "#act-delete")
    def on_delete(self):
        self.dismiss("delete")

    @on(Button.Pressed, "#act-cancel")
    def on_cancel_btn(self):
        self.dismiss("")

    def action_delete(self):
        self.dismiss("delete")

    def action_cancel(self):
        self.dismiss("")


class ErrorDialog(ModalScreen[str]):
    """에러 표시 + 자동 수정 요청"""

    DEFAULT_CSS = """
    ErrorDialog {
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }
    ErrorDialog > Vertical {
        width: 75;
        height: auto;
        max-height: 30;
        background: $panel;
        border: round $error;
        padding: 1 2;
    }
    ErrorDialog RichLog {
        height: auto;
        max-height: 15;
        border: round $primary-darken-2;
        padding: 0 1;
        margin: 1 0;
    }
    ErrorDialog .action-bar {
        height: 3;
        margin: 1 0 0 0;
    }
    ErrorDialog .action-bar Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "닫기"),
        Binding("f", "fix", "자동 수정"),
    ]

    def __init__(self, title: str, error_msg: str, context: str = ""):
        super().__init__()
        self._title = title
        self._error_msg = error_msg
        self._context = context

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(f"[red bold]❌ {self._title}[/red bold]", markup=True)
            log = RichLog(id="error-log", markup=True, wrap=True)
            yield log
            with Horizontal(classes="action-bar"):
                yield Button("Auto Fix (F)", variant="warning", id="err-fix")
                yield Button("Close (ESC)", variant="default", id="err-close")

    def on_mount(self):
        log = self.query_one("#error-log", RichLog)
        for line in self._error_msg.split("\n"):
            log.write(line)
        if self._context:
            log.write(f"\n[dim]{self._context}[/dim]")

    @on(Button.Pressed, "#err-fix")
    def on_fix(self):
        self.dismiss("fix")

    @on(Button.Pressed, "#err-close")
    def on_close_btn(self):
        self.dismiss("")

    def action_fix(self):
        self.dismiss("fix")

    def action_close(self):
        self.dismiss("")
