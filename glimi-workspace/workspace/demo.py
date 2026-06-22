"""workspace/demo.py — a seeded, live, real-time-viewable Workspace demo.

The Workspace analogue of the Community showcase (``scripts/seed_demo_mockup.py``):
a hand-authored, believable team — a **Coordinator** plus a **Researcher**,
**Builder**, and **Critic** — working a real goal (*plan the public launch of our
open-source project*), seeded directly into the kernel's in-memory store so you can
watch it **live** in the Core dashboard with zero setup: no API key, no network, no
Discord.

Two pieces, mirroring the Community demo's "seed + faked liveness":

1. :func:`seed` lays down the finished work — the interaction web across DMs,
   agent-to-agent channels, a group round, the owner-approved deliverable, plus
   relationships, emotions, 5-layer memory, semantic facts, and a few
   observability rows (tool calls + echo-backend usage at $0 — local is free).

2. :func:`activity_loop` keeps the dashboard **genuinely live**: it unfolds a short
   "launch prep" continuation one turn at a time, then drops into a heartbeat that
   keeps emotions and usage ticking — so the auto-refreshing dashboard shows new
   activity without a reload, and without spending a cent.

Built entirely on the ``glimi`` package — kernel only (no ``src``, no Discord), the
same boundary the rest of Glimi Workspace holds.

Run it (needs the dashboard extra: ``pip install "glimi[dashboard]"``)::

    PYTHONPATH=. python workspace/run.py --demo            # → http://127.0.0.1:8800
    PYTHONPATH=. python workspace/run.py --demo --host 0.0.0.0
"""
from __future__ import annotations

import json
import threading
from typing import Optional

from glimi import Glimi

try:  # script / flat-dir on sys.path
    from team import LABELS, SPECIALISTS, TEAM
except ImportError:  # imported as workspace.demo
    from .team import LABELS, SPECIALISTS, TEAM

# ── the demo's fixed setup ───────────────────────────────────────────────────
OWNER_NAME = "수민"
OWNER_ID = "owner"
GOAL = "오픈소스 프로젝트 공개 런칭 기획"

# Channels (mirror team.py's topology so the seeded demo and a real run look alike).
DM_COORDINATOR = "dm-coordinator"
DM = {"researcher": "dm-researcher", "builder": "dm-builder", "critic": "dm-critic"}
A2A_RC = "internal-researcher-critic"
A2A_BR = "internal-builder-researcher"
GROUP = "group-team"
APPROVALS = "mgr-approvals"  # mgr-* system log convention (never a chat channel)
# The read-only channel where the autonomous owner logs its per-round reasoning
# (the "owner thinking out loud" the web shows). The demo seeds + unfolds believable
# owner-review lines here so a visitor watches the FULL goal→work→review→next loop —
# scripted + echo + store-only → $0, exactly how the demo already fakes liveness.
OWNER_REVIEW = "internal-owner"

