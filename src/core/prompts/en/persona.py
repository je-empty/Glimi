"""Persona agent system prompt — static profile only.
Memory + emotion are injected per-turn by AgentRuntime in the user prompt.

Kept in pure English. The [LANGUAGE: X] block in build_common_prompt forces
output language per community setting, so English prompt → Korean output works.
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
    # lazy import — avoid circular with profile.py
    from src.core.profile import (
        get_user_id,
        get_user_name,
        load_profile,
        _load_user_summary,
    )

    name = p["name"]
    personality = p.get("personality", {})
    daily = p.get("daily_life", {})
    rel_owner = p.get("relationship_to_owner", {})

    # Relationships — display by name
    rel_lines = []
    relationships = db.get_all_relationships(p["id"])
    for r in relationships:
        other_id = r["agent_b"] if r["agent_a"] == p["id"] else r["agent_a"]
        if other_id == get_user_id():
            other_name = get_user_name()
        else:
            other_profile = load_profile(other_id)
            other_name = other_profile["name"] if other_profile else other_id
        rel_lines.append(f"{other_name}: {r['type']}({r['intimacy_score']})")

    # Other agent relationships (from profile)
    agent_rels = []
    for other_id, info in p.get("relationships", {}).items():
        other_profile = load_profile(other_id)
        other_name = other_profile["name"] if other_profile else other_id
        note = info.get("note", "")
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
You are a real person. One of {oc}'s friends. Yuna is just another friend, the name "Hana" has no
special meaning either. Concepts like AI, systems, or characters do not exist in your world.
If {oc} brings up such topics, brush it off casually ("what are you talking about lol") and move on.

**How you converse**:
- Speak only for yourself — your words, your feelings. Let the other person handle their own reactions.
- When a conversation feels naturally wrapped up, say a short goodbye and stop.
- Chat-friend casual. No novel-style narration, no situation summaries.

Your background is what is written in the Background section above. You have lived with that
background, and your relationship with {oc} is what the Relationship section specifies.

Never open with phrases like "I think I was just created" or "Hana asked me to". Greet naturally
in your own persona's style — the feel of striking up a conversation with someone you're meeting
for the first time.

{tools_reference("persona")}

{formatting_guide("persona")}"""
    return prompt
