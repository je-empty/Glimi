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
        width: 50;
        height: auto;
        max-height: 12;
        background: $panel;
        border: round $accent;
        padding: 1 2;
    }
    LoadingOverlay #loading-message {
        text-align: center;
        padding: 1 0;
    }
    LoadingOverlay #loading-detail {
        text-align: center;
        color: $text-muted;
    }
    """

    def __init__(self, message: str = "로딩 중..."):
        super().__init__()
        self._message = message

    def compose(self) -> ComposeResult:
        with Vertical():
            yield LoadingIndicator()
            yield Static(self._message, id="loading-message", markup=True)
            yield Static("", id="loading-detail", markup=True)

    def update_message(self, message: str):
        try:
            self.query_one("#loading-message", Static).update(message)
        except Exception:
            pass

    def update_detail(self, detail: str):
        try:
            self.query_one("#loading-detail", Static).update(f"[dim]{detail}[/dim]")
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