# ── the seeded transcript (hand-authored, believable — the finished work) ─────
# (channel, speaker_id, text). speaker "owner" == 수민.
TRANSCRIPT: list[tuple[str, str, str]] = [
    # 1) Owner ↔ Coordinator — the goal lands, the Coordinator plans.
    (DM_COORDINATOR, OWNER_ID,
     "목표는 이거예요: 우리 오픈소스 프로젝트 공개 런칭을 기획하는 거. 근거 없는 과장은 "
     "싫어요 — 깔끔하고 정직한 런칭이면 좋겠어요. 어디서부터 시작할까요?"),
    (DM_COORDINATOR, "coordinator",
     "알겠어요, 수민님 — 목표는 하나로 명확해요. 과장하지 않으면서도 신뢰를 주는 런칭. "
     "셋으로 나눠서 진행할게요. 리서처는 비슷한 프로젝트들이 실제로 어떻게 전환을 "
     "이끌어냈는지 파고들고, 빌더는 그 방향을 날짜와 담당자가 있는 순서 잡힌 체크리스트로 "
     "만들고, 크리틱은 런칭 당일에 터질 수 있는 지점들로 계획을 압박 검증해요. 종합은 제가 "
     "정리해서 가져올게요."),

    # 2) Coordinator ↔ each specialist — real delegation + first take.
    (DM["researcher"], "coordinator",
     "리서처 — 당신 몫은 이거예요. 비슷한 오픈소스 프로젝트들은 어떻게 런칭했고, 실제로 "
     "성과를 움직인 건 뭐였는지(허영 지표 말고). 구체적으로 가져와요."),
    (DM["researcher"], "researcher",
     "맡았어요. 첫 인상부터: 전환에 성공한 런칭들은 가장 시끄러운 쪽이 아니었어요 — '이게 "
     "이렇게 동작합니다'를 보여주는 60초 데모와, '이게 무엇이고 무엇이 아닌지'를 잔인할 만큼 "
     "명확하게 내건 쪽이었죠. 제가 뽑은 네 사례 중 셋에서 Show HN 하나에 타이밍 맞춘 스레드 "
     "하나가 산만한 멀티채널 푸시를 이겼어요. 지금 전환 데이터를 더 파고드는 중이에요."),

    (DM["builder"], "coordinator",
     "빌더 — 이 방향을 구체적이고 순서 잡힌 런칭 체크리스트로 만들어줘요. 단계, 담당자, "
     "현실적인 날짜까지. 당장 내보낼 수 있는 가장 작은 것으로."),
    (DM["builder"], "builder",
     "초안 잡는 중이에요. 뼈대: (1) 범위 확정 + 정직한 README 작성, (2) 60초 데모 녹화, "
     "(3) Show HN 글 + 첫 댓글 FAQ 준비, (4) 런칭 당일 이슈에 답할 인원 배치, (5) 화요일 "
     "오전 9시(PT) 출시. 이 다섯에 안 들어가는 건 다 쳐낼게요. 지금 의존 관계 순서를 잡고 "
     "있어요."),

    (DM["critic"], "coordinator",
     "크리틱 — 잡혀가는 계획을 압박 검증해줘요. 런칭 당일 우리가 실제로 아픈 지점이 어디죠? "
     "모든 리스크에 완화책을 같이."),
    (DM["critic"], "critic",
     "가장 큰 리스크는 트래픽이 아니에요 — 데모와 맨바닥 설치 사이의 간극이죠. 누가 클론 "
     "받고 첫 5분 안에 벽에 부딪히면, 그 스레드가 우리한테 등을 돌려요. 완화책: 깨끗한 환경에서 "
     "직접 검증한 '60초면 동작한다' 퀵스타트, 그리고 상단 고정된 알려진 이슈 안내. 두 번째 "
     "리스크는 지원 부담이에요."),

    # 3) Specialist ↔ specialist (A2A) — they genuinely debate.
    (A2A_RC, "researcher",
     "크리틱 — 제 판단엔 Show HN이 단일 수단으로는 레버리지가 가장 커요. 이견 있으면 "
     "반박해줘요."),
    (A2A_RC, "critic",
     "레버리지가 크다는 데는 동의해요 — 기본적으로 안전하다는 데는 동의 못 해요. Show HN은 "
     "'동작한다'엔 보상을 주고 '거의 동작한다'엔 벌을 줘요. 맨바닥 시작이 버틴다는 근거가 "
     "뭐예요?"),
    (A2A_RC, "researcher",
     "타당해요. 네 프로젝트 중 둘은 검증된 퀵스타트가 전환에 결정적이었다고 꼽았어요 — 그걸 "
     "건너뛴 하나는 설치가 깨졌다는 최상단 댓글이 달렸고 끝내 회복 못 했고요. 그러니까 당신이 "
     "말한 맨바닥 시작 리스크가 곁다리가 아니라 진짜 핵심 레버예요."),
    (A2A_RC, "critic",
     "그럼 합의 본 거네요. 데모가 시선을 끌고, 퀵스타트가 그 시선을 붙잡는다. 준비 완료라고 "
     "하기 전에 깨끗한 환경 테스트를 통과하도록 제가 계획을 잡고 있을게요."),

    (A2A_BR, "builder",
     "리서처 — 제 다섯 단계 중에 당신 데이터가 실제로 뒷받침하는 건 어떤 거고, 제가 그냥 "
     "가정하고 있는 건 어떤 거예요?"),
    (A2A_BR, "researcher",
     "1~3단계는 뒷받침돼요 — 정직한 README, 60초 데모, Show HN 타이밍 다 전환에 성공한 "
     "패턴과 맞아요. 4단계가 자원이 부족한 지점인데요. 데이터를 보면 부하는 당신이 잡은 한 "
     "나절이 아니라 여섯 시간쯤 치솟아요."),
    (A2A_BR, "builder",
     "잘 짚었어요 — 지원 시간을 하루 종일로 늘리고 백업 인원도 지정할게요. 데모 길이에 대해선 "
     "데이터가 뭐라고 하나요?"),
    (A2A_BR, "researcher",
     "90초 넘어가면 사람들이 떠나요. 60초가 딱 적당한 지점이에요 — 그대로 가요."),

    # 4) Group round — the team converges.
    (GROUP, "coordinator",
     "팀 — 정리합시다. 각자 한 문장씩: 런칭에서 가장 중요한 단 하나의 포인트."),
    (GROUP, "researcher",
     "검증된 60초 데모와 명확한 '이게 무엇이고 무엇이 아닌지'를 앞세우기 — 실제로 전환을 만든 "
     "건 그거예요."),
    (GROUP, "builder",
     "다섯 단계 체크리스트를 화요일에 출시하고, 거기 없는 건 다 쳐내기."),
    (GROUP, "critic",
     "준비 완료라고 하기 전에 깨끗한 환경에서 퀵스타트 테스트하기 — 맨바닥 시작이 승부의 "
     "전부예요."),

    # 5) The owner-approved deliverable, back in the owner DM.
    (DM_COORDINATOR, "coordinator",
     "수민님 — 종합 정리예요. 결정: 집중되고 정직한 런칭 — 화요일 오전 9시(PT) Show HN, "
     "검증된 60초 데모와 명확한 '이게 무엇이고 무엇이 아닌지' README를 앞세움. 계획: (1) 범위 "
     "확정 + 정직한 README, (2) 60초 데모 녹화, (3) Show HN 글 + 첫 댓글 FAQ 준비, "
     "(4) 깨끗한 환경에서 검증한 퀵스타트 + 상단 고정 알려진 이슈, (5) 런칭 당일 종일 지원 "
     "인원 다섯. 최대 리스크: 데모와 맨바닥 설치 사이의 간극 — 퀵스타트가 깨끗한 환경에서 "
     "통과하기 전엔 런칭하지 않습니다. 그게 마지노선이에요."),
]

