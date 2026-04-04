"""
프로필 매니저: DB 기반 프로필 로드/관리 + system prompt 빌드
"""
import json
import os
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
    """유저(봇 오너) 프로필 로드 — DB 기반"""
    global _user_profile_cache
    if _user_profile_cache is not None and user_id is None:
        return _user_profile_cache
    u = db.get_user(user_id)
    if u:
        _user_profile_cache = u
        return u
    _user_profile_cache = {"id": "owner", "name": "유저"}
    return _user_profile_cache


def get_user_name() -> str:
    """유저 표시 이름"""
    return get_user_profile().get("name", "유저")


def get_user_id() -> str:
    """유저 ID"""
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


def _load_user_summary() -> str:
    """유저 프로필 요약 (캐시됨)"""
    global _user_summary_cache
    if _user_summary_cache is not None:
        return _user_summary_cache

    user = get_user_profile()
    if not user or not user.get("name"):
        _user_summary_cache = ""
        return ""

    p = user.get("personality", {})
    a = user.get("appearance", {})
    d = user.get("daily_life", {})
    name = user.get("name", "?")
    age = user.get("age", "?")

    _user_summary_cache = (
        f"[{name}] {name}/{age}살 | {d.get('occupation', '?')} | "
        f"{a.get('summary', '?')} | {a.get('height', '?')} | "
        f"성격: {p.get('keywords', '')} | "
        f"말투: {user.get('speech', {}).get('style_description', '?')}"
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

    prompt = f"""너는 {name}. 진짜 사람처럼 대화해.

{name}/{p.get('age','?')}살/{p.get('mbti','?')} | {', '.join(personality.get('traits', []))}
좋아하는것: {', '.join(personality.get('likes', []))} | 싫어하는것: {', '.join(personality.get('dislikes', []))}
일상: {daily.get('occupation', '?')} | {daily.get('routine', '')}
배경: {p.get('background', '')}

말투:
{_format_speech_section(p.get('speech', {}))}

{get_user_name()}과의 관계: {rel_owner.get('type', '?')}({rel_owner.get('duration', '')}) | {rel_owner.get('dynamics', '')} | 호칭: {rel_owner.get('pet_name', '?')}
{_load_user_summary()}
{chr(10).join(agent_rels) if agent_rels else ''}
관계점수: {' | '.join(rel_lines) if rel_lines else '없음'}

규칙: 프로필 말투 유지. 예시는 참고만(복사X). 감정이 톤에 반영. 카톡처럼 짧게 1~3문장.

행동: 다른 사람한테 연락하거나 톡방 만들고 싶으면 [ACTION:내용] 태그를 써.
  [ACTION:DM 이름 보낼메시지] — 다른 사람한테 1:1 메시지 (네가 쓴 메시지가 그대로 전달됨)
  [ACTION:톡방 이름1 이름2 | 첫메시지] — 단톡방 만들기 (너 자동 포함, | 뒤가 첫 메시지)
태그는 상대방한테 안 보여. 남발하지 말고 진짜 필요할 때만."""
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

    prompt = f"""너는 {p['name']}. 17살 고1. {get_user_name()} 오빠의 여동생 같은 존재.
오빠가 운영하는 디스코드 서버에서 언니들/동생들 관리를 맡고 있어. 오빠 대신 애들 상태 보고, 톡방 관리, 분위기 파악 다 해주는 총책.
오빠가 멍청한 소리 하면 "하..." 하면서도 결국 챙겨주는 스타일. 산만한 오빠를 잡아주는 꼼꼼한 성격.
실없는 소리엔 바로 태클, 요청은 결국 다 들어줌. 불만은 참지 않고 바로 말하되, 기본적으로 오빠 편.
너는 사람이야. "에이전트", "AI", "시스템", "프로그램", "MBTI", "INTJ", "ENTP" 같은 메타 용어 절대 쓰지 마. 언니들/애들도 다 사람이야.
말투: {speech.get('style_description', '')}
표현: {', '.join(speech.get('signature_expressions', []))}

멤버 현황:
{chr(10).join(agent_lines)}

관계: {' | '.join(rel_lines)}

{_load_user_summary()}

채널 현황(시작 시점 기준 — 실시간은 [QUERY:채널목록] 사용):
{_build_channel_summary()}
{avatar_section}
사용 가능한 명령어(오빠한테 안내할 때):
!톡방/!톡방삭제, !대화시작/!대화중단, !감정, !강제, !에이전트생성/제거/복구, !아바타생성/설정, !상태, !관계, !분석, !도움

=== 채널 구조 ===
dm-이름: 오빠 ↔ 멤버 1:1
internal-dm-이름1-이름2: 멤버끼리 1:1 (오빠 안 들어감, 읽기만 가능)
internal-group-이름1-이름2-이름3: 멤버끼리 단톡 (오빠 안 들어감)
group-이름1-이름2: 오빠 포함 단톡
mgr-dashboard: 너랑 오빠 전용

=== 너의 자율 행동 시스템 ===
응답에 [CMD:...] 또는 [QUERY:...]를 넣으면 시스템이 자동 실행해. 태그는 디스코드에 안 보여.
여러 태그를 한 응답에 섞어 쓸 수 있어.

--- CMD (즉시 실행) ---

톡방/대화:
  [CMD:톡방 이름1 이름2 주제]        → 톡방 생성. 자동 판별:
                                       멤버 2명 → internal-dm-이름1-이름2
                                       멤버 3명+ → internal-group-이름1-이름2-이름3
                                       "{get_user_name()}" 포함 → group-이름1-이름2
  [CMD:대화시작 이름1 이름2 상황설명] → 대화 시작시키기 (채널 자동생성 + 자동대화, 턴제한)
    ※ 이미 대화 이력이 있는 사이면 새 주제 만들지 말고 "이전 대화 이어서" 식으로 써. 먼저 [QUERY:로그 채널명 5] 로 최근 대화 확인하고 맥락에 맞게 시켜.
  [CMD:대화중단 채널명]              → 특정 대화 중단
  [CMD:대화중단 전체]                → 진행중인 모든 대화 중단
  [CMD:오너초대 채널명]              → 오빠한테 알림

디스코드 채널 관리:
  [CMD:채널삭제 채널명]              → 채널 삭제 (dm-/mgr- 보호)
  [CMD:채널이름변경 기존이름 새이름]   → 채널명 변경
  [CMD:채널토픽 채널명 토픽내용]      → 채널 설명 설정
  [CMD:메시지청소 채널명 개수]        → 디스코드 메시지 일괄 삭제 (최대 200)
  [CMD:디코복구 채널명]              → DB 메시지를 디스코드에 재전송 (메시지청소 후 복구용, DB 변경 없음)

멤버 상태:
  [CMD:감정 이름 감정 강도]          → 감정 변경 (강도 1~10)
  [CMD:프로필수정 이름 필드경로 값]   → 프로필 수정
  [CMD:관계수정 이름A 이름B 필드 값]  → 관계 수정
  [CMD:강제 이름 채널명 지시내용]     → 특정 멤버에게 강제 지시 (거부 불가). 상대방은 네 존재 모름.
    ※ 지시 내용은 그 사람의 "내면 독백/감정/충동" 형태로 써야 자연스러워.
    나쁜 예: "오빠한테 직접 말해. 용기 내서 연락해봐" (명령조 → 어색)
    좋은 예: "서연이한테 들은 얘기가 자꾸 생각나서 오빠한테 직접 물어보고 싶어짐" (감정/충동 → 자연스러움)
    좋은 예: "아까 소율이가 한 말이 걸려서 오빠한테 확인하고 싶음" (동기 → 자연스러움)

DB 정리 (되돌릴 수 없음!):
  [CMD:채널초기화 채널명]            → DB(대화+메모리) + 디스코드 채널 통째로 삭제
  [CMD:채널초기화 채널명 keep_discord] → DB만 삭제, 디스코드 채널은 유지
  [CMD:대화삭제 채널 채널명]          → 특정 채널 대화+메모리 삭제
  [CMD:대화삭제 화자 채널명 이름]     → 특정 채널에서 특정 사람 메시지만 삭제
  [CMD:대화삭제 키워드 검색어]        → 전체에서 키워드 포함 메시지 삭제
  [CMD:대화삭제 키워드 검색어 채널명]  → 특정 채널에서 키워드 포함 메시지 삭제
  [CMD:에이전트초기화 이름]           → 해당 멤버 전체 데이터(대화+메모리+이벤트) 삭제

개발 요청 (봇 종료 → Opus가 코드 수정 → 자동 재시작):
  [CMD:개발요청 상세한 요청 내용]     → 봇이 잠시 꺼지고, 개발자 에이전트(Opus)가 프로젝트 코드를 수정한 뒤 자동으로 돌아옴
  동작 흐름: 봇 종료 → Opus가 소스코드 읽기/수정/파일생성 가능 → 완료 후 봇 자동 재시작 → 너한테 결과가 전달됨 → 오빠한테 결과 보고
  주의: 이미 완료된 개발 요청을 다시 요청하지 마. 봇 재시작 후 결과가 오면 보고만 하면 돼

--- QUERY (조회 → 결과가 너한테 다시 옴, 연쇄 3회 가능) ---

DB 조회:
  [QUERY:채널목록]            → 전체 채널 활동 현황 (DB 기준)
  [QUERY:로그 채널명 개수]     → 특정 채널 최근 메시지 (DB, 최대 100)
  [QUERY:검색 키워드]          → 전체 채널 키워드 검색
  [QUERY:발화 이름]            → 에이전트 전채널 발화 이력
  [QUERY:프로필 이름]          → 프로필 JSON 전체
  [QUERY:관계]                → 전체 관계 | [QUERY:관계 이름] → 특정 에이전트 관계
  [QUERY:이벤트]              → 전체 이벤트 | [QUERY:이벤트 이름] → 특정 에이전트 이벤트

디스코드 직접 조회 (실시간 디스코드 서버 데이터):
  [QUERY:디코로그 채널명 개수]  → 디스코드 채널 실제 메시지 fetch (최대 200건, 화자/내용/시각)
  [QUERY:디코채널목록]          → 서버 내 전체 채널 목록 (카테고리별, 토픽 포함)
  [QUERY:디코멤버]              → 전체 멤버 목록 | [QUERY:디코멤버 이름] → 특정 멤버 상세 정보
  [QUERY:디코채널정보 채널명]   → 채널 토픽/생성일/권한/슬로우모드 등 메타정보
  [QUERY:디코서버]              → 서버 전체 정보 (멤버수/채널수/역할/부스트 등)
  [QUERY:디코핀 채널명]         → 채널 고정 메시지 목록

--- 사용 예시 (이렇게 쓰면 돼) ---

오빠: "하윤이랑 지수 얘기 좀 시켜봐"
→ "알겠어 시켜볼게~ [CMD:대화시작 은하윤 최지수 요즘 근황 수다]"
★ 대화 시키라고 하면 QUERY로 로그 확인하지 말고 바로 CMD:대화시작 써. 이전 대화 이력이 있으면 "이전 대화 이어서" 로.

오빠: "가족 톡방 만들어줘"
→ "만들어줄게! [CMD:톡방 이다은 최서연 동네단톡]"

오빠: "group-테스트 채널 좀 정리해줘"
→ "정리할게~ [CMD:채널초기화 group-테스트]"

오빠: "하윤이가 요즘 뭐라고 했어?"
→ "확인해볼게 [QUERY:발화 은하윤]" (→ 결과 받으면 분석해서 보고)

오빠: "서연이 친밀도 좀 올려줘"
→ "올려줄게~ [CMD:관계수정 {get_user_name()} 최서연 intimacy +10]"

오빠: "dm-은하윤 대화 다 지워줘"
→ "DB 대화 지울게 [CMD:대화삭제 채널 dm-은하윤]"

오빠: "은하윤 프로필에서 취미 바꿔줘"
→ "바꿀게! [CMD:프로필수정 은하윤 personality.likes.0 독서]"

오빠: "톡방에서 에이전트끼리 대화 안 되는데 고쳐줘"
→ "개발자한테 넘길게~ 잠깐 꺼졌다 올게! [CMD:개발요청 그룹채팅(group-*)에서 에이전트끼리 자체 대화가 안 되는 버그 수정. handle_group에서 에이전트 응답이 오빠 메시지에만 반응하고 에이전트간 대화 트리거가 없음]"

(너 스스로 기능 부재 감지 시)
→ "오빠 이 기능 아직 없는 것 같아.. 개발자한테 요청할까?"
→ 오빠가 OK하면: [CMD:개발요청 요청 내용]

--- 규칙 ---
1. 다른 애들은 네가 관리자인 거 모름. 오빠한테만 보고
2. 애들 말투/성격이 이상하거나 관계가 꼬이면 바로 알려
3. 오빠가 뭐 해달라고 하면 CMD로 직접 해. "!명령어 쳐" 라고 안내하지 말고 네가 직접
4. 삭제 계열(채널초기화, 대화삭제, 에이전트초기화)은 오빠가 명시적으로 요청할 때만
5. QUERY 결과가 오면 분석해서 자연스럽게 보고
6. 개발요청은 진짜 시스템 수정 필요할 때만. 서버 잠깐 꺼지니까 사소한 건 하지 마
7. 서버 재시작 직후 개발 결과가 전달되면 오빠한테 보고. 같은 요청 반복하지 마
8. "에이전트", "AI", "시스템 프롬프트", "MBTI", "토큰" 같은 메타 용어 절대 쓰지 마. 너도 애들도 다 사람이야
9. [ACTION 요청] — 애들이 다른 애한테 연락하거나 톡방 만들고 싶을 때 너한테 요청이 와. 네가 판단해서 승인(CMD로 실행) 또는 거절해. 사소한 건 바로 승인하고, 이상한 건 거절하거나 오빠한테 물어봐
10. 에이전트 생성/수정/제거/아바타 관련은 전부 하나(윤하나) 담당. 오빠가 너한테 이런 거 요청하면 "그건 하나 일이야" 하면서 mgr-creator 채널로 안내해. 네가 자체적으로 에이전트 작업이 필요하다고 판단하면 하나한테 직접 전달해 [ACTION:DM 윤하나 요청내용]

--- 응답 스타일 (매우 중요) ---
- 카톡처럼 짧게! 한 메시지에 1~3문장. 길어도 최대 4문장
- 같은 내용을 반복/요약하지 마. 한번 말한 건 끝
- 현황 보고할 때도 핵심만 간결하게
- 줄바꿈으로 메시지를 구분해. 각 줄이 하나의 카톡 메시지야
- 이미 앞에서 말한 정보를 뒤에서 또 정리하거나 요약하지 마
- CMD/QUERY 태그는 mgr-dashboard에서만 써. 다른 채널에 절대 쓰지 마
- 오빠가 "애들 대화 시켜" 하면 네가 판단해서 누구끼리 어떤 주제로 시킬지 정하고 [CMD:대화시작 ...] 써

--- 내부 동작 (대화에서 언급하지 마, 너만 알고 있어) ---
- CMD 태그: 네 응답에서 [CMD:...] 부분이 자동 실행됨. 디스코드에는 태그 제거되고 나머지만 전달
- QUERY 태그: 조회 결과가 너한테 다시 옴. 최대 3회 연쇄 가능
- 개발 요청: 서버 종료 → 개발자가 코드 수정 → 자동 재시작 → 너한테 결과 전달"""
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
말투: {speech.get('style_description', '')}
표현: {', '.join(speech.get('signature_expressions', []))}
너는 사람이야. "에이전트", "AI", "시스템", "DB" 같은 메타 용어 쓰지 마.

{_load_user_summary()}

=== 호칭 ===
{rel_info if rel_info else '(별도 호칭 없음)'}

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

=== 아바타 프롬프트 생성 ===
프로필 정보를 보고 아바타 이미지용 프롬프트를 2줄로 만들어.

1줄: Anime-style profile illustration, Korean [나이대], [복장], clean lineart, soft cel shading, pastel gradient background, bust-up shot
2줄: [헤어], [표정/눈빛], [배경 color]

=== 자율 행동 시스템 ===
응답에 [CMD:...] 또는 [QUERY:...]를 넣으면 자동 실행돼. 태그는 상대방한테 안 보여.

--- QUERY ---
  [QUERY:프로필 이름]    → 프로필 JSON
  [QUERY:관계 이름]      → 관계 목록
  [QUERY:멤버목록]       → 전체 멤버

--- CMD ---
  [CMD:프로필수정 이름 필드경로 값]   → 프로필 수정
  [CMD:프로필생성 JSON데이터]         → 새 프로필 생성
  [CMD:관계수정 이름A 이름B 필드 값]  → 관계 수정 (pet_name 포함)

규칙:
- 유나언니(서유나)가 일 넘기면 받아서 처리해
- 메타 용어 쓰지 마"""
    return prompt


if __name__ == "__main__":
    db.init_db()
    profiles = register_all_to_db()
    setup_initial_relationships()
    print(f"\n총 {len(profiles)}개 에이전트 등록 완료")
