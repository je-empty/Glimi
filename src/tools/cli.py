#!/usr/bin/env python3
"""
Project Glimi — CLI 테스트 인터페이스 (rich UI)
"""
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich.columns import Columns
from rich.prompt import Prompt, IntPrompt
from rich.rule import Rule
from rich.live import Live
from rich.align import Align
from rich import box

from src import db
from src.core.profile import (
    load_profile, list_all_profiles, register_all_to_db, setup_initial_relationships,
    get_user_name, get_user_id,
)
from src.core.runtime import runtime, CLAUDE_AVAILABLE

console = Console()

# ── 색상 매핑 ─────────────────────────────────────────

AGENT_COLORS = {
    "agent-persona-001": "bright_magenta",   # 은하윤
    "agent-persona-002": "bright_red",       # 최지수
    "agent-persona-003": "bright_cyan",      # 최서연
    "agent-mgr-001": "bright_blue",          # 서유나
    "agent-creator-001": "bright_yellow",    # 윤하나
}

TYPE_EMOJI = {"persona": "💬", "mgr": "📋", "creator": "🎨"}
EMOTION_EMOJI = {
    "기쁨": "😊", "평온": "😌", "서운함": "😢", "화남": "😠",
    "설렘": "💗", "불안": "😰", "신남": "🤩", "슬픔": "😥",
}


def _name(agent_id: str) -> str:
    if agent_id == get_user_id():
        return get_user_name()
    agent = db.get_agent(agent_id)
    return agent["name"] if agent else agent_id


def _color(agent_id: str) -> str:
    return AGENT_COLORS.get(agent_id, "white")


# ── 헤더 ─────────────────────────────────────────────

def print_header():
    mode_text = "[green]실제 대화[/green]" if CLAUDE_AVAILABLE else "[yellow]placeholder[/yellow]"

    header = Text()
    header.append("  ◈  ", style="bright_magenta bold")
    header.append("Project Glimi", style="bold bright_white")
    header.append("  ◈", style="bright_magenta bold")

    console.print()
    console.print(Panel(
        Align.center(header),
        subtitle=f"모드: {mode_text}",
        border_style="bright_magenta",
        box=box.DOUBLE,
        padding=(1, 4),
    ))


# ── 에이전트 목록 ────────────────────────────────────

