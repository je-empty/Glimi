# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""
컨텍스트 예산 — 프롬프트가 모델 컨텍스트 윈도우(num_ctx)를 절대 넘지 않게 동적 조립.

배경: 로컬 모델(ollama)은 컨텍스트가 작다(기본 4096). Glimi 한 턴 프롬프트는
시스템(캐릭터+도구) + 5-레이어 메모리 주입 + 최근 대화가 합쳐 수천 토큰이라, num_ctx 를
넘으면 ollama 가 앞부분(시스템·메모리)을 조용히 잘라내 캐릭터·기억이 증발한다.

해결: num_ctx 에서 역산한 예산 안에 맞춰 조립.
  - num_ctx 가 메모리 풍부도(scale)를 결정 — 8192=기준(1.0), 4096=축소, 16384=풍부
  - 최종 fit-check 가 최근 대화를 오래된 것부터 잘라 **절대 초과 안 되게 보장**
  - 하드 floor 2048, 권장 최소 4096, 기본 8192

Claude 등 대용량 컨텍스트 백엔드는 이 시스템을 안 탄다 (scale=1.0, trim 없음 = 기존 동작).
"""
from __future__ import annotations

import os

# 컨텍스트 크기 기준점
# 실측 시스템 프롬프트: persona ≈2700tok, mgr ≈5100tok (캐릭터+brief 도구레퍼).
# 이게 못 줄이는 하드 바닥 → 메모리/대화를 0 으로 줄여도 그 이상은 필요.
#   2048: 절대 클램프 (이하 거부). 시스템 프롬프트도 못 담아 사실상 동작 X
#   4096: persona 최소 (메모리 축소 scale≈0.4). mgr 는 부족
#   8192: 권장 기본 — persona/mgr 모두 여유 (scale 1.0). 대부분 이걸 씀
HARD_FLOOR = 2048
RECOMMENDED_MIN = 4096
DEFAULT_NUM_CTX = 8192  # 기본 = scale 1.0 의 기준점 (QA 로 튜닝된 동작)
SAFETY_MARGIN = 256     # 토큰 추정 오차 + 특수토큰 여유

# 메모리 scale 범위 — num_ctx / 8192 에 비례, 8192 에서 1.0
MEM_SCALE_MIN = 0.25
MEM_SCALE_MAX = 2.0

# 출력 예약 (프롬프트 예산 계산용 — 실제 num_predict 와 별개의 휴리스틱).
# 대부분 응답은 짧지만 프롬프트 자리를 비워두기 위함.
# 프롬프트 예산 계산용 출력 예약 (실제 num_predict 와 별개). 대부분 응답은 짧지만
# mgr/creator 는 튜토리얼 등 멀티라인 출력이 있어 약간 더.
_OUTPUT_RESERVE = {
    "persona": 448,
    "mgr": 768,
    "creator": 768,
    "dev": 640,
}
_DEFAULT_OUTPUT_RESERVE = 512

# 현 메모리 주입 budget(문자)의 토큰 환산 기준 — memory.py BUDGET_* 합 ≈ 3700자 ≈ 1230tok.
# scale 1.0 일 때의 메모리 토큰 비용 추정값 (recent 트림 예산 계산에 사용).
MEM_DESIGN_TOKENS = 1230


def estimate_tokens(text: str) -> int:
    """가벼운 토큰 추정 — 한글은 토큰당 글자수가 적고(≈2.2자/tok), ascii 는 ≈4자/tok.
    정확한 토크나이저는 무겁고 백엔드마다 달라 불필요 — 보수적(약간 과대) 추정으로 충분."""
    if not text:
        return 0
    hangul = 0
    for ch in text:
        o = ord(ch)
        if 0xAC00 <= o <= 0xD7A3 or 0x3130 <= o <= 0x318F:  # 한글 음절 + 자모
            hangul += 1
    other = len(text) - hangul
    return int(hangul / 2.2 + other / 4.0) + 1


def resolve_num_ctx() -> int:
    """GLIMI_OLLAMA_NUM_CTX (기본 8192) — 하드 floor 2048 로 클램프."""
    try:
        v = int(os.environ.get("GLIMI_OLLAMA_NUM_CTX", str(DEFAULT_NUM_CTX)).strip())
    except Exception:
        v = DEFAULT_NUM_CTX
    return max(HARD_FLOOR, v)


# ── 동적 시스템 프롬프트 detail level (Elastic Prompt) ───────────────
# 시스템 프롬프트 자체를 num_ctx 에 맞춰 단계 조절. 제거가 아니라 "맞는 퀄리티" 선택:
#   compact  (num_ctx < 6144, 예: 4096) — 핵심 규칙·이름만 도구목록. 메모리 자리 확보
#   standard (6144 ≤ num_ctx < 12288, 예: 8192) — brief 도구목록 + 행동 규칙 포함 (기본)
#   full     (num_ctx ≥ 12288, 예: 16384) — 전체 규칙 + 예시 + verbose 도구
_LEVEL_ORDER = {"compact": 0, "standard": 1, "full": 2}


def prompt_detail_level(num_ctx: int | None = None) -> str:
    """num_ctx 기준 시스템 프롬프트 상세도. GLIMI_PROMPT_LEVEL 로 강제 가능(디버그)."""
    forced = os.environ.get("GLIMI_PROMPT_LEVEL", "").strip().lower()
    if forced in _LEVEL_ORDER:
        return forced
    nc = num_ctx if num_ctx is not None else resolve_num_ctx()
    if nc < 6144:
        return "compact"
    if nc < 12288:
        return "standard"
    return "full"


def level_at_least(target: str, level: str | None = None) -> bool:
    """현재(또는 주어진) detail level 이 target 이상인지. 프롬프트 섹션 게이팅용.
    예: `if level_at_least("standard"): prompt += 행동규칙`."""
    cur = level if level is not None else prompt_detail_level()
    return _LEVEL_ORDER.get(cur, 1) >= _LEVEL_ORDER.get(target, 1)


def output_reserve(agent_type: str) -> int:
    return _OUTPUT_RESERVE.get(agent_type, _DEFAULT_OUTPUT_RESERVE)


def memory_scale(num_ctx: int) -> float:
    """num_ctx 기준 메모리 주입 풍부도. 8192=1.0, 비례 + 클램프."""
    raw = num_ctx / float(DEFAULT_NUM_CTX)
    return max(MEM_SCALE_MIN, min(MEM_SCALE_MAX, raw))


def plan(num_ctx: int, agent_type: str, system_prompt: str, user_message: str,
         fixed_extra: str = "") -> dict:
    """이번 턴 조립 계획.

    Returns dict:
      - mem_scale: 메모리 char budget 배수
      - recent_token_budget: 최근 대화에 허용할 토큰 (오래된 것부터 trim)
      - prompt_budget: 프롬프트 전체 토큰 상한
      - system_tokens: 시스템 프롬프트 추정 토큰
    """
    prompt_budget = max(512, num_ctx - output_reserve(agent_type) - SAFETY_MARGIN)
    sys_tok = estimate_tokens(system_prompt)
    extra_tok = estimate_tokens(user_message) + estimate_tokens(fixed_extra)

    mscale = memory_scale(num_ctx)
    mem_tok_est = int(MEM_DESIGN_TOKENS * mscale)

    # 메모리·extra·시스템 빼고 남는 게 최근 대화 예산. 음수면 메모리부터 양보.
    recent_budget = prompt_budget - sys_tok - extra_tok - mem_tok_est
    if recent_budget < 150:
        # 컨텍스트가 빠듯 — 메모리 scale 을 줄여 최근 대화 최소분(150tok) 확보.
        deficit = 150 - recent_budget
        mem_tok_est = max(0, mem_tok_est - deficit)
        mscale = (mem_tok_est / MEM_DESIGN_TOKENS) if MEM_DESIGN_TOKENS else 0.0
        mscale = max(0.0, mscale)
        recent_budget = prompt_budget - sys_tok - extra_tok - mem_tok_est

    recent_budget = max(0, recent_budget)
    return {
        "mem_scale": round(mscale, 3),
        "recent_token_budget": recent_budget,
        "prompt_budget": prompt_budget,
        "system_tokens": sys_tok,
    }


def composition(num_ctx: int, agent_type: str, system_tokens: int) -> dict:
    """대시보드 시각화용 — 컨텍스트 윈도우가 무엇에 얼마나 쓰이는지 세그먼트 분해.
    합이 num_ctx 가 되도록: system + memory + recent + output_reserve + safety + free.
    plan() 과 동일한 배분 로직을 system_tokens 직접 입력으로 재현."""
    reserve = output_reserve(agent_type)
    prompt_budget = max(512, num_ctx - reserve - SAFETY_MARGIN)
    mscale = memory_scale(num_ctx)
    mem = int(MEM_DESIGN_TOKENS * mscale)
    recent = prompt_budget - system_tokens - mem
    if recent < 150:
        deficit = 150 - recent
        mem = max(0, mem - deficit)
        recent = prompt_budget - system_tokens - mem
    recent = max(0, recent)
    # system 이 예산 초과면 memory/recent 0, system 은 윈도우까지로 클램프(초과분은 잘림 경고 대상)
    over = max(0, (system_tokens + mem + recent + reserve + SAFETY_MARGIN) - num_ctx)
    if over > 0:
        # memory/recent 먼저 줄임
        take = min(over, recent); recent -= take; over -= take
        take = min(over, mem); mem -= take; over -= take
    sys_shown = min(system_tokens, num_ctx)
    used = sys_shown + mem + recent + reserve + SAFETY_MARGIN
    free = max(0, num_ctx - used)
    return {
        "num_ctx": num_ctx,
        "segments": [
            {"key": "system", "label_ko": "시스템 프롬프트", "label_en": "System prompt", "tokens": sys_shown},
            {"key": "memory", "label_ko": "메모리 주입", "label_en": "Memory", "tokens": mem},
            {"key": "recent", "label_ko": "최근 대화", "label_en": "Recent chat", "tokens": recent},
            {"key": "output", "label_ko": "출력 예약", "label_en": "Output reserve", "tokens": reserve},
            {"key": "safety", "label_ko": "여유", "label_en": "Free", "tokens": SAFETY_MARGIN + free},
        ],
        "mem_scale": round(mscale, 3),
        "system_over_budget": system_tokens > prompt_budget,
    }


def trim_recent_to_budget(recent: list, budget_tokens: int) -> list:
    """최근 대화 리스트를 토큰 예산에 맞춰 오래된 것부터 잘라냄. 최신 메시지 우선 보존."""
    if budget_tokens <= 0:
        return []
    kept: list = []
    used = 0
    for msg in reversed(recent):  # 최신부터
        t = estimate_tokens(msg.get("message", "")) + 6  # 화자 prefix 등 오버헤드
        if used + t > budget_tokens and kept:
            break
        kept.append(msg)
        used += t
    kept.reverse()
    return kept
