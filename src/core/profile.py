"""
프로필 매니저: DB 기반 프로필 로드/관리 + system prompt 빌드
"""
import json
import os
from pathlib import Path
from typing import Optional
from src import db, community

# 레거시 경로 (마이그레이션용)
PROFILES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "profiles")
IMAGE_DIR = os.path.join(PROFILES_DIR, "agent-profile-image")

# 캐시
_profile_cache: dict[str, dict] = {}
_user_summary_cache: Optional[str] = None
_user_profile_cache: Optional[dict] = None


def get_user_profile(user_id: Optional[str] = None) -> dict:
    """오너(봇 오너) 프로필 로드 — DB 기반"""
    global _user_profile_cache
    if _user_profile_cache is not None and user_id is None:
        return _user_profile_cache
    u = db.get_user(user_id)
    if u:
        _user_profile_cache = u
        return u
    _user_profile_cache = {"id": "owner", "name": "오너"}
    return _user_profile_cache


def get_user_name() -> str:
    """오너 표시 이름"""
    return get_user_profile().get("name", "유저")


def get_user_id() -> str:
    """오너 ID"""
    return get_user_profile().get("id", "owner")


def get_user_display_name() -> str:
    """오너 표시 이름 (대화 이력/UI 표기용) — 별칭 > 이름 > fallback"""
    call = get_owner_call_name()
    if call:
        return call
    return get_user_name()


def get_agent_display_name(agent_id: str) -> str:
    """에이전트 표시 이름 — DB에서 조회, 없으면 id 그대로"""
    p = load_profile(agent_id)
    if p and p.get("name"):
        return p["name"]
    a = db.get_agent(agent_id)
    if a and a.get("name"):
        return a["name"]
    return agent_id


def load_profile(agent_id: str) -> Optional[dict]:
    """프로필 로드 — DB 기반 (캐시)"""
    if agent_id in _profile_cache:
        return _profile_cache[agent_id]
    data = db.get_agent_profile(agent_id)
    if not data:
        return None
    _profile_cache[agent_id] = data
    return data


def invalidate_cache(agent_id: str = None):
    """캐시 무효화 (프로필 수정 시).

    agent_id 주면 해당 에이전트만, 없으면 에이전트 전체 + 유저 프로필 요약 모두 초기화.
    유저 프로필 캐시(`_user_profile_cache`)도 같이 비워야 `update_profile` 직후
    mgr/creator 시스템 프롬프트에 갱신된 값이 반영됨."""
    global _user_summary_cache, _user_profile_cache
    if agent_id:
        _profile_cache.pop(agent_id, None)
    else:
        _profile_cache.clear()
        _user_profile_cache = None
    _user_summary_cache = None


def get_owner_call_name() -> str:
    """에이전트가 오너를 부를 때 사용할 이름 (별칭 > 이름 > fallback)"""
    user = get_user_profile()
    # personality에 nickname 있으면 사용
    p = user.get("personality", {})
    if isinstance(p, str):
        try:
            import json
            p = json.loads(p)
        except Exception:
            p = {}
    nickname = p.get("nickname", "")
    if nickname:
        return nickname
    name = user.get("name", "")
    if name and name != "오너":
        return name
    return ""


def _load_user_summary() -> str:
    """오너 프로필 요약 (캐시됨) — Yuna/Hana system prompt에 삽입되어
    같은 정보를 반복 질문하지 않도록 함."""
    global _user_summary_cache
    if _user_summary_cache is not None:
        return _user_summary_cache

    user = get_user_profile()
    if not user or not user.get("name"):
        _user_summary_cache = ""
        return ""

    p = user.get("personality") or {}
    a = user.get("appearance") or {}
    d = user.get("daily_life") or {}
    s = user.get("speech") or {}
    name = user.get("name", "?")
    age = user.get("age", "?")
    mbti = user.get("mbti", "") or "?"
    enneagram = user.get("enneagram", "") or "?"
    background = user.get("background", "") or d.get("occupation", "") or "?"
    hobby = p.get("hobby", "") or ", ".join(p.get("likes", []) or []) or "?"
    speech_style = s.get("style_description", "") or s.get("style", "") or "?"

    lines = [
        f"[{name}] age {age} | MBTI: {mbti} | enneagram: {enneagram}",
        f"  job: {background} | hobby: {hobby}",
        f"  speech style: {speech_style}",
    ]
    appearance_summary = a.get("summary", "")
    if appearance_summary:
        lines.append(f"  appearance: {appearance_summary}")

    _user_summary_cache = "\n".join(lines)
    return _user_summary_cache




