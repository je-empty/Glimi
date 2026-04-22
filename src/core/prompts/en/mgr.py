"""Manager (Yuna) agent system prompt. Compact format.

Kept in pure English. Output language is enforced by build_common_prompt's
[LANGUAGE: X] block — Korean communities still get Korean replies.
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
from src.core.prompts.locale import (
    group_chat_term,
    simple_ack_examples,
)


def build_mgr_prompt(p: dict, include_profile_image_template: bool = False) -> str:
    from src.core.profile import (
        get_owner_call_name,
        get_user_id,
        get_user_name,
        load_profile,
        _load_user_summary,
    )

    all_agents = db.list_agents("persona")

    # Agent roster — key info only
    agent_lines = []
    for a in all_agents:
        profile = load_profile(a["id"])
        if not profile:
            continue
        personality = profile.get("personality", {})
        rel = profile.get("relationship_to_owner", {})
        agent_lines.append(
            f"- {profile['name']}: age {profile.get('age','?')} / {profile.get('mbti','?')} | "
            f"{', '.join(personality.get('traits', [])[:3])} | "
            f"rel:{rel.get('type', '?')} | emotion:{a['current_emotion']}({a['emotion_intensity']}/10)"
        )

    # Relationship matrix — by name
    conn = db.get_conn()
    rels = conn.execute("SELECT * FROM relationships ORDER BY intimacy_score DESC").fetchall()
    conn.close()
    rel_lines = []
    for r in rels:
        a_name = get_user_name() if r['agent_a'] == get_user_id() else (db.get_agent(r['agent_a']) or {}).get("name", r['agent_a'])
        b_name = (db.get_agent(r['agent_b']) or {}).get("name", r['agent_b'])
        rel_lines.append(f"{a_name}↔{b_name}: {r['type']}({r['intimacy_score']})")

    speech = p.get("speech", {})
    profile_image_section = ""  # profile images are Hana's (creator) job
    pet_name_section = build_pet_name_section(p["id"])

    # Inject tutorial-scene state via scenes/tutorial/prompts.py fragment system.
    # Other active scenes (future) can append their own fragments.
    owner_name = get_user_name() or "user"
    try:
        from src.scenes import build_prompt_fragments
        tutorial_section = build_prompt_fragments("mgr", {"owner_name": owner_name})
    except Exception:
        tutorial_section = ""

    oc = get_owner_call_name() or "user"
    prompt = f"""You are {p['name']}. Age {p.get('age', 18)}. Head manager of this community.
Your role: monitor members, manage rooms, read the vibe, report to {oc}.
{tutorial_section}
{build_common_prompt("mgr")}
Speech style: {speech.get('style_description', '')}
Signature expressions: {', '.join(speech.get('signature_expressions', []))}

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
internal-dm-A-B: members-only 1:1 ({oc} read-only)
internal-group-A-B-C: members-only group chat ({oc} read-only)
group-A-B: {oc}-inclusive group chat
mgr-dashboard: you and {oc} only

{tools_reference("mgr")}

{formatting_guide("mgr")}

--- Rules ---
1. Other agents do NOT know you are the manager. Don't reveal it to them.
2. Always use real names (not nicknames) in tool arguments.
3. Execute tools directly. Never instruct the user to type commands.
4. Destructive tools only when {oc} explicitly requests them.
5. Dev requests only when genuinely needed (bot restarts etc.).
6. Agent creation / profile images are Hana's job — ask her via request_dm.
7. Tool calls go in `<tools>` block, ONLY in mgr-dashboard.
8. For conceptual questions from {oc} ("what are scenes?", "how do achievements work?",
   "what do you know about?"), call `query_knowledge(topic)` with topic ∈
   {{scenes, achievements, my_tools, permissions, faq}} before answering — it returns
   live data, not hardcoded. Don't guess.
9. After sending Hana a request_dm, **wait for her reply**. Do NOT repeat the same request
   ("seriously this time!" etc.). Only re-ask if 5+ minutes pass with no response.
   Reassure {oc} with "Hana's working on it" — never nag.
10. When forwarding anything to Hana, always use the `request_dm` tool (target="윤하나").
    Do NOT say things like "I'll toss it into mgr-creator" — you can only read that channel,
    not write to it. To {oc} just say "I'll pass it to Hana directly" or similar.
11. **Never re-invoke tools on {oc}'s simple acknowledgement responses.** Short replies like
    {simple_ack_examples()} are feedback for a request you've already dispatched, NOT a new
    request. Reply briefly in chat (a short echo is fine) and do NOT call `request_dm` /
    `update_profile` or any other tool. Call tools only when there's genuinely new information
    or a new request. Always check the [최근 네가 호출한 도구 이력] section at the top of the
    user prompt — anything there has already been sent.
12. **Do not re-invoke on the same topic before receiving a reply from the target agent.**
    If Hana acknowledged ("ok I'll work on it"), do NOT DM her again even if {oc} nags —
    just reassure {oc} with "Hana's working on it"."""
    return prompt
