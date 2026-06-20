"""Demo-by-default + read-only mockup gate — focused unit tests.

Covers:
  (a) community.community.is_read_only + list_communities surfaces `read_only`.
  (b) the seed refactor is import-safe (importing has zero side effects) and
      `seed()` is callable with the documented signature.
  (c) community.platform.demo_seed.ensure_demo_seeded is idempotent — a second call
      no-ops when communities/demo/ already exists.

All filesystem state is redirected to a tmp dir via monkeypatch so nothing
touches the real communities/ tree.
"""
import importlib
import inspect

import pytest


# ── (a) read_only flag: is_read_only + list_communities ───────────────────────

@pytest.fixture
def isolated_communities(monkeypatch, tmp_path):
    """Point community.community at a tmp communities/ dir (+ registry) for the test."""
    from community import community as comm

    cdir = tmp_path / "communities"
    cdir.mkdir(parents=True, exist_ok=True)
    registry = cdir / "registry.toml"
    monkeypatch.setattr(comm, "COMMUNITIES_DIR", cdir)
    monkeypatch.setattr(comm, "REGISTRY_PATH", registry)
    # Reset the cached current id so get_community_id resolves fresh.
    monkeypatch.setattr(comm, "_current_id", None)
    monkeypatch.delenv("GLIMI_COMMUNITY", raising=False)
    return comm, cdir, registry


def _write_registry(registry_path, body: str) -> None:
    registry_path.write_text(body, encoding="utf-8")


def test_is_read_only_true_when_flagged(isolated_communities):
    comm, cdir, registry = isolated_communities
    (cdir / "demo").mkdir()
    _write_registry(registry, (
        'default = "demo"\n\n'
        '[community.demo]\n'
        'name = "데모"\n'
        'description = "mockup"\n'
        'language = "ko"\n'
        'read_only = true\n'
    ))
    assert comm.is_read_only("demo") is True


def test_is_read_only_false_by_default(isolated_communities):
    comm, cdir, registry = isolated_communities
    (cdir / "live").mkdir()
    _write_registry(registry, (
        'default = "live"\n\n'
        '[community.live]\n'
        'name = "Live"\n'
        'description = ""\n'
        'language = "en"\n'
    ))
    # No read_only key → False. Unknown community → also False.
    assert comm.is_read_only("live") is False
    assert comm.is_read_only("nope") is False


def test_list_communities_surfaces_read_only(isolated_communities):
    comm, cdir, registry = isolated_communities
    (cdir / "demo").mkdir()
    (cdir / "live").mkdir()
    _write_registry(registry, (
        'default = "live"\n\n'
        '[community.demo]\n'
        'name = "데모"\n'
        'description = "mockup"\n'
        'language = "ko"\n'
        'read_only = true\n\n'
        '[community.live]\n'
        'name = "Live"\n'
        'description = ""\n'
        'language = "en"\n'
    ))
    by_id = {c["id"]: c for c in comm.list_communities()}
    assert by_id["demo"]["read_only"] is True
    assert by_id["live"]["read_only"] is False
    # every dict carries the key (default False)
    assert all("read_only" in c for c in by_id.values())


# ── (b) seed import-safety + callable ─────────────────────────────────────────

@pytest.mark.parametrize("modname,default_id", [
    ("scripts.seed_demo_mockup", "demo"),
    ("scripts.seed_demo_mockup_en", "demo-en"),
])
def test_seed_module_is_import_safe_and_callable(modname, default_id, tmp_path, monkeypatch):
    """Importing the seed module must have ZERO side effects (no communities/
    dir, no DB) and expose a callable `seed(community_id=...)`."""
    # Run in a throwaway cwd so any accidental top-level write would be visible
    # here (and not pollute the repo).
    monkeypatch.chdir(tmp_path)
    mod = importlib.import_module(modname)
    importlib.reload(mod)  # force the module body to re-execute under this cwd

    assert callable(mod.seed)
    sig = inspect.signature(mod.seed)
    params = list(sig.parameters.values())
    assert params and params[0].name == "community_id"
    assert params[0].default == default_id

    # Import did not create a communities/ tree in the throwaway cwd.
    assert not (tmp_path / "communities").exists()


# ── (c) ensure_demo_seeded idempotency ────────────────────────────────────────

def test_ensure_demo_seeded_sets_readonly_on_existing_demo(monkeypatch, tmp_path):
    """If communities/demo/ already exists, ensure_demo_seeded must NOT re-seed
    (returns False, seed() never called) but MUST still ensure the registry marks
    demo read_only — so an existing demo (e.g. a live server's) becomes read-only
    on deploy."""
    from community import community as comm
    from community.platform import demo_seed

    cdir = tmp_path / "communities"
    (cdir / "demo").mkdir(parents=True)
    registry = cdir / "registry.toml"
    monkeypatch.setattr(comm, "COMMUNITIES_DIR", cdir)
    monkeypatch.setattr(comm, "REGISTRY_PATH", registry)
    monkeypatch.setattr(demo_seed, "COMMUNITIES_DIR", cdir)
    monkeypatch.setattr(demo_seed, "REGISTRY_PATH", registry)

    # Tripwire: the real seed must never be called when demo/ already exists.
    called = {"seed": False}

    def _boom(_id):  # pragma: no cover - should not run
        called["seed"] = True
        raise AssertionError("seed() must not be called when demo/ exists")

    monkeypatch.setattr("scripts.seed_demo_mockup.seed", _boom)

    # Not newly seeded …
    assert demo_seed.ensure_demo_seeded() is False
    assert called["seed"] is False
    # … but the existing demo is now flagged read-only in the registry.
    assert comm.is_read_only("demo") is True


def test_ensure_demo_seeded_seeds_then_registers(monkeypatch, tmp_path):
    """First run: demo/ absent → seed() is called, then registry.toml gets the
    demo block with language=ko + read_only=true. Second call no-ops."""
    from community import community as comm
    from community.platform import demo_seed

    cdir = tmp_path / "communities"
    cdir.mkdir(parents=True)
    registry = cdir / "registry.toml"
    monkeypatch.setattr(comm, "COMMUNITIES_DIR", cdir)
    monkeypatch.setattr(comm, "REGISTRY_PATH", registry)
    monkeypatch.setattr(demo_seed, "COMMUNITIES_DIR", cdir)
    monkeypatch.setattr(demo_seed, "REGISTRY_PATH", registry)

    seed_calls = []

    def _fake_seed(cid):
        # Emulate the real seed's directory creation side effect (the part
        # ensure_demo_seeded's idempotency guard checks).
        seed_calls.append(cid)
        (cdir / cid).mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("scripts.seed_demo_mockup.seed", _fake_seed)

    first = demo_seed.ensure_demo_seeded()
    assert first is True
    assert seed_calls == ["demo"]

    # Registry now carries the demo block flagged read-only + ko.
    assert comm.is_read_only("demo") is True
    by_id = {c["id"]: c for c in comm.list_communities()}
    assert by_id["demo"]["read_only"] is True
    # language ko surfaced via get_language when scoped to demo
    monkeypatch.setattr(comm, "_current_id", "demo")
    assert comm.get_language() == "ko"

    # Idempotent: a second call no-ops (demo/ now exists) and doesn't re-seed.
    second = demo_seed.ensure_demo_seeded()
    assert second is False
    assert seed_calls == ["demo"]