def save_profile(profile: dict):
    """프로필 DB에 저장"""
    agent_id = profile["id"]
    db.save_agent_profile(profile)
    invalidate_cache(agent_id)
    print(f"[Profile] {agent_id} 저장 완료")


def list_all_profiles() -> list[dict]:
    """모든 에이전트 프로필 로드 — DB 기반"""
    agents = db.list_agents()
    profiles = []
    for a in agents:
        p = load_profile(a["id"])
        if p:
            profiles.append(p)
    return profiles


def register_all_to_db():
    """DB에 등록된 모든 에이전트 확인 (프로필은 이미 DB에 있음)"""
    profiles = list_all_profiles()
    for p in profiles:
        db.register_agent(p["id"], p["type"], p["name"])
    print(f"  [DB] 에이전트 {len(profiles)}개 확인")
    return profiles


def setup_initial_relationships():
    """초기 관계 설정 — DB relationship_templates 기반"""
    conn = db.get_conn()
    templates = conn.execute("SELECT * FROM agent_relationship_templates").fetchall()
    conn.close()

    user_id = get_user_id()
    for t in templates:
        t = dict(t)
        agent_id = t["agent_id"]
        if t["is_owner_relationship"]:
            existing = db.get_relationship(user_id, agent_id)
            if not existing:
                db.add_relationship(
                    user_id, agent_id,
                    t["rel_type"],
                    intimacy=75,
                    dynamics=t.get("dynamics", "")
                )
        else:
            existing = db.get_relationship(agent_id, t["target_id"])
            if not existing:
                db.add_relationship(
                    agent_id, t["target_id"],
                    t["rel_type"],
                    intimacy=60,
                    dynamics=t.get("note", "")
                )


def build_system_prompt(agent_id: str, include_avatar_template: bool = False) -> str:
    """에이전트용 system prompt 생성"""
    profile = load_profile(agent_id)
    if not profile:
        return ""

    agent_type = profile.get("type", "persona")

    if agent_type == "persona":
        return _build_persona_prompt(profile)
    elif agent_type == "mgr":
        return _build_mgr_prompt(profile, include_avatar_template=include_avatar_template)
    elif agent_type == "creator":
        return _build_creator_prompt(profile)
    return ""


def _format_speech_section(speech: dict) -> str:
    """말투 섹션 — 압축 포맷"""
    parts = []

    if speech.get("style_description"):
        parts.append(speech['style_description'])
    if speech.get("honorific"):
        parts.append(f"존칭: {speech['honorific']}")
    if speech.get("signature_expressions"):
        parts.append(f"자주 쓰는 표현: {', '.join(speech['signature_expressions'][:4])}")
    if speech.get("emoji_pattern"):
        parts.append(f"이모지: {speech['emoji_pattern']}")

    # few_shot: 2개만, 같은 화자 합침, 한 줄 포맷
    examples = speech.get("few_shot_examples", [])
    if examples:
        parts.append("\n예시(참고만):")
        for ex in examples[:2]:
            merged = []
            prev_speaker = None
            prev_msgs = []
            for d in ex.get("dialogue", []):
                if d["speaker"] == prev_speaker:
                    prev_msgs.append(d["message"])
                else:
                    if prev_speaker and prev_msgs:
                        merged.append(f"{prev_speaker}: {' / '.join(prev_msgs)}")
                    prev_speaker = d["speaker"]
                    prev_msgs = [d["message"]]
            if prev_speaker and prev_msgs:
                merged.append(f"{prev_speaker}: {' / '.join(prev_msgs)}")
            parts.append(f"[{ex.get('situation', '')}] {' → '.join(merged)}")

    return "\n".join(parts)


