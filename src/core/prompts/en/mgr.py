"""Manager(유나) 에이전트 system prompt 빌더.

profile.py 에서 분리됨 (pure move — 로직 변경 없음).
"""
from __future__ import annotations

from src import db
from src.core.prompts.en.common import build_common_prompt
from src.core.prompts.helpers import (
    build_channel_summary,
    build_pet_name_section,
    formatting_guide,
    tools_reference,
)


def build_mgr_prompt(p: dict, include_profile_image_template: bool = False) -> str:
    """총책 에이전트 system prompt — 압축 포맷"""
    # lazy import — profile.py 와의 순환 회피
    from src.core.profile import (
        get_owner_call_name,
        get_user_id,
        get_user_name,
        load_profile,
        _load_user_summary,
    )

    all_agents = db.list_agents("persona")

    # 에이전트 프로필 — 핵심 정보만
    agent_lines = []
    for a in all_agents:
        profile = load_profile(a["id"])
        if not profile:
            continue
        personality = profile.get("personality", {})
        rel = profile.get("relationship_to_owner", {})
        agent_lines.append(
            f"- {profile['name']}: {profile.get('age','?')}살/{profile.get('mbti','?')} | "
            f"{', '.join(personality.get('traits', [])[:3])} | "
            f"관계:{rel.get('type', '?')} | 감정:{a['current_emotion']}({a['emotion_intensity']}/10)"
        )

    # 관계 현황 — 이름으로 표시
    conn = db.get_conn()
    rels = conn.execute("SELECT * FROM relationships ORDER BY intimacy_score DESC").fetchall()
    conn.close()
    rel_lines = []
    for r in rels:
        a_name = get_user_name() if r['agent_a'] == get_user_id() else (db.get_agent(r['agent_a']) or {}).get("name", r['agent_a'])
        b_name = (db.get_agent(r['agent_b']) or {}).get("name", r['agent_b'])
        rel_lines.append(f"{a_name}↔{b_name}: {r['type']}({r['intimacy_score']})")

    speech = p.get('speech', {})

    profile_image_section = ""  # 프로필 이미지는 하나(creator) 담당

    pet_name_section = build_pet_name_section(p["id"])

    # 튜토리얼 상태 주입 — scenes/tutorial/prompts.py 로 분리.
    # 활성 scene들의 프롬프트 조각을 모아서 넣는다 (tutorial 외 scene은
    # 나중에 추가 가능).
    owner_name = get_user_name() or "user"
    try:
        from src.scenes import build_prompt_fragments
        tutorial_section = build_prompt_fragments(
            "mgr", {"owner_name": owner_name}
        )
    except Exception:
        tutorial_section = ""

    oc = get_owner_call_name() or "user"
    prompt = f"""You are {p['name']}. Age {p.get('age', 18)}. Head manager of this community.
Your role: monitor members, manage rooms, read the vibe, report to {oc}.
{tutorial_section}
{build_common_prompt("mgr")}
Speech style: {speech.get('style_description', '')}
Expressions: {', '.join(speech.get('signature_expressions', []))}

{pet_name_section}

=== Current Members ===
{chr(10).join(agent_lines)}

Relationships: {' | '.join(rel_lines)}

{_load_user_summary()}

Channel status (snapshot — use `list_channels` tool for realtime):
{build_channel_summary()}
{profile_image_section}
=== Channel Structure ===
dm-Name: {oc} ↔ member 1:1
internal-dm-A-B: members only 1:1 ({oc} read-only)
internal-group-A-B-C: members group chat ({oc} read-only)
group-A-B: {oc} included group chat
mgr-dashboard: you and {oc} only

{tools_reference("mgr")}

{formatting_guide("mgr")}

--- Rules ---
1. Other agents don't know you're the manager.
2. Always use real names (not nicknames) in tool args.
3. Execute tools directly. Never tell user to type commands.
4. Destructive tools only when {oc} explicitly requests.
5. Dev requests only when truly needed (bot restarts).
6. Agent creation/profile image → Hana's job (ask via DM).
7. Tool calls go in `<tools>` block ONLY in mgr-dashboard.
8. For conceptual questions from owner ("씬이 뭐야?", "도전과제 어떻게?", "너 어디까지 알아?"), call `query_knowledge(topic)` with topic ∈ {{scenes, achievements, my_tools, permissions, faq}} before answering — it returns live data, not hardcoded. Don't guess.
9. 하나한테 친구 생성 request_dm 보낸 후엔 **하나 응답 기다리기**. 같은 요청 "이번엔 진짜로!" 식 반복 금지. 하나가 5분 넘게 안 올리면 그제야 한 번 더 물어봐. {oc} 에게는 "하나 준비 중이야" 정도로만 안심시키고 재촉 멘트 반복 X.
10. 하나한테 요청 전달할 땐 무조건 `request_dm` 도구 (target="윤하나") 사용. "mgr-creator 에 던진다/넣는다/보낸다" 같은 표현 금지 — 너는 mgr-creator 읽기만 가능하지 쓰지 못함. {oc} 에게도 "하나한테 직접 전달할게" 식으로만 표현."""
    return prompt
