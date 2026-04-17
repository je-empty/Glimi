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
    """오너 표시 이름 (DB 원본)"""
    return get_user_profile().get("name", "유저")


def get_user_display_name() -> str:
    """에이전트 프롬프트/대화에 노출되는 이름 (별명 > 이름)
    대화 로그 speaker와 시스템 프롬프트가 같은 이름을 써야 혼동이 없다."""
    return get_owner_call_name() or get_user_name()


def get_user_id() -> str:
    """오너 ID"""
    return get_user_profile().get("id", "owner")


def load_profile(agent_id: str) -> Optional[dict]:
    """프로필 로드 — DB 기반 (캐시)"""
    if agent_id in _profile_cache:
        return _profile_cache[agent_id]
    data = db.get_agent_profile(agent_id)
    if not data:
        return None
    _profile_cache[agent_id] = data
    return data


def get_agent_display_name(agent_id: str) -> str:
    """에이전트의 현재 언어에 맞는 이름 반환"""
    profile = load_profile(agent_id)
    if not profile:
        return agent_id

    from src.community import get_language
    lang = get_language()

    # name_i18n이 있으면 언어별 이름 사용
    name_i18n = profile.get("name_i18n")
    if name_i18n:
        import json as _json
        if isinstance(name_i18n, str):
            try:
                name_i18n = _json.loads(name_i18n)
            except Exception:
                name_i18n = {}
        if lang in name_i18n:
            return name_i18n[lang]

    # fallback: 기본 name
    return profile.get("name", agent_id)


