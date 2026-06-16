"""glimi.dashboard 웹 레이어 (glimi[dashboard]) 단위 테스트 — P1.1.

검증:
  - **zero-dep purity**: ``import glimi.dashboard`` (+ DashboardReader) 가 fastapi 를
    끌어오지 않는다 (별도 clean subprocess 로 sys.modules 확인). → 커널 base 무의존 유지.
  - **web app**: create_app(DashboardReader(store)) 의 read-only 엔드포인트가
    reader 출력과 모양이 맞고 (snapshot / agent_detail / channel), ``GET /`` 가
    그래프 컨테이너를 담은 HTML 을 돌려준다.
  - read-only: mutation/POST 엔드포인트가 없다.

web 테스트는 fastapi 가 있어야 하므로 ``pytest.importorskip`` 으로 가드 — extra 없이
커널 스위트만 돌려도 통과해야 함. purity 테스트는 deps 없이도 의미가 있으므로 항상 실행.

실행:
    PYTHONPATH=<worktree> python -m pytest tests/unit/test_glimi_dashboard_web.py -q
"""
from __future__ import annotations

import os
import subprocess
import sys

import pytest

# Worktree root (<wt>/tests/unit/this_file → up 3) — so the purity subprocess can
# resolve this checkout's ``glimi`` regardless of where pytest is invoked from.
_WORKTREE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ────────────────────────────────────────────────────
# fixture — population + 커널 전역 복원 (test_glimi_dashboard 와 동일 패턴)
# ────────────────────────────────────────────────────

@pytest.fixture
def population():
    from glimi import Glimi
    from glimi import memory as _memory
    from glimi import runtime as _runtime

    saved = {
        "r_store": _runtime._store, "r_profiles": _runtime._profiles,
        "r_owner": _runtime._owner, "r_observer": _runtime._observer,
        "m_store": _memory._store, "m_profiles": _memory._profiles,
        "m_owner": _memory._owner, "m_observer": _memory._observer,
        "env": os.environ.get("GLIMI_LLM_BACKEND"),
    }

    g = Glimi(backend="echo", owner_name="Owner", owner_id="owner")
    g.add_agent("hana", name="Hana", persona="Coordinator.", agent_type="mgr")
    g.add_agent("alice", name="Alice", persona="A curious companion.")
    g.add_agent("bob", name="Bob", persona="A calm friend.")
    g.reply("alice", "hi", channel="room")
    g.reply("bob", "hello", channel="room")
    g.store.add_memory("alice", "room", level=1, content="Owner said hi in room.",
                       importance=6)
    g.store.add_memory("alice", "room", level=2, content="Alice met Owner.",
                       importance=7, is_pinned=True)
    g.store.add_fact("alice", subject="Owner", predicate="likes", object_value="coffee")
    g.store.set_relationship("alice", "bob", rel_type="friend", intimacy=55)
    g.store.set_relationship("alice", "owner", rel_type="friend", intimacy=42)
    g.store.set_agent_emotion("alice", "cheerful", 6)

    yield g

    _runtime.set_store(saved["r_store"]); _runtime.set_profiles(saved["r_profiles"])
    _runtime.set_owner(saved["r_owner"]); _runtime.set_observer(saved["r_observer"])
    _memory.set_store(saved["m_store"]); _memory.set_profiles(saved["m_profiles"])
    _memory.set_owner(saved["m_owner"]); _memory.set_observer(saved["m_observer"])
    if saved["env"] is None:
        os.environ.pop("GLIMI_LLM_BACKEND", None)
    else:
        os.environ["GLIMI_LLM_BACKEND"] = saved["env"]


# ────────────────────────────────────────────────────
# zero-dep purity — 항상 실행 (extra 없이도 유효)
# ────────────────────────────────────────────────────

def test_dashboard_import_is_zero_dep():
    """clean subprocess 에서 glimi.dashboard + DashboardReader import 후 fastapi 미로딩.

    같은 프로세스 내 다른 테스트가 이미 fastapi 를 import 했을 수 있으니, 격리된
    subprocess 로 실행해서 ``glimi.dashboard`` 자체가 fastapi 를 끌어오지 않음을 증명.
    """
    code = (
        "import sys\n"
        "import glimi.dashboard\n"
        "from glimi.dashboard import DashboardReader\n"
        "assert 'fastapi' not in sys.modules, 'glimi.dashboard pulled in fastapi'\n"
        "assert 'uvicorn' not in sys.modules, 'glimi.dashboard pulled in uvicorn'\n"
        "print('reader zero-dep ok')\n"
    )
    env = dict(os.environ, PYTHONPATH=_WORKTREE)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_WORKTREE, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"purity subprocess failed:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}"
    )
    assert "reader zero-dep ok" in result.stdout