# The HITL approval trail for the one consequential action (delivering to 수민).
# Written to the mgr-approvals system-log channel (the convention from the
# Workspace HITL gate), so it's inspectable in the same dashboard.
APPROVAL_TRAIL: list[str] = [
    "[HITL] 제안됨 · final_deliverable · 수민님을 위한 런칭 종합",
    "[HITL] 결정 · 오너 승인 (수정: 최대 리스크 문구 더 단단하게)",
    "[HITL] 결과 · dm-coordinator 로 전달됨",
]

# Working relationships → the dashboard's connection-graph edges.
# (a, b, type, intimacy, dynamics)
RELATIONSHIPS: list[tuple[str, str, str, int, str]] = [
    ("coordinator", OWNER_ID, "lead", 82,
     "수민님을 위해 워크스페이스를 이끔. 목표를 받아 종합을 전달함."),
    ("coordinator", "researcher", "manages", 62,
     "'무엇이 전환을 만들었나' 방향을 배분하고 그 결과를 계획에 녹임."),
    ("coordinator", "builder", "manages", 62,
     "체크리스트를 배분하고 출시 가능한 다섯 단계로 붙들어 둠."),
    ("coordinator", "critic", "manages", 62,
     "리스크 점검을 배분하고 깨끗한 환경 게이트를 채택함."),
    ("researcher", "critic", "collaborator", 78,
     "결과를 두고 토론 — 맨바닥 시작 간극이 진짜 레버라는 데 의견을 모음."),
    ("builder", "researcher", "collaborator", 70,
     "체크리스트를 데이터에 기반시킴 — 지원 시간을 하루 종일로 늘림."),
]

