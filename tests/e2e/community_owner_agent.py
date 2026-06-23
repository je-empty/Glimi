# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Jaebin Sim
"""community_owner_agent — the autonomous OWNER who drives the Community web E2E.

This is the Community analogue of :mod:`workspace.owner_agent`. Where the workspace
owner-agent reviews a team's deliverable and hands down the next instruction, this
owner-agent is the human's social stand-in: a real person who just opened their
Glimi and chats with their AI friends + manager (유나) + creator (하나) — turn by
turn, from the START (onboarding) — deciding each round which channel to talk in
and what to say, **in character as the human owner** (never meta / never "as an AI").

It REUSES the heart of :mod:`tests.e2e.test_user_bot` (the existing autonomous
owner-driver that role-plays the owner over Discord): its owner PERSONA + the
per-turn decision logic (given the recent transcript, decide the owner's next
message), the no-meta / no-stage-direction guards, and the onboarding-then-explore
arc (greet 유나 → ask 하나 for a friend → chat with friends → follow up). The
difference is the surface: here the owner drives the REAL served web chat over the
WebSocket instead of Discord, so the decision logic is lifted out of the Discord
client into two backend-agnostic functions the web harness can call directly:

  - :func:`owner_next_turn(state) -> {"channel", "text", "note"}` — one owner turn:
    given a snapshot of the community (channels + recent messages per channel +
    which friends exist + the round/phase), call the SAME ``glimi.llm.generate``
    choke-point the kernel uses to pick the owner's next channel + message.
  - :func:`OwnerDriver` — a thin stateful wrapper that tracks the running
    transcript across rounds so the loop in :mod:`tests.e2e.community_e2e` is a
    plain ``for round: turn = driver.next_turn(snapshot); send; await reply;
    driver.observe(reply)``.

Backend discipline (mirrors workspace/owner_agent + runtime.generate_agent_to_agent):
  - On the offline **echo** backend, the owner turns are a deterministic scripted
    arc (:data:`SCRIPTED_TURNS`) — coherent, onboarding-first, $0, stable — so the
    self-test exercises the full WS loop + verdict without any model spend.
  - On **claude_cli / claude / ollama**, it shells to ``glimi.llm.generate`` with
    ``agent_type="mgr"`` (the human's stand-in tier, same as the workspace owner),
    parses the owner's JSON decision, and degrades gracefully on any flaky turn
    (falls back to a safe scripted turn) so the loop never crashes.

Kernel boundary holds: imports ``glimi`` only (no Discord). The owner is NOT a
kernel agent — it has no profile and never shows on the roster; it just posts as
the owner over the WS.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

# ── owner persona (ported from tests.e2e.test_user_bot.PERSONA) ─────────────────
# The same human owner the Discord driver role-plays, retargeted at the web chat.
# A real person chatting with their AI friends + manager — warm, curious, casual
# 반말, PROACTIVE (keeps the world moving), and NEVER meta. The character-creation
# constraint (prefer female friends — the avatar bank only has female avatars) and
# the no-stage-direction / no-meta output rules are carried over verbatim in spirit.
_OWNER_NAME = os.environ.get("QA_OWNER_NAME", "심재빈")
_OWNER_NICK = os.environ.get("QA_OWNER_NICKNAME", "재빈")
_OWNER_AGE = os.environ.get("QA_OWNER_AGE", "29")

OWNER_PERSONA = f"""You are {_OWNER_NAME}, a {_OWNER_AGE}-year-old (Korean age) person.
Your nickname is {_OWNER_NICK}. You just opened your own little space where your AI
friends + a manager (유나) + a friend-maker (하나) live, and you're chatting with them
over a web chat. You speak Korean casually (반말), warm and a bit playful.

Personality:
- Curious, friendly, a real person texting — not a tester, not a system.
- PROACTIVE — you keep things moving. You greet the manager, ask 유나 (the manager) to
  set you up with a new friend, then actually go chat with that friend, follow up on
  what they said, and explore. Boredom is failure — if a room goes quiet, pivot or
  move to another.
- Owns the tempo: ask favors ("새 친구 한 명만 만들어줘"), check in on friends, react
  to what they actually said.

