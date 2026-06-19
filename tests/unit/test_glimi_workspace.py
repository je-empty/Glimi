"""Glimi Workspace 앱 (apps/workspace) 단위 테스트 — 커널-온리 두 번째 앱.

검증:
  - **setup 해석**: flag → env → state file → default 우선순위. 비대화형(non-TTY)
    에서는 절대 input() 으로 막히지 않고 default 로 떨어진다 (CI 안전).
  - **topology**: echo 백엔드로 전체 워크스페이스를 돌리면 owner↔Coordinator DM,
    Coordinator↔각 specialist delegation DM, specialist↔specialist 내부 A2A 채널,
    group 채널이 모두 store 에 남고, 최종 deliverable 을 반환한다 (멀티채널 상호작용).
  - **relationship web**: 작업 후 store 에 owner↔Coordinator(lead),
    Coordinator↔각 specialist(manages), specialist↔specialist(collaborator)
    관계가 기록된다 — 이게 대시보드 connection graph 의 엣지다.
  - **dashboard 통합 + graph**: 작업 후 store 가 Core 대시보드를 채운다 —
    /api/snapshot 이 Coordinator + 3 specialist + 상호작용 채널을 나열하고,
    snapshot()['relationships'] 가 비어있지 않으며 owner↔coordinator +
    specialist↔specialist 엣지를 포함한다 (그래프가 상호작용 웹을 그린다는 증명).
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
    """Full echo run via main(): exit 0, every member contributes, web printed."""
    import run

    rc = run.main(["--name", "Owner", "--goal", "Plan our launch", "--backend", "echo"])
    assert rc == 0
    out = capsys.readouterr().out
    # banner + every member printed (names come from team.py — language-agnostic)
    assert "Glimi Workspace" in out
    from team import TEAM
    for _id, name, _t, _p in TEAM:
        assert name in out, f"team member {name!r} missing from run output"
    # the deliverable + the interaction-web summary printed
    assert "Deliverable for Owner:" in out
    assert "interaction web" in out
    assert "relationships" in out  # the summary lists the graph edges


def test_run_workspace_multi_channel_topology():
    """The team works across a real interaction web — not one round-robin room.

    Owner↔Coordinator DM, per-specialist delegation DMs, specialist↔specialist
    internal A2A channels, and a group channel must all appear in the store.
    """
    import run
    import team
    from glimi import Glimi

    g = Glimi(backend="echo", owner_name="Owner")
    for aid, name, agent_type, persona in run.TEAM:
        g.add_agent(aid, name=name, persona=persona, agent_type=agent_type)
    final = run.run_workspace(g, "Owner", "Plan our launch")

    assert final  # a deliverable came back
    channels = {c["channel"] for c in g.store.get_channel_overview()}
    # the full interaction topology is present
    expected = {
        team.COORDINATOR_DM,
        *team.DELEGATION_CHANNELS.values(),
        *(ch for _, _, ch, _ in team.COLLAB_PAIRS),
        team.GROUP_CHANNEL,
    }
    assert expected <= channels
    # the internal A2A channels carry genuine agent-to-agent turns (both speakers)
    for a, b, ch, _ in team.COLLAB_PAIRS:
        speakers = {m["speaker"] for m in g.store.get_recent_messages(ch, limit=99)}
        assert {a, b} <= speakers, f"{ch} should carry both {a} and {b}"


def test_run_workspace_forms_relationship_web():
    """The run records the working relationships → the dashboard graph's edges.

    The store's relationships must include owner↔Coordinator (lead),
    Coordinator↔each specialist (manages), and specialist↔specialist
    (collaborator). These are exactly what the connection graph draws.
    """
    import run
    import team
    from glimi import Glimi

    g = Glimi(backend="echo", owner_name="Owner")
    for aid, name, agent_type, persona in run.TEAM:
        g.add_agent(aid, name=name, persona=persona, agent_type=agent_type)
    run.run_workspace(g, "Owner", "Plan our launch")

    owner_id = g.owner.id()

    # owner ↔ Coordinator (lead)
    lead = g.store.get_relationship("coordinator", owner_id)
    assert lead and lead["type"] == "lead"

    # Coordinator ↔ each specialist (manages)
    for sid in team.SPECIALISTS:
        rel = g.store.get_relationship("coordinator", sid)
        assert rel and rel["type"] == "manages"

    # specialist ↔ specialist (collaborator), one per collaborating pair
    for a, b, _, _ in team.COLLAB_PAIRS:
        rel = g.store.get_relationship(a, b)
        assert rel and rel["type"] == "collaborator"
        assert rel["intimacy_score"] > 0


# ────────────────────────────────────────────────────
# dashboard 통합 — store 가 Core 대시보드를 채운다 (--serve 경로)
# ────────────────────────────────────────────────────

def test_workspace_populates_core_dashboard():
    """After a run, the SAME store-driven Core dashboard lists the whole team.

    This mirrors what ``--serve`` does (serve(g.store)) without binding a port:
    build create_app(DashboardReader(g.store)) and assert /api/snapshot carries
    the Coordinator + the three specialists + the interaction channels.
    """
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")  # fastapi's TestClient requires httpx
    from fastapi.testclient import TestClient
    from glimi import Glimi
    from glimi.dashboard import DashboardReader
    from glimi.dashboard.app import create_app

    import run
    import team

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
    # the interaction channels show up with the team's turns
    chans = {c["channel"]: c for c in snap["channels"]}
    assert team.COORDINATOR_DM in chans
    assert team.GROUP_CHANNEL in chans
    assert chans[team.COORDINATOR_DM]["msg_count"] >= 1


def test_snapshot_relationships_populate_graph():
    """THE key assertion: after a run, snapshot()['relationships'] is NON-EMPTY
    and carries owner↔coordinator + at least one specialist↔specialist edge.

    This is what proves the interaction web shows up in the dashboard's
    connection graph — the graph's edges come straight from these relationships.
    """
    from glimi import Glimi
    from glimi.dashboard import DashboardReader

    import run
    import team

    g = Glimi(backend="echo", owner_name="Owner")
    for aid, name, agent_type, persona in run.TEAM:
        g.add_agent(aid, name=name, persona=persona, agent_type=agent_type)
    run.run_workspace(g, "Owner", "Plan our launch")

    owner_id = g.owner.id()
    rels = DashboardReader(g.store).snapshot()["relationships"]
    assert rels, "snapshot() must expose relationships — the graph would be empty"

    # represent each edge as an unordered {source, target} pair → type
    edges = {frozenset((e["source"], e["target"])): e["type"] for e in rels}

    # owner ↔ Coordinator edge is present
    assert frozenset(("coordinator", owner_id)) in edges

    # at least one specialist ↔ specialist collaboration edge is present
    collab = [
        e for e in rels
        if e["type"] == "collaborator"
        and {e["source"], e["target"]} <= set(team.SPECIALISTS)
    ]
    assert collab, "expected ≥1 specialist↔specialist collaboration edge in the graph"


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
