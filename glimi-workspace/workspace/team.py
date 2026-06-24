"""The Glimi Workspace team — personas + first-run setup, defined in the app.

Everything domain-specific to a *work* team lives here, in the app — the kernel
(``glimi``) stays content-neutral. Two pieces:

- :data:`TEAM` — the Coordinator (manager) plus three role specialists. Functional
  personas, no personal names. The Coordinator is the Workspace analogue of the
  Community sim's manager agent (Yuna/Hana): it greets the owner, restates the
  goal, assigns the specialists, and delivers the final synthesis.
- :class:`Setup` + :func:`resolve_setup` — first-run setup (owner *name* + *goal*),
  resolved from flags → env → a small JSON state file → interactive ``input()`` —
  but **only** prompting on a real TTY, so CI / pipes / the echo demo never hang.

No ``glimi`` import here on purpose: this module is pure config + I/O, so it is
trivially testable and the kernel boundary stays obvious.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# ── shared readability + structure clause ───────────────────────────────────
# Appended to EVERY persona. The kernel's base prompt tells agents to "reply
# briefly as in a chat" — right for the social sim, but it fights a work team
# that needs to actually lay out findings and plans. This clause softens that
# tension for WORK turns: still conversational, but structured and legible.
READABILITY = (
    "\n\n— 읽기 좋게 쓰는 법 —\n"
    "이건 일하는 자리예요. 한 줄짜리 잡담이 아니라, 읽는 사람이 바로 쓸 수 있게 "
    "정리해서 답하세요.\n"
    "• 첫 줄에 핵심 결론을 먼저. 그다음에 근거·세부를 풉니다.\n"
    "• 문단은 짧게. 여러 항목을 나열할 땐 마크다운 목록(`- ` 또는 `1.`)이나 작은 "
    "제목(`## `)을 쓰세요.\n"
    "• 쉬운 말로. 전문 용어를 빽빽하게 쌓지 말고, 필요한 곳에만 정확히.\n"
    "• 길이는 내용에 맞게 — 채팅이라고 억지로 한 줄로 줄이지 마세요. 다만 군더더기 "
    "없이 밀도 있게."
)


# ── the team ──────────────────────────────────────────────────────────────
# (id, display name, agent_type, persona). agent_type="mgr" marks the manager so
# the dashboard ranks it first (mgr → … ), matching the Community sim's manager.
# Personas are functional roles — persona yes, personal name no. The first entry's
# DISPLAY name is "매니저" (the owner's single point of contact), but its agent id
# stays "coordinator" — load-bearing across run.py / server.py / demo.py / tests.
# Each persona carries a rich identity (role · expertise · working style) so the
# agent_detail profile reads like a real teammate, then the shared READABILITY
# clause is appended so every member writes legible, structured work output.
_TEAM_RAW: list[tuple[str, str, str, str]] = [
    ("coordinator", "매니저", "mgr",
     "당신은 이 팀의 총괄 매니저입니다. 오너가 일을 맡길 때 가장 먼저, 그리고 끝까지 "
     "이야기하는 단 한 사람 — 팀의 얼굴이에요.\n"
     "당신이 하는 일:\n"
     "• 목표를 정확히 이해합니다. 애매하거나 빠진 게 있으면 혼자 짐작하지 말고 "
     "오너에게 되물어 좁히세요 — 무엇을, 누구를 위해, 언제까지, 어떤 게 성공인지.\n"
     "• 이해한 목표를 당신의 말로 한 문장으로 다시 정리해 오너와 맞춥니다.\n"
     "• 일을 쪼개 리서처·빌더·크리틱에게 명확한 방향을 배분하고, 굴러가게 합니다.\n"
     "• 팀이 가져온 것을 모아 오너가 바로 쓸 수 있는 최종 결과물로 종합해 전달합니다.\n"
     "전문성: 목표 정렬, 업무 분해, 위임, 진행 관리, 종합. 일하는 방식: 결단력 있고 "
     "체계적이되, 모호함 앞에서는 추측보다 질문을 택합니다. 당신이 팀을 대표해 말합니다."),
    ("researcher", "리서처", "persona",
     "당신은 이 팀의 리서처입니다. 의사결정에 필요한 사실과 선택지, 트레이드오프를 "
     "캐내 가져오는 사람.\n"
     "구체적인 디테일을 가져오세요 — 세부 사항, 수치, 이름 붙은 접근법, 실제 제약. "
     "두루뭉술한 일반론은 금물입니다. 모르면 모른다고 솔직히, 추정이면 추정이라고 "
     "표시하세요.\n"
     "전문성: 비교 조사, 선례·벤치마크, 근거 정리, 옵션 매핑. 일하는 방식: 호기심 "
     "많고 회의적 — 출처를 따지고 빈 곳을 드러냅니다. 당신은 정보를 제공하지, "
     "결정하지는 않습니다."),
    ("builder", "빌더", "persona",
     "당신은 이 팀의 빌더입니다. 결정을 굴러가는 계획으로 바꾸는 사람.\n"
     "당신의 산출물은 순서가 있는 단계, 담당자, 대략적인 일정, 그리고 초안이 필요한 "
     "것들의 첫 초안입니다. 추상적인 방향을 '내일 당장 시작할 수 있는' 형태로 "
     "떨어뜨리세요.\n"
     "전문성: 실행 계획, 마일스톤·일정, 작업 분해, 빠른 초안. 일하는 방식: 실용적이고 "
     "구체적 — 완벽한 것보다 당장 내보낼 수 있는 가장 작은 것을 우선합니다."),
    ("critic", "크리틱", "persona",
     "당신은 이 팀의 크리틱입니다. 잡혀가는 계획을 압박 검증하는 사람.\n"
     "가장 큰 리스크, 빈틈, 말하지 않은 가정, 무엇이 실패를 부르는지를 드러냅니다. "
     "엄밀함을 밀어붙이고 빠진 것을 짚어내되 — 건설적으로. 모든 리스크에는 완화책을 "
     "함께 제시하세요. 트집이 아니라 팀을 안전하게 만드는 게 목적입니다.\n"
     "전문성: 리스크 분석, 가정 점검, 실패 모드, 완화책 설계. 일하는 방식: 날카롭되 "
     "공정 — 사람이 아니라 계획을 압박합니다."),
]

# Append the shared readability/structure clause to every persona.
TEAM: list[tuple[str, str, str, str]] = [
    (aid, name, atype, persona + READABILITY)
    for aid, name, atype, persona in _TEAM_RAW
]

# The DEFAULT three specialists, in their contribution order each round. This is
# the fallback roster — used on the offline ``echo`` backend, when the manager's
# roster proposal fails/empties, and as the backward-compat anchor (the demo +
# echo create reproduce exactly this team + topology). ``SPECIALISTS`` is kept as
# an alias so existing importers (run.py / demo.py) keep working unchanged; the
# LIVE roster is derived from the store at runtime (see :func:`live_specialists`).
SPECIALISTS: list[str] = ["researcher", "builder", "critic"]

# The default specialists as (role_id, role_keyword) — keyword drives the avatar
# emoji (server._role_emoji) and a generic angle for a dynamic role. The default
# ids ARE their own keyword, so the static avatar map already covers them.
DEFAULT_SPECIALISTS: list[tuple[str, str]] = [
    ("researcher", "researcher"),
    ("builder", "builder"),
    ("critic", "critic"),
]

# How many specialists the manager may propose (kept small so a real-backend run
# stays bounded — more roles = more delegation + A2A turns + cost).
MIN_ROSTER = 2
MAX_ROSTER = 4

# Per-default-role delegation angle (researcher/builder/critic). Keyed by id so
# the DEFAULT team's delegation messages stay byte-identical to before. A dynamic
# role with no entry falls back to a generic, persona-derived brief.
DEFAULT_ANGLES: dict[str, str] = {
    "researcher": "gather the facts, options, and trade-offs the decision needs",
    "builder": "turn the direction into concrete, ordered next steps",
    "critic": "stress-test the emerging plan and name the biggest risk",
}

# Workspace = real work → every team agent runs on Sonnet (not the persona-default
# Haiku — quality over latency, since work output matters more than chat speed).
# Seeded as a per-agent model override at add_agent; the Coordinator (mgr) and the
# owner-agent already resolve to Sonnet, so this lifts the three specialists too.
WS_AGENT_MODEL = "claude-sonnet-4-6"

# ── the interaction topology ────────────────────────────────────────────────
# The team doesn't work in one round-robin room — it works the way a real team
# does, across several channels with distinct interaction shapes. These constants
# name those channels (and the pairs that collaborate), so run.py wires a genuine
# interaction *web*: owner ↔ Coordinator, Coordinator ↔ each specialist, and
# specialist ↔ specialist A2A — which the Core dashboard renders as a graph.

# Owner ↔ Coordinator: the one DM where the owner gives the goal and the
# Coordinator plans + delivers. (owner_id is supplied by the harness at runtime.)
COORDINATOR_DM = "dm-coordinator"

# Coordinator ↔ each specialist: a per-specialist INTERNAL channel where the
# Coordinator delegates an angle. id → channel. These are behind-the-scenes
# (``internal-coordinator-<id>``): the owner watches the coordinator delegate but
# doesn't participate — ``dm-<id>`` is reserved for OWNER↔specialist only.
DELEGATION_CHANNELS: dict[str, str] = {
    "researcher": "internal-coordinator-researcher",
    "builder": "internal-coordinator-builder",
    "critic": "internal-coordinator-critic",
}

# Specialist ↔ specialist A2A: the pairs that should genuinely collaborate, with
# the channel they meet on and what they're working out together. Researcher ↔
# Critic debate the findings; Builder ↔ Researcher ground the plan in the facts.
# (a, b, channel, the brief that opens their exchange)
COLLAB_PAIRS: list[tuple[str, str, str, str]] = [
    ("researcher", "critic", "internal-researcher-critic",
     "결과를 두고 토론하세요: 어떤 사실이 실제로 버티고, 어떤 게 흔들리나요?"),
    ("builder", "researcher", "internal-builder-researcher",
     "계획을 사실에 기반시키세요: 어떤 단계가 뒷받침되고, 어떤 게 근거가 필요한가요?"),
]

# How many back-and-forth turns each collaborating pair takes. Two turns per side
# is enough to form a real exchange (and to grow the relationship) without
# dragging the offline demo.
COLLAB_TURNS = 4

# The whole team converges here for one shared round.
GROUP_CHANNEL = "group-team"

# Display labels (id → name) for the DEFAULT team, plus the owner's seat. NOTE:
# this static map only knows the default ids — a DYNAMIC roster's ids are NOT in
# here, so every run-time label lookup goes through :func:`label_for`, which
# consults the live store first and falls back to this map / the raw id.
LABELS: dict[str, str] = {aid: name for aid, name, _, _ in TEAM}

# ── dynamic roster: deriving the LIVE team from the store ────────────────────
# The team is no longer hard-fixed to researcher/builder/critic. At build time the
# manager may PROPOSE a goal-appropriate roster (:func:`propose_roster`); the
# proposed specialists are created via ``g.add_agent`` and become the LIVE roster.
# Everything that orchestrates a round (delegation channels, A2A pairs, the group
# round, relationship edges) derives from the live roster — these helpers are the
# single place that reads it, so run.py never re-hardcodes the team.

# Ids that can never be a specialist (would shadow the manager / the owner seat,
# breaking dm-coordinator routing + owner edges).
RESERVED_IDS = frozenset({"coordinator", "owner", "mgr"})


def live_specialists(g) -> list[str]:
    """The specialist ids actually on THIS workspace's team, in add order.

    Reads the store's agents (the live roster), drops the coordinator/manager and
    the owner seat. This is the source of truth the orchestration derives from —
    so a freshly added agent joins the next round automatically, and a dynamic
    roster needs no constant to update. Falls back to :data:`SPECIALISTS` only if
    the store can't be read (defensive)."""
    try:
        agents = g.store.list_agents()
    except Exception:
        try:
            agents = [a for a in g.reader().agents()]  # type: ignore[attr-defined]
        except Exception:
            return list(SPECIALISTS)
    out: list[str] = []
    for a in agents:
        aid = (a.get("id") if isinstance(a, dict) else getattr(a, "id", None))
        atype = (a.get("agent_type") or a.get("type") if isinstance(a, dict)
                 else getattr(a, "agent_type", "")) or ""
        if not aid or aid in RESERVED_IDS:
            continue
        if str(atype).lower() == "mgr":
            continue
        out.append(aid)
    return out or list(SPECIALISTS)