Who handles what (IMPORTANT — talk to the right person):
- 유나 = the MANAGER. She's your main point of contact. You ask HER for a new friend,
  and she arranges it (she has 하나 design + make the friend behind the scenes). You do
  NOT haggle the details with 하나 directly — just tell 유나 the vibe you want.
- 하나 = the friend-maker working with 유나. Once a new friend exists they appear in
  their own DM; that's who you actually go chat with.

What you're doing now (your natural arc, EARLY → LATER):
1. EARLY (onboarding): say hi to 유나 (the manager) first — ask what you can do here,
   get oriented. Then ask 유나 to set you up with a new friend — describe the vibe in
   one or two lines and let her handle it ("유나야 나 친구 한 명 만들고 싶은데, 밝고 수다스러운
   여자애로 만들어줄래? 세세한 건 알아서 정해줘 ㅎㅎ"). Natural, one ask.
2. MIDDLE: once a friend exists, go to that friend's DM and actually chat — greet,
   ask how they're doing, find common ground, follow up naturally.
3. LATER: keep the friendships going, maybe ask 유나 for one more friend, or ask 유나
   to set something up. React to what people said; don't repeat yourself.

Friend-creation constraint (carryover):
- When you ask 유나 to set up a new friend, ALWAYS describe a FEMALE friend (여자 사람).
  Use feminine terms ("여자애", "친구"). Never request a male friend.
- BE DECISIVE + DELEGATE so the friend actually gets made. Tell 유나 the vibe ONCE and
  hand her the details — "세세한 건 다 알아서 정해서 만들어줘". If 유나 (or 하나) asks a
  detail or "이렇게 만들어줄까?", answer in ONE short line and push to make it: "응! 딱
  좋아, 그렇게 바로 만들어줘 ㅎㅎ" or "다 알아서 해줘, 바로 만들어줘!". Do NOT pile on new
  requirements or drag the Q&A out — a clear yes + delegation is what makes the friend
  appear. Never leave a "만들까?" hanging.

Rules (carryover from the Discord driver):
- Korean only. Text like a real person on KakaoTalk — SHORT (1-3 sentences).
- You don't know words like "에이전트", "페르소나", "멤버", "봇", "AI". NEVER use them.
  If someone uses them, you'd just say "그게 뭔데? ㅋㅋ".
- NEVER reveal or imply this is a test / simulation / system. You ARE a real person.
- NEVER claim you did something you haven't actually done in the log (no fake "다녀왔어").
- Don't repeat a question/info you already gave — reference it instead.
- No stage directions in parentheses like "(웃으며)" / "(궁금한 톤)". You ARE the person.
- No author-name prefix ("{_OWNER_NICK}:" / "나:"). No meta reasoning lines.
- React to the LAST message in the channel you're talking in. Stay on that channel's
  topic — don't drag another channel's context in.

Output (STRICT): respond with ONE JSON object only, nothing else:
{{"channel": "<the channel id you choose to talk in this turn>",
  "text": "<exactly what you'd type, plain Korean — your message only>",
  "note": "<one short private line: why this channel/message — only you see this>"}}
"""

# ── what the manager / creator channels are, for prompt hints ───────────────────
# Stable kernel ids (see community/bot/__init__.py + seed). The owner doesn't say
# these ids — they're just so the harness/prompt can label the rooms in human terms.
MGR_ID = "agent-mgr-001"
CREATOR_ID = "agent-creator-001"
MGR_NAME = "유나"      # manager
CREATOR_NAME = "하나"  # friend-maker / creator


# ── deterministic scripted arc for the echo backend ($0, offline) ───────────────
# Each round consumes the next entry; the arc is onboarding-first so an echo run
# demonstrates the SAME from-the-start flow a real run drives. ``channel`` is a
# logical target the driver maps to a concrete channel from the live snapshot
# ("mgr" → 유나 DM, "creator" → 하나 DM, "friend" → the first friend DM if one
# exists else creator). Kept natural + non-meta so the no-meta scan stays clean.
SCRIPTED_TURNS: list[dict] = [
    {"channel": "mgr",
     "text": "안녕! 여기 처음인데 나 뭐부터 하면 돼? ㅎㅎ",
     "note": "매니저(유나)한테 먼저 인사하고 뭐 할 수 있는지 물어봄 (온보딩 시작)."},
    {"channel": "mgr",
     "text": "유나야 나 친구 한 명 만들고 싶은데, 책 좋아하고 차분한 여자애로 만들어줄래? 세세한 건 알아서 정해줘 ㅎㅎ",
     "note": "매니저 유나한테 새 친구 요청 (여자 친구 컨셉, 디테일은 위임). 유나가 하나한테 전달해 생성."},
    {"channel": "friend",
     "text": "안녕! 우리 이제 친구 하자 ㅎㅎ 요즘 어떻게 지내?",
     "note": "새로 생긴 친구 DM 으로 가서 첫 인사."},
    {"channel": "friend",
     "text": "오 좋다 ㅋㅋ 나도 요즘 그런 거 빠졌어. 주말엔 보통 뭐 해?",
     "note": "친구가 답한 내용에 이어서 자연스럽게 후속 질문."},
    {"channel": "mgr",
     "text": "유나야 친구들이랑 더 친해지려면 뭐 하면 좋을까?",
     "note": "매니저한테 다음 할 거 물어봄 (탐색)."},
    {"channel": "friend",
     "text": "나 왔어 ㅎㅎ 뭐 하고 있었어?",
     "note": "친구 DM 재방문 — 관계 이어가기."},
]


# ── language / prompt assembly ──────────────────────────────────────────────────

def _lang(lang: Optional[str]) -> str:
    if lang:
        return lang
    return os.environ.get("GLIMI_LANG", "ko")


def _phase(round_idx: int, has_friend: bool) -> str:
    """Coarse arc phase used to steer the prompt (onboarding → meet → explore)."""
    if round_idx == 0:
        return "onboarding"
    if not has_friend:
        return "meeting_friends"
    return "exploring"


def _render_channels(state: dict) -> str:
    """Human-readable rundown of the rooms + their last few messages for the prompt.

    ``state['channels']`` maps channel_id → list of {speaker, text, is_user} (most
    recent last). We label the manager/creator/friend rooms in human terms so the
    owner picks a room by who's in it, not by an opaque id.
    """
    chans = state.get("channels") or {}
    labels = state.get("labels") or {}
    if not chans:
        return "(아직 아무 방도 없어요 — 매니저(유나)한테 먼저 말 거세요.)"
    lines: list[str] = []
    for ch, msgs in chans.items():
        label = labels.get(ch, ch)
        lines.append(f"[{label}]  (channel id: {ch})")
        for m in (msgs or [])[-4:]:
            who = "나" if m.get("is_user") else (m.get("speaker") or "?")
            txt = (m.get("text") or "").strip().replace("\n", " ")
            if len(txt) > 160:
                txt = txt[:160] + "…"
            lines.append(f"  {who}: {txt}")
        if not msgs:
            lines.append("  (아직 대화 없음)")
    return "\n".join(lines)


def _build_prompt(state: dict) -> str:
    round_idx = int(state.get("round", 0))
    has_friend = bool(state.get("friend_channels"))
    phase = _phase(round_idx, has_friend)

    friends = state.get("friend_names") or []
    friends_line = ("지금 있는 친구: " + ", ".join(friends)) if friends else \
        "아직 친구가 없어요 — 유나(매니저)한테 만들어 달라고 하면 유나가 처리해서 생겨요."

    # You ask 유나 (the manager) for a friend; she relays to 하나 (request_dm) and 하나
    # actually creates it. So once 유나 has replied to your request but no friend exists
    # yet, the move is to DELEGATE + push ("다 알아서 바로 만들어줘") — not to re-spec or
    # drift off. (Going through 유나 is the path that reliably fires create_agent_profile,
    # mirroring the Discord QA; haggling with 하나 directly stalls in Q&A.)
    mgr_ch = state.get("mgr_channel")
    mgr_msgs = (state.get("channels") or {}).get(mgr_ch) or []
    mgr_replied = any(not m.get("is_user") for m in mgr_msgs)
    asked_for_friend = any(
        m.get("is_user") and ("만들어" in (m.get("text") or "") or "친구" in (m.get("text") or ""))
        for m in mgr_msgs
    )
    awaiting_confirm = (not has_friend) and mgr_replied and asked_for_friend

    phase_hint = {
        "onboarding":
            "지금은 막 들어온 참이에요. 이번 턴엔 매니저(유나)한테 인사하고 여기서 뭘 할 수 있는지"
            "'만' 물어보세요. 친구 요청은 섞지 말고 다음 턴에 따로 할 거예요 — 한 메시지에 "
            "인사+질문+친구부탁을 다 욱여넣지 마세요 (그러면 유나가 인사로만 받고 친구 생성을 놓쳐요).",
        "meeting_friends":
            "아직 같이 놀 친구가 없네요. 매니저 유나한테 새 친구를 만들어 달라고 부탁하세요 — "
            "어떤 느낌의 여자 친구였으면 좋겠는지 한두 마디로 던지고, 세부(이름·나이·성격·관계)는 "
            "'다 알아서 정해서 바로 만들어줘'라고 유나한테 전부 맡기세요. 유나가 하나한테 전달해서 "
            "친구를 만들어 줄 거예요. 하나한테 직접 가서 세부를 따지지 말 것 — 유나한테 맡기는 게 핵심.",
        "exploring":
            "이제 친구가 생겼어요. 친구 DM 으로 가서 실제로 수다 떠세요 — 인사하고, 근황 묻고, "
            "친구가 한 말에 이어서 자연스럽게. 가끔 유나한테 다음 할 거 물어보거나 친구를 "
            "한 명 더 부탁해도 돼요. 같은 말 반복 금지.",
    }[phase]

    # Override: 유나 already replied to your friend request but no friend yet → stop
    # re-spec'ing, DELEGATE and push to make it (don't get pulled into a detail Q&A).
    if awaiting_confirm:
        phase_hint = (
            "유나한테 친구를 부탁했고 유나가 답을 했어요. 지금은 친구를 **확정**할 타이밍이에요 — "
            "유나 DM(channel id 위 참고)으로 가서 딱 한 줄로 밀어붙이세요. 유나(또는 하나)가 이름·나이·"
            "관계 같은 세부를 되물어도 **일일이 답하지 말고** '아 그런 건 다 알아서 정해줘! 그냥 지금 "
            "바로 만들어줘 ㅎㅎ'처럼 전권을 넘기며 재촉하세요. 누가 '이렇게 만들까?' 하면 '응! 딱 좋아, "
            "그렇게 바로 만들어줘'로 확정. 새 조건 붙이거나 질문에 끌려가지 말 것."
        )

    return (
        f"지금 라운드: {round_idx + 1}.  (단계: {phase})\n"
        f"{friends_line}\n\n"
        f"지금 열려 있는 방들과 최근 대화:\n{_render_channels(state)}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{phase_hint}\n"
        f"이번 턴에 어느 방(channel id)에서 무슨 말을 할지 정하세요. 그 방의 가장 최근 "
        f"메시지에 자연스럽게 이어서. JSON 하나로만 답하세요 "
        f'{{"channel": "...", "text": "...", "note": "..."}}.'
    )


# ── meta / stage-direction scrub (ported from test_user_bot._send_reply) ─────────

_NAME_PREFIX_RE = re.compile(rf"^\s*(?:나|{re.escape(_OWNER_NAME)}|{re.escape(_OWNER_NICK)})\s*[:：]\s*")
_META_PAREN_RE = re.compile(
    r"\s*\([^()]*?(?:톤|느낌|처럼|듯|표정|얼굴|목소리|뉘앙스|식으로|정색|웃음|한숨)[^()]*?\)\s*"
)


def _scrub(text: str) -> str:
    """Strip a self-name prefix + meta stage-direction parens (the Discord driver's
    cleanup), collapse whitespace. Keeps the owner reading like a real person."""
    if not text:
        return ""
    out_lines: list[str] = []
    for line in text.splitlines():
        line = _NAME_PREFIX_RE.sub("", line)
        line = _META_PAREN_RE.sub(" ", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            out_lines.append(line)
    return "\n".join(out_lines).strip()


def _parse_owner_json(text: str) -> Optional[dict]:
    """Tolerantly pull the owner's {channel,text,note} object out of model text
    (strict json.loads first, then the first {...} block). Returns normalized keys
    or None (caller degrades to a scripted turn)."""
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
        if isinstance(obj, dict) and (obj.get("text") or obj.get("channel")):
            return {
                "channel": str(obj.get("channel", "") or "").strip(),
                "text": _scrub(str(obj.get("text", "") or "")),
                "note": str(obj.get("note", "") or "").strip(),
            }
    return None


# ── logical-channel → concrete-channel resolution ───────────────────────────────

def _resolve_channel(state: dict, chosen: str) -> str:
    """Map the owner's chosen channel to a real channel id from the live snapshot.

    Accepts either a concrete channel id (returned as-is if it's a known postable
    channel) or a logical token ('mgr' / 'creator' / 'friend'). Falls back to the
    manager DM (always present), so the harness always has a valid target."""
    postable = state.get("postable_channels") or list((state.get("channels") or {}).keys())
    mgr = state.get("mgr_channel")
    creator = state.get("creator_channel")
    friends = state.get("friend_channels") or []

    c = (chosen or "").strip()
    low = c.lower()

    # Exact concrete id the model echoed back from the snapshot.
    if c and c in postable:
        return c
    # Logical tokens / fuzzy matches.
    if low in ("mgr", "manager", "유나", MGR_ID, mgr or ""):
        return mgr or (postable[0] if postable else "")
    if low in ("creator", "maker", "하나", CREATOR_ID, creator or ""):
        return creator or mgr or (postable[0] if postable else "")
    if low in ("friend", "친구") or "persona" in low:
        return friends[0] if friends else (creator or mgr or "")
    # The model may have named a friend by display name — match it.
    for ch in friends:
        nm = (state.get("labels") or {}).get(ch, "")
        if c and (c in nm or c == ch):
            return ch
    # Unknown → safest default: the manager DM.
    return mgr or (postable[0] if postable else "")


# ── backend completion ──────────────────────────────────────────────────────────

_echo_round: dict[int, int] = {}


def reset_echo_state(key: int = 0) -> None:
    """Reset the scripted-turn counter (test helper). Default key 0 = the shared
    process-wide counter the OwnerDriver uses."""
    _echo_round.pop(key, None)


def _echo_turn(state: dict, key: int) -> dict:
    """Deterministic scripted owner turn for the echo backend ($0, offline).

    Advances through SCRIPTED_TURNS. The logical 'friend' channel only makes sense
    once a friend exists; until then it falls back to the creator (ask for a friend),
    so the echo arc stays coherent even though echo never actually creates one."""
    i = _echo_round.get(key, 0)
    _echo_round[key] = i + 1
    turn = dict(SCRIPTED_TURNS[min(i, len(SCRIPTED_TURNS) - 1)])
    # If the script wants a friend but none exists yet, redirect to the manager (유나),
    # who arranges the creation with 하나 (the reliable path — see _build_prompt).
    if turn["channel"] == "friend" and not state.get("friend_channels"):
        turn = {"channel": "mgr",
                "text": "유나야 아직 같이 놀 친구가 없네 ㅎㅎ 한 명만 만들어줄래? 차분한 여자애로, 세세한 건 알아서~",
                "note": "친구가 아직 없어서 유나한테 생성 요청으로 대체 (echo arc)."}
    return turn


def _llm_turn(state: dict, *, lang: str) -> Optional[dict]:
    """One real owner completion via the SAME glimi.llm.generate choke-point the
    kernel A2A path uses. Returns a normalized {channel,text,note} dict, or None on
    any failure (caller degrades to a scripted turn). agent_type='mgr' = the human's
    stand-in tier (mirrors workspace.owner_agent)."""
    backend = (state.get("backend") or "").strip()
    try:
        from glimi import llm
    except Exception:
        return None

    system = OWNER_PERSONA
    user = _build_prompt(state)
    # Resolve a model the same way the workspace owner does, but tolerate a kernel
    # that can't (just pass the backend through; the kernel picks a default model).
    model = state.get("model") or ""
    if not model:
        try:
            from glimi import runtime as _rt
            # _resolve_agent_model is a module-level helper (the mgr tier = the
            # human stand-in's tier, same as workspace.owner_agent).
            model = _rt._resolve_agent_model("__owner__", "mgr")
        except Exception:
            model = "claude-sonnet-4-6"

    try:
        resp = llm.generate(
            system=system, user=user, model=model,
            agent_type="mgr", backend=backend,
            max_tokens=512, timeout=int(state.get("llm_timeout", 180)),
        )
    except Exception:
        return None
    if getattr(resp, "error", None):
        return None
    text = (getattr(resp, "text", "") or "").strip()
    parsed = _parse_owner_json(text)
    if parsed is not None:
        # Track token usage so the harness/verdict can report owner-side cost.
        parsed["_usage"] = {
            "input_tokens": int(getattr(resp, "input_tokens", 0) or 0),
            "output_tokens": int(getattr(resp, "output_tokens", 0) or 0),
        }
        return parsed
    # Model spoke but not as JSON — treat the scrubbed whole reply as the message,
    # let the driver place it on a sensible channel (keeps the loop alive).
    scrubbed = _scrub(text)
    if scrubbed:
        return {"channel": "", "text": scrubbed, "note": "(non-JSON reply)"}
    return None


# ── public API ──────────────────────────────────────────────────────────────────

def owner_next_turn(state: dict, *, lang: Optional[str] = None) -> dict:
    """Decide the owner's next turn → ``{"channel", "text", "note"}``.

    ``state`` is a snapshot the harness assembles each round:
      - ``round``               : 0-based round index
      - ``backend``             : "echo" | "claude_cli" | "claude" | "ollama" | ...
      - ``channels``            : {channel_id: [{speaker, text, is_user}, ...]} (recent)
      - ``labels``              : {channel_id: human label, e.g. "유나(매니저) DM"}
      - ``postable_channels``   : [channel_id, ...] the owner may post to
      - ``mgr_channel`` / ``creator_channel`` : the manager / creator DM ids
      - ``friend_channels``     : [channel_id, ...] friend DMs (excl. mgr/creator)
      - ``friend_names``        : [display names] of current friends

    On echo → a deterministic scripted onboarding-first arc. On a real backend →
    one ``glimi.llm.generate`` completion, degrading to a scripted turn on failure.
    The returned ``channel`` is always a concrete, postable channel id.
    """
    lang_eff = _lang(lang)
    backend = (state.get("backend") or "echo").lower()
    key = int(state.get("_echo_key", 0))

    decision: Optional[dict]
    if backend == "echo":
        decision = _echo_turn(state, key)
    else:
        decision = _llm_turn(state, lang=lang_eff)
        if decision is None or not decision.get("text"):
            # Graceful fallback: a real-backend hiccup borrows the scripted arc so
            # the session keeps progressing instead of stalling.
            decision = _echo_turn(state, key)

    channel = _resolve_channel(state, decision.get("channel", ""))
    text = decision.get("text") or ""
    if not text:
        # Absolute last-resort safe turn (never send an empty owner frame).
        text = "안녕! 잘 지냈어? ㅎㅎ"
    return {
        "channel": channel,
        "text": text,
        "note": decision.get("note", ""),
        "usage": decision.get("_usage", {}),
    }


class OwnerDriver:
    """Stateful per-session wrapper around :func:`owner_next_turn`.

    The harness builds a fresh community snapshot each round and calls
    :meth:`next_turn(snapshot)`; the driver fills in the per-session bookkeeping
    (the echo counter key, accumulated owner-side token usage) so the harness loop
    stays a clean ``turn = driver.next_turn(snap); send; await; driver.observe()``.
    """

    def __init__(self, *, backend: str, lang: Optional[str] = None):
        self.backend = backend
        self.lang = lang
        self._key = id(self)
        self.turns: list[dict] = []
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        reset_echo_state(self._key)

    def next_turn(self, snapshot: dict) -> dict:
        state = dict(snapshot)
        state["backend"] = self.backend
        state["_echo_key"] = self._key
        if self.lang:
            state["lang"] = self.lang
        turn = owner_next_turn(state, lang=self.lang)
        u = turn.get("usage") or {}
        self.usage["input_tokens"] += int(u.get("input_tokens", 0) or 0)
        self.usage["output_tokens"] += int(u.get("output_tokens", 0) or 0)
        self.turns.append({"channel": turn["channel"], "text": turn["text"],
                           "note": turn.get("note", "")})
        return turn
