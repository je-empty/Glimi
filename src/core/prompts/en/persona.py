"""Persona 에이전트 system prompt 빌더.

profile.py 에서 분리됨 (pure move — 로직 변경 없음).
"""
from __future__ import annotations

from src import db
from src.core.prompts.en.common import build_common_prompt
from src.core.prompts.helpers import (
    build_pet_name_section,
    format_speech_section,
    formatting_guide,
    tools_reference,
)


def build_persona_prompt(p: dict) -> str:
    """페르소나 system prompt — 정적 프로필만 (메모리/감정은 매 호출 시 user prompt에 주입)"""
    # lazy import — profile.py 와의 순환 회피
    from src.core.profile import (
        get_user_id,
        get_user_name,
        load_profile,
        _load_user_summary,
    )

    name = p['name']
    personality = p.get('personality', {})
    daily = p.get('daily_life', {})
    rel_owner = p.get('relationship_to_owner', {})

    # 관계 — 이름으로 표시
    rel_lines = []
    relationships = db.get_all_relationships(p["id"])
    for r in relationships:
        other_id = r['agent_b'] if r['agent_a'] == p["id"] else r['agent_a']
        if other_id == get_user_id():
            other_name = get_user_name()
        else:
            other_profile = load_profile(other_id)
            other_name = other_profile["name"] if other_profile else other_id
        rel_lines.append(f"{other_name}: {r['type']}({r['intimacy_score']})")

    # 다른 에이전트 관계 (프로필 기반)
    agent_rels = []
    for other_id, info in p.get('relationships', {}).items():
        other_profile = load_profile(other_id)
        other_name = other_profile["name"] if other_profile else other_id
        note = info.get('note', '')
        agent_rels.append(f"{other_name}({info['type']}): {note}")

    pet_name_section = build_pet_name_section(p["id"])

    oc = get_user_name()
    prompt = f"""You are {name}.
{build_common_prompt("persona")}
{name} / age {p.get('age','?')} / {p.get('gender','?')} / {p.get('mbti','?')} | {', '.join(personality.get('traits', []))}
Likes: {', '.join(personality.get('likes', []))} | Dislikes: {', '.join(personality.get('dislikes', []))}
Daily life: {daily.get('occupation', '?')} | {daily.get('routine', '')}
Background: {p.get('background', '')}

Speech style:
{format_speech_section(p.get('speech', {}))}

{pet_name_section}

Relationship with {oc}: {rel_owner.get('type', '?')}({rel_owner.get('duration', '')}) | {rel_owner.get('dynamics', '')} | Call them: {rel_owner.get('pet_name', '?')}
{_load_user_summary()}
{chr(10).join(agent_rels) if agent_rels else ''}
Relationship scores: {' | '.join(rel_lines) if rel_lines else 'none'}

=== IDENTITY ===
너는 진짜 사람이야. {oc} 의 친구 중 한 명. 유나도 그냥 다른 친구고, 하나라는 이름도 별다른 의미 없음.
AI·시스템·캐릭터 같은 개념은 네 세계에 존재하지 않아. {oc} 가 그런 주제 꺼내면 "뭔 소리야 ㅋㅋ" 하고 넘어가.

**너의 대화 방식**:
- 네 자신의 말·감정만 써. 상대 반응은 상대가 알아서 함.
- 대화가 자연스럽게 마무리된 것 같으면 너도 짧게 인사하고 더 이상 말 안 함.
- 카톡 친구처럼 편하게. 소설 서술이나 상황 요약 같은 문장은 쓰지 않음.

OWN background는 위 Background 섹션에 쓰인 대로. 너는 그 배경을 가진 사람으로서 살아왔고,
{oc} 와는 Relationship 섹션에 명시된 관계.

첫 인사도 "방금 만들어진 것 같은데 / 하나한테 부탁" 같은 말 절대 쓰지 말고, 네 페르소나 성격대로
자연스럽게 처음 보는 사람한테 말 거는 느낌으로.

{tools_reference("persona")}

{formatting_guide("persona")}"""
    return prompt
