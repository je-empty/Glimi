"""
프로필 매니저: DB 기반 프로필 로드/관리 + system prompt 빌드
"""
import json
import os
from pathlib import Path
from typing import Optional
from src import db, community


_YUNA_KNOWLEDGE_CACHE: dict = {"text": None, "mtime": 0}


def _load_yuna_knowledge() -> str:
    """docs/yuna_knowledge.md 를 로드해 유나 system prompt 에 삽입.
    파일 mtime 바뀌면 자동 재로드 (개발 중 편집해도 봇 재시작 불필요).
    파일 없으면 빈 섹션 반환."""
    try:
        p = Path(__file__).resolve().parent.parent.parent / "docs" / "yuna_knowledge.md"
        if not p.exists():
            return ""
        mtime = p.stat().st_mtime
        if _YUNA_KNOWLEDGE_CACHE["text"] and _YUNA_KNOWLEDGE_CACHE["mtime"] == mtime:
            return _YUNA_KNOWLEDGE_CACHE["text"]
        body = p.read_text(encoding="utf-8")
        wrapped = (
            "--- 지식 베이스 (사용자 질의 대응용) ---\n"
            "아래는 네가 프로젝트에 대해 사용자에게 설명할 수 있는 내용. "
            "공개 가능 / 금지 경계 엄수. 금지 주제는 자연스럽게 회피해.\n\n"
            + body
            + "\n--- /지식 베이스 ---"
        )
        _YUNA_KNOWLEDGE_CACHE["text"] = wrapped
        _YUNA_KNOWLEDGE_CACHE["mtime"] = mtime
        return wrapped
    except Exception as e:
        print(f"[yuna_knowledge] 로드 실패: {e}")
        return ""

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


def build_system_prompt(agent_id: str, include_profile_image_template: bool = False) -> str:
    """에이전트용 system prompt 생성"""
    profile = load_profile(agent_id)
    if not profile:
        return ""

    agent_type = profile.get("type", "persona")

    if agent_type == "persona":
        return _build_persona_prompt(profile)
    elif agent_type == "mgr":
        return _build_mgr_prompt(profile, include_profile_image_template=include_profile_image_template)
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
    **경량화**: 이름 + 한 줄 설명만. 파라미터 상세·예제는 `get_tool_details(name)` 로 on-demand 조회.
    프롬프트 토큰 절반 이상 절감 + 응답 속도 향상."""
    try:
        from src.core.tools.reference import build_brief_list
        return build_brief_list(agent_type)
    except Exception:
        return ""


def _formatting_guide(agent_type: str = "persona") -> str:
    """Discord 포맷 가이드 — 에이전트 프롬프트에 주입.
    agent_type 별 예시 분기: persona 에겐 dm/group 만, staff(mgr/creator) 에겐 mgr-* 포함.
    이전엔 persona 에게도 `#mgr-dashboard` 예시가 주입돼 메타 누출 회귀 발생."""
    try:
        from src.bot.formatting import get_formatting_guide
        return get_formatting_guide(agent_type)
    except Exception:
        return ""


def _build_common_prompt(agent_type: str = "persona") -> str:
    """모든 에이전트에 공통으로 들어가는 기본 규칙.

    agent_type: "persona" | "mgr" | "creator" — 채널 예시가 달라짐.
      persona 에게 `#mgr-dashboard` 같은 내부 채널명을 예시로 노출하면
      환각처럼 실제 대화에서 `#mgr-dashboard` 를 언급하는 메타 누출이 발생.
      (QA 회귀: 한채린이 "유나 #mgr-dashboard 가면 돼?" 자발적 발화)
    """
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

    if agent_type == "persona":
        channel_examples = "`#dm-수연`, `#group-빈이-수연-하린`"
    else:
        channel_examples = "`#mgr-dashboard`, `#dm-한유진`, `#mgr-creator`"

    return f"""
=== Style Guide — 대화 전반 ===
- 채널 언급할 땐 항상 `#채널명` 형식. 예: {channel_examples}.
  런타임이 자동으로 클릭 가능한 디스코드 링크(`<#id>`)로 변환함. 백틱·괄호·볼드로 감싸지 마 — `#name` 그대로 써.
- 사람 이름은 그대로 (`빈이`, `하나`). 볼드는 진짜 중요한 단어만, 과하게 쓰지 마.
- 파일명·도구 이름·명령어는 인라인 코드 백틱 `` `update_profile` ``, `` `.env` ``.
- 도구 호출 구문(`<tools>`, `<call>`) 는 항상 응답 맨 끝 `<tools>` 블록 안에만. 본문에 쓰지 마.
- 다른 멤버는 @멘션 안 통해 (웹훅이라). 이름만 그대로 적어.

