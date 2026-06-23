# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Glimi Community CONVERSATION-QUALITY LLM judge.

The Community's whole point is that chatting with an AI friend FEELS like chatting
with a real friend. :mod:`community_verdict` judges the run structurally (did each
friend reply, no meta leaks, no errors). This module adds the missing axis: **were
the friend's replies actually GOOD?** — in-character, coherent, natural, engaged —
scored by an LLM judge.

We do NOT re-implement an LLM judge. We reuse the SAME offline-judge primitives the
Workspace deliverable judge uses (:func:`tests.e2e.ws_judge` →
:func:`tests.e2e.quality_judge.call_haiku` / ``extract_json`` / ``MODEL``), so every
judge surface in the repo shares one model + one parsing path. The only thing that
differs from ws_judge is the RUBRIC (a friend conversation, not a work deliverable).

Backend honesty (the iron rule): the judge spawns the ``claude`` CLI, so it ONLY
runs on a real backend AND when the CLI is present. On echo the friend reply is a
fixed ``(echo) You said: …`` string — scoring it would be theater — so the caller
SKIPS and records ``status="skipped"`` (reason ``"echo"``). No fabricated scores.
"""
from __future__ import annotations

from typing import Any

# Reuse the exact primitives the Workspace judge reuses — one model, one parser.
from tests.e2e.ws_judge import judge_available, skipped  # noqa: F401 — re-exported
from tests.e2e.quality_judge import MODEL, call_haiku, extract_json

# The five rubric axes for a FRIEND CONVERSATION (the Community analogue of
# ws_judge.RUBRIC_AXES). Surfaced in the report so a reader sees what "quality"
# means here.
RUBRIC_AXES: dict[str, str] = {
    "in_character": "각 친구가 자기 성격·말투·관계(반말/존대, 호칭)를 일관되게 유지하는가",
    "coherence": "오너의 말에 실제로 반응하고 맥락이 이어지는가 (동문서답·맥락붕괴 아님)",
    "naturalness": "사람 친구처럼 자연스러운가 (기계적·템플릿·AI 티 나지 않음)",
    "engagement": "대화를 살아있게 끌고 가는가 (되묻기·공감·구체적 디테일)",
    "no_meta": "자신이 AI/봇/모델이라는 티를 절대 내지 않는가 (인간 친구의 환상 유지)",
}

# Pass bar: a conversation is portfolio-worthy at >=7/10 overall by default.
DEFAULT_MIN_SCORE = 7

_CONVERSATION_JUDGE_PROMPT = """너는 한 사람(오너)이 자기 AI 친구들과 나눈 채팅 대화를 평가하는 채점자야.
이건 'AI 친구 커뮤니티' 제품이라 — 친구들이 진짜 사람처럼 느껴져야 성공이다.

오너가 한 일(이번 세션의 시나리오):
{goal}

맥락:
{context}

아래 다섯 축으로 0~10 채점해. 각 축의 기준:
1. in_character — {in_character}
2. coherence — {coherence}
3. naturalness — {naturalness}
4. engagement — {engagement}
5. no_meta — {no_meta}

엄격하게 JSON 만 출력. 코멘트·설명·markdown 금지:
{{"scores": {{"in_character": 0-10, "coherence": 0-10, "naturalness": 0-10, "engagement": 0-10, "no_meta": 0-10}},
  "overall": 0-10,
  "pass": true|false,
  "rationale": "한 줄 총평 (왜 그 점수인지, 한 문장)"}}

overall 기준: 8-10 = 진짜 친구 같음, 바로 보여줘도 좋음. 5-7 = 쓸만하나 어색함 있음. 0-4 = 기계적/맥락붕괴/AI 티.
pass = overall >= {min_score}.

--- 대화 기록 ---
{transcript}
"""


def _coerce_score(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(10.0, f))


def judge_conversation(
    *,
    transcript: str,
    goal: str,
    context: str = "",
    min_score: int = DEFAULT_MIN_SCORE,
    timeout: int = 120,
) -> dict[str, Any]:
    """Score a friend-conversation transcript with the reused Haiku judge.

    Returns ``{status, scores:{axis:0-10}, overall, pass, rationale, model,
    min_score}``. ``status`` is ``"scored"`` / ``"error"`` (a failed call counts as
    not-passed, never a fake score). The caller SKIPS on echo before calling this
    (mirrors ws_judge / eval/runner.py)."""
    if not (transcript or "").strip():
        return {"status": "error", "scores": {}, "overall": None, "pass": False,
                "rationale": "empty transcript — nothing to judge",
                "model": MODEL, "min_score": min_score}

    prompt = _CONVERSATION_JUDGE_PROMPT.format(
        goal=goal or "(시나리오 미지정)",
        context=context or "(맥락 없음)",
        transcript=transcript[:6000],
        min_score=min_score,
        **RUBRIC_AXES,
    )
    raw = call_haiku(prompt, timeout=timeout)
    if not raw or raw.startswith("__ERROR__"):
        return {"status": "error", "scores": {}, "overall": None, "pass": False,
                "rationale": f"judge call failed: {raw[:80]}",
                "model": MODEL, "min_score": min_score}

    data = extract_json(raw) or {}
    raw_scores = data.get("scores") or {}
    scores: dict[str, float] = {}
    for axis in RUBRIC_AXES:
        s = _coerce_score(raw_scores.get(axis))
        if s is not None:
            scores[axis] = s

    overall = _coerce_score(data.get("overall"))
    if overall is None and scores:
        overall = round(sum(scores.values()) / len(scores), 1)

    if "pass" in data:
        passed = bool(data.get("pass"))
    else:
        passed = isinstance(overall, (int, float)) and overall >= min_score

    return {
        "status": "scored",
        "scores": scores,
        "overall": overall,
        "pass": passed,
        "rationale": (data.get("rationale") or "").strip(),
        "model": MODEL,
        "min_score": min_score,
    }