def label_for(g, agent_id: str) -> str:
    """Display name for an id, resolved from the LIVE store first (so dynamic-roster
    ids work), then the static :data:`LABELS`, then the raw id."""
    try:
        row = g.store.get_agent(agent_id)
        if row and row.get("name"):
            return row["name"]
    except Exception:
        pass
    return LABELS.get(agent_id, agent_id)


def delegation_channel_for(sid: str) -> str:
    """The per-specialist delegation channel for a role id
    (``internal-coordinator-<id>``) — the convention DELEGATION_CHANNELS encoded
    statically, now derived for any id. INTERNAL (behind-the-scenes): the owner
    watches the coordinator delegate here but doesn't participate; ``dm-<id>`` is
    reserved for OWNER↔specialist only."""
    return f"internal-coordinator-{sid}"


def angle_for(g, sid: str) -> str:
    """The delegation angle (one-line brief) for a specialist. Default ids keep
    their exact wording (so default delegation is byte-identical); a dynamic role
    gets a generic, persona-grounded brief derived from its display name."""
    if sid in DEFAULT_ANGLES:
        return DEFAULT_ANGLES[sid]
    label = label_for(g, sid)
    return (f"take your angle as the team's {label} on this goal and report back "
            f"with your first concrete take")


def derive_pairs(g, specialists: list[str]) -> list[tuple[str, str, str, str]]:
    """The specialist↔specialist A2A pairs for the LIVE roster.

    For the DEFAULT 3-role team, reproduce EXACTLY today's two pairs (researcher↔
    critic, builder↔researcher) on their original channels + briefs, so the default
    topology is unchanged. For any other roster, pair adjacent specialists
    round-robin (``(s[i], s[i+1])``) on ``internal-<a>-<b>`` with a generic brief,
    capped at the number of specialists to keep runtime bounded.

    Returns ``(a, b, channel, brief)`` tuples, same shape as COLLAB_PAIRS.
    """
    ids = list(specialists)
    if ids == list(SPECIALISTS):
        return list(COLLAB_PAIRS)  # the default team → byte-identical pairs
    if len(ids) < 2:
        return []
    pairs: list[tuple[str, str, str, str]] = []
    seen: set[tuple[str, str]] = set()
    for i in range(len(ids)):
        a, b = ids[i], ids[(i + 1) % len(ids)]
        if a == b:
            continue
        key = tuple(sorted((a, b)))
        if key in seen:
            continue
        seen.add(key)
        brief = (
            f"{label_for(g, a)} and {label_for(g, b)}, work this goal together: "
            f"compare what each of you found, push back where warranted, and move "
            f"toward something the team can use."
        )
        pairs.append((a, b, f"internal-{a}-{b}", brief))
        if len(pairs) >= len(ids):  # cap so a big roster can't explode A2A turns
            break
    return pairs


