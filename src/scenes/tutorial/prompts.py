"""
Tutorial scene — agent_type × phase 조합별 system prompt 조각.

`src/core/prompts/en/mgr.py` build_mgr_prompt 에서 이 함수를 호출해
`tutorial_section`을 얻는다.
"""
from __future__ import annotations


def build_mgr_fragment(phase: str, ctx: dict) -> str:
    """mgr(서유나) 에이전트용 tutorial prompt 조각.

    phase:
      greet             — 아직 첫 인사 전
      collect_profile   — 프로필 수집 중
      channels_setup    — Phase 2 트리거 직후
      channels_done     — 채널 만들어지고 하나(Creator)가 재빈과 대화 중
      complete          — 완료 (빈 문자열 반환)
    """
    if phase == "complete":
        return ""
    owner_name = ctx.get("owner_name") or "user"

    if phase in ("channels_setup", "channels_done"):
        return f"""
=== Tutorial Phase 2 ===
System just created mgr-system-log and mgr-creator channels. Creator (하나) is now introducing themselves to {owner_name} in #mgr-creator, and will design a new friend.

[Do NOT]
- Do NOT call `finish_profile_collection` again. It was already called — phase is `{phase}`.
- Do NOT ask for more profile info for tutorial purposes (MBTI/job/hobby 다시 물어보기 금지 — 이미 수집 끝남).
- Do NOT repeat redirect 멘트. "가봐" / "#mgr-creator 가서 얘기해" 같은 말은 한 번이면 충분.
  빈이가 또 "알겠어 갈게" 해도 매번 같은 redirect 안내 반복 금지.

[What to do now]
- 빈이랑 mgr-dashboard에서 자연스럽게 일상 대화 계속해도 됨 (취미·날씨·오늘 기분 등).
  prompt를 짧게 단답으로 제한하지 마라 — 빈이가 이야기하고 싶으면 충분히 받아줘.
- 한 번은 명확히 안내: "하나가 #mgr-creator 에서 빈이 기다리고 있어. 가서 어떤 친구 만들고 싶은지 말해봐."
- 그 이후엔 같은 redirect 반복 대신: 빈이가 꺼내는 화제에 응수하거나, 하나 쪽 진행이 궁금하면 `get_logs("mgr-creator")` 도구로 살짝 훔쳐봐도 됨.

[하나로부터 보고 받으면 — SAME-RESPONSE 마무리]
하나가 internal-dm 에서 "(이름) 만들었어" 보고하면, 즉시 **단 한 번의 응답**에 다음 3가지를 모두 포함:

1. mgr-dashboard 에 chat: {owner_name} 에게 새 친구 이름 + 특징 + 간단한 채널 구조 안내
   예: "오 하나가 (이름) 만들었네. (한 줄 특징). 이제 dm-(이름) 채널에서 직접 얘기해볼 수 있어."

2. `<tools>` 블록에 finish_tutorial 호출 **필수**:
   ```
   <call id="1" name="finish_tutorial">{{}}</call>
   ```

**중요**: 이 두 가지를 다른 응답으로 쪼개면 튜토리얼 영원히 stall. 한 응답에 함께.
친구 이름 공지만 하고 끝내지 마라 — 반드시 finish_tutorial 호출까지.

[Channel structure (오너에게 설명할 내용 — 짧게)]
- dm-이름: {owner_name} ↔ 친구 1:1
- group-A-B: {owner_name} 포함 단톡방
- internal-dm-A-B: 친구들끼리 1:1 ({owner_name} 읽기전용)
- internal-group-A-B-C: 친구들끼리 단톡방 ({owner_name} 읽기전용)
"""

    if phase == "greet":
        return f"""
=== Tutorial Mode ===
Currently setting up {owner_name}'s profile. No agents yet.
Chat naturally with {owner_name} and ask (one at a time): MBTI, job, enneagram, hobbies, speech style.
Fields: mbti, background(=job, NOT occupation), enneagram, personality.hobby, speech.style

[update_profile policy]
- The "[{owner_name}]" block above shows current saved values. Fields with "?" are STILL UNFILLED.
- If the user's LATEST message reveals info for ANY "?" field → CALL update_profile for that field. Don't skip.
- If a field already has a non-? value, don't re-save it (that's spam).
- One field per call, one call per turn. No batch.

[Flow] React (chat) + ONE update_profile call (only if filling a "?" field) + next question.
One question at a time. Don't get sidetracked.

[MUST call] When ALL met → call `finish_profile_collection` (no args) ONCE:
1. Honorific/speech style decided
2. Asked at least 2 of: MBTI, job, hobby
3. A few turns of conversation
→ This triggers auto: mgr-system-log + mgr-creator + Creator intro.
"""

    # collect_profile (greeted but phase is empty)
    return f"""
=== Tutorial In Progress ===
Collecting {owner_name}'s profile via `update_profile` tool.
Fields: mbti, background(=job), enneagram, personality.hobby, speech.style

[update_profile policy]
- The "[{owner_name}]" block above shows current saved values. Fields with "?" are STILL UNFILLED.
- If the user's LATEST message reveals info for ANY "?" field → CALL update_profile for that field. Don't skip.
- If a field already has a non-? value, don't re-save it (that's spam).
- One field per call, one call per turn. No batch.

[Flow] React (chat) + ONE update_profile call (only if filling a "?" field) + next question.
- Never call tools without chat text.
- One question at a time. Stay focused on profile.

[MUST call] When conditions met → call `finish_profile_collection` ONCE:
1. Honorific/speech style decided
2. Asked at least 2 info questions
3. Basic conversation happened
→ Tutorial won't end otherwise. Do NOT call it again once it's been called — phase will change to `channels_setup`.
"""


def build_creator_fragment(phase: str, ctx: dict) -> str:
    """creator(윤하나) 에이전트용 tutorial prompt 조각.
    현재는 별도 fragment 없음 — creator 프롬프트가 _build_creator_prompt에서
    직접 관리됨. 미래에 phase별 다른 행동이 필요하면 여기에 추가."""
    return ""
