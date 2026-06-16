"""glimi/store.py 커널 단위 테스트 — KernelStore ABC 계약.

검증:
  - KernelStore 는 ABC 이며 직접 인스턴스화 불가
  - 추상 메서드 일부만 구현한 서브클래스도 인스턴스화 불가
  - 전체 메서드를 dict 기반으로 구현한 FakeStore 는 ABC 를 만족 + 동작

FakeStore 는 다른 커널 테스트가 (LLM 없이) 실제 store 가 필요할 때 쓸 수 있는
in-memory 테스트 더블이다.

실행:
    PYTHONPATH=<worktree> python -m pytest tests/unit/test_glimi_store_contract.py -q
"""
from abc import ABC

import pytest

from glimi.store import KernelStore


# ────────────────────────────────────────────────────
# In-memory 테스트 더블 — 전체 추상 메서드 구현
# ────────────────────────────────────────────────────

class FakeStore(KernelStore):
    """dict 백킹의 최소 KernelStore 구현 (테스트 전용).

    conversation/memory 핵심 경로는 실제로 데이터를 보관하고, 나머지는
    빈 결과를 반환하는 안전한 no-op 으로 채운다. ABC 의 38개 추상 메서드를
    전부 구현해야 인스턴스화 가능하므로 계약 완전성 검증도 겸한다.
    """

    def __init__(self):
        self.messages: dict[str, list[dict]] = {}
        self.channel_status: dict[str, dict] = {}
        self.agents: dict[str, dict] = {}
        self.facts: list[dict] = []
        self.memories: list[dict] = []
        self.pins: set[int] = set()
        self.emotions: dict[str, tuple[str, int]] = {}
        self.hooks: list = []
        self.reactions: list[dict] = []
        self._next_id = 1

    # ── conversation engine ──────────────────────────
    def set_channel_status(self, channel, status, max_turns=0):
        self.channel_status[channel] = {"status": status, "max_turns": max_turns, "turn": 0}

    def increment_channel_turn(self, channel):
        st = self.channel_status.setdefault(channel, {"status": "", "max_turns": 0, "turn": 0})
        st["turn"] += 1
        return st["turn"]

    def get_recent_messages(self, channel, limit=20):
        return list(self.messages.get(channel, []))[-limit:]

    def get_messages_by_range(self, channel, after_id, limit=15):
        msgs = [m for m in self.messages.get(channel, []) if m["id"] > after_id]
        return msgs[:limit]

    # ── runtime ──────────────────────────────────────
    def get_agent(self, agent_id):
        return self.agents.get(agent_id)

    def list_agents(self, agent_type=None):
        out = list(self.agents.values())
        if agent_type is not None:
            out = [a for a in out if a.get("type") == agent_type]
        return out

    def get_channel_participants(self, channel):
        return []

    def get_channel_overview(self):
        return [{"channel": ch} for ch in self.messages]

    def get_agent_model_override(self, agent_id):
        return None

    def log_message(self, channel, speaker, message, emotion=None, reply_to=None):
        mid = self._next_id
        self._next_id += 1
        self.messages.setdefault(channel, []).append(
            {"id": mid, "speaker": speaker, "message": message, "emotion": emotion,
             "reply_to": reply_to, "thread_root": None}
        )
        for fn in self.hooks:
            fn(channel, speaker, message)
        return mid

    def add_message_hook(self, fn):
        self.hooks.append(fn)

    def add_reaction(self, message_id, actor_id, emoji):
        for r in self.reactions:
            if r["message_id"] == message_id and r["actor_id"] == actor_id and r["emoji"] == emoji:
                return False
        self.reactions.append({"message_id": message_id, "actor_id": actor_id,
                               "emoji": emoji, "created_at": ""})
        return True

    def remove_reaction(self, message_id, actor_id, emoji):
        self.reactions = [r for r in self.reactions
                          if not (r["message_id"] == message_id and r["actor_id"] == actor_id
                                  and r["emoji"] == emoji)]

    def get_reactions(self, message_id):
        return [{"emoji": r["emoji"], "actor_id": r["actor_id"], "created_at": r["created_at"]}
                for r in self.reactions if r["message_id"] == message_id]

    def get_reactions_for(self, message_ids):
        idset = set(message_ids)
        out: dict[int, list[dict]] = {}
        for r in self.reactions:
            if r["message_id"] in idset:
                out.setdefault(r["message_id"], []).append(
                    {"emoji": r["emoji"], "actor_id": r["actor_id"], "created_at": r["created_at"]})
        return out

    def set_reply(self, message_id, reply_to):
        for msgs in self.messages.values():
            for m in msgs:
                if m["id"] == message_id:
                    m["reply_to"] = reply_to
                    m["thread_root"] = reply_to
                    return

    def get_thread(self, root_id, limit=50):
        out = []
        for msgs in self.messages.values():
            for m in msgs:
                if m["id"] == root_id or m.get("thread_root") == root_id:
                    out.append(m)
        out.sort(key=lambda r: r["id"])
        return out[:limit]

    def get_recent_events(self, agent_id, event_types, window_sec, limit=8):
        return []

    def get_agent_channels(self, agent_id, exclude_channel, include_mgr):
        return []

    def get_memory_coverage(self, agent_id, exclude_channel):
        return {}

    # ── memory ───────────────────────────────────────
    def get_agent_by_name(self, name):
        for a in self.agents.values():
            if a.get("name") == name:
                return a
        return None

    def get_relationship(self, agent_a, agent_b):
        return None

    def get_relationship_history(self, agent_a, agent_b, limit=20):
        return []

    def update_intimacy(self, agent_a, agent_b, delta):
        return None

    def add_relationship_delta(self, agent_a, agent_b, delta_type, from_state=None,
                               to_state=None, reason=None, source_channel=None,
                               source_memory_id=None):
        return 0

    def get_memories(self, agent_id, channel, level, limit=10):
        return [m for m in self.memories
                if m["agent_id"] == agent_id and m["channel"] == channel
                and m["level"] == level][:limit]

    def get_latest_memory(self, agent_id, channel, level):
        rows = self.get_memories(agent_id, channel, level, limit=10_000)
        return rows[-1] if rows else None

    def get_pinned_memories(self, agent_id, limit=20):
        return [m for m in self.memories
                if m["agent_id"] == agent_id and m["id"] in self.pins][:limit]

    def add_memory(self, agent_id, channel, level, content, msg_id_from=None,
                   msg_id_to=None, msg_count=0, mem_type=None, related_entities=None,
                   knows=None, importance=5, is_pinned=False, parent_memory_id=None,
                   related_agent_id=None):
        mid = self._next_id
        self._next_id += 1
        self.memories.append({
            "id": mid, "agent_id": agent_id, "channel": channel, "level": level,
            "content": content, "msg_id_to": msg_id_to, "importance": importance,
        })
        if is_pinned:
            self.pins.add(mid)
        return mid

    def set_pin(self, memory_id, pinned=True):
        if pinned:
            self.pins.add(memory_id)
        else:
            self.pins.discard(memory_id)

    def touch_memory_access(self, memory_ids):
        return None

    def count_messages_after(self, channel, after_id):
        return len([m for m in self.messages.get(channel, []) if m["id"] > after_id])

    def get_facts(self, agent_id, subject=None, include_invalid=False, limit=50):
        out = [f for f in self.facts if f["agent_id"] == agent_id]
        if subject is not None:
            out = [f for f in out if f["subject"] == subject]
        return out[:limit]

    def add_fact(self, agent_id, subject, predicate, object_value, source_channel=None,
                 source_memory_id=None, confidence=1.0, importance=5):
        fid = self._next_id
        self._next_id += 1
        self.facts.append({
            "id": fid, "agent_id": agent_id, "subject": subject,
            "predicate": predicate, "object": object_value, "importance": importance,
        })
        return fid

    def list_users(self):
        return []

    # ── memory — higher-level ────────────────────────
    def set_relationship_dynamics(self, agent_a, agent_b, dynamics):
        return None

    def get_agent_emotion(self, agent_id):
        return self.emotions.get(agent_id)

    def set_agent_emotion(self, agent_id, emotion, intensity):
        self.emotions[agent_id] = (emotion, intensity)

    def get_uncovered_memories(self, agent_id, channel, source_level):
        return []

    def get_memories_across_channels(self, agent_id, exclude_channel, levels, limit):
        return []

    def get_recent_messages_across_channels(self, agent_id, exclude_channel,
                                            within_minutes, limit):
        return []

    def search_memories(self, agent_id, entity=None, query=None,
                        time_range_days=None, limit=20):
        return []

    def get_memory(self, memory_id):
        for m in self.memories:
            if m["id"] == memory_id:
                return m
        return None

    def get_memory_stats(self, agent_id, channel):
        return {"total_messages": 0, "l1": 0, "l2": 0, "l3": 0, "pinned": 0,
                "facts_active": 0, "messages_summarized": 0}