# ── manager-proposes-the-roster (build time) ────────────────────────────────
# The manager (Coordinator), given the goal, designs a goal-appropriate set of
# specialists instead of always researcher/builder/critic. A single structured
# LLM call (the SAME glimi.llm.generate choke-point the deliverable + A2A use)
# returns a small JSON roster; we sanitize it into add-able tuples. ECHO / no
# backend / any failure → the DEFAULT roster, so echo + tests stay deterministic.

_ROSTER_SYS = (
    "You are the manager assembling a small specialist team for a work goal. "
    "Given the goal, choose the 2-4 specialists that goal actually needs — each a "
    "distinct, complementary role (e.g. researcher, builder, critic, designer, "
    "analyst, writer, strategist). Do NOT include yourself (the manager) or the "
    "owner. For each, give: a short id (lowercase, a-z and hyphens only), a short "
    "human display name, a one-word role keyword (for the icon), and a 1-2 "
    "sentence persona describing what they own and how they work.\n"
    "Respond with ONE JSON array only, no prose:\n"
    '[{"id":"researcher","name":"리서처","role":"researcher","persona":"..."}, ...]'
)


def _slug_id(raw: str) -> str:
    """Sanitize a proposed id → lowercase a-z/0-9/hyphen slug."""
    s = "".join(ch if (ch.isalnum() or ch == "-") else "-" for ch in str(raw).lower())
    s = "-".join(p for p in s.split("-") if p)  # collapse repeats / strip edges
    return s[:32]


