"""Glimi Workspace 앱 (apps/workspace) 단위 테스트 — 커널-온리 두 번째 앱.

검증:
  - **setup 해석**: flag → env → state file → default 우선순위. 비대화형(non-TTY)
    에서는 절대 input() 으로 막히지 않고 default 로 떨어진다 (CI 안전).
  - **flow**: echo 백엔드로 전체 워크스페이스를 돌리면 Coordinator + 3 specialist 가
    하나의 공유 채널에 turn 을 남기고, 최종 deliverable 을 반환한다.
  - **dashboard 통합**: 작업 후 store 가 Core 대시보드를 채운다 —
    create_app(DashboardReader(g.store)) 의 /api/snapshot 이 Coordinator + 3
    specialist 를 모두 나열한다. (--serve 와 같은 store-driven 경로, 블로킹 없음.)
  - **kernel-only**: apps/workspace 가 discord / src 를 import 하지 않는다.

web 부분은 fastapi 가 있어야 하므로 ``pytest.importorskip("fastapi")`` 로 가드.

실행:
    PYTHONPATH=<worktree> python -m pytest tests/unit/test_glimi_workspace.py -q
"""
from __future__ import annotations

import os
import re
import sys

import pytest

# Worktree root (<wt>/tests/unit/this → up 3) + apps/workspace on sys.path so the
# app's flat modules (run / team) import the same way the script does.
_WORKTREE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_APP_DIR = os.path.join(_WORKTREE, "apps", "workspace")
if _APP_DIR not in sys.path:
    sys.path.insert(0, _APP_DIR)
if _WORKTREE not in sys.path:
    sys.path.insert(0, _WORKTREE)


# ────────────────────────────────────────────────────
# kernel 전역 복원 — 다른 Glimi 테스트와 동일 패턴
# ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _restore_kernel_globals():
    from glimi import memory as _memory
    from glimi import runtime as _runtime
    saved = {
        "r_store": _runtime._store, "r_profiles": _runtime._profiles,
        "r_owner": _runtime._owner, "r_observer": _runtime._observer,
        "m_store": _memory._store, "m_profiles": _memory._profiles,
        "m_owner": _memory._owner, "m_observer": _memory._observer,
        "env": os.environ.get("GLIMI_LLM_BACKEND"),
        "wsname": os.environ.get("GLIMI_WORKSPACE_NAME"),
        "wsgoal": os.environ.get("GLIMI_WORKSPACE_GOAL"),
    }
    yield
    _runtime.set_store(saved["r_store"]); _runtime.set_profiles(saved["r_profiles"])
    _runtime.set_owner(saved["r_owner"]); _runtime.set_observer(saved["r_observer"])
    _memory.set_store(saved["m_store"]); _memory.set_profiles(saved["m_profiles"])
    _memory.set_owner(saved["m_owner"]); _memory.set_observer(saved["m_observer"])
    for key, val in (("GLIMI_LLM_BACKEND", saved["env"]),
                     ("GLIMI_WORKSPACE_NAME", saved["wsname"]),
                     ("GLIMI_WORKSPACE_GOAL", saved["wsgoal"])):
        if val is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = val


# ────────────────────────────────────────────────────
# setup 해석 — flag / env / state / default + non-TTY 안전
# ────────────────────────────────────────────────────

def test_setup_flags_win(tmp_path):
    import team
    s = team.resolve_setup(name_flag="Alice", goal_flag="Ship it",
                           state_path=tmp_path / "s.json", interactive=False)
    assert (s.owner_name, s.name_source) == ("Alice", "flag")
    assert (s.goal, s.goal_source) == ("Ship it", "flag")


def test_setup_env_then_default(tmp_path, monkeypatch):
    import team
    monkeypatch.setenv("GLIMI_WORKSPACE_NAME", "Bob")
    monkeypatch.delenv("GLIMI_WORKSPACE_GOAL", raising=False)
    s = team.resolve_setup(state_path=tmp_path / "s.json", interactive=False)
    assert (s.owner_name, s.name_source) == ("Bob", "env")
    # goal has no flag/env/state → default (NOT a prompt, since non-interactive)
    assert (s.goal, s.goal_source) == (team.DEFAULT_GOAL, "default")