# Current emotion per agent (drives the agent cards + node tone).
EMOTIONS: dict[str, tuple[str, int]] = {
    "coordinator": ("집중", 7),
    "researcher": ("호기심", 7),
    "builder": ("몰입", 8),
    "critic": ("경계", 7),
}

# 5-layer memory: (agent, channel, level, content, importance, pinned).
MEMORIES: list[tuple[str, str, int, str, int, bool]] = [
    ("coordinator", DM_COORDINATOR, 2,
     "런칭 결정: 집중되고 정직한 Show HN, 화요일 오전 9시(PT), 검증된 60초 데모를 "
     "앞세움.", 9, True),
    ("coordinator", GROUP, 1,
     "전문가 각자의 한 줄 포인트가 깔끔하게 모였다 — 데모, 체크리스트, 깨끗한 환경 "
     "테스트.", 6, False),
    ("researcher", A2A_RC, 2,
     "검증된 퀵스타트가 전환과 '설치가 깨졌다는 최상단 댓글'을 가른 차이였다.", 8, True),
    ("researcher", DM["researcher"], 1,
     "Show HN 하나에 타이밍 맞춘 스레드 하나가 산만한 멀티채널 푸시를 이겼다 (4건 중 "
     "3건).", 6, False),
    ("builder", DM["builder"], 1,
     "다섯 단계 체크리스트; 화요일 출시; 나머지는 다 쳐낸다.", 7, False),
    ("builder", A2A_BR, 2,
     "지원 부하는 한나절이 아니라 약 6시간 치솟는다 — 시간을 늘리고 백업 인원을 "
     "지정함.", 7, True),
    ("critic", DM["critic"], 2,
     "맨바닥 시작 간극이 승부의 전부 — 퀵스타트가 깨끗한 환경에서 통과하기 전엔 "
     "런칭하지 않는다.", 9, True),
]

# Semantic facts (Layer 3): (agent, subject, predicate, object).
FACTS: list[tuple[str, str, str, str]] = [
    ("coordinator", "수민", "원한다", "과장하지 않는 런칭"),
    ("coordinator", "런칭", "출시한다", "화요일 오전 9시(PT)"),
    ("researcher", "Show HN", "보상한다", "'동작한다'; 벌한다 '거의 동작한다'"),
    ("builder", "지원 시간", "이어야 한다", "백업 인원을 지정한 런칭 당일 종일"),
    ("critic", "가장 큰 리스크", "는", "데모와 맨바닥 설치 사이의 간극"),
]

# A few illustrative observability rows so the dashboard's Tool-call Timeline shows
# the feature populated. (The capture plumbing is real — every adapter's tool calls
# flow through one choke-point; here we pre-seed a labeled showcase, like the rest
# of the demo. The live loop adds genuine echo-backend usage on top.)
TOOL_CALLS: list[tuple[str, str, str, dict, str]] = [
    # (agent, channel, tool_name, args, result_preview)
    ("researcher", A2A_RC, "recall_memory",
     {"query": "비슷한 런칭 전환 사례"},
     "기억 3건: 검증된 퀵스타트 → 전환; Show HN 타이밍; 데모 길이"),
    ("critic", DM["critic"], "remember",
     {"content": "맨바닥 시작 간극이 런칭의 가장 큰 리스크", "importance": 9},
     "저장됨 (L2, 고정)"),
    ("builder", A2A_BR, "recall_memory",
     {"query": "지원 부하 시간대"},
     "기억 1건: 부하는 한나절이 아니라 약 6시간 치솟음"),
    ("coordinator", GROUP, "summarize_channel",
     {"channel": "group-team"},
     "3개 포인트로 수렴: 데모, 체크리스트, 깨끗한 환경 테스트"),
]