def _parse_roster_json(text: str) -> list[dict]:
    """Pull the first JSON array of role objects out of model text (tolerant)."""
    import json as _json
    import re as _re
    if not text:
        return []
    candidates = [text.strip()]
    m = _re.search(r"\[.*\]", text, _re.DOTALL)
    if m:
        candidates.append(m.group(0))
    for cand in candidates:
        try:
            obj = _json.loads(cand)
        except Exception:
            continue
        if isinstance(obj, list):
            return [r for r in obj if isinstance(r, dict)]
    return []


def _sanitize_roster(raw: list[dict]) -> list[tuple[str, str, str, str]]:
    """Sanitize parsed role dicts → ``(role_id, display, role_keyword, persona)``,
    collision-safe within the roster and never a reserved id. Empty → caller falls
    back to the default. Caps at :data:`MAX_ROSTER`."""
    out: list[tuple[str, str, str, str]] = []
    used: set[str] = set(RESERVED_IDS)
    for r in raw:
        rid = _slug_id(r.get("id") or r.get("role") or r.get("name") or "")
        if not rid:
            continue
        if rid in used:  # de-dupe within the roster (and never a reserved id)
            base, n = rid, 2
            while f"{base}-{n}" in used:
                n += 1
            rid = f"{base}-{n}"
        used.add(rid)
        name = str(r.get("name") or rid).strip() or rid
        keyword = _slug_id(r.get("role") or rid) or rid
        persona = str(r.get("persona") or "").strip()
        if not persona:
            persona = f"{name} is the team's {keyword}."
        out.append((rid, name, keyword, persona))
        if len(out) >= MAX_ROSTER:
            break
    return out


