"""
Project Chaos — 공통 TUI 컴포넌트
"""
from textual.screen import ModalScreen
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static, LoadingIndicator


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
