"""Store-level fact supersession coverage via D1's ``InMemoryKernelStore``.

D4 (#9) covered the pure memory logic but NOT fact supersession
(``valid_from`` / ``valid_to``), because supersession lives in the
``KernelStore`` implementation — specifically ``InMemoryKernelStore.add_fact``
(``glimi/stores/memory.py``) — not in a pure function. This module exercises
that contract end-to-end, LLM-free, against the real store.

Contract learned from the source (do not assume field names):
- A fact row keys the value under ``"object"`` (not ``object_value``).
- "current / active" == ``valid_to is None``; superseded == ``valid_to`` set.
- ``get_facts(..., include_invalid=False)`` (the default) returns only active
  facts; ``include_invalid=True`` returns history too (nothing is deleted).
- Re-adding the SAME (subject, predicate, object) is idempotent: it returns the
  existing fact id and does not supersede.

Run::

    PYTHONPATH=<repo> python -m pytest tests/unit/test_glimi_supersession.py -q
"""
from glimi import InMemoryKernelStore

AGENT = "agent-1"


def _by_object(facts):
    """Map fact ``object`` -> row, for order-independent assertions."""
    return {f["object"]: f for f in facts}


def test_adding_fact_makes_it_current():
    store = InMemoryKernelStore()
    fid = store.add_fact(AGENT, "user", "favorite_color", "blue")
    assert isinstance(fid, int)

    active = store.get_facts(AGENT)
    assert len(active) == 1
    row = active[0]
    assert row["subject"] == "user"
    assert row["predicate"] == "favorite_color"
    assert row["object"] == "blue"
    # Current facts are the ones with no close-out timestamp.
    assert row["valid_to"] is None
    assert row["valid_from"] is not None


def test_contradicting_fact_supersedes_prior():
    store = InMemoryKernelStore()
    old_id = store.add_fact(AGENT, "user", "favorite_color", "blue")
    new_id = store.add_fact(AGENT, "user", "favorite_color", "green")

    assert new_id != old_id

    # Only the new value is "current".
    active = store.get_facts(AGENT)
    assert len(active) == 1
    assert active[0]["id"] == new_id
    assert active[0]["object"] == "green"
    assert active[0]["valid_to"] is None

    # The prior fact is marked superseded: valid_to is now set, and it is
    # excluded from the default (current-only) query.
    all_rows = _by_object(store.get_facts(AGENT, include_invalid=True))
    assert all_rows["blue"]["id"] == old_id
    assert all_rows["blue"]["valid_to"] is not None


def test_superseded_fact_history_is_preserved():
    store = InMemoryKernelStore()
    store.add_fact(AGENT, "user", "favorite_color", "blue")
    store.add_fact(AGENT, "user", "favorite_color", "green")

    # Current view hides the old value...
    assert {f["object"] for f in store.get_facts(AGENT)} == {"green"}

    # ...but the superseded fact is still retrievable (not deleted).
    history = store.get_facts(AGENT, include_invalid=True)
    objects = {f["object"] for f in history}
    assert objects == {"blue", "green"}
    assert len(history) == 2


def test_supersession_chain_keeps_only_latest_active():
    store = InMemoryKernelStore()
    store.add_fact(AGENT, "user", "favorite_color", "blue")
    store.add_fact(AGENT, "user", "favorite_color", "green")
    last_id = store.add_fact(AGENT, "user", "favorite_color", "red")

    active = store.get_facts(AGENT)
    assert len(active) == 1
    assert active[0]["id"] == last_id
    assert active[0]["object"] == "red"

    # All three values survive in history; the two older ones are closed out.
    history = _by_object(store.get_facts(AGENT, include_invalid=True))
    assert set(history) == {"blue", "green", "red"}
    assert history["blue"]["valid_to"] is not None
    assert history["green"]["valid_to"] is not None
    assert history["red"]["valid_to"] is None


def test_readding_same_value_is_idempotent_no_supersession():
    store = InMemoryKernelStore()
    fid = store.add_fact(AGENT, "user", "favorite_color", "blue")
    again = store.add_fact(AGENT, "user", "favorite_color", "blue")

    # Re-asserting the same value returns the existing row, creates no new one,
    # and does not close out the original.
    assert again == fid
    history = store.get_facts(AGENT, include_invalid=True)
    assert len(history) == 1
    assert history[0]["valid_to"] is None


def test_different_predicate_coexists_without_superseding():
    store = InMemoryKernelStore()
    color_id = store.add_fact(AGENT, "user", "favorite_color", "blue")
    food_id = store.add_fact(AGENT, "user", "favorite_food", "pizza")

    assert color_id != food_id

    # Different predicate on the same subject does NOT supersede.
    active = _by_object(store.get_facts(AGENT))
    assert set(active) == {"blue", "pizza"}
    assert active["blue"]["valid_to"] is None
    assert active["pizza"]["valid_to"] is None


def test_different_subject_coexists_without_superseding():
    store = InMemoryKernelStore()
    store.add_fact(AGENT, "user", "favorite_color", "blue")
    store.add_fact(AGENT, "alice", "favorite_color", "green")

    # Same predicate but different subject must not collide.
    active = _by_object(store.get_facts(AGENT))
    assert set(active) == {"blue", "green"}
    assert active["blue"]["subject"] == "user"
    assert active["green"]["subject"] == "alice"
    assert active["blue"]["valid_to"] is None
    assert active["green"]["valid_to"] is None


def test_facts_are_isolated_per_agent():
    store = InMemoryKernelStore()
    store.add_fact("agent-a", "user", "favorite_color", "blue")
    store.add_fact("agent-b", "user", "favorite_color", "green")

    # Supersession is scoped to (agent, subject, predicate) — agent-b's fact
    # must not close out agent-a's.
    a = store.get_facts("agent-a")
    b = store.get_facts("agent-b")
    assert {f["object"] for f in a} == {"blue"}
    assert {f["object"] for f in b} == {"green"}
    assert a[0]["valid_to"] is None
    assert b[0]["valid_to"] is None


def test_subject_filter_returns_only_matching_subject():
    store = InMemoryKernelStore()
    store.add_fact(AGENT, "user", "favorite_color", "blue")
    store.add_fact(AGENT, "alice", "favorite_color", "green")

    only_user = store.get_facts(AGENT, subject="user")
    assert {f["object"] for f in only_user} == {"blue"}
    assert all(f["subject"] == "user" for f in only_user)