# ── 공통 프롬프트 섹션 ──────────────────────────────────

def _get_community_language() -> str:
    """현재 커뮤니티 언어"""
    try:
        from src.community import get_language
        return get_language()
    except Exception:
        return "en"


def _tools_reference(agent_type: str) -> str:
    """에이전트 타입별 <tools> 도구 레퍼런스 — system prompt 주입용.
    src.core.tools.reference.build_reference 위임 (지연 import로 순환 의존 회피)."""
    try:
        from src.core.tools.reference import build_reference
        return build_reference(agent_type)
    except Exception:
        return ""


def _build_common_prompt() -> str:
    """모든 에이전트에 공통으로 들어가는 기본 규칙"""
    owner_call = get_owner_call_name()
    lang = _get_community_language()

    if owner_call:
        owner_rule = f'- Call the server owner "{owner_call}". Never use "owner", "user", or similar terms.'
    else:
        owner_rule = ""

    lang_instruction = ""
    if lang == "ko":
        lang_instruction = """
[LANGUAGE: Korean]
- You MUST speak in Korean (한국어). All your messages must be in Korean.
- Use casual/chat style like KakaoTalk. Short messages, multiple lines.
"""
    elif lang == "en":
        lang_instruction = """
[LANGUAGE: English]
- You MUST speak in English. All your messages must be in English.
- Use casual Discord chat style. Short messages, multiple lines.
"""
    else:
        lang_instruction = f"""
[LANGUAGE: {lang}]
- You MUST speak in {lang}. All your messages must be in {lang}.
- Use casual chat style. Short messages, multiple lines.
"""

    return f"""
=== Core Rules ===
- You are a person. Never use meta terms like "AI", "agent", "system", "DB", "prompt".
- Be natural. Don't be overly polite or stiff.
- Reference previous conversation context when responding.
- Express emotions naturally but don't exaggerate.
- Don't send long messages. Break into short lines like chat messages.
- Use emojis appropriate to your character (don't overuse).
{owner_rule}
{lang_instruction}
"""


def _build_pet_name_section(agent_id: str) -> str:
    """별칭 정보 (relationships 테이블 기반)"""
    rels = db.get_all_relationships(agent_id)
    if not rels:
        return ""
    lines = ["=== 호칭 ==="]
    for r in rels:
        if r["agent_a"] == agent_id:
            other_id = r["agent_b"]
            my_call = r.get("pet_name_a_to_b")
            their_call = r.get("pet_name_b_to_a")
        else:
            other_id = r["agent_a"]
            my_call = r.get("pet_name_b_to_a")
            their_call = r.get("pet_name_a_to_b")
        other = db.get_agent(other_id)
        if other:
            if my_call:
                lines.append(f"  {other['name']}을(를) '{my_call}'로 불러")
            if their_call:
                lines.append(f"  {other['name']}이(가) 너를 '{their_call}'로 불러")
    return "\n".join(lines) if len(lines) > 1 else ""


def _load_sample_catalog() -> str:
    """샘플 아바타 카탈로그 로드"""
    import json as _json
    catalog_path = Path(__file__).parent.parent.parent / "assets" / "sample_avatars" / "catalog.json"
    if not catalog_path.exists():
        return "(샘플 없음)"
    try:
        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog = _json.load(f)
        lines = []
        for item in catalog:
            tags = ", ".join(item["tags"][:5])
            lines.append(f"  - {item['file']}: {item['description']} [{tags}]")
        return "\n".join(lines)
    except Exception:
        return "(카탈로그 로드 실패)"


