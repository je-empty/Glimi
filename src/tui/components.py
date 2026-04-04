"""
Project Chaos — 공통 TUI 컴포넌트
"""
from textual import on
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.app import ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Static, LoadingIndicator, Button


class LoadingOverlay(ModalScreen):
    """로딩 중 다른 조작 차단하는 오버레이"""

    DEFAULT_CSS = """
    LoadingOverlay {
        align: center middle;
        background: rgba(0, 0, 0, 0.6);
    }
    LoadingOverlay > Vertical {
        width: 80;
        height: auto;
        max-height: 40;
        background: $panel;
        border: round $accent;
        padding: 1 2;
    }
    LoadingOverlay #loading-message {
        text-align: center;
        padding: 1 0;
    }
    LoadingOverlay #loading-log {
        height: auto;
        min-height: 5;
        max-height: 30;
        padding: 0 1;
    }
    """

    def __init__(self, message: str = "로딩 중..."):
        super().__init__()
        self._message = message
        self._log_lines: list[str] = []

    def compose(self) -> ComposeResult:
        with Vertical():
            yield LoadingIndicator()
            yield Static(self._message, id="loading-message", markup=True)
            yield Static("[dim]대기 중...[/dim]", id="loading-log", markup=True)

    def update_message(self, message: str):
        try:
            self.query_one("#loading-message", Static).update(message)
        except Exception:
            pass

    def update_detail(self, detail: str):
        """진행 로그 누적 표시"""
        self._log_lines.append(detail)
        visible = self._log_lines[-15:]
        try:
            log_widget = self.query_one("#loading-log", Static)
            log_widget.update("\n".join(f"[dim]{l}[/dim]" for l in visible))
            log_widget.refresh()
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
    """에러 발생 시 표시 — 닫기 또는 자동 수정 요청"""

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
        overflow-y: auto;
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
            yield Static(f"[red bold]❌ {self._title}[/red bold]\n", markup=True)
            yield Static(self._error_msg, markup=True)
            if self._context:
                yield Static(f"\n[dim]{self._context}[/dim]", markup=True)
            yield Static("")
            with Horizontal(classes="action-bar"):
                yield Button("Auto Fix", variant="warning", id="err-fix")
                yield Button("Close", variant="default", id="err-close")
            yield Static("[dim]F 자동수정 / ESC 닫기[/dim]", markup=True)

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