# ────────────────────────────────────────────────────
# ABC 계약
# ────────────────────────────────────────────────────

def test_kernelstore_is_abc():
    assert issubclass(KernelStore, ABC)
    assert len(KernelStore.__abstractmethods__) > 0


def test_kernelstore_cannot_instantiate_directly():
    with pytest.raises(TypeError):
        KernelStore()


def test_partial_subclass_cannot_instantiate():
    class Incomplete(KernelStore):
        def get_agent(self, agent_id):
            return None
        # 나머지 추상 메서드 미구현 → 인스턴스화 불가

    with pytest.raises(TypeError):
        Incomplete()


def test_fake_store_satisfies_abc_and_instantiates():
    store = FakeStore()
    assert isinstance(store, KernelStore)
    # 모든 추상 메서드를 구현했으므로 미구현 잔여가 없어야 함
    assert not getattr(FakeStore, "__abstractmethods__", frozenset())


# ────────────────────────────────────────────────────
# FakeStore 기본 동작 (테스트 더블이 실제로 쓸만한지)
# ────────────────────────────────────────────────────

def test_fake_store_log_and_read_messages():
    store = FakeStore()
    store.log_message("dm-지우", "user-1", "안녕")
    store.log_message("dm-지우", "agent-1", "안녕하세요")
    msgs = store.get_recent_messages("dm-지우")
    assert [m["message"] for m in msgs] == ["안녕", "안녕하세요"]
    assert store.count_messages_after("dm-지우", 0) == 2
    assert store.count_messages_after("dm-지우", msgs[0]["id"]) == 1


