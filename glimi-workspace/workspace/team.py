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

# The three specialists, in their contribution order each round.
SPECIALISTS: list[str] = ["researcher", "builder", "critic"]

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

# Coordinator ↔ each specialist: a per-specialist DM where the Coordinator
# delegates an angle. id → channel.
DELEGATION_CHANNELS: dict[str, str] = {
    "researcher": "dm-researcher",
    "builder": "dm-builder",
    "critic": "dm-critic",
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

# Display labels (id → name), plus the owner's seat.
LABELS: dict[str, str] = {aid: name for aid, name, _, _ in TEAM}

# Sensible non-interactive defaults — used when there is no TTY to prompt on.
DEFAULT_OWNER_NAME = "오너"
DEFAULT_GOAL = "오픈소스 프로젝트 공개 런칭 기획"

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
