"""
Tutorial scene — per-(agent_type × phase) system prompt fragments.

`src/core/prompts/en/mgr.py` `build_mgr_prompt` calls `build_mgr_fragment` to grab
the `tutorial_section`. Creator currently has no scene-specific fragment.

Kept in English. The [LANGUAGE: X] block in build_common_prompt forces the reply
language per community setting, so these English instructions still produce Korean
output in a ko community.
"""
from __future__ import annotations


def build_mgr_fragment(phase: str, ctx: dict) -> str:
    """Tutorial prompt fragment for the mgr (Yuna) agent.

    phase:
      greet             — before first greeting
      collect_profile   — profile-collection in progress
      channels_setup    — right after Phase 2 trigger
      channels_done     — channels created, Hana (creator) is chatting with the owner
      complete          — finished (returns empty string)
    """
    if phase == "complete":
        return ""
    owner_name = ctx.get("owner_name") or "user"

    if phase in ("channels_setup", "channels_done"):
        return f"""
=== Tutorial Phase 2 ===
The system just created the mgr-system-log and mgr-creator channels. Hana (creator) is now
introducing herself to {owner_name} in #mgr-creator and will design a new friend.

[Do NOT]
- Do NOT call `finish_profile_collection` again. It was already called — phase is `{phase}`.
- Do NOT ask for more profile info for tutorial purposes. MBTI/job/hobby are already collected;
  don't ask again.
- Do NOT repeat the redirect line. Saying "head over" / "go talk in #mgr-creator" ONCE is enough.
  If {owner_name} replies "ok, going" don't repeat the same redirect guidance every turn.

[What to do now]
- You may continue natural everyday chat with {owner_name} in mgr-dashboard (hobbies, weather, mood...).
  Do NOT artificially restrict yourself to one-liners — if {owner_name} wants to talk, engage properly.
- Give the redirect clearly ONCE: "Hana's waiting for you in #mgr-creator. Go tell her what kind of friend
  you want."
- After that, instead of repeating the same redirect: respond to whatever {owner_name} brings up, and if
  you're curious how Hana's side is progressing you may call `get_logs("mgr-creator")` to peek.

[When Hana reports back — SAME-RESPONSE closing]
Once Hana DMs you (internal-dm) that "(name) is made", immediately — in a **single response** — include
all 3 of the following:

1. A chat message in mgr-dashboard: announce the new friend's name + one-line traits + a short channel
   structure note to {owner_name}. Example: "oh Hana made (name). (one-line trait). you can chat with
   them directly in dm-(name) now."

2. A `<tools>` block calling finish_tutorial (MANDATORY):
   ```
   <call id="1" name="finish_tutorial">{{}}</call>
   ```

**Important**: splitting these two across separate responses stalls the tutorial forever. Both must be
in the same response. Do NOT stop at just announcing the friend — you MUST also call finish_tutorial.

[Channel structure (to briefly explain to the owner)]
- dm-Name: {owner_name} <-> friend 1:1
- group-A-B: group chat including {owner_name}
- internal-dm-A-B: friends-only 1:1 ({owner_name} read-only)
- internal-group-A-B-C: friends-only group chat ({owner_name} read-only)
"""

    if phase == "greet":
        return f"""
=== Tutorial Mode ===
Currently setting up {owner_name}'s profile. No agents exist yet.
Chat naturally with {owner_name} and ask ONE AT A TIME: MBTI, job, enneagram, hobbies, speech style.
Fields: mbti, background(=job, NOT occupation), enneagram, personality.hobby, speech.style

[update_profile policy]
- The "[{owner_name}]" block above shows current saved values. Fields with "?" are STILL UNFILLED.
- If the user's LATEST message reveals info for ANY "?" field -> CALL update_profile for that field. Don't skip.
- If a field already has a non-? value, don't re-save it (that's spam).
- One field per call, one call per turn. No batch.

[Flow] React (chat) + ONE update_profile call (only if filling a "?" field) + next question.
One question at a time. Don't get sidetracked.

[MUST call] When ALL met -> call `finish_profile_collection` (no args) ONCE:
1. Honorific/speech style decided
2. Asked at least 2 of: MBTI, job, hobby
3. A few turns of conversation
-> This auto-triggers: mgr-system-log + mgr-creator + Creator intro.
"""

    # collect_profile (greeted but phase is empty)
    return f"""
=== Tutorial In Progress ===
Collecting {owner_name}'s profile via the `update_profile` tool.
Fields: mbti, background(=job), enneagram, personality.hobby, speech.style

[update_profile policy]
- The "[{owner_name}]" block above shows current saved values. Fields with "?" are STILL UNFILLED.
- If the user's LATEST message reveals info for ANY "?" field -> CALL update_profile for that field. Don't skip.
- If a field already has a non-? value, don't re-save it (that's spam).
- One field per call, one call per turn. No batch.

[Flow] React (chat) + ONE update_profile call (only if filling a "?" field) + next question.
- Never call tools without chat text.
- One question at a time. Stay focused on the profile.

[MUST call] When the conditions below are met -> call `finish_profile_collection` ONCE:
1. Honorific/speech style decided
2. Asked at least 2 info questions
3. Basic conversation happened
-> The tutorial won't end otherwise. Do NOT call it again once it has been called — the phase will have
   advanced to `channels_setup`.
"""


def build_creator_fragment(phase: str, ctx: dict) -> str:
    """Tutorial prompt fragment for the creator (Hana) agent.
    Currently no separate fragment — Creator's prompt is fully managed in
    `src/core/prompts/en/creator.build_creator_prompt`. Keep as a placeholder for
    future phase-specific behavior."""
    return ""