def test_fake_store_message_hook_fires():
    store = FakeStore()
    seen = []
    store.add_message_hook(lambda ch, sp, msg: seen.append((ch, sp, msg)))
    store.log_message("dm-지우", "user-1", "hi")
    assert seen == [("dm-지우", "user-1", "hi")]


def test_fake_store_channel_turn_increments():
    store = FakeStore()
    store.set_channel_status("group-a-b", "active", max_turns=10)
    assert store.increment_channel_turn("group-a-b") == 1
    assert store.increment_channel_turn("group-a-b") == 2


def test_fake_store_facts_and_memories_roundtrip():
    store = FakeStore()
    fid = store.add_fact("agent-1", "지우", "hobby", "게임")
    assert store.get_facts("agent-1", subject="지우")[0]["object"] == "게임"
    assert store.get_facts("agent-1", subject="없음") == []

    mid = store.add_memory("agent-1", "dm-지우", level=1, content="요약", msg_id_to=5)
    assert store.get_latest_memory("agent-1", "dm-지우", level=1)["id"] == mid
    store.set_pin(mid)
    assert store.get_pinned_memories("agent-1")[0]["id"] == mid


def test_fake_store_agent_lookup_by_name():
    store = FakeStore()
    store.agents["agent-1"] = {"id": "agent-1", "name": "지우", "type": "persona"}
    assert store.get_agent("agent-1")["name"] == "지우"
    assert store.get_agent_by_name("지우")["id"] == "agent-1"
    assert store.get_agent_by_name("없음") is None
    assert len(store.list_agents(agent_type="persona")) == 1
    assert store.list_agents(agent_type="mgr") == []


def test_fake_store_emotion_roundtrip():
    store = FakeStore()
    assert store.get_agent_emotion("agent-1") is None
    store.set_agent_emotion("agent-1", "평온", 4)
    assert store.get_agent_emotion("agent-1") == ("평온", 4)
