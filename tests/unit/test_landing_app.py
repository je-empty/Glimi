"""Tests for the standalone landing portal (apps/landing).

Kernel-light: imports the app's ``server`` module + FastAPI's TestClient, plus
``glimi`` (for the canonical static path). Never ``src`` / Discord.
"""
from __future__ import annotations

import os
import sys

import pytest

# CI installs the kernel only; fastapi/httpx (TestClient) may be absent → skip.
pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient

# Import via the PACKAGE path (apps.landing.server), NOT a flat ``import server``:
# apps/workspace also has a flat server.py, and a flat ``import server`` here would
# poison that module name for the workspace tests (one cached `server` wins).
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from apps.landing import server  # noqa: E402


@pytest.fixture()
def client():
    return TestClient(server.create_app())


def test_landing_renders_ko_default(client):
    r = client.get("/")
    assert r.status_code == 200
    body = r.text
    assert "Glimi" in body
    # KO default (primary audience): Korean copy + browse CTA.
    assert "둘러보기" in body
    # It's a portal, NOT a per-workspace dashboard → no data-api-base.
    assert "data-api-base" not in body


def test_landing_lang_en(client):
    r = client.get("/?lang=en")
    assert r.status_code == 200
    assert "Browse" in r.text
    assert "둘러보기" not in r.text


def test_landing_links_come_from_env(monkeypatch):
    # Link targets are read per-request from env → deployment decides routing.
    monkeypatch.setenv("GLIMI_COMMUNITY_URL", "https://glimi-community.example/community/demo")
    monkeypatch.setenv("GLIMI_WORKSPACE_URL", "https://glimi-workspace.example/w/demo")
    c = TestClient(server.create_app())
    body = c.get("/").text
    assert "https://glimi-community.example/community/demo" in body
    assert "https://glimi-workspace.example/w/demo" in body


def test_landing_no_workspace_card_when_unset(monkeypatch):
    # Workspace card is conditional on the env URL being set.
    monkeypatch.delenv("GLIMI_WORKSPACE_URL", raising=False)
    c = TestClient(server.create_app())
    body = c.get("/").text
    assert "glimi-workspace" not in body  # no workspace card rendered


def test_healthz(client):
    assert client.get("/healthz").json() == {"ok": True}


# ── central token-admin panel (community + workspace) ────────────────────────

def test_admin_disabled_without_password(monkeypatch):
    monkeypatch.delenv("GLIMI_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("GLIMI_ADMIN_PW_FILE", raising=False)
    monkeypatch.delenv("GLIMI_ADMIN_SECRET", raising=False)
    c = TestClient(server.create_app())
    assert "비활성화" in c.get("/admin").text
    # issue rejected when not authed
    assert c.post("/admin/issue", data={"label": "x", "target": "community"}).status_code == 403


def test_admin_first_run_web_setup(monkeypatch, tmp_path):
    pwf = tmp_path / "admin_pw"
    monkeypatch.delenv("GLIMI_ADMIN_PASSWORD", raising=False)
    monkeypatch.setenv("GLIMI_ADMIN_PW_FILE", str(pwf))          # setup-file path → enabled
    monkeypatch.setenv("GLIMI_INVITES_STORE", str(tmp_path / "t.json"))
    c = TestClient(server.create_app())
    # first visit → first-run setup form (zero SSH)
    assert "첫 설정" in c.get("/admin").text
    # too-short rejected
    assert "e=2" in c.post("/admin/setup", data={"password": "abc"},
                           follow_redirects=False).headers["location"]
    # valid → password file written + session cookie
    ok = c.post("/admin/setup", data={"password": "secret123"}, follow_redirects=False)
    assert ok.status_code == 303 and "glimi_admin" in ok.headers.get("set-cookie", "")
    from glimi.dashboard import invites
    assert pwf.exists() and invites.needs_setup() is False
    assert invites.check_password("secret123") is True
    # re-setup refused (no web takeover once a password exists)
    assert "e=2" in c.post("/admin/setup", data={"password": "other999"},
                           follow_redirects=False).headers["location"]


def test_admin_login_issue_target_and_revoke(monkeypatch, tmp_path):
    from glimi.dashboard import invites
    monkeypatch.setenv("GLIMI_ADMIN_PASSWORD", "pw123")
    monkeypatch.setenv("GLIMI_INVITES_STORE", str(tmp_path / "tok.json"))
    monkeypatch.setenv("GLIMI_COMMUNITY_URL", "https://glimi-community.example/community/demo")
    monkeypatch.setenv("GLIMI_WORKSPACE_URL", "https://glimi-workspace.example/w/demo")
    c = TestClient(server.create_app())
    # not authed → login form; wrong pw → error flag
    assert "로그인" in c.get("/admin").text
    assert "e=1" in c.post("/admin/login", data={"password": "nope"},
                           follow_redirects=False).headers["location"]
    # right pw → session cookie (carried by the TestClient)
    ok = c.post("/admin/login", data={"password": "pw123"}, follow_redirects=False)
    assert "glimi_admin" in ok.headers.get("set-cookie", "")
    # issue a COMMUNITY-target token → stored with that target
    c.post("/admin/issue", data={"label": "alice", "kind": "continue", "target": "community"})
    toks = invites.list_tokens()
    assert len(toks) == 1 and toks[0]["target"] == "community"
    tok = toks[0]["token"]
    # the panel renders the community link (built from GLIMI_COMMUNITY_URL), not the workspace one
    panel = c.get("/admin").text
    assert f"https://glimi-community.example/community/demo?invite={tok}" in panel
    # revoke → gone
    c.post("/admin/revoke", data={"token": tok})
    assert invites.list_tokens() == []


def test_logo_route(client):
    # The repo ships resources/Glimi-logo.svg|png; if present it's served as an
    # image, otherwise the route still answers (404) — never 500.
    r = client.get("/logo")
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert r.headers["content-type"].startswith("image/")
