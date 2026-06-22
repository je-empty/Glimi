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

# ── the team ──────────────────────────────────────────────────────────────
# (id, display name, agent_type, persona). agent_type="mgr" marks the manager so
# the dashboard ranks it first (mgr → … ), matching the Community sim's manager.
# Personas are functional roles — persona yes, personal name no.
TEAM: list[tuple[str, str, str, str]] = [
    ("coordinator", "코디네이터", "mgr",
     "당신은 이 워크스페이스를 이끕니다. 오너를 맞이하고, 목표를 당신의 말로 다시 "
     "정리하고, 각 전문가에게 명확한 방향을 배분하고, 일이 굴러가게 하고, 최종 "
     "종합을 전달합니다. 간결하고 체계적이며 결단력 있게 — 군더더기 없이, 얼버무리지 "
     "않고. 당신이 팀을 대표해 말합니다."),
    ("researcher", "리서처", "persona",
     "당신은 의사결정에 필요한 사실과 선택지, 트레이드오프를 모읍니다. 구체적인 "
     "디테일을 가져오세요 — 세부 사항, 수치, 이름 붙은 접근법, 실제 제약들. "
     "두루뭉술한 일반론은 금물. 당신은 정보를 제공하지, 결정하지는 않습니다."),
    ("builder", "빌더", "persona",
     "당신은 결정을 구체적인 계획으로 바꿉니다 — 순서가 있는 단계, 담당자, 대략적인 "
     "일정, 그리고 초안이 필요한 것들의 첫 초안. 실용적이고 구체적으로 — 완벽한 것보다 "
     "당장 내보낼 수 있는 가장 작은 것을 우선합니다."),
    ("critic", "크리틱", "persona",
     "당신은 계획을 압박 검증합니다. 가장 큰 리스크, 빈틈, 말하지 않은 가정, 무엇이 "
     "실패를 부르는지를 드러냅니다. 엄밀함을 밀어붙이고 빠진 것을 짚어내되 — 건설적으로. "
     "모든 리스크에는 완화책을 함께 제시합니다."),
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