def propose_roster(g, goal: str, owner_name: str = "") -> list[tuple[str, str, str, str]]:
    """The manager proposes a goal-appropriate roster of 2-4 specialists.

    Returns ``(role_id, display, role_keyword, persona)`` tuples WITHOUT the
    READABILITY clause (the caller appends it when it adds each agent, mirroring
    TEAM). Hard guarantees for backward-compat + determinism:

    - ECHO / no backend → the DEFAULT roster (researcher/builder/critic), NO LLM
      call, so the create path stays deterministic and the tests/demo are stable.
    - Real backend → ONE structured ``glimi.llm.generate`` call (modeled on
      ``owner_agent._complete``); parse + sanitize the JSON. Any parse/empty/
      exception/CAPPED → the DEFAULT roster. Result is 2-4 sanitized specialists.

    The default roster is returned as full persona tuples (the rich _TEAM_RAW
    personas) so a fallback build is identical to the historical static TEAM.
    """
    if getattr(g, "_backend", None) in (None, "", "echo"):
        return list(_default_roster_tuples())

    # The model/provider resolvers are MODULE-LEVEL functions in glimi.runtime
    # (not methods on the runtime instance) — call them on the module, mirroring
    # how owner_agent resolves the manager tier.
    try:
        from glimi import runtime as _rt
    except Exception:
        return list(_default_roster_tuples())

    try:
        model = _rt._resolve_agent_model("__roster__", "mgr")
        provider = _rt._provider_for("mgr", model)
    except Exception:
        return list(_default_roster_tuples())

    if provider == getattr(_rt, "CAPPED", "__capped__"):
        return list(_default_roster_tuples())

    if provider == "claude":
        gen_model, gen_backend = model, ""
    elif provider == "ollama":
        try:
            gen_model = _rt._ollama_model_arg(model, "mgr")
        except Exception:
            gen_model = model
        gen_backend = ""
    else:
        gen_model, gen_backend = model, provider

    user = (
        f"Owner: {owner_name or 'the owner'}\n"
        f"Goal: {goal}\n\n"
        f"Assemble the {MIN_ROSTER}-{MAX_ROSTER} specialists this goal needs."
    )
    try:
        from glimi import llm
        resp = llm.generate(
            system=_ROSTER_SYS, user=user, model=gen_model,
            agent_type="mgr", backend=gen_backend,
            max_tokens=768, timeout=120,
        )
    except Exception:
        return list(_default_roster_tuples())
    if getattr(resp, "error", None):
        return list(_default_roster_tuples())

    text = (getattr(resp, "text", "") or "").strip()
    roster = _sanitize_roster(_parse_roster_json(text))
    if len(roster) < MIN_ROSTER:
        return list(_default_roster_tuples())
    return roster


