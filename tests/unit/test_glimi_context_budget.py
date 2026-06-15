"""glimi/context_budget.py 커널 단위 테스트 — env·산술 순수 로직만.

대상:
  - estimate_tokens (한글/ascii 비율, 단조성)
  - resolve_num_ctx (env override + HARD_FLOOR 클램프)
  - prompt_detail_level (compact/standard/full 구간)
  - level_at_least (순서)
  - trim_recent_to_budget (윈도우 절대 초과 방지)

실행:
    PYTHONPATH=<worktree> python -m pytest tests/unit/test_glimi_context_budget.py -q
"""
import glimi.context_budget as cb
from glimi.context_budget import (
    estimate_tokens,
    resolve_num_ctx,
    prompt_detail_level,
    level_at_least,
    trim_recent_to_budget,
    HARD_FLOOR,
    DEFAULT_NUM_CTX,
)


# ────────────────────────────────────────────────────
# estimate_tokens
# ────────────────────────────────────────────────────

def test_estimate_tokens_empty_is_zero():
    assert estimate_tokens("") == 0
    assert estimate_tokens(None) == 0


def test_estimate_tokens_positive_for_nonempty():
    assert estimate_tokens("hi") >= 1
    assert estimate_tokens("안녕") >= 1


def test_estimate_tokens_hangul_costs_more_per_char_than_ascii():
    # 한글은 토큰당 글자수가 적음(≈2.2자/tok) → 같은 글자수면 한글이 토큰 더 많음
    n = 22
    hangul = estimate_tokens("가" * n)
    ascii_ = estimate_tokens("a" * n)
    assert hangul > ascii_


def test_estimate_tokens_monotonic_longer_not_fewer():
    short = estimate_tokens("안녕하세요")
    longer = estimate_tokens("안녕하세요 반갑습니다 오늘 날씨가 좋네요")
    assert longer >= short
    # ascii 도 동일
    assert estimate_tokens("hello world foo bar") >= estimate_tokens("hello")


# ────────────────────────────────────────────────────
# resolve_num_ctx (env override + clamp)
# ────────────────────────────────────────────────────

def test_resolve_num_ctx_default(monkeypatch):
    monkeypatch.delenv("GLIMI_OLLAMA_NUM_CTX", raising=False)
    assert resolve_num_ctx() == DEFAULT_NUM_CTX


def test_resolve_num_ctx_env_override(monkeypatch):
    monkeypatch.setenv("GLIMI_OLLAMA_NUM_CTX", "16384")
    assert resolve_num_ctx() == 16384


def test_resolve_num_ctx_clamps_to_hard_floor(monkeypatch):
    monkeypatch.setenv("GLIMI_OLLAMA_NUM_CTX", "1000")
    assert resolve_num_ctx() == HARD_FLOOR


def test_resolve_num_ctx_garbage_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("GLIMI_OLLAMA_NUM_CTX", "not-a-number")
    assert resolve_num_ctx() == DEFAULT_NUM_CTX


# ────────────────────────────────────────────────────
# prompt_detail_level tiers
# ────────────────────────────────────────────────────

def test_prompt_detail_level_compact(monkeypatch):
    monkeypatch.delenv("GLIMI_PROMPT_LEVEL", raising=False)
    assert prompt_detail_level(4096) == "compact"
    assert prompt_detail_level(6143) == "compact"


def test_prompt_detail_level_standard(monkeypatch):
    monkeypatch.delenv("GLIMI_PROMPT_LEVEL", raising=False)
    assert prompt_detail_level(6144) == "standard"
    assert prompt_detail_level(8192) == "standard"
    assert prompt_detail_level(12287) == "standard"


def test_prompt_detail_level_full(monkeypatch):
    monkeypatch.delenv("GLIMI_PROMPT_LEVEL", raising=False)
    assert prompt_detail_level(12288) == "full"
    assert prompt_detail_level(16384) == "full"


def test_prompt_detail_level_forced_env(monkeypatch):
    monkeypatch.setenv("GLIMI_PROMPT_LEVEL", "full")
    # num_ctx 가 작아도 강제 레벨이 우선
    assert prompt_detail_level(2048) == "full"
    monkeypatch.setenv("GLIMI_PROMPT_LEVEL", "compact")
    assert prompt_detail_level(16384) == "compact"


def test_prompt_detail_level_uses_resolve_when_none(monkeypatch):
    monkeypatch.delenv("GLIMI_PROMPT_LEVEL", raising=False)
    monkeypatch.setenv("GLIMI_OLLAMA_NUM_CTX", "4096")
    assert prompt_detail_level() == "compact"


# ────────────────────────────────────────────────────
# level_at_least ordering
# ────────────────────────────────────────────────────

def test_level_at_least_ordering():
    assert level_at_least("compact", "compact") is True
    assert level_at_least("compact", "standard") is True
    assert level_at_least("compact", "full") is True
    assert level_at_least("standard", "compact") is False
    assert level_at_least("standard", "standard") is True
    assert level_at_least("standard", "full") is True
    assert level_at_least("full", "standard") is False
    assert level_at_least("full", "full") is True


# ────────────────────────────────────────────────────
# trim_recent_to_budget — 윈도우 절대 초과 방지 + 최신 보존
# ────────────────────────────────────────────────────

def _msgs(n, text="안녕하세요 오늘 뭐했어"):
    return [{"message": f"{text} {i}"} for i in range(n)]


def test_trim_zero_budget_returns_empty():
    assert trim_recent_to_budget(_msgs(5), 0) == []
    assert trim_recent_to_budget(_msgs(5), -10) == []


def test_trim_keeps_newest_messages():
    msgs = _msgs(20)
    kept = trim_recent_to_budget(msgs, 60)
    assert len(kept) < len(msgs)
    # 최신 메시지(마지막 원소)는 항상 보존, 순서 유지
    assert kept[-1] is msgs[-1]
    assert kept == sorted(kept, key=lambda m: msgs.index(m))


def test_trim_result_never_exceeds_budget_when_multiple_kept():
    msgs = _msgs(30)
    budget = 200
    kept = trim_recent_to_budget(msgs, budget)
    # 2개 이상 보존됐다면 합산 추정 토큰이 예산을 넘지 않아야 함
    # (구현: 추가 후 초과하면 직전에서 멈춤 — kept 가 비지 않은 한 budget 준수)
    total = sum(estimate_tokens(m["message"]) + 6 for m in kept)
    if len(kept) >= 2:
        assert total <= budget


def test_trim_large_budget_keeps_everything():
    msgs = _msgs(5)
    kept = trim_recent_to_budget(msgs, 100000)
    assert kept == msgs


def test_trim_tiny_budget_keeps_at_least_one():
    # 예산이 1메시지보다 작아도 최소 1개(최신)는 보존 (kept 비면 break 안 함)
    msgs = _msgs(10)
    kept = trim_recent_to_budget(msgs, 5)
    assert len(kept) == 1
    assert kept[0] is msgs[-1]
