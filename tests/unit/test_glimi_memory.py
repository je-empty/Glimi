"""glimi/memory.py 커널 단위 테스트 — PURE 로직만 (LLM·DB 없이).

대상:
  - _validate_fact (meta/추상 subject·일시 object·미등록 subject·profile 중복 reject)
  - _canonical_predicate + PREDICATE_ALIASES 정규화
  - _is_meta_subject / _is_transient_object
  - _normalize_entity / _owner_aliases (mock OwnerContext 주입)
  - _channel_knows

주의: set_owner/set_profiles 로 주입한 전역 상태는 fixture teardown 에서 복원해
  다른 테스트(및 기존 테스트)에 누수되지 않게 한다.

⚠ datetime helper(_parse_iso/_format_age/_is_stale/_days_since) 는 별도 PR
  (fix/memory-tz) 소유 — 여기서 건드리지 않음.

실행:
    PYTHONPATH=<worktree> python -m pytest tests/unit/test_glimi_memory.py -q
"""
import pytest

import glimi.memory as memory
from glimi.memory import (
    _is_meta_subject,
    _is_transient_object,
    _canonical_predicate,
    _normalize_entity,
    _owner_aliases,
    _validate_fact,
    _channel_knows,
    PREDICATE_ALIASES,
)


class FakeOwner:
    """OwnerContext 를 구조적으로 만족하는 테스트 더블."""

    def __init__(self, name="심재빈", oid="user-1", nickname=None):
        self._name = name
        self._id = oid
        self._nickname = nickname

    def name(self):
        return self._name

    def id(self):
        return self._id

    def display_name(self):
        return self._name

    def call_name(self):
        return self._name

    def profile(self):
        if self._nickname:
            return {"personality": {"nickname": self._nickname}}
        return {}


class FakeProfiles:
    """ProfileProvider.get 만 흉내내는 최소 더블 (profile 중복 검사용)."""

    def __init__(self, mapping=None):
        self._mapping = mapping or {}

    def get(self, agent_id):
        return self._mapping.get(agent_id)


@pytest.fixture
def owner():
    """오너(닉네임 포함) 주입 후 teardown 에서 전역 복원."""
    prev_owner = memory._owner
    prev_profiles = memory._profiles
    o = FakeOwner(name="심재빈", oid="user-1", nickname="빈이")
    memory.set_owner(o)
    memory.set_profiles(FakeProfiles())
    yield o
    memory.set_owner(prev_owner)
    memory.set_profiles(prev_profiles)


# ────────────────────────────────────────────────────
# _is_meta_subject
# ────────────────────────────────────────────────────

@pytest.mark.parametrize("s", [
    "멤버들", "친구들", "사람들", "이 커뮤니티", "커뮤니티", "에이전트",
    "새 친구", "신규 에이전트", "캐릭터", "봇", "시스템", "모두", "전체",
    "user", "agent", "member", "bot",
])
def test_is_meta_subject_rejects_abstract(s):
    assert _is_meta_subject(s) is True


@pytest.mark.parametrize("s", ["지우", "심재빈", "은하윤", "아스나"])
def test_is_meta_subject_accepts_real_names(s):
    assert _is_meta_subject(s) is False


def test_is_meta_subject_rejects_empty_single_digit():
    assert _is_meta_subject("") is True
    assert _is_meta_subject("   ") is True
    assert _is_meta_subject("3") is True   # digit-only
    assert _is_meta_subject("가") is True   # single char


# ────────────────────────────────────────────────────
# _is_transient_object
# ────────────────────────────────────────────────────

@pytest.mark.parametrize("o", ["오늘", "지금", "방금", "오랜만", "잠깐", "이따",
                               "나중", "나중에", "어제", "내일", "요즘", "현재"])
def test_is_transient_object_true(o):
    assert _is_transient_object(o) is True


@pytest.mark.parametrize("o", ["떡볶이", "게임", "오늘 영화 봄", "커피"])
def test_is_transient_object_false(o):
    assert _is_transient_object(o) is False


def test_is_transient_object_empty_is_false():
    assert _is_transient_object("") is False
    assert _is_transient_object(None) is False


# ────────────────────────────────────────────────────
# _canonical_predicate + PREDICATE_ALIASES
# ────────────────────────────────────────────────────

def test_canonical_predicate_alias_map():
    assert _canonical_predicate("취미") == "hobby"
    assert _canonical_predicate("성격") == "personality"
    assert _canonical_predicate("성향") == "personality"
    assert _canonical_predicate("원하는친구특성") == "preferred_friend_type"
    assert _canonical_predicate("말투") == "speech_style"
    assert _canonical_predicate("직업") == "occupation"


def test_canonical_predicate_strips_whitespace_for_alias_match():
    # alias 테이블은 공백 없는 형태 — 공백/언더스코어 정규화 후 매칭
    assert _canonical_predicate("좋아하는 것") == "likes"
    assert _canonical_predicate("좋아하는_것") == "likes"


def test_canonical_predicate_lowercases_alias_key():
    assert _canonical_predicate("MBTI") == "mbti"


def test_canonical_predicate_unknown_normalizes_spaces_to_underscore():
    assert _canonical_predicate("custom pred name") == "custom_pred_name"
    assert _canonical_predicate("already_snake") == "already_snake"


def test_canonical_predicate_empty_passthrough():
    assert _canonical_predicate("") == ""