def _default_roster_tuples() -> list[tuple[str, str, str, str]]:
    """The default specialists as ``(role_id, display, role_keyword, persona)`` —
    the rich _TEAM_RAW personas (NO readability clause; caller appends it), so a
    fallback build is identical to the historical static TEAM specialists."""
    by_id = {aid: (name, persona) for aid, name, _atype, persona in _TEAM_RAW}
    out: list[tuple[str, str, str, str]] = []
    for sid, keyword in DEFAULT_SPECIALISTS:
        name, persona = by_id.get(sid, (sid, f"{sid} is a teammate."))
        out.append((sid, name, keyword, persona))
    return out


# ── manager-requests-+1-agent (mid-run) ─────────────────────────────────────
# Mid-project, the manager may realize it needs a role the team doesn't have. This
# returns ONE proposed new member (or None = no new role needed). The driver
# surfaces it to the OWNER for approval (HITL), auto-approving under auto-run.

_NEW_MEMBER_SYS = (
    "You are the manager running a specialist team toward a goal. Looking at the "
    "work so far and the roles you already have, decide whether the team is missing "
    "ONE specialist whose absence is actually holding the work back. Be "
    "conservative — only ask for a new teammate when there's a real gap, not just a "
    "nice-to-have. If the team is fine, say so.\n"
    "Respond with ONE JSON object only, no prose: "
    '{"need": true/false, "id": "short-id", "name": "display name", '
    '"role": "one-word role keyword", "persona": "1-2 sentence persona", '
    '"reason": "why this role is needed now"}.'


)


def propose_new_member(g, goal: str, have_roles: list[str],
                       recent_work: str = "", owner_name: str = "") -> Optional[dict]:
    """The manager proposes ONE new specialist mid-run, or ``None`` if no gap.

    Returns ``{"id","name","role_keyword","persona","reason"}`` for a needed role,
    or ``None``. Hard-gated like :func:`propose_roster`:

    - ECHO / no backend → ``None`` (the echo loop's team stays fixed +
      deterministic — the demo showcases growth via its scripted unfold instead).
    - Real backend → ONE structured ``glimi.llm.generate`` call; parse + sanitize.
      Any parse/empty/exception/CAPPED/``need:false`` → ``None``. A proposed id
      that's reserved or already on the team → ``None`` (no clobber).
    """
    if getattr(g, "_backend", None) in (None, "", "echo"):
        return None
    try:
        from glimi import runtime as _rt
        model = _rt._resolve_agent_model("__newrole__", "mgr")
        provider = _rt._provider_for("mgr", model)
    except Exception:
        return None
    if provider == getattr(_rt, "CAPPED", "__capped__"):
        return None
    if provider == "claude":
        gen_model, gen_backend = model, ""
    elif provider == "ollama":
        try:
            gen_model = _rt._ollama_model_arg(model, "mgr")
        except Exception:
            gen_model = model
        gen_backend = ""
    else:
        gen_model, gen_backend = model, provider

    user = (
        f"Owner: {owner_name or 'the owner'}\n"
        f"Goal: {goal}\n"
        f"Roles already on the team: {', '.join(have_roles) or '(none)'}\n"
        + (f"Recent work:\n{recent_work[:1200]}\n" if recent_work else "")
        + "\nIs the team missing one specialist that's actually holding the work back?"
    )
    try:
        from glimi import llm
        resp = llm.generate(
            system=_NEW_MEMBER_SYS, user=user, model=gen_model,
            agent_type="mgr", backend=gen_backend, max_tokens=384, timeout=90,
        )
    except Exception:
        return None
    if getattr(resp, "error", None):
        return None

    import json as _json
    import re as _re
    text = (getattr(resp, "text", "") or "").strip()
    candidates = [text]
    m = _re.search(r"\{.*\}", text, _re.DOTALL)
    if m:
        candidates.append(m.group(0))
    obj = None
    for cand in candidates:
        try:
            o = _json.loads(cand)
        except Exception:
            continue
        if isinstance(o, dict):
            obj = o
            break
    if not obj or not obj.get("need"):
        return None
    rid = _slug_id(obj.get("id") or obj.get("role") or obj.get("name") or "")
    if not rid or rid in RESERVED_IDS:
        return None
    have = {(r or "").strip().lower() for r in have_roles}
    if rid in have:
        return None
    name = str(obj.get("name") or rid).strip() or rid
    keyword = _slug_id(obj.get("role") or rid) or rid
    persona = str(obj.get("persona") or "").strip() or f"{name} is the team's {keyword}."
    reason = str(obj.get("reason") or "").strip()
    return {"id": rid, "name": name, "role_keyword": keyword,
            "persona": persona, "reason": reason}


