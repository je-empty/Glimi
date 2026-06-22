# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""workspace/owner_agent.py — the owner-agent: the human's autonomous stand-in.

In a normal workspace a *human* owner gives the Coordinator a goal, then each
round reads what the team brought back, says what's good / what's missing, and
hands down the next concrete ask — until it's good enough. The owner-agent does
exactly that, autonomously, so the workspace can run the **goal → work → review →
next-instruction** loop on its own (the work-clone analogue of the Community's
autonomous social-sim).

Crucially the owner-agent is **NOT a kernel agent** — it is not in ``TEAM``, has
no profile, and never shows on the dashboard roster. It is the human's
stand-in: a thin LLM caller that reuses the workspace's configured backend (the
SAME ``glimi.llm`` choke-point the kernel's agent-to-agent engine uses), then
posts to channels *as the owner* (``g.owner.id()``). Keeping it off the roster is
deliberate — the graph stays a clean picture of the *team*, with the owner as the
single human seat it already has.

Two things happen each round:

1. :func:`owner_review` runs the owner-persona turn — it reads the goal, the
   running transcript, and the latest deliverable, and returns
   ``{done, instruction, note}``: whether the work is good enough, the next
   concrete ask for the Coordinator (empty when done), and the owner's private
   reasoning.
2. That private reasoning is logged to the read-only **internal-owner** channel
   (``OWNER_REVIEW_CHANNEL``) — the "owner thinking out loud" the web shows so a
   viewer can watch the owner review the work, the same way the internal A2A
   channels let you watch specialists debate.

The owner's *instruction* is posted to ``dm-coordinator`` by the DRIVER, not
here, so the post→run ordering lives in exactly one place (the driver). This
module only produces the instruction + logs the reasoning.

Backend discipline (mirrors ``runtime.generate_agent_to_agent``):
  - On the offline **echo** backend, :func:`_complete` returns a deterministic
    scripted review from :data:`SCRIPTED_REVIEWS` — coherent, progressing, and
    ``$0`` — so demos and tests are free and stable.
  - On **claude / ollama**, it shells to the same ``glimi.llm.generate`` helper
    the A2A path uses; if the provider resolves to ``CAPPED`` (monthly budget
    exhausted, no local fallback) it returns ``{done: True}`` so the owner can't
    keep spending — a defensive brake on top of the driver's own budget gate.

Kernel boundary holds: imports ``glimi`` only (no ``src`` / Discord).
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from glimi import Glimi

# The read-only channel where the owner's reasoning is logged so the web can show
# "the owner thinking". It starts with ``internal-`` so the kernel's write-gate
# (``_ws_postable``) treats it as read-only with no extra plumbing, and
# ``_list_chat_channels`` already buckets it under "Behind the scenes".
OWNER_REVIEW_CHANNEL = "internal-owner"

# Owner-persona system prompt. Korean is the default per the UI rule; EN via
# GLIMI_LANG. The contract: respond with ONE JSON object
# {"done": bool, "instruction": str, "note": str}. NEVER any meta term — the
# owner must read as a human delegating work, not a system describing itself.
OWNER_SYS_KO = (
    "당신은 이 일의 주인입니다. 매니저가 이끄는 팀에게 목표를 주고, 매 라운드 "
    "그들이 가져온 결과물을 사람 오너처럼 검토합니다. 좋은 점과 부족한 점을 짧게 "
    "짚고, 다음에 시킬 구체적인 한 가지 지시를 정하거나, 충분하면 끝냅니다. 메타 "
    "용어(에이전트/봇/AI/시뮬레이션/프롬프트/페르소나) 절대 금지 — 그냥 동료에게 "
    "일을 맡기는 사람처럼 말하세요.\n"
    "반드시 JSON 객체 하나로만 답하세요: "
    '{"done": true/false, "instruction": "매니저에게 줄 다음 구체적 지시 '
    '(끝났으면 빈 문자열)", "note": "당신만 보는 짧은 검토 메모"}.'
)

OWNER_SYS_EN = (
    "You are the owner of this work. You give a goal to the team the Coordinator "
    "leads, and each round you review what they brought back like a human owner. "
    "Briefly note what's good and what's missing, then either decide one concrete "
    "next instruction or, if it's good enough, finish. NEVER use any meta term "
    "(agent / bot / AI / simulation / prompt / persona) — speak like a person "
    "handing work to colleagues.\n"
    "Respond with ONE JSON object only: "
    '{"done": true/false, "instruction": "the next concrete ask for the '
    'Coordinator (empty string if finished)", "note": "a short private review '
    'note only you see"}.'
)

