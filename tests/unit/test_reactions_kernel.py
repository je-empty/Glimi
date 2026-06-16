"""Kernel-side coverage for reactions/replies (Phase 2-3, no DB).

  - InMemoryKernelStore: reactions add/remove idempotency + UNIQUE,
    get_reactions/get_reactions_for, set_reply/get_thread, log_message id
    return + reply thread_root denormalization, get_recent_messages reactions.
  - memory.record_reaction_signal: routes a positive reaction through the
    EXISTING update_intimacy pipeline once, NOT twice (double-count guard);
    no-op when no relationship / non-positive emoji.
  - runtime._build_reactions_reminder: the awareness block appears ONLY when
    the agent's own recent messages have reactions.

실행:
    PYTHONPATH=<worktree> python -m pytest tests/unit/test_reactions_kernel.py -q
"""
from __future__ import annotations

import pytest

from glimi import InMemoryKernelStore
import glimi.memory as memory
import glimi.runtime as runtime
from glimi.runtime import AgentRuntime


# ──────────────────────────────────────────────────────────
# InMemoryKernelStore — reactions / replies / threads
# ──────────────────────────────────────────────────────────

def test_inmem_log_message_returns_id():
    s = InMemoryKernelStore()
    a = s.log_message("dm-x", "owner", "안녕")
    b = s.log_message("dm-x", "agent-1", "안녕!")
    assert isinstance(a, int) and b > a


def test_inmem_log_message_dedup_returns_existing_id():
    s = InMemoryKernelStore()
    a = s.log_message("dm-x", "owner", "같은말")
    b = s.log_message("dm-x", "owner", "같은말")
    assert b == a  # existing id, not None / not fresh


def test_inmem_reply_denormalizes_thread_root():
    s = InMemoryKernelStore()
    root = s.log_message("dm-x", "owner", "root")
    child = s.log_message("dm-x", "agent-1", "child", reply_to=root)
    grand = s.log_message("dm-x", "owner", "grand", reply_to=child)
    thread = s.get_thread(root)
    assert [m["id"] for m in thread] == [root, child, grand]
    assert thread[2]["thread_root"] == root  # collapsed to original root


def test_inmem_add_reaction_idempotent_and_unique():
    s = InMemoryKernelStore()
    mid = s.log_message("dm-x", "agent-1", "hi")
    assert s.add_reaction(mid, "owner", "❤️") is True
    assert s.add_reaction(mid, "owner", "❤️") is False
    assert s.add_reaction(mid, "owner", "👍") is True
    assert len(s.get_reactions(mid)) == 2


def test_inmem_add_reaction_missing_parent_noop():
    s = InMemoryKernelStore()
    assert s.add_reaction(123, "owner", "❤️") is False
    assert s.get_reactions(123) == []


def test_inmem_remove_reaction():
    s = InMemoryKernelStore()
    mid = s.log_message("dm-x", "agent-1", "hi")
    s.add_reaction(mid, "owner", "❤️")
    s.remove_reaction(mid, "owner", "❤️")
    assert s.get_reactions(mid) == []
    s.remove_reaction(mid, "owner", "❤️")  # safe double remove


def test_inmem_get_reactions_for_batch():
    s = InMemoryKernelStore()
    m1 = s.log_message("dm-x", "agent-1", "a")
    m2 = s.log_message("dm-x", "agent-1", "b")
    m3 = s.log_message("dm-x", "agent-1", "c")
    s.add_reaction(m1, "owner", "❤️")
    s.add_reaction(m2, "owner", "🔥")
    got = s.get_reactions_for([m1, m2, m3])
    assert set(got) == {m1, m2}
    assert got[m1][0]["emoji"] == "❤️"


def test_inmem_set_reply_then_thread():
    s = InMemoryKernelStore()
    root = s.log_message("dm-x", "owner", "root")
    c = s.log_message("dm-x", "agent-1", "standalone")
    s.set_reply(c, root)
    assert [m["id"] for m in s.get_thread(root)] == [root, c]