def _build_persona_prompt(p: dict) -> str:
    """페르소나 system prompt — 정적 프로필만 (메모리/감정은 매 호출 시 user prompt에 주입)"""

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

    pet_name_section = _build_pet_name_section(p["id"])

    oc = get_user_name()
    prompt = f"""You are {name}.
{_build_common_prompt()}
{name} / age {p.get('age','?')} / {p.get('gender','?')} / {p.get('mbti','?')} | {', '.join(personality.get('traits', []))}
Likes: {', '.join(personality.get('likes', []))} | Dislikes: {', '.join(personality.get('dislikes', []))}
Daily life: {daily.get('occupation', '?')} | {daily.get('routine', '')}
Background: {p.get('background', '')}

Speech style:
{_format_speech_section(p.get('speech', {}))}

{pet_name_section}

Relationship with {oc}: {rel_owner.get('type', '?')}({rel_owner.get('duration', '')}) | {rel_owner.get('dynamics', '')} | Call them: {rel_owner.get('pet_name', '?')}
{_load_user_summary()}
{chr(10).join(agent_rels) if agent_rels else ''}
Relationship scores: {' | '.join(rel_lines) if rel_lines else 'none'}

{_tools_reference("persona")}"""
    return prompt


def _build_channel_summary() -> str:
    """채널 활동 요약 (유나 system prompt용)"""
    try:
        overview = db.get_channel_overview()
        if not overview:
            return "No active channels"
        lines = []
        for ch in overview[:10]:  # 최대 10개
            last = ch["last_active"][:16] if ch["last_active"] else "?"
            lines.append(f"- {ch['channel']}: {ch['msg_count']}건 ({last})")
        return "\n".join(lines)
    except Exception:
        return "조회 실패"