# Deterministic scripted reviews for the echo backend (free, offline, $0). Each
# round consumes the next entry; the last marks ``done`` so an echo run converges
# instead of looping. Written as believable Korean owner reviews — no meta terms,
# each pushing a distinct concrete next ask so QA's "progressing, not repeating"
# check passes.
SCRIPTED_REVIEWS: list[dict] = [
    {"done": False,
     "instruction": "방향은 좋아요. 다음엔 핵심 결정을 실제로 통과하는지부터 검증해 "
                    "주세요 — 가장 약한 가정 하나를 깨끗한 환경에서 직접 확인해요.",
     "note": "팀이 가져온 방향 좋아요 — 정직한 기조 맞고. 다만 진짜 통과하는지 검증이 "
             "빠졌네. 다음 라운드에 그거 검증부터 시켜야겠다."},
    {"done": False,
     "instruction": "검증은 통과했네요. 이제 일정과 담당자까지 박은 실행 계획으로 "
                    "마무리해 주세요 — 당장 시작할 수 있게.",
     "note": "검증 통과 확인했고. 이제 실제로 굴릴 수 있게 일정·담당까지 잡으면 끝이 "
             "보인다."},
    {"done": True,
     "instruction": "",
     "note": "일정·담당까지 다 잡혔어요. 이 정도면 충분합니다 — 여기서 마무리."},
]


def _lang(lang: Optional[str]) -> str:
    """Effective language: explicit arg → GLIMI_LANG → 'ko' (UI default)."""
    if lang:
        return lang
    return os.environ.get("GLIMI_LANG", "ko")


def _owner_system(lang: str) -> str:
    return OWNER_SYS_EN if str(lang).lower().startswith("en") else OWNER_SYS_KO


def _render_transcript(transcript: list) -> str:
    """Compact rendering of prior rounds for the review prompt.

    ``transcript`` is the driver's running list of
    ``(round_idx, instruction, deliverable, owner_note)``. We keep deliverables
    short (preview) so the prompt stays bounded across many rounds; the latest
    deliverable is passed in full separately.
    """
    if not transcript:
        return "(아직 진행된 라운드가 없습니다 — 첫 지시를 정하세요.)"
    lines = []
    for entry in transcript:
        try:
            idx, instruction, deliverable, _note = entry
        except Exception:
            # tolerate (idx, instruction, deliverable) tuples too
            idx, instruction, deliverable = entry[0], entry[1], entry[2]
        preview = (deliverable or "").strip().replace("\n", " ")
        if len(preview) > 240:
            preview = preview[:240] + "…"
        lines.append(f"[라운드 {idx}] 지시: {instruction}\n  결과: {preview}")
    return "\n".join(lines)


def _build_review_prompt(*, goal: str, context: str, backlog, transcript: list,
                         last_deliverable: str, first_round: bool) -> str:
    """Assemble the owner's review/decision prompt."""
    backlog_text = _normalize_backlog(backlog)
    parts = [f"목표: {goal}"]
    if context:
        parts.append(f"컨텍스트: {context}")
    if backlog_text:
        parts.append("백로그(아직 남은 것들):\n" + backlog_text)

    if first_round:
        parts.append(
            "\n아직 아무 작업도 시작되지 않았습니다. 이 목표를 위해 매니저에게 줄 "
            "첫 지시를 정하세요 — 무엇부터 시작하면 좋을지 구체적으로. (done 은 false)"
        )
    else:
        parts.append("\n지금까지의 진행:\n" + _render_transcript(transcript))
        parts.append(
            "\n방금 받은 최신 결과물(전체):\n" + (last_deliverable or "(없음)")
        )
        parts.append(
            "\n이 결과를 사람 오너처럼 검토하세요. 충분하면 done=true 로 끝내고, "
            "아니면 다음에 시킬 구체적인 한 가지 지시(instruction)를 정하세요. "
            "앞 라운드와 똑같은 지시를 반복하지 말고 일을 한 걸음 진전시키세요."
        )
    return "\n".join(parts)


def _normalize_backlog(backlog) -> str:
    """Backlog → newline-joined text. Accepts a list or a string."""
    if not backlog:
        return ""
    if isinstance(backlog, str):
        items = [ln.strip() for ln in backlog.splitlines() if ln.strip()]
    else:
        items = [str(x).strip() for x in backlog if str(x).strip()]
    return "\n".join(f"- {it}" for it in items)


def _parse_owner_json(text: str) -> Optional[dict]:
    """Tolerantly pull the owner's JSON object out of model text.

    Tries a strict ``json.loads`` first, then the first ``{...}`` block. Returns
    a dict with normalized keys, or None if nothing parseable was found — the
    caller then degrades gracefully (never crashes the loop)."""
    if not text:
        return None
    candidates = [text.strip()]
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        candidates.append(m.group(0))
    for cand in candidates:
        try:
            obj = json.loads(cand)
        except Exception:
            continue
        if isinstance(obj, dict):
            return {
                "done": bool(obj.get("done", False)),
                "instruction": str(obj.get("instruction", "") or "").strip(),
                "note": str(obj.get("note", "") or "").strip(),
            }
    return None


# How many scripted reviews echo runs have produced this process. Keyed by the
# Glimi store id so concurrent workspaces (and fresh test instances) each advance
# their own script independently.
_echo_round: dict[int, int] = {}


def _echo_review(g: Glimi) -> dict:
    """Deterministic scripted owner review for the echo backend ($0, offline)."""
    key = id(g.store)
    i = _echo_round.get(key, 0)
    review = SCRIPTED_REVIEWS[min(i, len(SCRIPTED_REVIEWS) - 1)]
    _echo_round[key] = i + 1
    return dict(review)