# The live "launch prep" continuation — unfolded one turn per tick by the activity
# loop so a viewer watches the work move forward in real time.
CONTINUATION: list[tuple[str, str, str]] = [
    (GROUP, "builder", "퀵스타트 초안 올렸어요 — 지금 새 VM에서 테스트 중이에요."),
    (A2A_BR, "researcher",
     "깨끗한 환경 실행: 설치부터 첫 출력까지 48초. 버텨요."),
    (GROUP, "critic",
     "깨끗한 환경 실행을 제가 직접 확인했어요. 4단계 보류 해제할게요."),
    (DM_COORDINATOR, "coordinator",
     "수민님 — 퀵스타트가 깨끗한 환경에서 통과해요. 화요일 진행 가능합니다."),
    (GROUP, "researcher",
     "데모 58초로 줄였어요 — 군말 없이 바로 동작하는 출력으로 끝나요."),
    (A2A_RC, "critic",
     "상단 고정 알려진 이슈 안내 초안 잡았어요. 우리 발목 잡을 거 하나 줄였네요."),
    (GROUP, "builder",
     "Show HN 글 + 첫 댓글 FAQ 준비됐어요. 지원 인원 다섯 명 확정됐고요."),
    (DM_COORDINATOR, "coordinator", "전부 준비됐어요, 수민님. 진행 신호만 기다릴게요."),
]

# The owner's reasoning for the FINISHED first round — seeded into internal-owner so
# the channel isn't empty on first load (a visitor switching to "오너의 검토" sees the
# owner already reviewed round 1). Logged from OWNER_ID (read-only channel).
OWNER_REVIEW_SEED: list[str] = [
    "팀이 가져온 방향 좋아요 — 정직한 런칭 기조 맞고. 다만 '깨끗한 환경 퀵스타트'가 "
    "진짜 통과하는지 확인이 빠졌네. 다음 라운드에 그거 검증부터 시켜야겠다.",
]

# The autonomous owner-driver loop, scripted for the demo ($0). Interleaved with the
# CONTINUATION (team work) by the activity loop so a viewer watches the genuine
# cycle: owner posts a new instruction to dm-coordinator → team turns appear → an
# owner review lands in internal-owner. (channel, speaker_id, text). speaker == OWNER_ID
# for both the instruction (to the Coordinator) and the review (to internal-owner).
OWNER_TURNS: list[tuple[str, str, str]] = [
    # Round 2 instruction — the owner hands down the next concrete ask, as a human would.
    (DM_COORDINATOR, OWNER_ID,
     "퀵스타트 검증이 통과했다니 좋네요. 이제 화요일에 실제로 굴릴 수 있게 일정과 담당자까지 "
     "박은 실행 계획으로 마무리해 줘요 — 당장 시작할 수 있게."),
    # Round 2 owner review — lands in internal-owner after the team's round-2 work shows.
    (OWNER_REVIEW, OWNER_ID,
     "퀵스타트 검증 통과 확인했고 데모 길이도 잡혔어요. 일정·담당까지 들어오면 화요일 진행 "
     "충분합니다 — 거의 다 왔다."),
    (OWNER_REVIEW, OWNER_ID,
     "실행 계획까지 다 잡혔어요. 이 정도면 화요일 진행 충분합니다 — 여기서 마무리."),
]

# Emotions the continuation nudges as the work lands (speaker → new emotion).
_CONT_EMOTION: dict[str, tuple[str, int]] = {
    "builder": ("활기", 8),
    "researcher": ("자신감", 8),
    "critic": ("안도", 6),
    "coordinator": ("집중", 8),
}


# ── seeding ──────────────────────────────────────────────────────────────────

def _agent_type(agent_id: str) -> str:
    for aid, _name, atype, _persona in TEAM:
        if aid == agent_id:
            return atype
    return "persona"


