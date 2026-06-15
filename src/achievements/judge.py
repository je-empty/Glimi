"""LLM-judge tier — pre-filter 된 후보 메시지를 Haiku 가 batch 판정.

비용·속도 통제:
  - 후보 ≤ ~10건/도전과제 (pre_filter 가 좁힘)
  - Haiku 1회 호출로 여러 후보 일괄 판정 ("yes/no" 만 라인별로)
  - 결과 캐시 — 같은 (achievement_key, message_id, message_hash) 조합은 다시 호출 안 함
  - state='done' 된 도전과제는 engine 이 이미 skip (judge 호출 자체 안 옴)

비용 예상 (community 1개, 일반 사용):
  - 후보 ~5건/도전과제 × LLM-tier 도전과제 ~5종 × 새 메시지 trigger
  - Haiku ~$0.001/회 → 활성 시간 1h 당 ~$0.005 미만
"""
from __future__ import annotations

import hashlib
import json as _json
import os
import re as _re
from typing import Optional

from src import log_writer

JUDGE_MODEL = "claude-haiku-4-5"
# 로컬 모델(ollama)은 Haiku 보다 느릴 수 있어 여유 확보. claude 경로엔 max 상한일 뿐 영향 없음.
JUDGE_TIMEOUT_SEC = 60
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# In-memory cache: { (achievement_key, message_id, hash): bool }
# 봇 프로세스 수명 동안 유지. 영구 캐시는 추후 (DB) 추가 가능.
_JUDGE_CACHE: dict = {}


def _msg_hash(msg: str) -> str:
    return hashlib.md5(msg.encode("utf-8")).hexdigest()[:10]


def _cache_key(achievement_key: str, message_id: int, message: str) -> tuple:
    return (achievement_key, message_id, _msg_hash(message))


def _build_batch_prompt(prompt_template: str, candidates: list[dict]) -> str:
    """N 개 candidate 를 한 prompt 로 묶음. 응답 형식: 각 줄 i:yes 또는 i:no."""
    lines = [
        prompt_template.strip(),
        "",
        "Answer for each numbered item below. Output format — exactly one line per item:",
        "  1: yes  (or)  1: no",
        "  2: yes  (or)  2: no",
        "  ...",
        "No prose, no explanations, no extra lines. Just the numbered yes/no lines.",
        "",
        "─" * 50,
    ]
    for i, c in enumerate(candidates, 1):
        speaker = c.get("speaker_name") or c.get("speaker", "?")
        msg = (c.get("message") or "").strip()[:300]
        lines.append(f"{i}. [{speaker}] {msg}")
    return "\n".join(lines)


_VERDICT_RE = _re.compile(r"^\s*(\d+)\s*[:\.\)]\s*(yes|no|y|n|1|0|true|false)\b", _re.IGNORECASE)


def _parse_verdicts(text: str, n: int) -> list[bool]:
    """LLM 응답 → bool[n]. 파싱 실패 시 그 인덱스는 False."""
    verdicts = [False] * n
    for line in text.splitlines():
        m = _VERDICT_RE.match(line)
        if not m:
            continue
        idx = int(m.group(1)) - 1
        if 0 <= idx < n:
            v = m.group(2).lower()
            verdicts[idx] = v in ("yes", "y", "1", "true")
    return verdicts


def batch_classify(
    achievement_key: str,
    candidates: list[dict],
    prompt_template: str,
) -> list[bool]:
    """후보 list → bool list (같은 길이). True = 도전과제 trigger 자격.

    - 빈 candidates → 빈 리스트
    - 캐시 hit → 호출 안 함
    - LLM 호출 실패 → 모두 False (보수적, false-positive 방지)
    """
    if not candidates:
        return []

    # 캐시 분리
    results: list[Optional[bool]] = [None] * len(candidates)
    to_judge: list[tuple[int, dict]] = []
    for i, c in enumerate(candidates):
        ck = _cache_key(achievement_key, c.get("id", -1), c.get("message", ""))
        if ck in _JUDGE_CACHE:
            results[i] = _JUDGE_CACHE[ck]
        else:
            to_judge.append((i, c))

    if not to_judge:
        return [bool(r) for r in results]

    # Build batch prompt
    cands_only = [c for _, c in to_judge]
    prompt = _build_batch_prompt(prompt_template, cands_only)

    # src.llm 경유 — GLIMI_LLM_BACKEND=ollama 면 로컬 gemma, 아니면 claude(haiku) 폴백.
    # 백엔드 선택은 _select_backend 가 env 기반으로 결정. 실패는 모두 False (보수적).
    try:
        from src.glimi import llm
        resp = llm.generate(
            system="", user=prompt,
            model=JUDGE_MODEL, agent_type="judge",
            max_tokens=512, timeout=JUDGE_TIMEOUT_SEC,
        )
    except Exception as e:
        log_writer.system(f"[ach.judge] {achievement_key} 오류: {type(e).__name__}: {e}")
        for i, _ in to_judge:
            results[i] = False
        return [bool(r) for r in results]

    if resp.error:
        log_writer.system(
            f"[ach.judge] {achievement_key} LLM 오류: {resp.error[:120]} — 모두 False 처리"
        )
        for i, _ in to_judge:
            results[i] = False
        return [bool(r) for r in results]

    verdicts = _parse_verdicts(resp.text or "", len(to_judge))
    pos_count = sum(1 for v in verdicts if v)
    try:
        _backend = llm.current_backend_name("judge")
    except Exception:
        _backend = "?"
    log_writer.system(
        f"[ach.judge] {achievement_key}: {pos_count}/{len(to_judge)} 양성 (backend={_backend})"
    )

    # Write back + cache
    for (orig_idx, c), v in zip(to_judge, verdicts):
        results[orig_idx] = v
        ck = _cache_key(achievement_key, c.get("id", -1), c.get("message", ""))
        _JUDGE_CACHE[ck] = v

    return [bool(r) for r in results]


def cache_size() -> int:
    return len(_JUDGE_CACHE)


def clear_cache() -> None:
    _JUDGE_CACHE.clear()


__all__ = ["batch_classify", "cache_size", "clear_cache", "JUDGE_MODEL"]