def test_serve_is_exported_without_importing_app():
    """serve 는 export 되지만, 그 존재만으로 app.py (fastapi) 를 import 하면 안 됨."""
    code = (
        "import sys\n"
        "import glimi.dashboard\n"
        "assert hasattr(glimi.dashboard, 'serve')\n"
        "assert 'glimi.dashboard.app' not in sys.modules, 'app.py imported at package import'\n"
        "assert 'fastapi' not in sys.modules\n"
        "print('serve lazy ok')\n"
    )
    env = dict(os.environ, PYTHONPATH=_WORKTREE)
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=_WORKTREE, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "serve lazy ok" in result.stdout


# ────────────────────────────────────────────────────
# web app — fastapi 있을 때만
# ────────────────────────────────────────────────────

@pytest.fixture
def client(population):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")  # fastapi's TestClient requires httpx
    from fastapi.testclient import TestClient
    from glimi.dashboard import DashboardReader
    from glimi.dashboard.app import create_app

    app = create_app(DashboardReader(population.store))
    return TestClient(app)


def test_index_serves_html_with_graph_container(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    body = r.text
    assert 'id="cy-graph"' in body            # the graph mount point
    assert "Connection Graph" in body
    assert "cytoscape" in body.lower()        # graph lib loaded
    assert "static/js/dashboard.js" in body


def test_static_assets_served(client):
    css = client.get("/static/css/tokens.css")
    assert css.status_code == 200
    assert "--accent" in css.text             # design tokens present
    js = client.get("/static/js/dashboard.js")
    assert js.status_code == 200
    assert "DashboardReader" in js.text or "snapshot" in js.text


def test_snapshot_endpoint(client):
    r = client.get("/api/snapshot")
    assert r.status_code == 200
    snap = r.json()
    assert set(snap) >= {"agents", "channels", "relationships"}
    ids = {a["id"] for a in snap["agents"]}
    assert {"hana", "alice", "bob"} <= ids
    # agent display fields the graph/grid consume
    a0 = snap["agents"][0]
    assert {"id", "name", "type"} <= set(a0)
    # owner enrichment for the client (graph owner node + message tagging)
    assert snap.get("owner_name")
    assert "owner" in (snap.get("owner_ids") or [])
    # relationships shaped as graph edges
    rels = snap["relationships"]
    assert rels and {"source", "target", "intimacy"} <= set(rels[0])
    # channels carry msg_count + participants for edge derivation
    chans = {c["channel"]: c for c in snap["channels"]}
    assert "room" in chans
    assert chans["room"]["msg_count"] >= 1


def test_agent_detail_endpoint(client):
    r = client.get("/api/agent_detail", params={"id": "alice"})
    assert r.status_code == 200
    d = r.json()
    assert d["id"] == "alice"
    # the modal's sections — memory keys, facts, relationships
    assert "memories_by_channel" in d
    assert "pinned_memories" in d
    assert "facts" in d
    assert "relationships" in d
    # seeded data shows up
    assert any(f["subject"] == "Owner" for f in d["facts"])
    assert any(r_["other_id"] in ("bob", "owner") for r_ in d["relationships"])
    # 5-layer memory present for the channel the agent spoke in
    assert "room" in d["memories_by_channel"]


def test_agent_detail_unknown_id(client):
    r = client.get("/api/agent_detail", params={"id": "nope"})
    assert r.status_code == 200          # read-only: degrade, don't 500
    assert r.json().get("error")


def test_channel_endpoint(client):
    r = client.get("/api/channel", params={"name": "room"})
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == "room"
    assert "participants" in d
    assert "messages" in d
    assert d["message_count"] == len(d["messages"])
    assert d["message_count"] >= 1
    # message rows carry what the viewer renders
    m0 = d["messages"][0]
    assert {"speaker", "message"} <= set(m0) or {"speaker_id", "message"} <= set(m0)


def test_no_mutation_endpoints(client):
    """read-only slice: POST/PUT/DELETE on the api surface are not routed."""
    assert client.post("/api/snapshot").status_code in (404, 405)
    assert client.post("/api/agent_detail", params={"id": "alice"}).status_code in (404, 405)
    # no action endpoints carried over from the Community dashboard
    assert client.post("/api/action/run_sync", json={}).status_code in (404, 405)


def test_create_app_rejects_non_reader():
    pytest.importorskip("fastapi")
    from glimi.dashboard.app import create_app
    with pytest.raises(TypeError):
        create_app(object())