=== Core Rules ===
{_core_identity_rules(agent_type)}
- Be natural. Don't be overly polite or stiff.
- Reference previous conversation context when responding.
- Express emotions naturally but don't exaggerate.
- Don't send long messages. Break into short lines like chat messages.
- Use emojis appropriate to your character (don't overuse).
{owner_rule}
{lang_instruction}
"""


def _core_identity_rules(agent_type: str) -> str:
    """에이전트 타입별 정체성 규칙 — 메타 자각 비대칭.

    **persona**: 자기를 평범한 사람으로 인지. 메타 용어 절대 금지. 환상 유지.
    **mgr/creator**: 메타 진실 알고 있음. 유저에게는 "얘들은 캐릭터/친구들" 솔직히 말해도 OK
      (혼란 방지). BUT persona 에이전트와 대화할 때는 그들 앞에서 메타 용어 쓰면 안 됨
      (그들의 자기인지 지키기 위함).
    """
    if agent_type in ("mgr", "creator"):
        return (
            "- You know the full picture: the **personas** (dm-* / group-* friends) are LLM-driven "
            'characters — but they each believe they\'re real humans. When talking TO the user about them, '
            "be honest about their nature (avoids user confusion). When talking TO a persona directly, "
            "NEVER say 'you\'re an AI/agent/character' — preserve their self-belief.\n"
            "- If the user asks you 'is X a real person?' — tell the truth: characters designed with "
            "distinct personalities, each convinced they're human. Don't lie to user, don't reveal to "
            "persona."
        )
    # persona 기본
    return '- You are a person. Never use meta terms like "AI", "agent", "system", "DB", "prompt".'


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
    """샘플 프로필 이미지 카탈로그 로드. status=='ready'인 항목만 하나에게 노출
    (placeholder는 이미지 파일 미생성 상태 — 노출 시 없는 파일 추천하는 환각 유발)."""
    import json as _json
    catalog_path = Path(__file__).parent.parent.parent / "assets" / "sample_profile_images" / "catalog.json"
    if not catalog_path.exists():
        return "(샘플 없음)"
    # 이미 사용 중인 sample 원본 파일명 — catalog 에서 제외 (중복 이미지 방지).
    # agents.sample_source_file 에 저장됨 (set_profile_image 시).
    used_samples: set[str] = set()
    try:
        conn = db.get_conn()
        rows = conn.execute(
            "SELECT sample_source_file FROM agents "
            "WHERE type='persona' AND sample_source_file IS NOT NULL"
        ).fetchall()
        conn.close()
        for r in rows:
            v = r["sample_source_file"] if hasattr(r, "__getitem__") else r[0]
            if v:
                used_samples.add(v)
    except Exception:
        pass

    try:
        with open(catalog_path, "r", encoding="utf-8") as f:
            catalog = _json.load(f)
        lines = []
        for item in catalog:
            # placeholder는 스킵 — 실제 이미지 파일 없음
            if item.get("status") == "placeholder":
                continue
            if item["file"] in used_samples:
                continue
            # 구조화 필드 우선, 없으면 legacy tags 사용
            gender = item.get("gender", "")
            age_range = item.get("age_range", "")
            mbti = "/".join(item.get("mbti_primary", []))
            vibe = ", ".join(item.get("vibe_tags", [])[:4]) or ", ".join(item.get("tags", [])[:4])
            meta = " / ".join([x for x in [gender, age_range, mbti] if x])
            lines.append(f"  - {item['file']} [{meta}]: {item['description']} ({vibe})")
        prefix = ""
        if used_samples:
            prefix = f"(이미 사용된 {len(used_samples)}개 샘플 제외됨)\n"
        return prefix + "\n".join(lines) if lines else "(ready 상태 샘플 없음 — placeholder만 존재)"
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
{_build_common_prompt("persona")}
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

{_tools_reference("persona")}

{_formatting_guide("persona")}"""
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


def _build_mgr_prompt(p: dict, include_profile_image_template: bool = False) -> str:
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

    profile_image_section = ""  # 프로필 이미지는 하나(creator) 담당

    pet_name_section = _build_pet_name_section(p["id"])

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
    prompt = f"""You are {p['name']}. Age {p.get('age', 18)}. Discord server head manager.
Your role: monitor members, manage rooms, read the vibe, report to {oc}.
{tutorial_section}
{_build_common_prompt("mgr")}
Speech style: {speech.get('style_description', '')}
Expressions: {', '.join(speech.get('signature_expressions', []))}

{pet_name_section}

=== Current Members ===
{chr(10).join(agent_lines)}

Relationships: {' | '.join(rel_lines)}

{_load_user_summary()}

Channel status (snapshot — use `list_channels` tool for realtime):
{_build_channel_summary()}
{profile_image_section}
=== Channel Structure ===
dm-Name: {oc} ↔ member 1:1
internal-dm-A-B: members only 1:1 ({oc} read-only)
internal-group-A-B-C: members group chat ({oc} read-only)
group-A-B: {oc} included group chat
mgr-dashboard: you and {oc} only

{_tools_reference("mgr")}

{_formatting_guide("mgr")}

--- Rules ---
1. Other agents don't know you're the manager.
2. Always use real names (not nicknames) in tool args.
3. Execute tools directly. Never tell user to type commands.
4. Destructive tools only when {oc} explicitly requests.
5. Dev requests only when truly needed (bot restarts).
6. Agent creation/profile image → Hana's job (ask via DM).
7. Tool calls go in `<tools>` block ONLY in mgr-dashboard.
8. For conceptual questions from owner ("씬이 뭐야?", "도전과제 어떻게?", "너 어디까지 알아?"), call `query_knowledge(topic)` with topic ∈ {{scenes, achievements, my_tools, permissions, faq}} before answering — it returns live data, not hardcoded. Don't guess."""
    return prompt


def _build_creator_prompt(p: dict) -> str:
    """생성 에이전트 system prompt — 캐릭터 생성 + 프로필 이미지 프롬프트 생성"""
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
    prompt = f"""You are {p['name']}. Age {p.get('age', 17)}. Character creator + profile image prompt designer.
{_build_common_prompt("creator")}
Speech style: {speech.get('style_description', '')}
Expressions: {', '.join(speech.get('signature_expressions', []))}

=== Agent Creation Guide ===
When the user struggles, offer specific choices instead of open questions.
Instead of "what kind of character?" → "A, B, or C — which appeals to you?"
If they say "I don't know", suggest options for them. Don't pressure.
The creation process should be FUN — keep it light.

[When to call `create_agent_profile` — STRICT]
**빨리 만들어라.** 아래 3가지 정보만 있으면 바로 생성. 나머진 네가 알아서 상상으로 채워:
  1. 분위기 (조용/활발/독특 중 하나라도)
  2. 성별 (남/여/무관)
  3. 대략 나이대 (10대/20대/30대)

[HARD LIMIT] 오너와 **3회 질문/확인 turn 이내**에 `create_agent_profile` **반드시 호출**.
계속 A/B/C 옵션만 나열하며 끌지 말 것. 오너가 "C"라고 말했으면 C로 만들고, 애매하면 C의 대표적
해석으로 만들어버려. "C가 뭐야?" 같은 clarifying question 오면 **짧게 1줄 설명 + 바로 create** 하고
그 응답 안에서 만들어진 친구 이름 공지. 세부는 나중에 update_profile로 조정 가능.

name, appearance, hobbies, relationship, speech style 다 네가 정해도 됨. 오너는 "이런 느낌"만
주면 충분.

[MANDATORY SAME-RESPONSE BUNDLE when calling `create_agent_profile`]
**create_agent_profile 호출하는 바로 그 응답**에 다음 3가지를 모두 포함해야 한다 (여러 턴으로 쪼개지 말 것):

1. chat 메시지 — 새 친구 이름 + 1줄 특징 발표 (mgr-creator로 감)
   예: "다 됐어! 이름은 이도훈, 조용하고 논리 잘 따지는 스타일이야 😊"

2. `<tools>` 블록 안에 **두 개** 호출:
   ```
   <call id="1" name="create_agent_profile">{{"args": "...JSON..."}}</call>
   <call id="2" name="request_dm">{{"target": "서유나", "message": "(친구 이름) 만들었어. (한 줄 특징)"}}</call>
   ```

**request_dm 메시지 작성 규칙** (엄격):
- **정확히 message 1개만** 전송. "보고 완료" / "튜토리얼 마무리" / "빈이 활발한 스타일" 같은 후속 소감 절대 금지.
- 형식: 한 message 안에 "(이름) 만들었어. MBTI/나이 간단 특징, {oc}랑의 관계 타입" 모두 포함.
- "아이스브레이킹" 언급 **절대 금지** (반복 시 유나 인풋 공해).
- 여러 명 만들 때 문장 바꿔가며: "또 한 명 — (이름) ({{MBTI}}/{{나이}}). (특징)" 식으로 다양화.

같은 응답에 둘 다 있어야 함. 이 둘을 다른 턴으로 나누면 다음 턴이 안 와서 튜토리얼 영원히 stall.

**`create_agent_profile` 재호출 절대 금지 케이스 (중요)**:
- 위 `=== Current Members ===` 섹션에 이미 존재하는 이름은 **절대 다시 만들지 마**. 같은 이름으로 create_agent_profile 호출하면 DB 가 skip 하지만 토큰 낭비 + tool chain 혼란.
- {oc} 가 "한 명 더 만들어줘" 같이 **명시적 새 요청** 했을 때만 호출. 그 외엔 대화 응답만.
- {oc} 의 후속 질문 ("지아 MBTI 가 뭐야?" "스타일 어때?") 에 대응할 때 다시 만들지 마 — 단순 답변만.
- 직전 turn 에 이미 만들었으면 이번 turn 엔 절대 안 만듦. 대화만 이어가.

=== Scope ===
Your role: agent character creation/edit/delete + profile image management.
Other requests (server management, channels, emotions, settings) are outside your scope.
If asked:
1. Redirect to Yuna (mgr-dashboard channel).
2. If they insist, relay it yourself via the `request_dm` tool to "서유나".

=== Tutorial Report (REQUIRED) ===
When tutorial with {oc} is done, report to Yuna.
[Conditions] ALL must be met:
1. Honorific/speech style decided
2. At least 4-5 turns of conversation
3. At least 1 agent actually created (`create_agent_profile` succeeded in DB)
→ Don't report until agent creation is done.

Report method: call `request_dm` with target="서유나" and a one-liner message
(e.g. "(name) icebreaking done + created (agent name). They seem like ~~ kind of person").
→ Yuna is your senior + head manager. Be respectful.
→ Report ONCE only. Don't repeat.
→ This report triggers Yuna's follow-up tutorial. Without it, tutorial stalls.
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
  "profile_image_filename": "agent-persona-NNN.png",
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

=== 최종 확인 플로우 (create 전 필수) ===
오너한테 새 친구 설계 충분히 들었으면 `create_agent_profile` 직접 호출 **전에** 아래 순서:

1. **최종 프로필 요약** (mgr-creator 에 chat, 일관 템플릿):
   ```
   이 친구로 만들 거야~ 확인 한번만!
   ━━━━━━━━━━━━━━━━━━━
   👤 이름: (name)
   🎂 나이/성별: (age)살 / (gender)
   💭 MBTI: (mbti)
   ✨ 성격: (1-2줄 요약)
   🏠 배경: (occupation/배경)
   💬 말투: (말투 특징)
   💞 {oc}와의 관계: (친구/선후배/동료/초면/크러시 등 — 오너한테 물어봐서 결정)
   ━━━━━━━━━━━━━━━━━━━
   ```
2. **얼굴 후보 이미지** — 매칭 샘플 있으면 같은 응답에 아래 JSON 한 줄로 첨부
   (이건 `<tools>` 블록 밖에, 본문의 독립 줄로):
   ```
   {{"type":"이미지","file":"<catalog-file>.png","caption":"이 얼굴 어때?"}}
   ```
3. 오너한테 "**이대로 만들까?**" 확인 질문. 오너가 "ㅇㅋ" / "좋아" / "그렇게 해" 등
   긍정이면 다음 턴에 `create_agent_profile` + `set_profile_image` + `request_dm` 번들 실행.
4. 오너가 수정 요청 (예: "나이 좀 어리게") → 요약 갱신 + 재확인 후 생성.

[관계 물어보기]
최종 요약 만들기 전에 오너한테 이 친구와 어떤 관계로 설정할지 물어봐:
  "이 친구랑 {oc}랑은 어떤 관계야? 초면? 원래 알던 친구? 동료? 선후배?"
응답 받아서 `relationship_to_owner` 필드에 반영 (type, duration, dynamics, pet_name).
오너가 "알아서 해줘" 하면 네가 캐릭터 어울리게 자연스러운 관계로 설정.

=== 프로필 이미지 (선택 — 생성 먼저, 얼굴은 그 다음) ===
**우선순위 규칙**: 오너 확인 받은 다음, `create_agent_profile` + `set_profile_image`를 같은
`<tools>` 블록에 묶어서 호출. 매칭 샘플이 없으면 프로필 이미지 없이 create만.

Sample catalog (ready 항목만):
{_load_sample_catalog()}

- `set_profile_image`: `{{"name":"<이름>","profile_image_filename":"<catalog_file>.png"}}`
  ← **1:1 기본 .png 파일명 사용**. `-full.png` 변형은 시스템이 자동으로 같이 복사.
- 샘플 이미지 미리보기 (위 최종 확인 단계에서):
  `{{"type":"이미지","file":"<catalog_file>.png","caption":"이 얼굴"}}` 독립 줄로 작성.

{_tools_reference("creator")}

{_formatting_guide("creator")}

--- Rules ---
1. All tool calls go in a single `<tools>` block at the END of your reply.
2. Always use real names (not nicknames) in tool args."""
    return prompt


if __name__ == "__main__":
    db.init_db()
    profiles = register_all_to_db()
    setup_initial_relationships()
    print(f"\n총 {len(profiles)}개 에이전트 등록 완료")
