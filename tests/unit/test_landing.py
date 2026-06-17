"""The public showcase landing is host-gated by GLIMI_FRONT_HOST.

On the configured front host the root serves the no-login landing (links to the
demos); on any other host the root keeps the normal app behavior. Default (unset)
→ no landing, so the OSS default is unchanged.
"""
from __future__ import annotations

from starlette.testclient import TestClient

from src.platform import app as app_mod
from src.platform.routers import pages


def _client(base):
    return TestClient(app_mod.app, base_url=base)


def test_landing_served_on_front_host(monkeypatch):
    monkeypatch.setattr(pages, "_FRONT_HOST", "front.example")
    monkeypatch.setattr(pages, "_WORKSPACE_URL", "https://ws.example")
    monkeypatch.setattr(pages.setup_mod, "is_configured", lambda: True)
    with _client("http://front.example") as c:
        r = c.get("/", follow_redirects=False)
    assert r.status_code == 200
    assert "lw-card" in r.text  # the landing markup
    assert "https://ws.example" in r.text  # workspace demo link rendered


def test_other_host_is_not_landing(monkeypatch):
    monkeypatch.setattr(pages, "_FRONT_HOST", "front.example")
    monkeypatch.setattr(pages.setup_mod, "is_configured", lambda: True)
    with _client("http://community.example") as c:
        r = c.get("/", follow_redirects=False)
    # Not the landing — either a redirect (anon → demo/login) or the app home.
    assert not (r.status_code == 200 and "lw-card" in r.text)


def test_no_front_host_means_no_landing(monkeypatch):
    monkeypatch.setattr(pages, "_FRONT_HOST", "")
    monkeypatch.setattr(pages.setup_mod, "is_configured", lambda: True)
    with _client("http://front.example") as c:
        r = c.get("/", follow_redirects=False)
    assert not (r.status_code == 200 and "lw-card" in r.text)