def _est_tokens(text: str) -> int:
    """Estimate tokens for a turn (chars/4), via the kernel's own pricing helper
    when available, so the usage panel shows plausible — clearly estimated — counts."""
    try:
        from glimi.llm.pricing import estimate_tokens_from_chars
        return int(estimate_tokens_from_chars(len(text)))
    except Exception:
        return max(1, len(text) // 4)


def _record_turn_usage(g: Glimi, speaker: str, text: str, prompt_chars: int = 220) -> None:
    """Record one echo-backend usage row for an agent turn — local is $0, tokens
    are estimated (estimated=True), so the dashboard shows honest 'est. · $0'."""
    if speaker == OWNER_ID:
        return
    out_tok = _est_tokens(text)
    in_tok = _est_tokens("x" * prompt_chars)
    latency = 180 + (len(text) % 420)  # deterministic, plausible
    try:
        g.store.record_usage(
            agent_id=speaker, agent_type=_agent_type(speaker),
            model="echo (offline demo)", backend="echo",
            input_tokens=in_tok, output_tokens=out_tok,
            est_cost=0.0, estimated=True, latency_ms=latency,
        )
    except Exception:
        pass


def seed(g: Glimi) -> None:
    """Lay down the finished work + the relationships/memory/observability that the
    dashboard renders. Idempotent enough for a fresh store (the demo's normal case)."""
    store = g.store

    # Participants per channel (so the graph + channel viewer know who's in each).
    store.set_channel_participants(DM_COORDINATOR, [OWNER_ID, "coordinator"])
    for sid in SPECIALISTS:
        store.set_channel_participants(DM[sid], [OWNER_ID, "coordinator", sid])
    store.set_channel_participants(A2A_RC, ["researcher", "critic"])
    store.set_channel_participants(A2A_BR, ["builder", "researcher"])
    store.set_channel_participants(GROUP, [OWNER_ID, "coordinator", *SPECIALISTS])
    store.set_channel_participants(APPROVALS, ["coordinator"])
    # internal-owner: the owner's read-only reasoning channel (only the owner posts).
    store.set_channel_participants(OWNER_REVIEW, [OWNER_ID])

    # The transcript (+ honest echo usage per agent turn).
    for channel, speaker, text in TRANSCRIPT:
        store.log_message(channel, speaker, text)
        _record_turn_usage(g, speaker, text)

    # The owner's reasoning for the finished round 1 (so internal-owner isn't empty).
    for line in OWNER_REVIEW_SEED:
        store.log_message(OWNER_REVIEW, OWNER_ID, line)

    # The HITL approval trail (system-log channel).
    for line in APPROVAL_TRAIL:
        store.log_message(APPROVALS, "coordinator", line)

    # Relationships → graph edges.
    for a, b, rtype, intimacy, dynamics in RELATIONSHIPS:
        store.set_relationship(a, b, rel_type=rtype, intimacy=intimacy, dynamics=dynamics)

    # Emotions.
    for aid, (emotion, intensity) in EMOTIONS.items():
        store.set_agent_emotion(aid, emotion, intensity)

    # 5-layer memory.
    for aid, channel, level, content, importance, pinned in MEMORIES:
        store.add_memory(aid, channel, level=level, content=content,
                         importance=importance, is_pinned=pinned)

    # Semantic facts (Layer 3).
    for aid, subject, predicate, obj in FACTS:
        store.add_fact(aid, subject=subject, predicate=predicate, object_value=obj)

    # Illustrative tool-call timeline rows.
    for aid, channel, tool_name, args, preview in TOOL_CALLS:
        try:
            store.record_tool_call(
                agent_id=aid, agent_type=_agent_type(aid), channel=channel,
                tool_name=tool_name, args_json=json.dumps(args, ensure_ascii=False),
                result_preview=preview, ok=True,
                latency_ms=40 + (len(preview) % 160),
            )
        except Exception:
            pass


# ── live activity loop ───────────────────────────────────────────────────────

class _Heartbeat:
    """Rotating emotion intensities so the dashboard keeps visibly ticking after the
    continuation has fully unfolded — no transcript spam, just signs of life."""

    def __init__(self) -> None:
        self._i = 0
        self._order = ["coordinator", "researcher", "builder", "critic"]

    def beat(self, g: Glimi) -> None:
        aid = self._order[self._i % len(self._order)]
        self._i += 1
        base = EMOTIONS.get(aid, ("집중", 6))
        # gently oscillate intensity 6↔8 so the agent cards change between polls.
        intensity = 6 + (self._i % 3)
        try:
            g.store.set_agent_emotion(aid, base[0], intensity)
            g.store.record_usage(
                agent_id=aid, agent_type=_agent_type(aid),
                model="echo (offline demo)", backend="echo",
                input_tokens=8, output_tokens=12, est_cost=0.0,
                estimated=True, latency_ms=90 + self._i % 60,
            )
        except Exception:
            pass


def _demo_script() -> list[tuple[str, str, str]]:
    """The merged, ordered live script the activity loop unfolds one turn per tick.

    Interleaves the autonomous owner-driver loop (OWNER_TURNS) with the team's work
    (CONTINUATION) so a viewer watches the FULL cycle, not just the team talking:

      owner instruction → team works → owner review → (loops)

    Concretely: the round-2 owner instruction first (the owner hands down the next
    ask in dm-coordinator), then the team's continuation turns (their round-2 work),
    with the two owner reviews dropped in at natural beats so the owner's "thinking"
    in internal-owner lands AFTER the work it's reacting to."""
    instr2 = OWNER_TURNS[0]
    reviews = OWNER_TURNS[1:]
    cont = list(CONTINUATION)
    script: list[tuple[str, str, str]] = [instr2]   # owner posts the next instruction
    # Spread the work, slipping an owner review in mid-stream and one near the end so
    # the review reads as a reaction to the work just shown (goal→work→review).
    mid = max(1, len(cont) // 2)
    script.extend(cont[:mid])
    if reviews:
        script.append(reviews[0])                   # interim review after the first half
    script.extend(cont[mid:])
    if len(reviews) > 1:
        script.append(reviews[1])                   # final "충분합니다 — 마무리" review
    return script


def activity_loop(g: Glimi, stop: threading.Event, interval: float = 6.0) -> None:
    """Unfold the launch-prep + owner-driver continuation one turn per tick, then
    heartbeat forever.

    Genuine store mutations on a timer → the auto-refreshing dashboard shows new
    activity without a reload. All offline (echo), so it never costs anything. The
    script interleaves the autonomous owner loop (instruction → work → review) so
    the demo VISIBLY showcases the owner-driver cycle, $0, no Claude calls."""
    # Phase 1 — unfold the merged owner-driver + team script (one turn per tick).
    for channel, speaker, text in _demo_script():
        if stop.wait(interval):
            return
        try:
            g.store.log_message(channel, speaker, text)
            _record_turn_usage(g, speaker, text)  # skips OWNER_ID (owner turns are free)
            emo = _CONT_EMOTION.get(speaker)
            if emo:
                g.store.set_agent_emotion(speaker, emo[0], emo[1])
        except Exception:
            pass

    # Phase 2 — heartbeat (keep it alive without spamming the transcript).
    hb = _Heartbeat()
    while not stop.wait(interval):
        hb.beat(g)


# ── orchestration ────────────────────────────────────────────────────────────

def build(backend: str = "echo") -> Glimi:
    """Build the seeded demo population on a fresh store and return the Glimi."""
    g = Glimi(backend=backend, owner_name=OWNER_NAME, owner_id=OWNER_ID)
    for aid, name, atype, persona in TEAM:
        g.add_agent(aid, name=name, persona=persona, agent_type=atype)
    seed(g)
    return g


def run_demo(*, host: str = "127.0.0.1", port: int = 8800,
             interval: float = 6.0, serve: bool = True,
             backend: str = "echo") -> int:
    """Seed the demo, start the live activity loop, and serve the Core dashboard.

    Returns a process exit code. When ``serve`` is False, builds + returns 0 after
    a single synchronous unfold-less seed (used by tests)."""
    g = build(backend=backend)

    if not serve:
        return 0

    stop = threading.Event()
    thread = threading.Thread(
        target=activity_loop, args=(g, stop, interval), daemon=True,
        name="glimi-workspace-demo-activity",
    )
    thread.start()

    url = f"http://{host}:{port}"
    print("=" * 64)
    print("  Glimi Workspace — 라이브 데모")
    print("=" * 64)
    print(f"  목표    : {GOAL}")
    print(f"  팀      : 코디네이터, 리서처, 빌더, 크리틱  (오너: {OWNER_NAME})")
    print(f"  백엔드  : {backend} (오프라인 — API 키 불필요, $0)")
    print(f"  보기    : {url}   ← 실시간으로 업데이트 (Ctrl-C 로 중지)")
    print("=" * 64 + "\n")

    try:
        import glimi.dashboard
        glimi.dashboard.serve(g.store, host=host, port=port)
    except ImportError as exc:
        stop.set()
        print(f"Dashboard deps not installed: {exc}")
        print('Install with:  pip install "glimi[dashboard]"')
        return 1
    except KeyboardInterrupt:
        print("\nDemo stopped.")
    finally:
        stop.set()
    return 0