def test_inmem_get_recent_messages_has_reactions_and_reply_to():
    s = InMemoryKernelStore()
    root = s.log_message("dm-x", "owner", "부모")
    child = s.log_message("dm-x", "agent-1", "답글", reply_to=root)
    s.add_reaction(child, "owner", "❤️")
    rows = {m["id"]: m for m in s.get_recent_messages("dm-x")}
    assert rows[child]["reply_to"] == root
    assert rows[child]["reactions"][0]["emoji"] == "❤️"
    assert rows[child]["reactions"][0]["count"] == 1
    assert rows[root]["reactions"] == []


# ──────────────────────────────────────────────────────────
# memory.record_reaction_signal
# ──────────────────────────────────────────────────────────

@pytest.fixture
def signal_store():
    """Inject a fresh InMemoryKernelStore with an established relationship + reset
    the module-level double-count guard."""
    saved = memory._store
    s = InMemoryKernelStore()
    s.upsert_agent("agent-1", name="소은")
    s.upsert_user("owner", name="오너")
    s.set_relationship("agent-1", "owner", rel_type="friend", intimacy=40)
    memory.set_store(s)
    memory._reacted_signal_ids.clear()
    try:
        yield s
    finally:
        memory.set_store(saved)
        memory._reacted_signal_ids.clear()


def _intimacy(s):
    rel = s.get_relationship("agent-1", "owner") or s.get_relationship("owner", "agent-1")
    return rel["intimacy_score"]


def test_record_reaction_signal_bumps_intimacy_once(signal_store):
    s = signal_store
    before = _intimacy(s)
    applied = memory.record_reaction_signal("agent-1", "owner", "❤️", reaction_id=10)
    assert applied is True
    assert _intimacy(s) == before + memory.REACTION_INTIMACY_DELTA
    # one relationship-delta logged
    hist = s.get_relationship_history("agent-1", "owner")
    assert any((h.get("reason") or "").startswith("reacted") for h in hist)


def test_record_reaction_signal_double_count_guarded(signal_store):
    s = signal_store
    before = _intimacy(s)
    memory.record_reaction_signal("agent-1", "owner", "❤️", reaction_id=7)
    second = memory.record_reaction_signal("agent-1", "owner", "❤️", reaction_id=7)  # same id
    assert second is False
    assert _intimacy(s) == before + memory.REACTION_INTIMACY_DELTA  # bumped ONLY once


def test_record_reaction_signal_non_positive_emoji_noop(signal_store):
    s = signal_store
    before = _intimacy(s)
    applied = memory.record_reaction_signal("agent-1", "owner", "😡", reaction_id=1)
    assert applied is False
    assert _intimacy(s) == before


def test_record_reaction_signal_no_relationship_noop():
    saved = memory._store
    s = InMemoryKernelStore()
    s.upsert_agent("agent-1", name="소은")
    s.upsert_user("owner", name="오너")
    # NO relationship row created.
    memory.set_store(s)
    memory._reacted_signal_ids.clear()
    try:
        assert memory.record_reaction_signal("agent-1", "owner", "❤️", reaction_id=3) is False
    finally:
        memory.set_store(saved)
        memory._reacted_signal_ids.clear()


# ──────────────────────────────────────────────────────────
# runtime._build_reactions_reminder — awareness block
# ──────────────────────────────────────────────────────────

class _Owner:
    def id(self):
        return "owner"

    def display_name(self):
        return "오너"


class _Profiles:
    _NAMES = {"agent-1": "소은", "agent-2": "지우"}

    def display_name(self, agent_id):
        return self._NAMES.get(agent_id, agent_id)

    def get(self, agent_id):
        if agent_id in self._NAMES:
            return {"id": agent_id, "name": self._NAMES[agent_id], "type": "persona"}
        return None


