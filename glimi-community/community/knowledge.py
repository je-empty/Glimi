"""
중앙 지식 리졸버 — 에이전트가 사용자 질문에 답하기 위해 on-demand 로 호출.

설계 원칙:
  - SSoT (Single Source of Truth): 씬·도전과제·도구는 각자의 definitions/registry 가 정답.
    중복 문서 유지하지 말 것 — 여기서 **동적으로 enumerate** 해서 반환.
  - FAQ/deflection 만 `docs/yuna_knowledge.md` 에서 로드 (code 로 못 표현하는 스타일·회피 전략).
  - 에이전트 타입별 접근 제어: `query(topic, agent_id)` 가 caller type 에 따라 필터.

대부분 유나(mgr) 가 호출. 추후 하나(creator)/페르소나 도 필요해지면 각 topic 별
access matrix 확장.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from community import db


# ── 허용 매트릭스 (topic × agent_type) ─────────────────────

# 각 토픽을 볼 수 있는 에이전트 타입. 미등록 타입은 거부.
_ACCESS: dict[str, frozenset[str]] = {
    "achievements": frozenset({"mgr"}),
    "scenes":       frozenset({"mgr"}),
    "my_tools":     frozenset({"mgr", "creator", "persona"}),
    "permissions":  frozenset({"mgr"}),
    "faq":          frozenset({"mgr"}),
}


TOPICS = list(_ACCESS.keys())


# ── 리졸버 ──────────────────────────────────────────────

def _resolve_achievements(agent_id: str) -> str:
    """도전과제 카탈로그 + 현재 유저 진척도. definitions.py 가 SSoT."""
    from community.achievements.definitions import ACHIEVEMENTS
    from community.achievements import engine as _eng

    summary = _eng.dashboard_summary()
    progress_by_key = {it["key"]: it for it in summary.get("items", [])}

    lines = [
        f"[도전과제 — 현재 {summary.get('done', 0)}/{summary.get('total', len(ACHIEVEMENTS))} 완료]",
        "각 과제는 오너가 자연스럽게 활동하다 보면 자동 체크됨. 강제 달성 불가.",
        "",
    ]
    for ach in ACHIEVEMENTS:
        cur = progress_by_key.get(ach.key, {})
        state = cur.get("state", "locked")
        state_kr = {"done": "✓ 완료", "unlocked": "⏳ 진행", "locked": "🔒 미시작"}.get(state, state)
        prog = cur.get("progress")
        prog_str = ""
        if prog:
            if "msgs" in prog and "need" in prog:
                prog_str = f"  (진척 {prog['msgs']}/{prog['need']})"
            elif "talked_to" in prog and "need" in prog:
                prog_str = f"  (진척 {len(prog['talked_to'])}/{prog['need']})"
        lines.append(f"  {ach.icon} {ach.title} — {ach.description} [{state_kr}]{prog_str}")
    return "\n".join(lines)


def _resolve_scenes(agent_id: str) -> str:
    """현재 활성/정의된 씬. src/scenes/ 에서 enumerate."""
    import importlib, pkgutil

    lines = [
        "[씬(Scene) — 세계관 에피소드]",
        "각 씬은 시작·진행·종료 조건이 있는 스토리 단위. 강제 진행됨 (supervisor 가 감시).",
        "",
    ]
    try:
        scenes_pkg = importlib.import_module("community.scenes")
        scenes_found = []
        for _, modname, ispkg in pkgutil.iter_modules(scenes_pkg.__path__):
            if not ispkg or modname in ("__pycache__",):
                continue
            try:
                sub = importlib.import_module(f"community.scenes.{modname}")
                if hasattr(sub, "scene"):
                    sc = sub.scene
                    scenes_found.append((modname, sc))
            except Exception:
                continue

        if not scenes_found:
            lines.append("  (활성 씬 없음)")
        else:
            for modname, sc in scenes_found:
                name = getattr(sc, "display_name", None) or getattr(sc, "id", modname)
                phase = sc.current_phase() if hasattr(sc, "current_phase") else "?"
                active = sc.is_active() if hasattr(sc, "is_active") else False
                mark = "🎬 활성" if active else "— 대기/완료"
                lines.append(f"  {mark}  {name}  (phase={phase})")
    except Exception as e:
        lines.append(f"  (enumerate 실패: {e})")

    lines += [
        "",
        "예정 씬: 생일 파티, 갈등 중재, 단톡방 모임, 외출 등 (추후 추가).",
    ]
    return "\n".join(lines)


def _resolve_my_tools(agent_id: str) -> str:
    """caller 가 쓸 수 있는 도구 + 간단 설명."""
    from glimi.tools.registry import tools_for_agent
    from community.core.profile import load_profile

    profile = load_profile(agent_id) or {}
    agent_type = profile.get("type", "persona")
    tools = tools_for_agent(agent_type)
    if not tools:
        return f"[내 도구] ({agent_type} 용 도구 없음)"
    lines = [f"[내 도구 — {agent_type}]"]
    by_cat: dict[str, list] = {}
    for t in tools:
        by_cat.setdefault(t.category, []).append(t)
    for cat in ("management", "query", "request"):
        if cat not in by_cat:
            continue
        lines.append(f"  - {cat}:")
        for t in by_cat[cat]:
            marker = "⚠ " if t.destructive else ""
            lines.append(f"    · {marker}`{t.name}` — {t.description}")
    return "\n".join(lines)


def _resolve_permissions(agent_id: str) -> str:
    """유나가 볼 수 있는 범위 요약."""
    from community.core.profile import load_profile
    profile = load_profile(agent_id) or {}
    if profile.get("type") != "mgr":
        return "[접근 범위] — mgr 아님. 본 과제 비적용."

    # DB 기반 실 데이터
    conn = db.get_conn()
    ch_rows = conn.execute("SELECT channel FROM channels").fetchall()
    channels = [r["channel"] for r in ch_rows]
    personas = conn.execute("SELECT COUNT(*) FROM agents WHERE type='persona'").fetchone()[0]
    conn.close()

    groups = {"dm": 0, "group": 0, "internal-dm": 0, "internal-group": 0, "mgr": 0}
    for ch in channels:
        if ch.startswith("dm-"): groups["dm"] += 1
        elif ch.startswith("group-"): groups["group"] += 1
        elif ch.startswith("internal-dm"): groups["internal-dm"] += 1
        elif ch.startswith("internal-group"): groups["internal-group"] += 1
        elif ch.startswith("mgr"): groups["mgr"] += 1

    lines = [
        "[내 접근 범위 (실데이터)]",
        f"  페르소나: {personas}명",
        f"  채널: dm {groups['dm']} / group {groups['group']} / "
        f"internal-dm {groups['internal-dm']} / internal-group {groups['internal-group']} / mgr {groups['mgr']}",
        "",
        "볼 수 있는 것: 모든 채널 대화, 멤버 프로필·관계, 이벤트",
        "볼 수 없는 것: 멤버 개인 내면 기억 (그들만의 것), 하나의 비공개 작업 상세",
    ]
    return "\n".join(lines)


def _resolve_faq(agent_id: str) -> str:
    """docs/yuna_knowledge.md 의 정적 FAQ/회피 전략."""
    try:
        p = Path(__file__).resolve().parent.parent / "docs" / "yuna_knowledge.md"
        if not p.exists():
            return "[FAQ] (파일 없음)"
        return p.read_text(encoding="utf-8")
    except Exception as e:
        return f"[FAQ] (로드 실패: {e})"


_RESOLVERS = {
    "achievements": _resolve_achievements,
    "scenes": _resolve_scenes,
    "my_tools": _resolve_my_tools,
    "permissions": _resolve_permissions,
    "faq": _resolve_faq,
}


# ── 공개 API ────────────────────────────────────────────

def query(topic: str, agent_id: str) -> str:
    """topic 에 해당하는 내용을 문자열로 반환. 접근권한 없으면 빈 결과 + 이유."""
    from community.core.profile import load_profile

    topic = (topic or "").strip().lower()
    if topic not in _ACCESS:
        avail = ", ".join(TOPICS)
        return f"[모르는 주제: {topic}] 가능한 주제: {avail}"

    profile = load_profile(agent_id) or {}
    agent_type = profile.get("type", "persona")
    if agent_type not in _ACCESS[topic]:
        return f"[{topic}] 접근 권한 없음 ({agent_type})"

    try:
        resolver = _RESOLVERS.get(topic)
        if not resolver:
            return f"[{topic}] 리졸버 미정의"
        return resolver(agent_id)
    except Exception as e:
        return f"[{topic}] 조회 실패: {e}"


def list_topics(agent_id: str) -> list[str]:
    """주어진 에이전트가 쓸 수 있는 토픽 리스트."""
    from community.core.profile import load_profile
    profile = load_profile(agent_id) or {}
    agent_type = profile.get("type", "persona")
    return [t for t, types in _ACCESS.items() if agent_type in types]