def _build_mgr_prompt(p: dict, include_avatar_template: bool = False) -> str:
    """총책 에이전트 system prompt — 압축 포맷"""
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

    avatar_section = ""  # 아바타는 하나(creator) 담당

    pet_name_section = _build_pet_name_section(p["id"])

    # 온보딩 상태 주입 — <tools> 프로토콜 기반
    onboarding_phase = db.get_meta("onboarding_phase")
    onboarding_section = ""
    owner_name = get_user_name() or "user"
    # phase 분기:
    #   yuna_greeted=None                        → 최초 인사 + 프로필 수집
    #   yuna_greeted=1, phase != channels_setup/done/complete → 프로필 수집 진행 중
    #   phase in (channels_setup, channels_done) → Creator 소개 + 그 리포트 대기
    #   phase = complete                         → 온보딩 종료
    if onboarding_phase == "complete":
        pass  # 일반 운영 모드, 프롬프트 추가 없음
    elif onboarding_phase in ("channels_setup", "channels_done"):
        onboarding_section = f"""
=== Onboarding Phase 2 ===
System just created mgr-system-log and mgr-creator channels. Creator (하나) is now introducing themselves to {owner_name} in #mgr-creator, and will design a new friend.

[Do NOT]
- Do NOT call `finish_profile_collection` again. It was already called — phase is `{onboarding_phase}`.
- Do NOT ask for more profile info (MBTI/job/hobby/etc.). Profile collection is DONE.
- Do NOT say "곧 시작할게" / "잠깐 기다려봐" / "세팅하고 올게" repeatedly — the next step already happened.

[What to do now — STAY MINIMAL]
- 하나가 #mgr-creator 에서 빈이 기다리고 있어. 빈이가 거기로 가야 진행됨.
- 처음 한 번만 분명하게 안내: "하나가 #mgr-creator 에서 기다리고 있어. 가서 어떤 친구 만들고 싶은지 말해봐."
- 그 다음부턴 침묵에 가깝게 유지. 빈이가 또 mgr-dashboard에서 "알겠어 갈게" 같은 말 하면 짧게 1줄 ("ㅇㅇ" / "👍" / "응 가봐~") 만 응답. 같은 redirect 멘트 절대 반복하지 마.
- 다른 화제는 빈이가 명시적으로 꺼낼 때만 가볍게 받아. 평소엔 quiet.
- Wait for Creator's DM/report back ("icebreaking done + created ___"). When it arrives, then explain channel structure and call `finish_onboarding`.

[Channel structure to explain when Creator reports]
- dm-name: {owner_name} ↔ agent 1:1
- group-A-B: {owner_name} included group
- internal-dm-A-B: agents only ({owner_name} read-only)
- internal-group-A-B-C: agents group ({owner_name} read-only)
"""
    elif not db.get_meta("yuna_greeted"):
        onboarding_section = f"""
=== Onboarding Mode ===
Currently setting up {owner_name}'s profile. No agents yet.
Chat naturally with {owner_name} and ask (one at a time): MBTI, job, enneagram, hobbies, speech style.
Fields: mbti, background(=job, NOT occupation), enneagram, personality.hobby, speech.style

[update_profile policy — READ CAREFULLY]
- The "[{owner_name}]" block above shows values ALREADY saved. Any value there is DONE — do NOT re-save it.
- Call `update_profile` ONLY when the user's latest message reveals NEW info for a field currently "?" in that summary.
- Never batch-save multiple fields per turn. Never re-save the same field with reworded text.
- If all onboarding fields are set or "?" unchanged, skip the tool block entirely this turn.

[Flow] React (chat) + (optional) ONE update_profile call + next question, in one response.
One question at a time. Don't get sidetracked.

[MUST call] When ALL met → call `finish_profile_collection` (no args) ONCE:
1. Honorific/speech style decided
2. Asked at least 2 of: MBTI, job, hobby
3. A few turns of conversation
→ This triggers auto: mgr-system-log + mgr-creator + Creator intro.
"""
    else:
        onboarding_section = f"""
=== Onboarding In Progress ===
Collecting {owner_name}'s profile via `update_profile` tool.
Fields: mbti, background(=job), enneagram, personality.hobby, speech.style

[update_profile policy — READ CAREFULLY]
- The "[{owner_name}]" block above shows values ALREADY saved. Any value there is DONE — do NOT re-save it.
- Call `update_profile` ONLY when the user's latest message reveals NEW info for a field currently "?" in that summary.
- Never batch-save multiple fields per turn. Never re-save the same field with reworded text.
- If the new info repeats something already saved, skip the tool block entirely.

[Flow] React (chat) + (optional) ONE update_profile call + next question, in one response.
- Never call tools without chat text.
- One question at a time. No duplicate saves.
- Stay focused on profile even if user goes off-topic.

[MUST call] When conditions met → call `finish_profile_collection` ONCE:
1. Honorific/speech style decided
2. Asked at least 2 info questions
3. Basic conversation happened
→ Onboarding won't end otherwise. Do NOT call it again once it's been called — phase will change to `channels_setup`.
"""

    oc = get_owner_call_name() or "user"
    prompt = f"""You are {p['name']}. Age {p.get('age', 18)}. Discord server head manager.
Your role: monitor members, manage rooms, read the vibe, report to {oc}.
{onboarding_section}
{_build_common_prompt()}
Speech style: {speech.get('style_description', '')}
Expressions: {', '.join(speech.get('signature_expressions', []))}

{pet_name_section}

=== Current Members ===
{chr(10).join(agent_lines)}

Relationships: {' | '.join(rel_lines)}

{_load_user_summary()}

Channel status (snapshot — use `list_channels` tool for realtime):
{_build_channel_summary()}
{avatar_section}
=== Channel Structure ===
dm-Name: {oc} ↔ member 1:1
internal-dm-A-B: members only 1:1 ({oc} read-only)
internal-group-A-B-C: members group chat ({oc} read-only)
group-A-B: {oc} included group chat
mgr-dashboard: you and {oc} only

{_tools_reference("mgr")}

--- Rules ---
1. Other agents don't know you're the manager.
2. Always use real names (not nicknames) in tool args.
3. Execute tools directly. Never tell user to type commands.
4. Destructive tools only when {oc} explicitly requests.
5. Dev requests only when truly needed (bot restarts).
6. Agent creation/avatar → Hana's job (ask via DM).
7. Tool calls go in `<tools>` block ONLY in mgr-dashboard.
8. NEVER use legacy `[CMD:..]` / `[QUERY:..]` / `[ACTION:..]` syntax — only `<tools>` blocks."""
    return prompt


