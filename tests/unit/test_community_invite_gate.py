"""Community invite gate (the chat-enabled, invite-only 'demo-live' presenter).

Covers the security-critical bits without spinning the whole platform app:
  - registry flag is_invite_required (+ stays orthogonal to read_only)
  - invite_gate.invite_ok: token (query/cookie) and owner (CF header)
  - target isolation: a workspace-target token must NEVER count as a community token
  - ensure_demo_live_seeded clones demo → demo-live with the right flags + real-model .env
"""
from __future__ import annotations

import pytest


# ── registry flag ────────────────────────────────────────────────────────────

def test_is_invite_required_flag_and_orthogonality(tmp_path, monkeypatch):
    import src.community as community
    reg = tmp_path / "registry.toml"
    reg.write_text(
        '[community.demo]\nname = "d"\nlanguage = "ko"\nread_only = true\n'
        '[community.demo-live]\nname = "dl"\nlanguage = "ko"\nread_only = true\ninvite_required = true\n'
        '[community.real]\nname = "r"\nlanguage = "ko"\nread_only = false\n',
        encoding="utf-8")
    monkeypatch.setattr(community, "REGISTRY_PATH", reg)
    assert community.is_invite_required("demo-live") is True
    assert community.is_invite_required("demo") is False       # public demo: not gated
    assert community.is_invite_required("real") is False       # normal community: not gated
    assert community.is_read_only("demo-live") is True         # still browsable by anon


# ── invite_gate predicate ────────────────────────────────────────────────────

class _Scope:
    """Minimal stand-in for a Starlette Request/WebSocket (query/cookies/headers)."""
    def __init__(self, query=None, cookies=None, headers=None):
        from starlette.datastructures import Headers
        self.query_params = query or {}
        self.cookies = cookies or {}
        self.headers = Headers(headers or {})


def test_invite_ok_token_query_and_cookie(monkeypatch):
    from src.platform import invite_gate
    monkeypatch.setenv("GLIMI_INVITE_TOKENS", "GOOD")
    monkeypatch.delenv("GLIMI_OWNER_EMAIL", raising=False)
    monkeypatch.delenv("GLIMI_INVITES_STORE", raising=False)
    assert invite_gate.invite_ok(_Scope(query={"invite": "GOOD"})) is True
    assert invite_gate.invite_ok(_Scope(cookies={"glimi_invite": "GOOD"})) is True
    assert invite_gate.invite_ok(_Scope(query={"invite": "BAD"})) is False
    assert invite_gate.invite_ok(_Scope()) is False            # no token → blocked


def test_invite_ok_owner_via_cf_header(monkeypatch):
    from src.platform import invite_gate
    monkeypatch.setenv("GLIMI_OWNER_EMAIL", "me@x.com")
    monkeypatch.delenv("GLIMI_INVITE_TOKENS", raising=False)
    monkeypatch.delenv("GLIMI_INVITES_STORE", raising=False)
    assert invite_gate.invite_ok(
        _Scope(headers={"Cf-Access-Authenticated-User-Email": "me@x.com"})) is True
    assert invite_gate.invite_ok(
        _Scope(headers={"Cf-Access-Authenticated-User-Email": "other@x.com"})) is False


def test_community_tokens_ignore_workspace_target(monkeypatch, tmp_path):
    # The shared store is target-tagged; a workspace token must not unlock community.
    from src.platform import invite_gate
    from glimi.dashboard import invites
    monkeypatch.delenv("GLIMI_INVITE_TOKENS", raising=False)
    monkeypatch.setenv("GLIMI_INVITES_STORE", str(tmp_path / "t.json"))
    c = invites.issue("alice", "continue", "community")["token"]
    invites.issue("bob", "continue", "workspace")  # different target
    toks = invite_gate.community_tokens()
    assert toks == {c}                                          # only the community one


# ── demo-live clone ──────────────────────────────────────────────────────────

def test_ensure_demo_live_clones_with_flags(tmp_path, monkeypatch):
    import src.community as community
    from src.platform import demo_seed
    cdir = tmp_path / "communities-demo"
    (cdir / "demo").mkdir(parents=True)
    (cdir / "demo" / "community.db").write_text("db", encoding="utf-8")
    (cdir / "demo" / ".env").write_text("DISCORD_BOT_TOKEN=mockup-no-token\n", encoding="utf-8")
    reg = cdir / "registry.toml"
    reg.write_text('default = "demo"\n\n[community.demo]\nname = "내 커뮤니티"\n'
                   'language = "ko"\nread_only = true\n', encoding="utf-8")
    for mod in (community, demo_seed):
        monkeypatch.setattr(mod, "COMMUNITIES_DIR", cdir)
        monkeypatch.setattr(mod, "REGISTRY_PATH", reg)

    assert demo_seed.ensure_demo_live_seeded() is True          # cloned
    live = cdir / "demo-live"
    assert (live / "community.db").exists()                     # friends + history copied
    env = (live / ".env").read_text(encoding="utf-8")
    assert "GLIMI_LLM_BACKEND=ollama" in env                    # real local model wired
    assert community.is_invite_required("demo-live") is True
    assert community.is_read_only("demo-live") is True
    assert demo_seed.ensure_demo_live_seeded() is False         # idempotent (already exists)


def test_ensure_demo_live_noop_without_demo(tmp_path, monkeypatch):
    # On an instance that has no public demo (e.g. the owner's real-use server),
    # nothing is created.
    import src.community as community
    from src.platform import demo_seed
    cdir = tmp_path / "communities"
    cdir.mkdir()
    reg = cdir / "registry.toml"
    reg.write_text('default = "real"\n', encoding="utf-8")
    for mod in (community, demo_seed):
        monkeypatch.setattr(mod, "COMMUNITIES_DIR", cdir)
        monkeypatch.setattr(mod, "REGISTRY_PATH", reg)
    assert demo_seed.ensure_demo_live_seeded() is False
    assert not (cdir / "demo-live").exists()
