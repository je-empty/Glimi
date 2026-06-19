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


def test_logo_route(client):
    # The repo ships resources/Glimi-logo.svg|png; if present it's served as an
    # image, otherwise the route still answers (404) — never 500.
    r = client.get("/logo")
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert r.headers["content-type"].startswith("image/")