def test_predicate_aliases_all_resolve_to_known_canonical():
    # 모든 alias 의 canonical 값은 그 자체를 다시 변환해도 안정적이어야 함 (no chain)
    canonicals = set(PREDICATE_ALIASES.values())
    for canon in canonicals:
        # canonical 자체는 alias 키로 다시 매핑되면 안 됨 (idempotent)
        assert _canonical_predicate(canon) == canon


# ────────────────────────────────────────────────────
# _owner_aliases / _normalize_entity (mock owner)
# ────────────────────────────────────────────────────

def test_owner_aliases_includes_name_nickname_roles(owner):
    aliases = _owner_aliases()
    assert aliases[0] == "심재빈"           # canonical 우선
    assert "빈이" in aliases                # profile nickname
    assert "오너" in aliases and "owner" in aliases  # role terms


def test_normalize_entity_owner_name_and_aliases(owner):
    assert _normalize_entity("심재빈") == "심재빈"
    assert _normalize_entity("빈이") == "심재빈"      # nickname → canonical
    assert _normalize_entity("오너") == "심재빈"      # role term → canonical
    assert _normalize_entity("user") == "심재빈"


def test_normalize_entity_suffix_shortform(owner):
    # canonical 의 뒷부분과 매칭되는 줄임형 → canonical (예: 재빈 → 심재빈)
    assert _normalize_entity("재빈") == "심재빈"


def test_normalize_entity_other_name_unchanged(owner):
    assert _normalize_entity("지우") == "지우"
    assert _normalize_entity("은하윤") == "은하윤"


def test_normalize_entity_empty(owner):
    assert _normalize_entity("") == ""


# ────────────────────────────────────────────────────
# _validate_fact (allowed_subjects 로 store 우회)
# ────────────────────────────────────────────────────

def test_validate_fact_accepts_valid(owner):
    allowed = {"지우", "심재빈"}
    result = _validate_fact("agent-1", "지우", "취미", "게임", allowed_subjects=allowed)
    assert result == ("지우", "hobby", "게임")  # predicate 정규화 적용


def test_validate_fact_rejects_meta_subject(owner):
    allowed = {"지우", "심재빈"}
    assert _validate_fact("agent-1", "멤버들", "likes", "게임",
                          allowed_subjects=allowed) is None


def test_validate_fact_rejects_unknown_subject(owner):
    allowed = {"지우", "심재빈"}
    assert _validate_fact("agent-1", "모르는사람", "likes", "게임",
                          allowed_subjects=allowed) is None


def test_validate_fact_rejects_transient_object(owner):
    allowed = {"지우", "심재빈"}
    assert _validate_fact("agent-1", "지우", "request", "지금",
                          allowed_subjects=allowed) is None


def test_validate_fact_rejects_empty_fields(owner):
    allowed = {"지우"}
    assert _validate_fact("agent-1", "", "likes", "x", allowed_subjects=allowed) is None
    assert _validate_fact("agent-1", "지우", "", "x", allowed_subjects=allowed) is None
    assert _validate_fact("agent-1", "지우", "likes", "", allowed_subjects=allowed) is None


def test_validate_fact_normalizes_owner_alias_subject(owner):
    # 닉네임 subject 가 canonical 로 정규화되고 allowed 에 canonical 이 있으면 통과
    allowed = {"심재빈"}
    result = _validate_fact("agent-1", "빈이", "likes", "커피", allowed_subjects=allowed)
    assert result == ("심재빈", "likes", "커피")


def test_validate_fact_skips_self_fact_duplicating_profile(owner):
    # 자기 자신(agent-1=지우) 의 fact 가 profile 에 이미 있으면 skip
    profiles = FakeProfiles({
        "agent-1": {
            "name": "지우",
            "personality": {"data": {"likes": ["게임", "영화"]}},
        }
    })
    memory.set_profiles(profiles)
    allowed = {"지우"}
    # likes=게임 은 profile 에 이미 있음 → drop
    assert _validate_fact("agent-1", "지우", "likes", "게임",
                          allowed_subjects=allowed) is None
    # 새 정보(독서)는 profile 에 없음 → 통과
    assert _validate_fact("agent-1", "지우", "likes", "독서",
                          allowed_subjects=allowed) == ("지우", "likes", "독서")


# ────────────────────────────────────────────────────
# _channel_knows
# ────────────────────────────────────────────────────

def test_channel_knows_dm():
    assert _channel_knows("dm-지우", "지우") == ["owner", "지우"]


def test_channel_knows_group_includes_owner():
    knows = _channel_knows("group-지우-수민", "지우")
    assert set(knows) == {"지우", "수민", "owner"}


def test_channel_knows_internal_dm_excludes_owner():
    knows = _channel_knows("internal-dm-지우-수민", "지우")
    assert set(knows) == {"지우", "수민"}
    assert "owner" not in knows


def test_channel_knows_internal_group_excludes_owner():
    knows = _channel_knows("internal-group-a-b-c", "a")
    assert set(knows) == {"a", "b", "c"}
    assert "owner" not in knows


def test_channel_knows_mgr():
    assert _channel_knows("mgr-creator", "유나") == ["owner", "유나"]


def test_channel_knows_unknown_channel_empty():
    assert _channel_knows("random-channel", "지우") == []
    assert _channel_knows("", "지우") == []


# ────────────────────────────────────────────────────
# Fact supersession (valid_from/valid_to)
# ────────────────────────────────────────────────────
# 참고: memory.py 에는 supersession 을 수행하는 PURE 함수가 없다.
# add_fact 의 valid_from/valid_to 무효화 로직은 KernelStore 구현(앱 SQLite 어댑터)
# 책임이므로 LLM 없이도 store 통합 테스트(별도 PR)에서 다뤄야 한다.
