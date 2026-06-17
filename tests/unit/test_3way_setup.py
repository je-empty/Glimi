"""Three-way model setup (Claude-only / Hybrid / Local-only).

Honest framing: the free runtime is local models (Ollama). Claude-backed agents
cost metered API credits, so Claude-only + Hybrid carry a monthly cap; Local-only
is all-$0 (no cap). Hybrid is the recommended default — personas (the highest-
volume spender) route to local Ollama while mgr/creator/dev stay on Claude.

These tests pin the shared helper's env output, that apply_setup accepts the new
modes against an isolated .env, and that the community-create path accepts hybrid.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.platform import setup as setup_mod


# ── shared helper: backend_mode_to_env ──────────────────────────────


def test_hybrid_env_has_agent_map_cap_tier():
    env = setup_mod.backend_mode_to_env("hybrid", "quality", 20)
    # valid JSON agent map, personas → ollama, mgr → claude
    assert "GLIMI_LLM_AGENT_MAP" in env
    amap = json.loads(env["GLIMI_LLM_AGENT_MAP"])  # must be valid JSON
    assert amap["persona"] == "ollama"
    assert amap["_default"] == "ollama"
    assert amap["mgr"] == "claude"
    assert amap["creator"] == "claude"
    assert amap["dev"] == "claude"
    # cap + tier present; hybrid does NOT force a global backend
    assert env["GLIMI_MONTHLY_CAP_USD"] == "20"
    assert env["GLIMI_LOCAL_TIER"] == "quality"
    assert "GLIMI_LLM_BACKEND" not in env


def test_claude_env_has_cap_no_backend_force():
    env = setup_mod.backend_mode_to_env("claude", "standard", 35)
    assert env["GLIMI_MONTHLY_CAP_USD"] == "35"
    # claude = default backend; backend explicitly cleared (no ollama force), no agent map
    assert env["GLIMI_LLM_BACKEND"] == ""
    assert "GLIMI_LLM_AGENT_MAP" not in env


def test_local_env_forces_ollama_tier_no_cap():
    env = setup_mod.backend_mode_to_env("local", "lite", 20)
    assert env["GLIMI_LLM_BACKEND"] == "ollama"
    assert env["GLIMI_LOCAL_TIER"] == "lite"
    # local is all-$0 → no monthly cap written
    assert "GLIMI_MONTHLY_CAP_USD" not in env


def test_cloud_alias_maps_to_claude():
    env = setup_mod.backend_mode_to_env("cloud", "standard", 20)
    assert env["GLIMI_MONTHLY_CAP_USD"] == "20"
    assert env["GLIMI_LLM_BACKEND"] == ""


def test_invalid_mode_raises():
    with pytest.raises(ValueError):
        setup_mod.backend_mode_to_env("nonsense", "standard", 20)


def test_default_cap_is_20():
    env = setup_mod.backend_mode_to_env("claude")
    assert env["GLIMI_MONTHLY_CAP_USD"] == str(setup_mod.DEFAULT_MONTHLY_CAP_USD) == "20"


# ── apply_setup: accepts the three modes, writes the right .env ──────


@pytest.fixture()
def isolated_setup(tmp_path, monkeypatch):
    """Point apply_setup at a temp .env + marker and stub admin bootstrap."""
    env_file = tmp_path / ".env"
    marker = tmp_path / ".setup_complete"
    monkeypatch.setattr(setup_mod, "ENV_PATH", env_file)
    monkeypatch.setattr(setup_mod, "SETUP_MARKER", marker)
    monkeypatch.setattr(setup_mod, "mark_configured", lambda: marker.write_text("ok\n"))
    # don't touch the real platform DB
    monkeypatch.setattr(setup_mod.accounts, "bootstrap", lambda: None)
    # claude creds present so the steering warning doesn't fire for claude/hybrid
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    return env_file


def _env_dict(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for ln in path.read_text(encoding="utf-8").splitlines():
        if "=" in ln and not ln.lstrip().startswith("#"):
            k, v = ln.split("=", 1)
            v = v.strip()
            # dotenv.set_key quotes values; upsert_env does not — strip if present.
            if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
                v = v[1:-1]
            out[k.strip()] = v
    return out


def test_apply_setup_accepts_hybrid(isolated_setup):
    res = setup_mod.apply_setup(
        backend="hybrid", admin_password="abcd", api_key="sk-ant-test",
        tier="standard", monthly_cap_usd=20,
    )
    assert res["needs_local_download"] is True  # hybrid needs Ollama for personas
    env = _env_dict(isolated_setup)
    assert "GLIMI_LLM_AGENT_MAP" in env
    amap = json.loads(env["GLIMI_LLM_AGENT_MAP"])
    assert amap["persona"] == "ollama" and amap["mgr"] == "claude"
    assert env["GLIMI_MONTHLY_CAP_USD"] == "20"
    assert env["GLIMI_LOCAL_TIER"] == "standard"


def test_apply_setup_accepts_claude(isolated_setup):
    res = setup_mod.apply_setup(
        backend="claude", admin_password="abcd", api_key="sk-ant-test",
        monthly_cap_usd=20,
    )
    assert res["needs_local_download"] is False
    env = _env_dict(isolated_setup)
    assert env["GLIMI_MONTHLY_CAP_USD"] == "20"
    assert env["GLIMI_LLM_BACKEND"] == ""  # default claude, no ollama force


def test_apply_setup_accepts_local(isolated_setup):
    res = setup_mod.apply_setup(
        backend="local", admin_password="abcd", tier="lite",
    )
    assert res["needs_local_download"] is True
    env = _env_dict(isolated_setup)
    assert env["GLIMI_LLM_BACKEND"] == "ollama"
    assert env["GLIMI_LOCAL_TIER"] == "lite"
    assert "GLIMI_MONTHLY_CAP_USD" not in env


def test_apply_setup_rejects_bad_mode(isolated_setup):
    with pytest.raises(ValueError):
        setup_mod.apply_setup(backend="bogus", admin_password="abcd")


def test_apply_setup_steers_when_no_claude_creds(isolated_setup, monkeypatch):
    # no key + no working CLI → warn rather than silently mis-configure
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(setup_mod, "claude_creds_available", lambda api_key="": False)
    res = setup_mod.apply_setup(
        backend="hybrid", admin_password="abcd", use_cli=True, tier="standard",
    )
    assert res["warnings"]  # a steering warning was surfaced


# ── community create path accepts hybrid ────────────────────────────


def test_community_create_in_accepts_hybrid():
    from src.platform.routers.communities import CreateCommunityIn, _VALID_MODEL_MODES

    assert "hybrid" in _VALID_MODEL_MODES
    model = CreateCommunityIn(
        id="t", token="x", owner={"name": "n"},
        model_mode="hybrid", model_tier="standard", model_monthly_cap_usd=20,
    )
    assert model.model_mode == "hybrid"


def test_write_community_model_hybrid(tmp_path):
    from src.platform.routers.communities import _write_community_model

    env_path = str(tmp_path / "community.env")
    Path(env_path).touch()
    _write_community_model(env_path, "hybrid", "sk-ant-test", "standard", 15)
    env = _env_dict(Path(env_path))
    assert "GLIMI_LLM_AGENT_MAP" in env
    amap = json.loads(env["GLIMI_LLM_AGENT_MAP"])
    assert amap["persona"] == "ollama" and amap["mgr"] == "claude"
    assert env["GLIMI_LOCAL_TIER"] == "standard"
    assert env["GLIMI_MONTHLY_CAP_USD"] == "15"
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"