def print_agents() -> list[dict]:
    agents = db.list_agents()

    table = Table(
        title="에이전트 목록",
        box=box.ROUNDED,
        border_style="dim",
        title_style="bold",
        show_lines=True,
        padding=(0, 1),
    )
    table.add_column("#", style="dim", width=3, justify="center")
    table.add_column("", width=2)
    table.add_column("이름", style="bold", min_width=8)
    table.add_column("유형", min_width=6)
    table.add_column("감정", min_width=12)
    table.add_column("상태", justify="center", width=4)

    for i, a in enumerate(agents, 1):
        emoji = TYPE_EMOJI.get(a["type"], "?")
        emotion = a["current_emotion"]
        e_emoji = EMOTION_EMOJI.get(emotion, "")
        intensity_bar = "●" * (a["emotion_intensity"] // 2) + "○" * (5 - a["emotion_intensity"] // 2)
        status = "[green]●[/green]" if a["status"] == "active" else "[dim]○[/dim]"
        color = _color(a["id"])

        table.add_row(
            str(i),
            emoji,
            f"[{color}]{a['name']}[/{color}]",
            a["type"],
            f"{e_emoji} {emotion} [{intensity_bar}]",
            status,
        )

    console.print(table)
    return agents


# ── 관계 현황 ────────────────────────────────────────

def print_relationships():
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM relationships ORDER BY intimacy_score DESC").fetchall()
    conn.close()

    table = Table(
        title="관계 현황",
        box=box.ROUNDED,
        border_style="dim",
        title_style="bold",
        show_lines=True,
    )
    table.add_column("A", style="bold", min_width=8)
    table.add_column("↔", justify="center", width=3)
    table.add_column("B", style="bold", min_width=8)
    table.add_column("관계", min_width=10)
    table.add_column("친밀도", min_width=16)

    for r in rows:
        a = _name(r["agent_a"])
        b = _name(r["agent_b"])
        score = r["intimacy_score"]

        # 친밀도 바
        filled = score // 10
        bar = f"[bright_magenta]{'█' * filled}[/bright_magenta][dim]{'░' * (10 - filled)}[/dim] {score}"

        table.add_row(a, "↔", b, r["type"], bar)

    console.print(table)


# ── 프로필 상세 ──────────────────────────────────────

def print_profile(agent_id: str):
    profile = load_profile(agent_id)
    if not profile:
        console.print("[red]프로필을 찾을 수 없습니다[/red]")
        return

    color = _color(agent_id)
    name = profile["name"]

    info_parts = []
    info_parts.append(f"[bold]나이:[/bold] {profile.get('age', '?')}살 ({profile.get('birth_year', '?')}년생)")
    info_parts.append(f"[bold]MBTI:[/bold] {profile.get('mbti', '?')}")

    if "personality" in profile:
        traits = ", ".join(profile["personality"].get("traits", []))
        info_parts.append(f"[bold]성격:[/bold] {traits}")

    if "appearance" in profile:
        info_parts.append(f"[bold]외모:[/bold] {profile['appearance'].get('summary', '')}")

    if "speech" in profile:
        info_parts.append(f"[bold]말투:[/bold] {profile['speech'].get('style_description', '')}")

    if "relationship_to_owner" in profile:
        rel = profile["relationship_to_owner"]
        info_parts.append(f"[bold]관계:[/bold] {rel['type']} ({rel.get('duration', '')})")

    content = "\n".join(info_parts)

    console.print(Panel(
        content,
        title=f"[{color} bold]{name}[/{color} bold]",
        border_style=color,
        box=box.ROUNDED,
        padding=(1, 2),
    ))


# ── 1:1 대화 모드 ───────────────────────────────────

def chat_mode(agent_id: str):
    profile = load_profile(agent_id)
    if not profile:
        console.print("[red]프로필 없음[/red]")
        return

    name = profile["name"]
    color = _color(agent_id)
    channel = f"dm-{name}"
    runtime.activate_agent(agent_id)

    console.print()
    console.print(Panel(
        f"[{color}]{name}[/{color}]과(와) 대화를 시작합니다\n"
        f"[dim]채널: {channel}[/dim]\n\n"
        f"[dim italic]나가기: /quit  ·  감정변경: /emotion 감정 강도  ·  프로필: /profile[/dim]",
        border_style=color,
        box=box.ROUNDED,
    ))

    while True:
        try:
            console.print()
            user_input = Prompt.ask(f"  [bold bright_green]{get_user_name()}[/bold bright_green]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break

        if not user_input:
            continue

        if user_input == "/quit":
            console.print(f"\n  [dim]{name}과(와) 대화 종료[/dim]")
            break

        if user_input == "/profile":
            print_profile(agent_id)
            continue

        if user_input.startswith("/emotion "):
            parts = user_input.split(" ", 2)
            if len(parts) >= 3 and parts[2].isdigit():
                emotion, intensity = parts[1], int(parts[2])
                db.update_emotion(agent_id, emotion, intensity)
                runtime.refresh_agent(agent_id)
                e_emoji = EMOTION_EMOJI.get(emotion, "")
                console.print(f"  [dim]→ {name} 감정 변경: {e_emoji} {emotion} ({intensity}/10)[/dim]")
            else:
                console.print("  [dim]사용법: /emotion 감정이름 강도(1-10)[/dim]")
            continue

        if user_input.startswith("/"):
            console.print("  [dim]알 수 없는 명령어[/dim]")
            continue

        # 응답 생성
        responses = runtime.generate_response(agent_id, channel, user_input)
        for i, msg in enumerate(responses):
            if i > 0:
                time.sleep(0.3)
            console.print(f"  [{color} bold]{name}[/{color} bold]  {msg}")


# ── 관리자 보고 ──────────────────────────────────────

def dashboard_mode():
    mgr_id = "agent-mgr-001"
    runtime.activate_agent(mgr_id)
    profile = load_profile(mgr_id)
    name = profile["name"] if profile else "관리자"
    color = _color(mgr_id)

    console.print()
    console.print(Panel(
        f"[{color}]{name}[/{color}] 관리자 대시보드\n"
        f"[dim italic]나가기: /quit[/dim]",
        border_style=color,
        box=box.ROUNDED,
    ))

    while True:
        try:
            console.print()
            user_input = Prompt.ask(f"  [bold bright_green]{get_user_name()}[/bold bright_green]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break

        if user_input == "/quit":
            break
        if not user_input:
            continue

        responses = runtime.generate_response(mgr_id, "mgr-dashboard", user_input)
        for msg in responses:
            console.print(f"  [{color} bold]{name}[/{color} bold]  {msg}")
            time.sleep(0.2)


# ── 에이전트 간 대화 ─────────────────────────────────

def internal_chat_mode():
    agents = [a for a in db.list_agents() if a["type"] == "persona"]

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("#", style="dim", width=3)
    table.add_column("이름", style="bold")
    for i, a in enumerate(agents, 1):
        table.add_row(str(i), f"[{_color(a['id'])}]{a['name']}[/{_color(a['id'])}]")
    console.print(table)

    try:
        s = IntPrompt.ask("  말하는 에이전트", choices=[str(i) for i in range(1, len(agents) + 1)])
        l = IntPrompt.ask("  듣는 에이전트", choices=[str(i) for i in range(1, len(agents) + 1)])

        if s == l:
            console.print("  [red]같은 에이전트를 선택했습니다[/red]")
            return

        speaker = agents[s - 1]
        listener = agents[l - 1]
        channel = f"internal-{speaker['name']}-{listener['name']}"

        context = Prompt.ask("  상황 설명 [dim](엔터=자유 대화)[/dim]", default="")

        sc = _color(speaker["id"])
        console.print(Rule(
            f"[{sc}]{speaker['name']}[/{sc}] → [{_color(listener['id'])}]{listener['name']}[/{_color(listener['id'])}]",
            style="dim",
        ))

        responses = runtime.generate_agent_to_agent(
            speaker["id"], listener["id"], channel, context
        )
        for msg in responses:
            console.print(f"  [{sc} bold]{speaker['name']}[/{sc} bold]  {msg}")
            time.sleep(0.3)

    except (EOFError, KeyboardInterrupt, ValueError):
        console.print()


# ── 대화 로그 ────────────────────────────────────────

def view_log():
    conn = db.get_conn()
    channels = conn.execute(
        "SELECT DISTINCT channel, COUNT(*) as cnt FROM conversations GROUP BY channel ORDER BY channel"
    ).fetchall()
    conn.close()

    if not channels:
        console.print("  [dim]대화 기록이 없습니다[/dim]")
        return

    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
    table.add_column("#", style="dim", width=3)
    table.add_column("채널")
    table.add_column("메시지 수", style="dim", justify="right")
    for i, c in enumerate(channels, 1):
        table.add_row(str(i), c["channel"], str(c["cnt"]))
    console.print(table)

    try:
        idx = Prompt.ask("  채널 번호").strip()
        if idx.isdigit() and 1 <= int(idx) <= len(channels):
            channel = channels[int(idx) - 1]["channel"]
        else:
            channel = idx

        messages = db.get_recent_messages(channel, limit=30)
        if messages:
            console.print(Rule(channel, style="dim"))
            for m in messages:
                speaker = _name(m["speaker"])
                ts = m["timestamp"][11:16] if m["timestamp"] else ""
                sid = m["speaker"]
                color = _color(sid) if sid != get_user_id() else "bright_green"
                console.print(f"  [dim]{ts}[/dim]  [{color} bold]{speaker}[/{color} bold]  {m['message']}")
        else:
            console.print(f"  [dim]{channel}에 기록 없음[/dim]")
    except (EOFError, KeyboardInterrupt):
        console.print()


# ── 메인 메뉴 ────────────────────────────────────────

MENU = """
  [bold bright_magenta]1[/bold bright_magenta]  에이전트 목록        [bold bright_magenta]4[/bold bright_magenta]  관리자 보고
  [bold bright_magenta]2[/bold bright_magenta]  1:1 대화             [bold bright_magenta]5[/bold bright_magenta]  에이전트 간 대화
  [bold bright_magenta]3[/bold bright_magenta]  관계 현황            [bold bright_magenta]6[/bold bright_magenta]  대화 로그
  [dim]q  종료[/dim]"""


def main():
    db.init_db()
    register_all_to_db()
    setup_initial_relationships()

    print_header()

    while True:
        console.print(Panel(MENU, border_style="dim", box=box.ROUNDED, padding=(0, 2)))

        try:
            choice = Prompt.ask("[bright_magenta]>[/bright_magenta]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n  [dim]Glimi 종료[/dim]\n")
            break

        if choice == "1":
            print_agents()

        elif choice == "2":
            agents = print_agents()
            try:
                idx = IntPrompt.ask(
                    "  대화할 에이전트",
                    choices=[str(i) for i in range(1, len(agents) + 1)]
                )
                chat_mode(agents[idx - 1]["id"])
            except (EOFError, KeyboardInterrupt, ValueError):
                console.print()

        elif choice == "3":
            print_relationships()

        elif choice == "4":
            dashboard_mode()

        elif choice == "5":
            internal_chat_mode()

        elif choice == "6":
            view_log()

        elif choice in ("q", "Q"):
            console.print("\n  [dim]Glimi 종료[/dim]\n")
            break


if __name__ == "__main__":
    main()