def test_setup_non_interactive_never_prompts(tmp_path, monkeypatch):
    """The whole point: non-TTY runs fall back to defaults, never input()."""
    import builtins
    import team

    def _boom(*a, **k):  # input() must never be called
        raise AssertionError("resolve_setup called input() in non-interactive mode")

    monkeypatch.setattr(builtins, "input", _boom)
    monkeypatch.delenv("GLIMI_WORKSPACE_NAME", raising=False)
    monkeypatch.delenv("GLIMI_WORKSPACE_GOAL", raising=False)
    s = team.resolve_setup(state_path=tmp_path / "s.json", interactive=False)
    assert s.owner_name == team.DEFAULT_OWNER_NAME
    assert s.goal == team.DEFAULT_GOAL
    assert not s.is_first_run  # nothing persisted in non-interactive default path


def test_setup_reads_saved_state(tmp_path):
    import team
    path = tmp_path / "s.json"
    path.write_text('{"owner_name": "Carol", "goal": "Win"}', encoding="utf-8")
    s = team.resolve_setup(state_path=path, interactive=False)
    assert (s.owner_name, s.name_source) == ("Carol", "state")
    assert (s.goal, s.goal_source) == ("Win", "state")


# ────────────────────────────────────────────────────
# flow — echo 백엔드 전체 실행
# ────────────────────────────────────────────────────

def test_run_workspace_echo_flow(capsys):
    """Full echo run via main(): exit 0, every member contributes, one channel."""
    import run

    rc = run.main(["--name", "Owner", "--goal", "Plan our launch", "--backend", "echo"])
    assert rc == 0
    out = capsys.readouterr().out
    # banner + every member label printed
    assert "Glimi Workspace" in out
    for label in ("Coordinator:", "Researcher:", "Builder:", "Critic:"):
        assert label in out
    # the deliverable + summary printed
    assert "Deliverable for Owner:" in out
    assert "one shared store" in out


def test_run_workspace_one_shared_channel():
    """All members work on a single shared channel (shared store)."""
    import run
    from glimi import Glimi

    g = Glimi(backend="echo", owner_name="Owner")
    for aid, name, agent_type, persona in run.TEAM:
        g.add_agent(aid, name=name, persona=persona, agent_type=agent_type)
    final = run.run_workspace(g, "Owner", "Plan our launch")

    assert final  # a deliverable came back
    # Coordinator (1 greet + 1 deliver) + 3 specialists * 2 rounds = 8 agent turns,
    # +2 owner prompts logged → 10 messages, all in ONE channel.
    log = g.history("coordinator", channel=run.WORKSPACE, limit=999)
    assert len(log) == 10
    # no per-agent DM channels were created — everything is on the shared channel
    overview = {c["channel"] for c in g.store.get_channel_overview()}
    assert overview == {run.WORKSPACE}


# ────────────────────────────────────────────────────
# dashboard 통합 — store 가 Core 대시보드를 채운다 (--serve 경로)
# ────────────────────────────────────────────────────

def test_workspace_populates_core_dashboard():
    """After a run, the SAME store-driven Core dashboard lists the whole team.

    This mirrors what ``--serve`` does (serve(g.store)) without binding a port:
    build create_app(DashboardReader(g.store)) and assert /api/snapshot carries
    the Coordinator + the three specialists.
    """
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient
    from glimi import Glimi
    from glimi.dashboard import DashboardReader
    from glimi.dashboard.app import create_app

    import run

    g = Glimi(backend="echo", owner_name="Owner")
    for aid, name, agent_type, persona in run.TEAM:
        g.add_agent(aid, name=name, persona=persona, agent_type=agent_type)
    run.run_workspace(g, "Owner", "Plan our launch")

    client = TestClient(create_app(DashboardReader(g.store)))
    snap = client.get("/api/snapshot").json()
    ids = {a["id"] for a in snap["agents"]}
    assert {"coordinator", "researcher", "builder", "critic"} <= ids
    # the Coordinator is the manager (ranked first, type mgr)
    coordinator = next(a for a in snap["agents"] if a["id"] == "coordinator")
    assert coordinator["type"] == "mgr"
    # the shared workspace channel shows up with the team's turns
    chans = {c["channel"]: c for c in snap["channels"]}
    assert run.WORKSPACE in chans
    assert chans[run.WORKSPACE]["msg_count"] >= 1


# ────────────────────────────────────────────────────
# kernel-only — discord / src import 금지
# ────────────────────────────────────────────────────

def test_app_is_kernel_only():
    """apps/workspace imports nothing from discord or the Community app (src)."""
    forbidden = re.compile(r"^\s*(import\s+discord|from\s+src|import\s+src)\b", re.M)
    for fname in ("run.py", "team.py", "__init__.py"):
        path = os.path.join(_APP_DIR, fname)
        with open(path, encoding="utf-8") as fh:
            assert not forbidden.search(fh.read()), f"{fname} imports discord/src"