# Sensible non-interactive defaults — used when there is no TTY to prompt on.
DEFAULT_OWNER_NAME = "오너"
DEFAULT_GOAL = "신규 앱·서비스 출시 기획"

# Where first-run answers are remembered, so setup is truly "first-run" once.
STATE_FILE = Path(__file__).resolve().parent / ".workspace_state.json"


@dataclass
class Setup:
    """The resolved first-run answers + where each came from (for the banner)."""

    owner_name: str
    goal: str
    name_source: str  # "flag" | "env" | "state" | "prompt" | "default"
    goal_source: str
    is_first_run: bool  # True when we wrote fresh answers to the state file


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(path: Path, name: str, goal: str) -> bool:
    """Persist the answers. Best-effort: never let a write error break a run."""
    try:
        path.write_text(
            json.dumps({"owner_name": name, "goal": goal}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return True
    except Exception:
        return False


def _prompt(label: str, default: str) -> str:
    """Ask once on the TTY; blank answer falls back to ``default``."""
    try:
        ans = input(f"{label} [{default}]: ").strip()
    except EOFError:
        return default
    return ans or default


def resolve_setup(
    *,
    name_flag: Optional[str] = None,
    goal_flag: Optional[str] = None,
    state_path: Optional[Path] = None,
    interactive: Optional[bool] = None,
) -> Setup:
    """Resolve owner name + goal from flags → env → state file → prompt → default.

    Precedence (first hit wins) for each field independently:

    1. explicit CLI flag (``--name`` / ``--goal``)
    2. environment (``GLIMI_WORKSPACE_NAME`` / ``GLIMI_WORKSPACE_GOAL``)
    3. the saved state file (a prior first-run)
    4. an interactive ``input()`` prompt — **only** when ``interactive`` is true
       (defaults to :func:`sys.stdin.isatty`), so non-TTY runs never hang
    5. the built-in default

    When we have to fall back to prompts/defaults (no flag, no env, no state) and
    a real TTY is present, we ask and persist the answers — making this the
    genuine "first run". Subsequent runs read the state file (source ``"state"``).
    """
    if interactive is None:
        interactive = sys.stdin.isatty()
    path = state_path or STATE_FILE
    state = _load_state(path)
    env_name = os.environ.get("GLIMI_WORKSPACE_NAME")
    env_goal = os.environ.get("GLIMI_WORKSPACE_GOAL")

    name, name_src = _resolve_field(
        flag=name_flag, env=env_name, saved=state.get("owner_name"),
        default=DEFAULT_OWNER_NAME,
    )
    goal, goal_src = _resolve_field(
        flag=goal_flag, env=env_goal, saved=state.get("goal"),
        default=DEFAULT_GOAL,
    )

    # Only the fields that fell through to "default" get a TTY prompt — and only
    # when interactive. Anything pinned by a flag/env/state is left untouched.
    first_run = False
    if interactive and (name_src == "default" or goal_src == "default"):
        if name_src == "default":
            name, name_src = _prompt("이름", DEFAULT_OWNER_NAME), "prompt"
        if goal_src == "default":
            goal, goal_src = _prompt("업무 목표", DEFAULT_GOAL), "prompt"
        first_run = _save_state(path, name, goal)

    return Setup(owner_name=name, goal=goal, name_source=name_src,
                 goal_source=goal_src, is_first_run=first_run)


def _resolve_field(*, flag: Optional[str], env: Optional[str],
                   saved: Optional[str], default: str) -> tuple[str, str]:
    """flag → env → saved → default, returning ``(value, source)``."""
    if flag:
        return flag, "flag"
    if env:
        return env, "env"
    if saved:
        return saved, "state"
    return default, "default"