def reset_echo_state(g: Optional[Glimi] = None) -> None:
    """Reset the scripted-review counter (test helper). ``None`` clears all."""
    if g is None:
        _echo_round.clear()
    else:
        _echo_round.pop(id(g.store), None)


def _complete(g: Glimi, system: str, user: str) -> dict:
    """Run one owner completion and return ``{done, instruction, note}``.

    - echo backend → deterministic scripted review (free).
    - claude / ollama → the SAME ``glimi.llm.generate`` choke-point A2A uses, via
      the kernel's provider resolution. If the provider resolves to ``CAPPED``
      (monthly budget exhausted, no local fallback), returns a budget-stop dict so
      the owner stops spending mid-run.
    - On any error / unparseable output, degrades gracefully: the raw text becomes
      the instruction (done=False) so the loop survives a flaky turn.
    """
    if getattr(g, "_backend", None) == "echo":
        return _echo_review(g)

    # Real backend: mirror generate_agent_to_agent's provider selection. The owner
    # is the human's stand-in, not a kernel agent, so we resolve a provider using
    # the "mgr" agent_type (same tier the Coordinator runs on) but pass NO agent
    # profile — it's a one-shot completion.
    try:
        from glimi import runtime as _rt
    except Exception:
        # Kernel unavailable — should not happen, but never crash the loop.
        return {"done": False, "instruction": "", "note": ""}

    rt = _rt.runtime
    try:
        model = rt._resolve_agent_model("__owner__", "mgr")
        provider = rt._provider_for("mgr", model)
    except Exception:
        model, provider = "claude-sonnet-4-6", "claude"

    if provider == _rt.CAPPED:
        # Monthly budget exhausted + no local fallback → stop spending.
        return {"done": True, "instruction": "",
                "note": "예산 한도 — 이번 달은 여기까지."}

    from glimi import llm
    if provider == "claude":
        gen_model, gen_backend = model, ""
    elif provider == "ollama":
        try:
            gen_model = rt._ollama_model_arg(model, "mgr")
        except Exception:
            gen_model = model
        gen_backend = ""
    else:  # explicit non-claude backend name (echo handled above, but be safe)
        gen_model, gen_backend = model, provider

    try:
        resp = llm.generate(
            system=system, user=user, model=gen_model,
            agent_type="mgr", backend=gen_backend,
            max_tokens=1024, timeout=180,
        )
    except Exception as exc:  # network/CLI failure → graceful, non-crashing
        return {"done": False, "instruction": "",
                "note": f"(검토 호출 실패: {type(exc).__name__})"}

    if getattr(resp, "error", None):
        return {"done": False, "instruction": "",
                "note": f"(검토 호출 오류)"}

    text = (getattr(resp, "text", "") or "").strip()
    parsed = _parse_owner_json(text)
    if parsed is not None:
        return parsed
    # Unparseable — treat the whole reply as the instruction, keep going.
    return {"done": False, "instruction": text, "note": text[:200]}


def owner_review(
    g: Glimi, *,
    goal: str,
    context: str = "",
    backlog=None,
    transcript: Optional[list] = None,
    last_deliverable: str = "",
    owner_name: str = "",
    lang: Optional[str] = None,
) -> dict:
    """Run the owner's per-round review and return ``{done, instruction, note}``.

    Steps:
      1. Build the review prompt from goal + context + backlog + a compact
         transcript + the latest deliverable in full. The first round (empty
         transcript) asks for an opening instruction instead of a review.
      2. Call the backend (:func:`_complete`).
      3. Log the owner's reasoning to the read-only ``internal-owner`` channel so
         the web can show the owner "thinking", and mirror a one-line summary to
         the kernel observer.
      4. Return the decision.

    The instruction itself is posted to ``dm-coordinator`` by the DRIVER, not
    here — this keeps the post/run ordering in one place.
    """
    transcript = transcript or []
    first_round = not transcript
    lang_eff = _lang(lang)
    system = _owner_system(lang_eff)
    user = _build_review_prompt(
        goal=goal, context=context, backlog=backlog, transcript=transcript,
        last_deliverable=last_deliverable, first_round=first_round,
    )

    decision = _complete(g, system, user)
    # Defensive normalization (a raw _complete from a flaky path may miss keys).
    decision = {
        "done": bool(decision.get("done", False)),
        "instruction": str(decision.get("instruction", "") or "").strip(),
        "note": str(decision.get("note", "") or "").strip(),
    }

    note = decision["note"] or decision["instruction"] or "(검토함)"
    _log_owner_reasoning(g, note)
    return decision


def _log_owner_reasoning(g: Glimi, note: str) -> None:
    """Write the owner's private reasoning to the read-only internal-owner channel
    (so the web shows the owner thinking) + mirror to the kernel observer."""
    owner_id = g.owner.id()
    try:
        g.store.set_channel_participants(OWNER_REVIEW_CHANNEL, [owner_id])
        g.store.log_message(OWNER_REVIEW_CHANNEL, owner_id, note)
    except Exception:
        pass
    try:
        g.observer.system(f"[OWNER] round review: {note[:120]}")
    except Exception:
        pass