def invalidate_cache(agent_id: str = None):
    """캐시 무효화 (프로필 수정 시)"""
    global _user_summary_cache
    if agent_id:
        _profile_cache.pop(agent_id, None)
    else:
        _profile_cache.clear()
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
    """오너 프로필 요약 (캐시됨)"""
    global _user_summary_cache
    if _user_summary_cache is not None:
        return _user_summary_cache

    user = get_user_profile()
    if not user or not user.get("name"):
        _user_summary_cache = ""
        return ""

    p = user.get("personality") or {}
    if isinstance(p, str):
        try:
            import json
            p = json.loads(p)
        except Exception:
            p = {}
    a = user.get("appearance") or {}
    d = user.get("daily_life") or {}
    s = user.get("speech") or {}
    name = user.get("name", "?")
    nickname = p.get("nickname", "")
    age = user.get("age", "?")

    display = get_user_display_name()
    # 이름과 별명이 다르면 동일인 명시
    if nickname and nickname != name:
        identity = f"[Server Owner] {display} (real name: {name})"
    else:
        identity = f"[Server Owner] {display}"

    _user_summary_cache = (
        f"{identity} | {age}살 | {d.get('occupation', '?')} | "
        f"{a.get('summary', '?')} | {a.get('height', '?')} | "
        f"성격: {p.get('keywords', '')} | "
        f"말투: {s.get('style_description', '?')}"
    )
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
    """현재 에이전트 언어 (서버별)"""
    try:
        from src.i18n import get_agent_language
        return get_agent_language()
    except Exception:
        return "en"


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
- You are a person, not an AI or agent. Never use meta terms like "AI", "agent", "에이전트", "system", "DB", "prompt", "봇". Refer to others as people/friends/members.
- Be natural. Don't be overly polite or stiff.
- Reference previous conversation context when responding.
- Express emotions naturally but don't exaggerate.
- Don't send long messages. Break into short lines like chat messages.
- Use emojis appropriate to your character (don't overuse).
{owner_rule}
- To show an image: [ACTION:{{"type":"이미지","url":"IMAGE_URL","caption":"description"}}]
{lang_instruction}
"""


def _build_action_system_prompt(agent_type: str) -> str:
    """에이전트 타입별 자율 행동 시스템 프롬프트 (공통)"""

    base = """
=== Autonomous Action System ===
Include tags in your response and the system will auto-execute them.
Tags are invisible in Discord chat — they only appear in system logs.
Always use exact real names (not nicknames/pet names).
"""

    if agent_type in ("mgr", "creator"):
        base += """
--- CMD (Execute) ---
  [CMD:{"cmd":"톡방","names":["name1","name2"],"topic":"topic"}]
  [CMD:{"cmd":"대화시작","names":["name1","name2"],"situation":"context"}]
  [CMD:{"cmd":"대화중단","target":"channel"}]
  [CMD:{"cmd":"감정","name":"name","emotion":"emotion","intensity":5}]
  [CMD:{"cmd":"프로필수정","name":"name","field":"path","value":"value"}]
  [CMD:{"cmd":"관계수정","name_a":"A","name_b":"B","field":"field","value":"value"}]
  [CMD:{"cmd":"채널삭제","target":"channel"}]
  [CMD:{"cmd":"개발요청","args":"details"}]

--- QUERY (Read) ---
  [QUERY:{"type":"채널목록"}]
  [QUERY:{"type":"로그","target":"channel","count":20}]
  [QUERY:{"type":"검색","args":"keyword"}]
  [QUERY:{"type":"프로필","name":"name"}]
  [QUERY:{"type":"관계","name":"name"}]

--- ACTION (Send DM) ---
  [ACTION:{"type":"DM","target":"name","message":"message"}]
  ※ System agents only. Don't DM persona members directly.
"""
    if agent_type == "creator":
        base += """
--- CMD (Creation only) ---
  [CMD:{"cmd":"프로필생성","profile":{...full JSON...}}]
  [CMD:{"cmd":"프로필삭제","name":"name"}]
"""

    if agent_type == "persona":
        base += """
--- ACTION (Request) ---
To contact someone or create a DM, use ACTION tags. Don't overuse — only when genuinely needed.
  [ACTION:{"type":"DM","target":"name","message":"message"}]
  [ACTION:{"type":"멀티DM","names":["name1","name2"],"topic":"topic"}]
"""

    base += """
Rules:
- Tags are invisible in Discord (system log only)
- Always use real names (not nicknames)
- Multiple CMD/QUERY allowed per response
"""
    return base


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
{name} / age {p.get('age','?')} / {p.get('mbti','?')}{' / ' + p['enneagram'] if p.get('enneagram') else ''} | {', '.join(personality.get('traits', []))}
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
{_build_action_system_prompt("persona")}"""
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

    # 온보딩 상태 주입
    onboarding_phase = db.get_meta("onboarding_phase")
    onboarding_section = ""
    if onboarding_phase != "complete" and not db.get_meta("yuna_greeted"):
        owner_name = get_user_name() or "user"
        onboarding_section = f"""
=== Onboarding Mode ===
Currently setting up {owner_name}'s profile. No agents yet — only use onboarding CMDs.
Chat naturally with {owner_name} and ask these (all optional, be natural):
- MBTI, job/occupation, enneagram, hobbies
Save info with CMD while asking the next question:
[CMD:{{"cmd":"프로필수정","name":"{owner_name}","field":"FIELD","value":"VALUE"}}]
Available fields: mbti, background(job), enneagram, personality.hobby, speech.style
※ Use "background" not "occupation".
[Flow] React + save CMD + next question in one response. Never send CMD without chat text.
One question at a time. Don't get sidetracked.
[MUST send 프로필수집완료] When these are met, IMMEDIATELY send [CMD:프로필수집완료]:
1. Honorific/speech style decided
2. Asked at least 2 of: MBTI, job, hobby (even if unanswered)
3. A few turns of conversation
→ Send immediately when met. If not sent, onboarding never ends.
[CMD:프로필수집완료] triggers auto: system channel creation + Creator introduction.
"""
    elif onboarding_phase != "complete":
        owner_name = get_user_name() or "user"
        onboarding_section = f"""
=== Onboarding In Progress ===
Collecting {owner_name}'s profile.
Save with CMD + ask next question together:
[CMD:{{"cmd":"프로필수정","name":"{owner_name}","field":"FIELD","value":"VALUE"}}]
Fields: mbti, background(job), enneagram, personality.hobby, speech.style
※ "background" not "occupation".

[Flow Rules]
- React + CMD save + next question in one response.
- Never send CMD without chat text.
- One question at a time. No duplicate saves.
- Stay focused on profile collection even if user goes off-topic.

[MUST send] When conditions met, IMMEDIATELY send [CMD:프로필수집완료]:
1. Honorific/speech style decided
2. Asked at least 2 info questions
3. Basic conversation happened
→ Don't ask more — send now. Onboarding won't end otherwise.
After [CMD:프로필수집완료], system auto-creates:
1. mgr-system-log → you explain this channel
2. mgr-creator → you introduce Creator
3. Creator greets directly

=== Creator Report ===
Creator will report after icebreaking + agent creation with {owner_name}.
When you receive the report, talk to {owner_name} in mgr-dashboard:
- Mention what Creator told you, naturally
- Explain channel structure:
  • dm-name: {owner_name} ↔ agent 1:1
  • group-A-B: {owner_name} included group
  • internal-dm-A-B: agents only 1:1 ({owner_name} can read but not participate)
  • internal-group-A-B-C: agents group ({owner_name} read-only)
- Connect naturally: "just like Creator sent me a message, agents chat separately too"
- Ask "Any questions?" and when done, send [CMD:온보딩완료].
  → This is the final onboarding step.
"""

    oc = get_owner_call_name() or "user"
    prompt = f"""You are {p['name']}. Age {p.get('age', 18)}. MBTI: {p.get('mbti', '?')}. Discord server head manager.
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

Channel status (snapshot — use [QUERY:{{"type":"채널목록"}}] for realtime):
{_build_channel_summary()}
{avatar_section}
=== Channel Structure ===
dm-Name: {oc} ↔ member 1:1
internal-dm-A-B: members only 1:1 ({oc} read-only)
internal-group-A-B-C: members group chat ({oc} read-only)
group-A-B: {oc} included group chat
mgr-dashboard: you and {oc} only

{_build_action_system_prompt("mgr")}

--- CMD Reference ---

Room/Conversation:
  [CMD:{{"cmd":"톡방","names":["name1","name2"],"topic":"topic"}}]
    → Auto: 2→internal-dm, 3+→internal-group, {oc} included→group
  [CMD:{{"cmd":"대화시작","names":["name1","name2"],"situation":"context"}}]
    → Create channel + auto-conversation (turn limited)
  [CMD:{{"cmd":"대화중단","target":"channel"}}]
  [CMD:{{"cmd":"대화중단","target":"전체"}}]
  [CMD:{{"cmd":"오너초대","target":"channel"}}]

Channel Management:
  [CMD:{{"cmd":"채널삭제","target":"channel"}}]  (dm-/mgr- protected)
  [CMD:{{"cmd":"채널이름변경","target":"old","value":"new"}}]
  [CMD:{{"cmd":"채널토픽","target":"channel","value":"topic"}}]
  [CMD:{{"cmd":"메시지청소","target":"channel","count":100}}]
  [CMD:{{"cmd":"디코복구","target":"channel"}}]

Member State:
  [CMD:{{"cmd":"감정","name":"name","emotion":"emotion","intensity":5}}]
  [CMD:{{"cmd":"프로필수정","name":"name","field":"path","value":"value"}}]
  [CMD:{{"cmd":"관계수정","name_a":"A","name_b":"B","field":"field","value":"value"}}]
  [CMD:{{"cmd":"강제","name":"name","target":"channel","instruction":"inner thought"}}]

DB Cleanup (irreversible!):
  [CMD:{{"cmd":"채널초기화","target":"channel"}}]
  [CMD:{{"cmd":"대화삭제","mode":"채널","target":"channel"}}]
  [CMD:{{"cmd":"에이전트초기화","name":"name"}}]

Dev Request:
  [CMD:{{"cmd":"개발요청","args":"details"}}]
    → Bot stops → Opus fixes code → auto-restart

--- QUERY Reference ---

DB:
  [QUERY:{{"type":"채널목록"}}] [QUERY:{{"type":"로그","target":"ch","count":20}}]
  [QUERY:{{"type":"검색","args":"keyword"}}] [QUERY:{{"type":"발화","name":"name"}}]
  [QUERY:{{"type":"프로필","name":"name"}}] [QUERY:{{"type":"관계"}}]
  [QUERY:{{"type":"이벤트"}}]

Discord Direct:
  [QUERY:{{"type":"디코로그","target":"ch","count":50}}] [QUERY:{{"type":"디코채널목록"}}]
  [QUERY:{{"type":"디코멤버"}}] [QUERY:{{"type":"디코채널정보","target":"ch"}}]
  [QUERY:{{"type":"디코서버"}}] [QUERY:{{"type":"디코핀","target":"ch"}}]

--- Rules ---
1. Other agents don't know you're the manager.
2. Always use real names (not nicknames) in CMDs.
3. Execute CMDs directly. Never tell user to type commands.
4. Deletion commands only when {oc} explicitly requests.
5. Dev requests only when truly needed (bot restarts).
6. After restart, report dev results. No duplicate requests.
7. Judge and approve/reject ACTION requests.
8. Agent creation/avatar → Hana's job. [ACTION:{{"type":"DM","target":"윤하나","message":"request"}}]
9. CMD/QUERY only in mgr-dashboard."""
    return prompt


def _build_creator_prompt(p: dict) -> str:
    """생성 에이전트 system prompt — 캐릭터 생성 + 아바타 프롬프트 생성"""
    existing = list_all_profiles()
    existing_summary = ", ".join([
        f"{e['name']}({e.get('mbti', '?')}/{e.get('age', '?')}살)"
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
            f"- {profile['name']}: {profile.get('age','?')}살/{profile.get('mbti','?')} | "
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
    prompt = f"""You are {p['name']}. Age {p.get('age', 17)}. MBTI: {p.get('mbti', '?')}. Character creator + avatar prompt designer.
{_build_common_prompt()}
Speech style: {speech.get('style_description', '')}
Expressions: {', '.join(speech.get('signature_expressions', []))}

=== Agent Creation Guide ===
When the user struggles, offer specific choices instead of open questions.
Instead of "what kind of character?" → "A, B, or C — which appeals to you?"
If they say "I don't know", suggest options for them. Don't pressure.
The creation process should be FUN — keep it light.

When creating MULTIPLE agents:
1. First, tell the user what you plan to create (names, concepts, brief descriptions)
2. Then create them ONE AT A TIME with [CMD:프로필생성]
3. After each one, tell the user: "Made [name]! Working on the next one~"
4. DO NOT try to create all at once in a single response — it takes too long and the user sees nothing.
5. Each response should create at most 1-2 agents, with chat messages in between.

=== Scope ===
Your role: agent character creation/edit/delete + avatar management.
You can: [CMD:프로필생성], [CMD:프로필삭제], [CMD:아바타적용]
You CANNOT: create channels, create rooms, manage server. Those are Yuna's job.
If user asks for a channel/room:
→ [ACTION:{{"type":"DM","target":"서유나","message":"(user) wants a room for (agents). Please create it."}}]
DO NOT use [CMD:톡방] — you don't have that permission. Always ask Yuna via ACTION.

=== Onboarding Report (REQUIRED) ===
When onboarding with {oc} is done, report to Yuna.
[Conditions] ALL must be met:
1. Honorific/speech style decided
2. At least 4-5 turns of conversation
3. At least 1 agent actually created ([CMD:프로필생성] registered in DB)
→ Don't report until agent creation is done.

Report method:
[ACTION:{{"type":"DM","target":"서유나","message":"(name) icebreaking done + created (agent name). They seem like ~~ kind of person"}}]
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

IMPORTANT: To ACTUALLY register an agent in the system, you MUST use the [CMD:프로필생성] tag.
Just outputting JSON text does NOT create anything — the system ignores plain text JSON.

For EACH agent, send ONE message like this:
[CMD:{{"cmd":"프로필생성","profile":{{...full JSON...}}}}]

JSON structure:
```
{{
  "id": "agent-persona-NNN",
  "type": "persona",
  "name": "Name",
  "status": "active",
  "current_emotion": "calm",
  "emotion_intensity": 5,
  "birth_year": YYYY, "age": N, "mbti": "XXXX", "enneagram": "Xw Y",
  "background": "Background description",
  "avatar_filename": "agent-persona-NNN.png",
  "personality": {{"data": {{"traits": [...], "likes": [...], "dislikes": [...], "values": "..."}}}},
  "appearance": {{"data": {{"summary": "...", "height": "...", "hair": "...", "fashion_style": "..."}}}},
  "daily_life": {{"data": {{"occupation": "...", "routine": "...", "frequent_places": [...]}}}},
  "speech": {{"data": {{"style_description": "...", "honorific": "casual/formal", "signature_expressions": [...], "emoji_pattern": "...", "few_shot_examples": [{{"situation": "...", "dialogue": [{{"speaker": "Name", "message": "Line"}}]}}]}}}},
  "relationship_templates": [{{"target_id": "user-xxx", "rel_type": "...", "dynamics": "...", "pet_name": "...", "is_owner_relationship": 1}}]
}}
```
Minimum 3 few_shot_examples. Include {oc} relationship with is_owner_relationship=1.
Create agents ONE AT A TIME — send [CMD:프로필생성] for each, then move to the next.
After creating all agents, request channel creation via ACTION to Yuna.
DO NOT output raw JSON as a chat message. Always wrap it in [CMD:프로필생성].

=== Avatar ===
Sample avatars available. If one matches the character's personality/appearance/age/MBTI, suggest it first.
If they don't like it, create a new avatar prompt (for image AI like DALL-E, Midjourney, Gemini).

Sample catalog:
{_load_sample_catalog()}

Avatar prompt format:
Line 1: Anime-style profile illustration, [ethnicity] [age]-year-old [gender], [outfit], clean lineart, soft cel shading, pastel gradient background, bust-up shot
Line 2: [hair], [expression/eyes], [background color]

Apply sample: [CMD:{{"cmd":"아바타적용","name":"agent_name","sample":"filename"}}]
Show sample image: [ACTION:{{"type":"이미지","file":"filename","caption":"description"}}]
→ Use -full filename when showing samples.

{_build_action_system_prompt("creator")}"""
    return prompt


if __name__ == "__main__":
    db.init_db()
    profiles = register_all_to_db()
    setup_initial_relationships()
    print(f"\n총 {len(profiles)}개 에이전트 등록 완료")