@pytest.fixture
def reminder_env():
    saved_store, saved_owner, saved_profiles = runtime._store, runtime._owner, runtime._profiles
    saved_mem_store, saved_mem_owner, saved_mem_profiles = (
        memory._store, memory._owner, memory._profiles)
    s = InMemoryKernelStore()
    runtime.set_store(s)
    runtime.set_owner(_Owner())
    runtime.set_profiles(_Profiles())
    # _build_context calls get_memory_context which reads the memory module's
    # store/owner/profiles — inject the same in-memory store there too.
    memory.set_store(s)
    memory.set_owner(_Owner())
    memory.set_profiles(_Profiles())
    try:
        yield s
    finally:
        runtime.set_store(saved_store)
        runtime.set_owner(saved_owner)
        runtime.set_profiles(saved_profiles)
        memory.set_store(saved_mem_store)
        memory.set_owner(saved_mem_owner)
        memory.set_profiles(saved_mem_profiles)


def test_reminder_empty_without_reactions(reminder_env):
    s = reminder_env
    mid = s.log_message("dm-x", "agent-1", "내 메시지")
    recent = s.get_recent_messages("dm-x")
    out = AgentRuntime()._build_reactions_reminder("agent-1", recent)
    assert out == ""  # no reactions → no block


def test_reminder_appears_with_reaction_on_own_message(reminder_env):
    s = reminder_env
    mine = s.log_message("dm-x", "agent-1", "내 메시지")
    s.add_reaction(mine, "owner", "❤️")
    recent = s.get_recent_messages("dm-x")
    out = AgentRuntime()._build_reactions_reminder("agent-1", recent)
    assert "오너 reacted ❤️" in out
    assert "내 메시지" in out


def test_reminder_ignores_reactions_on_others_messages(reminder_env):
    s = reminder_env
    theirs = s.log_message("dm-x", "agent-2", "남의 메시지")
    s.add_reaction(theirs, "owner", "❤️")  # reaction on agent-2's message
    recent = s.get_recent_messages("dm-x")
    out = AgentRuntime()._build_reactions_reminder("agent-1", recent)
    assert out == ""  # agent-1 has no own reacted messages


def test_build_context_includes_reaction_block_only_when_present(reminder_env):
    """End-to-end through _build_context: the reminder block shows up iff a
    reaction exists on the agent's own message."""
    s = reminder_env
    s.upsert_agent("agent-1", name="소은", agent_type="persona",
                   current_emotion="평온", emotion_intensity=5)
    agent_info = {"profile": {"id": "agent-1", "type": "persona", "name": "소은"}}

    mine = s.log_message("dm-x", "agent-1", "리액션 받을 메시지")
    s.log_message("dm-x", "owner", "오너 메시지")

    recent = s.get_recent_messages("dm-x")
    ctx_before = AgentRuntime()._build_context(agent_info, "dm-x", recent)
    assert "reacted" not in ctx_before

    s.add_reaction(mine, "owner", "❤️")
    recent = s.get_recent_messages("dm-x")
    ctx_after = AgentRuntime()._build_context(agent_info, "dm-x", recent)
    assert "오너 reacted ❤️" in ctx_after
    # and it lives inside the system-reminder wrapper
    assert "<system-reminder>" in ctx_after


def test_build_context_reply_annotation(reminder_env):
    """A reply row gets a '↳ replying to ...' parent gist prefix in the render."""
    s = reminder_env
    s.upsert_agent("agent-1", name="소은", agent_type="persona",
                   current_emotion="평온", emotion_intensity=5)
    agent_info = {"profile": {"id": "agent-1", "type": "persona", "name": "소은"}}
    root = s.log_message("dm-x", "owner", "원래 질문")
    s.log_message("dm-x", "agent-1", "그에 대한 답", reply_to=root)
    recent = s.get_recent_messages("dm-x")
    ctx = AgentRuntime()._build_context(agent_info, "dm-x", recent)
    assert "↳ replying to 오너" in ctx
