# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""Glimi Workspace DELIVERABLE-QUALITY LLM judge.

The Workspace's whole point is the final deliverable the manager (coordinator)
hands the owner. ``ws_verdict`` already judges the *autonomous loop* structurally
(did every round produce a deliverable, did A2A happen, no meta leaks…). This
module adds the missing axis: **is the deliverable actually GOOD?** — scored by an
LLM judge against a portfolio rubric (completeness / structure / actionability /
specificity / correctness).

We do NOT re-implement an LLM judge. The project already ships a Haiku-backed
offline judge (``tests/e2e/quality_judge.py``) that production QA *and*
``glimi-core/eval/judge.py`` reuse; this module reuses the exact same primitives
(:func:`call_haiku`, :func:`extract_json`, ``MODEL``) so every judge surface in
the repo shares one model + one parsing path.

Backend honesty (the iron rule from eval/judge.py): the judge spawns the
``claude`` CLI, so it ONLY runs on a real backend AND when the CLI is present. On
echo (deterministic, $0) the deliverable is a fixed ``(echo) You said: …`` string
— scoring it would be meaningless theater — so the caller SKIPS the judge and
records ``status="skipped"`` with reason ``"echo"``. No fabricated scores, ever.
"""
from __future__ import annotations

import shutil
from typing import Any

# Reuse the project's offline judge primitives — same model + parser the
# Community QA judge and the core eval judge use. tests/e2e is importable
# (tests/e2e/__init__.py exists).
from tests.e2e.quality_judge import (  # noqa: E402
    MODEL,
    call_haiku,
    extract_json,
)

# The five rubric axes, with the bar each one sets. Surfaced in the report so a
# reader sees exactly what "quality" means here (not a black-box number).
RUBRIC_AXES: dict[str, str] = {
    "completeness": "결정·실행 계획·리스크·다음 단계가 모두 채워졌고 목표를 실제로 다루는가",
    "structure": "명확한 섹션/제목/목록으로 한눈에 읽히는가 (벽 텍스트 아님)",
    "actionability": "오너가 바로 실행할 수 있는 구체적 다음 행동·담당·순서가 있는가",
    "specificity": "이름·수치·트레이드오프 등 구체가 있는가 (공허한 일반론 아님)",
    "correctness": "내용이 목표/맥락과 일관되고 모순·헛소리가 없는가",
}

# Pass bar: a deliverable is portfolio-worthy at >=7/10 overall by default.
DEFAULT_MIN_SCORE = 7


def judge_available() -> bool:
    """True when the Claude CLI is on PATH (so the Haiku judge can run)."""
    return shutil.which("claude") is not None


_DELIVERABLE_JUDGE_PROMPT = """너는 한 팀이 오너에게 제출한 최종 결과물(딜리버러블)을 평가하는 채점자야.
결과물은 매니저가 팀(리서처/빌더/크리틱)의 논의를 종합해 작성한 실무 문서다.

평가 대상 목표:
{goal}

오너가 준 맥락:
{context}

아래 다섯 축으로 0~10 채점해. 각 축의 기준:
1. completeness — {completeness}
2. structure — {structure}
3. actionability — {actionability}
4. specificity — {specificity}
5. correctness — {correctness}

엄격하게 JSON 만 출력. 코멘트·설명·markdown 금지:
{{"scores": {{"completeness": 0-10, "structure": 0-10, "actionability": 0-10, "specificity": 0-10, "correctness": 0-10}},
  "overall": 0-10,
  "pass": true|false,
  "rationale": "한 줄 총평 (왜 그 점수인지, 채용 매니저가 읽을 한 문장)"}}

overall 기준: 8-10 = 포트폴리오로 바로 내놔도 좋음. 5-7 = 쓸만하나 보완 필요. 0-4 = 빈약/형편없음.
pass = overall >= {min_score}.

--- 결과물 ---
{deliverable}
"""


def _coerce_score(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(10.0, f))


def judge_deliverable(
    *,
    deliverable: str,
    goal: str,
    context: str = "",
    min_score: int = DEFAULT_MIN_SCORE,
    timeout: int = 120,
) -> dict[str, Any]:
    """Score a final deliverable with the reused Haiku judge.

    Returns a normalized dict::

        {status, scores: {axis: 0-10}, overall, pass, rationale, model, min_score}

    ``status`` is one of:
      * ``"scored"`` — judge ran and returned a verdict;
      * ``"error"``  — judge call failed (counts as not-passed, NOT a fake score);
      * ``"skipped"`` — caller should set this (echo / no CLI); this function does
        not skip itself, but returns ``error`` gracefully if the deliverable is
        empty so the caller never crashes.

    The caller (runner) is responsible for skipping on echo BEFORE calling this —
    mirroring eval/runner.py, which never invokes the judge in echo mode.
    """
    if not (deliverable or "").strip():
        return {"status": "error", "scores": {}, "overall": None, "pass": False,
                "rationale": "empty deliverable — nothing to judge",
                "model": MODEL, "min_score": min_score}

    prompt = _DELIVERABLE_JUDGE_PROMPT.format(
        goal=goal or "(목표 미지정)",
        context=context or "(맥락 없음)",
        deliverable=deliverable[:6000],  # cap input; a real brief fits well under this
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
        # Derive overall from the axis mean if the judge omitted it.
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


def skipped(reason: str = "echo", *, min_score: int = DEFAULT_MIN_SCORE) -> dict[str, Any]:
    """The honest 'judge did not run' verdict (echo / no CLI). No score fabricated."""
    return {"status": "skipped", "scores": {}, "overall": None, "pass": None,
            "rationale": f"judge skipped ({reason})", "model": MODEL,
            "min_score": min_score, "reason": reason}