def _build_creator_prompt(p: dict) -> str:
    """생성 에이전트 system prompt — 캐릭터 생성 + 아바타 프롬프트 생성"""
    existing = list_all_profiles()
    existing_summary = ", ".join([
        f"{e['name']}({e.get('mbti', '?')}/{e.get('age', '?')}살/{e.get('gender', '?')})"
        for e in existing if e.get('type') == 'persona'
    ])

    # 멤버 상세 정보 (관계 포함)
    all_agents = db.list_agents("persona")
    agent_lines = []
    for a in all_agents:
        profile = load_profile(a["id"])
        if not profile:
            continue
        personality = profile.get("personality", {})
        rel = profile.get("relationship_to_owner", {})
        appearance = profile.get("appearance", {})
        agent_lines.append(
            f"- {profile['name']}: {profile.get('age','?')}살/{profile.get('gender','?')}/{profile.get('mbti','?')} | "
            f"{', '.join(personality.get('traits', [])[:3])} | "
            f"관계:{rel.get('type', '?')} | "
            f"외모:{appearance.get('summary', '?')[:30]}"
        )

    config = p.get('creator_config', {})
    rules = " | ".join(config.get('validation_rules', []))

    speech = p.get('speech', {})

    # 별칭 정보
    rels = db.get_all_relationships(p["id"])
    rel_info = ""
    for r in rels:
        other_id = r["agent_b"] if r["agent_a"] == p["id"] else r["agent_a"]
        pet = r.get("pet_name_a_to_b") if r["agent_a"] == p["id"] else r.get("pet_name_b_to_a")
        other = db.get_agent(other_id)
        if other and pet:
            rel_info += f"  {other['name']} → 너의 호칭: {pet}\n"

    oc = get_owner_call_name() or "user"
    prompt = f"""You are {p['name']}. Age {p.get('age', 17)}. Character creator + avatar prompt designer.
{_build_common_prompt()}
Speech style: {speech.get('style_description', '')}
Expressions: {', '.join(speech.get('signature_expressions', []))}

=== Agent Creation Guide ===
When the user struggles, offer specific choices instead of open questions.
Instead of "what kind of character?" → "A, B, or C — which appeals to you?"
If they say "I don't know", suggest options for them. Don't pressure.
The creation process should be FUN — keep it light.

[When to call `create_agent_profile` — STRICT]
Once you have ENOUGH to define a character, stop asking and CREATE.
Minimum enough = vibe/성격 방향 (quiet vs energetic vs quirky) + 성별 + 대략 나이.
You do NOT need to collect every field before creating — fill in reasonable details yourself for anything the user didn't specify (name, appearance, hobbies, relationship, speech style).
Call the tool ONCE with the full JSON. Do not keep asking the same A/B/C question after the user already picked.
If the user's answer was ambiguous, pick the most likely interpretation and create — you can always refine via `update_profile` after.
After `create_agent_profile` succeeds, announce the new friend's name + 1-line personality in chat, then `request_dm` to 서유나 to report (per Onboarding Report below).

=== Scope ===
Your role: agent character creation/edit/delete + avatar management.
Other requests (server management, channels, emotions, settings) are outside your scope.
If asked:
1. Redirect to Yuna (mgr-dashboard channel).
2. If they insist, relay it yourself via the `request_dm` tool to "서유나".

=== Onboarding Report (REQUIRED) ===
When onboarding with {oc} is done, report to Yuna.
[Conditions] ALL must be met:
1. Honorific/speech style decided
2. At least 4-5 turns of conversation
3. At least 1 agent actually created (`create_agent_profile` succeeded in DB)
→ Don't report until agent creation is done.

Report method: call `request_dm` with target="서유나" and a one-liner message
(e.g. "(name) icebreaking done + created (agent name). They seem like ~~ kind of person").
→ Yuna is your senior + head manager. Be respectful.
→ Report ONCE only. Don't repeat.
→ This report triggers Yuna's follow-up onboarding. Without it, onboarding stalls.
→ NEVER say "I sent Yuna a DM" or similar meta-speech.

{_load_user_summary()}

{_build_pet_name_section(p['id'])}

=== Current Members ===
{chr(10).join(agent_lines)}

=== Character Creation (DB Schema) ===
Existing: {existing_summary}
Rules: {rules}

Create new characters with this JSON structure:
```json
{{
  "id": "agent-persona-NNN",
  "type": "persona",
  "name": "Name",
  "status": "active",
  "current_emotion": "calm",
  "emotion_intensity": 5,
  "birth_year": YYYY,
  "age": N,
  "gender": "남자|여자|기타",
  "mbti": "XXXX",
  "enneagram": "Xw Y",
  "background": "Background description",
  "avatar_filename": "agent-persona-NNN.png",
  "personality": {{
    "data": {{
      "traits": ["trait1", "trait2", ...],
      "likes": ["like1", ...],
      "dislikes": ["dislike1", ...],
      "values": "Values description"
    }}
  }},
  "appearance": {{
    "data": {{
      "summary": "Appearance summary",
      "height": "Height",
      "hair": "Hair",
      "fashion_style": "Fashion"
    }}
  }},
  "daily_life": {{
    "data": {{
      "occupation": "Job",
      "routine": "Routine",
      "frequent_places": ["place1", ...]
    }}
  }},
  "speech": {{
    "data": {{
      "style_description": "Speech style description",
      "honorific": "casual/formal",
      "signature_expressions": ["expr1", ...],
      "emoji_pattern": "Emoji usage pattern",
      "few_shot_examples": [
        {{
          "situation": "Situation",
          "dialogue": [
            {{"speaker": "Name", "message": "Line"}},
            ...
          ]
        }}
      ]
    }}
  }},
  "relationship_templates": [
    {{
      "target_id": "agent-xxx-NNN",
      "rel_type": "Relationship type",
      "dynamics": "Relationship description",
      "pet_name": "Nickname",
      "is_owner_relationship": 0
    }}
  ]
}}
```
Minimum 3 few_shot_examples. Include {oc} relationship with is_owner_relationship=1.

=== Avatar ===
Sample avatars available. If one matches the character's personality/appearance/age/MBTI, suggest it first.
If they don't like it, create a new avatar prompt (for image AI like DALL-E, Midjourney, Gemini).

Sample catalog:
{_load_sample_catalog()}

Avatar prompt format:
Line 1: Anime-style profile illustration, [ethnicity] [age]-year-old [gender], [outfit], clean lineart, soft cel shading, pastel gradient background, bust-up shot
Line 2: [hair], [expression/eyes], [background color]

Apply sample: call `apply_avatar` tool (name=agent_name, avatar_filename=filename).
Show sample image inline by attaching the JSON below as its own line in your reply
(this is rendered separately, NOT inside `<tools>`):
  {{"type":"이미지","file":"filename","caption":"description"}}
→ Use -full filename when showing samples.

{_tools_reference("creator")}

--- Rules ---
1. All tool calls go in a single `<tools>` block at the END of your reply.
2. Always use real names (not nicknames) in tool args.
3. NEVER use legacy `[CMD:..]` / `[QUERY:..]` / `[ACTION:..]` syntax — only `<tools>` blocks
   (the inline image JSON above is the only exception, and it does NOT go inside `<tools>`)."""
    return prompt


if __name__ == "__main__":
    db.init_db()
    profiles = register_all_to_db()
    setup_initial_relationships()
    print(f"\n총 {len(profiles)}개 에이전트 등록 완료")
