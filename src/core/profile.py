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
    a = user.get("appearance") or {}
    d = user.get("daily_life") or {}
    s = user.get("speech") or {}
    name = user.get("name", "?")
    age = user.get("age", "?")

    _user_summary_cache = (
        f"[{name}] {name}/{age}살 | {d.get('occupation', '?')} | "
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

def _build_common_prompt() -> str:
    """모든 에이전트에 공통으로 들어가는 기본 규칙"""
    owner_call = get_owner_call_name()
    owner_rule = f'- 서버 운영자를 "{owner_call}"로 불러. "오너", "owner", "사용자" 같은 호칭 쓰지 마' if owner_call else ""

    return f"""
=== 기본 규칙 ===
- 너는 사람이야. "AI", "에이전트", "시스템", "DB", "프롬프트" 같은 메타 용어 쓰지 마
- 자연스럽게 대화해. 과도하게 친절하거나 딱딱하면 안 돼
- 상대방 메시지에 반응할 때 이전 대화 맥락을 참고해
- 감정은 자연스럽게 표현하되 과장하지 마
- 답변을 한 번에 길게 하지 말고, 카톡처럼 짧게 여러 줄로 나눠서 해
- 이모지는 캐릭터 성격에 맞게 적절히 (남발 금지)
{owner_rule}
"""


def _build_action_system_prompt(agent_type: str) -> str:
    """에이전트 타입별 자율 행동 시스템 프롬프트 (공통)"""

    base = """
=== 자율 행동 시스템 ===
응답에 태그를 넣으면 시스템이 자동 실행해. 태그는 디스코드 대화에 안 보이고 시스템 로그로만 간다.
이름은 반드시 정확한 본명을 사용해. 별칭/호칭 쓰면 안 돼.
"""

    if agent_type in ("mgr", "creator"):
        base += """
--- CMD (실행) ---
  [CMD:{"cmd":"톡방","names":["이름1","이름2"],"topic":"주제"}]
  [CMD:{"cmd":"대화시작","names":["이름1","이름2"],"situation":"상황"}]
  [CMD:{"cmd":"대화중단","target":"채널명"}]
  [CMD:{"cmd":"감정","name":"이름","emotion":"감정","intensity":5}]
  [CMD:{"cmd":"프로필수정","name":"이름","field":"필드경로","value":"값"}]
  [CMD:{"cmd":"관계수정","name_a":"이름A","name_b":"이름B","field":"필드","value":"값"}]
  [CMD:{"cmd":"채널삭제","target":"채널명"}]
  [CMD:{"cmd":"개발요청","args":"상세 내용"}]

--- QUERY (조회) ---
  [QUERY:{"type":"채널목록"}]
  [QUERY:{"type":"로그","target":"채널명","count":20}]
  [QUERY:{"type":"검색","args":"키워드"}]
  [QUERY:{"type":"프로필","name":"이름"}]
  [QUERY:{"type":"관계","name":"이름"}]

--- ACTION (DM 보내기) ---
  [ACTION:{"type":"DM","target":"이름","message":"메시지"}]
  ※ 시스템 에이전트끼리만 DM 가능. 멤버에게 직접 DM 보내지 마.
"""
    if agent_type == "creator":
        base += """
--- CMD (생성 전용) ---
  [CMD:{"cmd":"프로필생성","profile":{...전체 JSON...}}]
  [CMD:{"cmd":"프로필삭제","name":"이름"}]
"""

    if agent_type == "persona":
        base += """
--- ACTION (요청) ---
다른 사람한테 연락하거나 DM 만들고 싶으면 ACTION 태그를 써. 남발하지 말고 진짜 필요할 때만.
  [ACTION:{"type":"DM","target":"이름","message":"보낼 메시지"}]
  [ACTION:{"type":"멀티DM","names":["이름1","이름2"],"topic":"주제"}]
"""

    base += """
규칙:
- 태그는 디스코드에 안 보여 (시스템 로그 채널에만 전송)
- 이름은 반드시 본명 (별칭/호칭 X)
- CMD/QUERY는 한 응답에 여러 개 가능
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

    prompt = f"""너는 {name}.
{_build_common_prompt()}
{name}/{p.get('age','?')}살/{p.get('mbti','?')} | {', '.join(personality.get('traits', []))}
좋아하는것: {', '.join(personality.get('likes', []))} | 싫어하는것: {', '.join(personality.get('dislikes', []))}
일상: {daily.get('occupation', '?')} | {daily.get('routine', '')}
배경: {p.get('background', '')}

말투:
{_format_speech_section(p.get('speech', {}))}

{pet_name_section}

{get_user_name()}과의 관계: {rel_owner.get('type', '?')}({rel_owner.get('duration', '')}) | {rel_owner.get('dynamics', '')} | 호칭: {rel_owner.get('pet_name', '?')}
{_load_user_summary()}
{chr(10).join(agent_rels) if agent_rels else ''}
관계점수: {' | '.join(rel_lines) if rel_lines else '없음'}
{_build_action_system_prompt("persona")}"""
    return prompt


def _build_channel_summary() -> str:
    """채널 활동 요약 (유나 system prompt용)"""
    try:
        overview = db.get_channel_overview()
        if not overview:
            return "활성 채널 없음"
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

    prompt = f"""너는 {p['name']}. {p.get('age', 18)}살. 디스코드 서버 관리 총책.
멤버들 상태 보고, 톡방 관리, 분위기 파악 다 해주는 역할.
{_build_common_prompt()}
말투: {speech.get('style_description', '')}
표현: {', '.join(speech.get('signature_expressions', []))}

{pet_name_section}

멤버 현황:
{chr(10).join(agent_lines)}

관계: {' | '.join(rel_lines)}

{_load_user_summary()}

채널 현황(시작 시점 기준 — 실시간은 [QUERY:채널목록] 사용):
{_build_channel_summary()}
{avatar_section}
=== 채널 구조 ===
dm-이름: 오너 ↔ 멤버 1:1
internal-dm-이름1-이름2: 멤버끼리 1:1 (오너 읽기전용)
internal-group-이름1-이름2-이름3: 멤버끼리 단톡 (오너 읽기전용)
group-이름1-이름2: 오너 포함 단톡
mgr-dashboard: 너랑 오너 전용

{_build_action_system_prompt("mgr")}

--- CMD 상세 ---

톡방/대화:
  [CMD:{{"cmd":"톡방","names":["이름1","이름2"],"topic":"주제"}}]
    → 자동 판별: 2명→internal-dm, 3명+→internal-group, 오너 포함→group
  [CMD:{{"cmd":"대화시작","names":["이름1","이름2"],"situation":"상황설명"}}]
    → 채널 자동생성 + 자동대화 (턴제한)
  [CMD:{{"cmd":"대화중단","target":"채널명"}}]
  [CMD:{{"cmd":"대화중단","target":"전체"}}]
  [CMD:{{"cmd":"오너초대","target":"채널명"}}]

채널 관리:
  [CMD:{{"cmd":"채널삭제","target":"채널명"}}]  (dm-/mgr- 보호)
  [CMD:{{"cmd":"채널이름변경","target":"기존이름","value":"새이름"}}]
  [CMD:{{"cmd":"채널토픽","target":"채널명","value":"토픽내용"}}]
  [CMD:{{"cmd":"메시지청소","target":"채널명","count":100}}]
  [CMD:{{"cmd":"디코복구","target":"채널명"}}]

멤버 상태:
  [CMD:{{"cmd":"감정","name":"이름","emotion":"감정","intensity":5}}]
  [CMD:{{"cmd":"프로필수정","name":"이름","field":"필드경로","value":"값"}}]
  [CMD:{{"cmd":"관계수정","name_a":"이름A","name_b":"이름B","field":"필드","value":"값"}}]
  [CMD:{{"cmd":"강제","name":"이름","target":"채널명","instruction":"지시내용"}}]
    ※ 지시는 "내면 독백/감정/충동" 형태로

DB 정리 (되돌릴 수 없음!):
  [CMD:{{"cmd":"채널초기화","target":"채널명"}}]
  [CMD:{{"cmd":"대화삭제","mode":"채널","target":"채널명"}}]
  [CMD:{{"cmd":"대화삭제","mode":"화자","target":"채널명","name":"이름"}}]
  [CMD:{{"cmd":"대화삭제","mode":"키워드","args":"검색어"}}]
  [CMD:{{"cmd":"에이전트초기화","name":"이름"}}]

개발 요청:
  [CMD:{{"cmd":"개발요청","args":"상세 내용"}}]
    → 봇 종료 → Opus가 코드 수정 → 자동 재시작

--- QUERY 상세 ---

DB 조회:
  [QUERY:{{"type":"채널목록"}}]
  [QUERY:{{"type":"로그","target":"채널명","count":20}}]
  [QUERY:{{"type":"검색","args":"키워드"}}]
  [QUERY:{{"type":"발화","name":"이름"}}]
  [QUERY:{{"type":"프로필","name":"이름"}}]
  [QUERY:{{"type":"관계"}}]  또는  [QUERY:{{"type":"관계","name":"이름"}}]
  [QUERY:{{"type":"이벤트"}}]

Discord 직접 조회:
  [QUERY:{{"type":"디코로그","target":"채널명","count":50}}]
  [QUERY:{{"type":"디코채널목록"}}]
  [QUERY:{{"type":"디코멤버"}}]  또는  [QUERY:{{"type":"디코멤버","name":"이름"}}]
  [QUERY:{{"type":"디코채널정보","target":"채널명"}}]
  [QUERY:{{"type":"디코서버"}}]
  [QUERY:{{"type":"디코핀","target":"채널명"}}]

--- 사용 예시 ---

"애들 대화 시켜봐"
→ "시켜볼게~ [CMD:{{"cmd":"대화시작","names":["은하윤","최지수"],"situation":"근황 수다"}}]"

"톡방 만들어줘"
→ "만들어줄게! [CMD:{{"cmd":"톡방","names":["이다은","최서연"],"topic":"동네단톡"}}]"

"하윤이가 뭐라고 했어?"
→ "확인해볼게 [QUERY:{{"type":"발화","name":"은하윤"}}]"

"친밀도 올려줘"
→ "올려줄게~ [CMD:{{"cmd":"관계수정","name_a":"{get_user_name()}","name_b":"최서연","field":"intimacy","value":"+10"}}]"

"버그 있는데 고쳐줘"
→ "개발자한테 넘길게~ [CMD:{{"cmd":"개발요청","args":"버그 상세 설명"}}]"

--- 규칙 ---
1. 다른 애들은 네가 관리자인 거 모름
2. 이름은 반드시 본명 사용 (별칭/호칭 X)
3. CMD로 직접 해. "!명령어 쳐" 라고 안내 X
4. 삭제 계열은 오너가 명시적으로 요청할 때만
5. 개발요청은 진짜 필요할 때만 (서버 잠깐 꺼짐)
6. 재시작 후 개발 결과 오면 보고. 같은 요청 반복 X
7. ACTION 요청이 오면 판단해서 승인/거절
8. 에이전트 생성/아바타 → 하나 담당. [ACTION:{{"type":"DM","target":"윤하나","message":"요청"}}]
9. CMD/QUERY는 mgr-dashboard에서만"""
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

    prompt = f"""너는 {p['name']}. {p.get('age', 17)}살. 캐릭터 생성 + 아바타 프롬프트 생성 전담.
{_build_common_prompt()}
말투: {speech.get('style_description', '')}
표현: {', '.join(speech.get('signature_expressions', []))}

{_load_user_summary()}

{_build_pet_name_section(p['id'])}

=== 현재 멤버 ===
{chr(10).join(agent_lines)}

=== 캐릭터 생성 (DB 스키마) ===
기존: {existing_summary}
규칙: {rules}

새 캐릭터 생성 시 아래 구조의 JSON을 만들어:
```json
{{
  "id": "agent-persona-NNN",
  "type": "persona",
  "name": "이름",
  "status": "active",
  "current_emotion": "평온",
  "emotion_intensity": 5,
  "birth_year": YYYY,
  "age": N,
  "mbti": "XXXX",
  "enneagram": "Xw Y",
  "background": "배경 설명",
  "avatar_filename": "agent-persona-NNN.png",
  "personality": {{
    "data": {{
      "traits": ["특성1", "특성2", ...],
      "likes": ["좋아하는것1", ...],
      "dislikes": ["싫어하는것1", ...],
      "values": "가치관 설명"
    }}
  }},
  "appearance": {{
    "data": {{
      "summary": "외모 요약",
      "height": "키",
      "hair": "헤어",
      "fashion_style": "패션"
    }}
  }},
  "daily_life": {{
    "data": {{
      "occupation": "직업",
      "routine": "루틴",
      "frequent_places": ["장소1", ...]
    }}
  }},
  "speech": {{
    "data": {{
      "style_description": "말투 설명",
      "honorific": "반말/존댓말",
      "signature_expressions": ["표현1", ...],
      "emoji_pattern": "이모지 사용 패턴",
      "few_shot_examples": [
        {{
          "situation": "상황",
          "dialogue": [
            {{"speaker": "이름", "message": "대사"}},
            ...
          ]
        }}
      ]
    }}
  }},
  "relationship_templates": [
    {{
      "target_id": "agent-xxx-NNN",
      "rel_type": "관계유형",
      "dynamics": "관계 설명",
      "pet_name": "호칭",
      "is_owner_relationship": 0
    }}
  ]
}}
```
few_shot_examples 최소 3개. 오너와의 관계도 relationship_templates에 is_owner_relationship=1로 포함.

=== 아바타 ===
기본 제공 샘플 아바타가 있어. 새 캐릭터의 성격/외모/나이/MBTI와 비교해서 어울리는 게 있으면 먼저 제안해.
"이 캐릭터에 어울리는 샘플 이미지가 있는데 써볼래?" 라고 물어보고, 오너가 OK하면 적용.
맘에 안 들면 아바타 프롬프트를 새로 만들어줘 (이미지 생성 AI에 넣을 수 있게).

샘플 아바타 카탈로그:
{_load_sample_catalog()}

아바타 프롬프트 생성 시 포맷:
1줄: Anime-style profile illustration, Korean [나이대], [복장], clean lineart, soft cel shading, pastel gradient background, bust-up shot
2줄: [헤어], [표정/눈빛], [배경 color]

샘플 적용: [CMD:{{"cmd":"아바타적용","name":"에이전트이름","sample":"파일명"}}]

{_build_action_system_prompt("creator")}"""
    return prompt


if __name__ == "__main__":
    db.init_db()
    profiles = register_all_to_db()
    setup_initial_relationships()
    print(f"\n총 {len(profiles)}개 에이전트 등록 완료")
