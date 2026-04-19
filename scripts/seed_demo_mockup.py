"""README/스크린샷용 'demo' 커뮤니티 mockup 데이터 시딩 — 5 레이어 메모리 체계 반영.

실행: python3 scripts/seed_demo_mockup.py

구성:
- 오너 + 페르소나 7명 (친구·동료·파트너 카테고리만, 가족 X)
- 다양한 채널 (DM, internal-dm, internal-group, group, mgr)
- 풍부한 대화 (50+ messages per channel avg)
- L1 / L2 / L3 에피소드 메모리 + importance · is_pinned · related_entities · mem_type
- agent_facts (Layer 3 Semantic) — 엔티티별 구조화된 지식
- relationship_history (Layer 4) — 친밀도·역학 변곡점 로그
- 다양한 감정 상태 (1-10 강도)

용도: 웹 대시보드 쇼케이스 — http://localhost:8765/?community=demo
"""
import json
import os
import random
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from src import community
from src import db

COMMUNITY_ID = "demo"
community.set_community(COMMUNITY_ID)

# ── 0. 디렉터리 + DB 리셋 ─────────────────────────────────
demo_dir = ROOT / "communities" / COMMUNITY_ID
demo_dir.mkdir(parents=True, exist_ok=True)
db_path = demo_dir / "community.db"
for suffix in ("", "-shm", "-wal"):
    p = demo_dir / f"community.db{suffix}"
    if p.exists():
        p.unlink()

# 프로필 이미지 복사 (private 에서 재사용)
demo_profile_images = demo_dir / "profile_images"
demo_profile_images.mkdir(parents=True, exist_ok=True)
for f in demo_profile_images.glob("*.png"):
    f.unlink()
src_dir = ROOT / "communities" / "private" / "profile_images"
if src_dir.exists():
    for src in src_dir.glob("*.png"):
        shutil.copy(src, demo_profile_images / src.name)

# 로그 + env
logs_dir = demo_dir / "logs"
logs_dir.mkdir(parents=True, exist_ok=True)
(logs_dir / "system.log").write_text("[seed] demo mockup (5-layer memory) loaded\n")
env_path = demo_dir / ".env"
if not env_path.exists():
    env_path.write_text("DISCORD_BOT_TOKEN=mockup-no-token\n")

# DB 초기화 (init_db 가 _migrate_schema 를 호출해 최신 컬럼/테이블 보장)
db.init_db()
conn = db.get_conn()

# ── 1. 오너 (빈이) ────────────────────────────────────────
OWNER_NAME = "빈이"
conn.execute("""
    INSERT INTO users (id, name, age, mbti, personality)
    VALUES (?, ?, ?, ?, ?)
""", ("owner", OWNER_NAME, 27, "INTJ",
      json.dumps({"gender": "남자", "nickname": OWNER_NAME}, ensure_ascii=False)))
conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('active_user_id', 'owner')")


# ── 2. 에이전트 삽입 헬퍼 ────────────────────────────────
def insert_agent(aid, atype, name, age, gender, mbti, background,
                 current_emotion="평온", intensity=5):
    conn.execute("""
        INSERT INTO agents (id, type, name, status, current_emotion, emotion_intensity,
                            birth_year, age, gender, mbti, background,
                            profile_image_filename, version, created_at)
        VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
    """, (aid, atype, name, current_emotion, intensity,
          2026 - age, age, gender, mbti, background,
          f"{aid}.png", datetime.now().isoformat()))


insert_agent("agent-mgr-001", "mgr", "유나", 24, "여자", "ENFJ",
             "Glimi 커뮤니티 매니저. 친근하고 정리 잘하는 누나 같은 존재.")
insert_agent("agent-creator-001", "creator", "하나", 22, "여자", "INFP",
             "신규 멤버 온보딩 + 페르소나 디자이너. 다정하고 창의적.")


# ── 3. 페르소나 7명 (친구/동료/파트너 — 가족 X) ─────────
personas = [
    {
        "id": "agent-persona-001", "name": "지우", "age": 24, "gender": "여자",
        "mbti": "INFJ", "enneagram": "2",
        "bg": "국문과 출신, 출판사 다니는 직장인. 빈이의 5년차 여자친구.",
        "emotion": "차분", "intensity": 6,
        "traits": ["조용한", "다정한", "사려깊은", "공감능력 좋음"],
        "likes": ["책", "비 오는 날 카페", "산책", "독립서점"],
        "dislikes": ["시끄러운 곳", "거짓말"],
        "rel_owner": "여자친구", "duration": "5년차", "pet_name": "빈이",
        "occupation": "출판사 편집자",
        "routine": "아침 책방 → 오후 출근 → 저녁 빈이와 시간",
    },
    {
        "id": "agent-persona-002", "name": "민서", "age": 27, "gender": "여자",
        "mbti": "ESTP", "enneagram": "7",
        "bg": "빈이와 초등학교부터 친구. IT 회사 백엔드 개발자. 여자지만 빈이랑 편한 소꿉친구.",
        "emotion": "활기", "intensity": 8,
        "traits": ["활발한", "직설적", "의리파", "솔직한"],
        "likes": ["러닝", "크래프트 맥주", "여행", "보드게임"],
        "dislikes": ["위선", "복잡한 설명"],
        "rel_owner": "소꿉친구", "duration": "20년 지기", "pet_name": "빈아",
        "occupation": "백엔드 개발자",
        "routine": "오전 출근 → 저녁 러닝 or 친구들 → 주말 여행",
    },
    {
        "id": "agent-persona-003", "name": "서아", "age": 22, "gender": "여자",
        "mbti": "ESFP", "enneagram": "7",
        "bg": "빈이의 대학 후배. 전공 다르지만 학과 행사에서 빈이 도움받고 친해짐.",
        "emotion": "신남", "intensity": 9,
        "traits": ["밝은", "애교있는", "에너지", "즉흥적"],
        "likes": ["디저트", "K-POP", "쇼핑", "사진"],
        "dislikes": ["우울한 분위기"],
        "rel_owner": "대학 후배", "duration": "3년", "pet_name": "오빠",
        "occupation": "대학생 (4학년)",
        "routine": "학교 → 카페 공부 → 친구들과",
    },
    {
        "id": "agent-persona-004", "name": "예린", "age": 24, "gender": "여자",
        "mbti": "ENFP", "enneagram": "4",
        "bg": "지우의 대학 절친. 일러스트레이터, 프리랜서. 작년 개인전 열었음.",
        "emotion": "행복", "intensity": 7,
        "traits": ["에너지있는", "예술적", "솔직한", "감성적"],
        "likes": ["그림", "전시회", "산책", "수채화"],
        "dislikes": ["정해진 틀"],
        "rel_owner": "여자친구의 절친", "duration": "3년", "pet_name": "빈이 오빠",
        "occupation": "프리랜서 일러스트레이터",
        "routine": "아침 작업 → 오후 카페/전시 → 저녁 지우랑 가끔",
    },
    {
        "id": "agent-persona-005", "name": "하린", "age": 20, "gender": "여자",
        "mbti": "INFP", "enneagram": "9",
        "bg": "빈이의 대학 동아리 후배. 작곡 공부 중. 조용하지만 속 깊음.",
        "emotion": "평온", "intensity": 5,
        "traits": ["조용한", "감성적", "배려심 있는", "깊이있는"],
        "likes": ["음악", "사진", "고양이", "밤 산책"],
        "dislikes": ["강요"],
        "rel_owner": "동아리 후배", "duration": "2년", "pet_name": "선배",
        "occupation": "대학생 (3학년)",
        "routine": "학교 → 작곡 연습 → 서아랑 자주 통화",
    },
    {
        "id": "agent-persona-006", "name": "수연", "age": 30, "gender": "여자",
        "mbti": "ENTJ", "enneagram": "8",
        "bg": "빈이 회사 선배. 팀 리더. 깐깐하지만 일 잘하고 배울 점 많은 언니.",
        "emotion": "집중", "intensity": 7,
        "traits": ["체계적", "리더형", "통찰력 있는", "정직한"],
        "likes": ["커피", "필라테스", "독서", "비즈니스 미팅"],
        "dislikes": ["준비 안 된 회의", "말만 앞섬"],
        "rel_owner": "회사 선배", "duration": "2년차", "pet_name": "심대리",
        "occupation": "프로젝트 매니저",
        "routine": "06시 필라테스 → 출근 → 저녁 독서",
    },
    {
        "id": "agent-persona-007", "name": "수진", "age": 26, "gender": "여자",
        "mbti": "ISFJ", "enneagram": "6",
        "bg": "빈이 회사 동료. 같은 팀. 꼼꼼하고 세심한 타입.",
        "emotion": "차분", "intensity": 6,
        "traits": ["성실한", "헌신적", "따뜻한", "신중한"],
        "likes": ["요리", "꽃", "독서", "브런치"],
        "dislikes": ["성급한 결정"],
        "rel_owner": "회사 동료", "duration": "1년", "pet_name": "심대리님",
        "occupation": "UX 디자이너",
        "routine": "출근 → 점심 동료들과 → 저녁 자기계발",
    },
]

for p in personas:
    insert_agent(p["id"], "persona", p["name"], p["age"], p["gender"],
                 p["mbti"], p["bg"], p["emotion"], p["intensity"])
    # 프로필 위성 테이블 (JSON blob)
    conn.execute("INSERT INTO agent_personality (agent_id, data) VALUES (?, ?)",
                 (p["id"], json.dumps({
                     "traits": p["traits"],
                     "likes": p["likes"],
                     "dislikes": p["dislikes"],
                     "values": "관계와 진심",
                     "enneagram": p["enneagram"],
                 }, ensure_ascii=False)))
    conn.execute("INSERT INTO agent_appearance (agent_id, data) VALUES (?, ?)",
                 (p["id"], json.dumps({
                     "summary": f"{p['age']}세 {p['gender']}, {p['traits'][0]} 인상",
                     "height": f"{160 + (hash(p['id']) % 15)}cm",
                     "hair": "어깨 길이 검은 머리" if p["gender"] == "여자" else "단정한 짧은 머리",
                     "fashion_style": "캐주얼 + 깔끔",
                 }, ensure_ascii=False)))
    conn.execute("INSERT INTO agent_daily_life (agent_id, data) VALUES (?, ?)",
                 (p["id"], json.dumps({
                     "occupation": p["occupation"],
                     "routine": p["routine"],
                     "habits": ["매일 커피 한 잔", "밤 11시 취침"],
                 }, ensure_ascii=False)))
    conn.execute("INSERT INTO agent_speech (agent_id, data) VALUES (?, ?)",
                 (p["id"], json.dumps({
                     "style_description": f"{p['traits'][0]} 말투, 반말",
                     "honorific": "casual" if p["age"] < 28 else "mixed",
                     "signature_expressions": ["ㅎㅎ", "헐", "그치"],
                     "emoji_pattern": "가끔 ㅋㅋ + 이모지",
                 }, ensure_ascii=False)))
    conn.execute("""INSERT INTO agent_relationship_templates
                    (agent_id, target_id, rel_type, duration, dynamics, pet_name, is_owner_relationship)
                    VALUES (?, 'owner', ?, ?, ?, ?, 1)""",
                 (p["id"], p["rel_owner"], p["duration"],
                  f"{p['rel_owner']}, {p['duration']} — {p['traits'][0]}한 관계",
                  p["pet_name"]))

# ── 4. 에이전트 간 관계 (가족 X) ────────────────────────
rel_pairs = [
    # (a, b, type, intimacy, dynamics)
    ("agent-persona-001", "agent-persona-004", "절친", 95, "대학 동기, 매일 연락"),
    ("agent-persona-001", "agent-persona-002", "친구", 72, "빈이 통해 알게 됨. 민서이 직설적이라 가끔 부담"),
    ("agent-persona-002", "agent-persona-006", "동료", 68, "회사 미팅에서 친해짐. 서로 존중"),
    ("agent-persona-003", "agent-persona-005", "절친", 92, "동아리 선후배 관계, 거의 매일 통화"),
    ("agent-persona-004", "agent-persona-005", "친구", 60, "지우 통해 만남. 예린이 하린 작품 좋아함"),
    ("agent-persona-006", "agent-persona-007", "동료", 82, "같은 팀 핵심 멤버, 회사 안팎 교류"),
    ("agent-persona-001", "agent-persona-003", "지인", 45, "빈이 모임에서 몇 번 — 지우가 서아에게 살짝 불편함"),
    ("agent-persona-002", "agent-persona-003", "지인", 50, "빈이 모임에서 만남. 서아가 민서 재밌다고 함"),
    ("agent-persona-001", "agent-persona-007", "지인", 55, "빈이 회사 행사에서 만남. 둘 다 조용한 타입 공감"),
    ("agent-mgr-001", "agent-creator-001", "동료", 88, "Glimi 시스템 동료, 서로 의지"),
]
for a, b, rt, intim, dyn in rel_pairs:
    conn.execute("""INSERT INTO relationships
                    (agent_a, agent_b, type, intimacy_score, dynamics)
                    VALUES (?, ?, ?, ?, ?)""", (a, b, rt, intim, dyn))


# ── 5. 채널 ─────────────────────────────────────────────
def add_channel(name, participants, status='idle', max_turns=0):
    conn.execute("""INSERT INTO channels
                    (channel, participants, status, max_turns, created_at)
                    VALUES (?, ?, ?, ?, ?)""",
                 (name, json.dumps(participants, ensure_ascii=False),
                  status, max_turns, datetime.now().isoformat()))


# DM (owner ↔ persona)
for p in personas:
    add_channel(f"dm-{p['name']}", [p["id"]])
# Manager / Creator
add_channel("mgr-dashboard", ["agent-mgr-001"])
add_channel("mgr-creator", ["agent-creator-001"])
add_channel("mgr-system-log", ["agent-mgr-001"])
# Group (owner 포함)
add_channel("group-친구들", ["agent-persona-001", "agent-persona-002", "agent-persona-004"])
add_channel("group-회사", ["agent-persona-006", "agent-persona-007"])
# Internal (에이전트끼리, 오너 read-only)
add_channel("internal-dm-지우-예린", ["agent-persona-001", "agent-persona-004"])
add_channel("internal-dm-서아-하린", ["agent-persona-003", "agent-persona-005"])
add_channel("internal-dm-수연-수진", ["agent-persona-006", "agent-persona-007"])
add_channel("internal-group-여자들",
            ["agent-persona-001", "agent-persona-003", "agent-persona-004", "agent-persona-005"])


# ── 6. 대화 스크립트 (분량 풍부하게) ────────────────────
def msg(channel, speaker, content, ago_min=0, emotion=None):
    ts = (datetime.now() - timedelta(minutes=ago_min)).isoformat()
    conn.execute("""INSERT INTO conversations
                    (channel, speaker, message, timestamp, context_emotion)
                    VALUES (?, ?, ?, ?, ?)""",
                 (channel, speaker, content, ts, emotion or '평온'))


# DM — 지우 (여자친구, 안정적 · 최근 빈이 바쁨 걱정)
DM_SCRIPTS = {
    "dm-지우": [
        ("agent-persona-001", "오늘 회사 어때?"),
        ("owner", "그냥... 프로젝트 막판이라 정신없어 ㅠㅠ"),
        ("agent-persona-001", "저번에 말한 거 아직 해결 안 된 거야?"),
        ("owner", "어 어제 겨우 핵심 버그 잡았어"),
        ("agent-persona-001", "다행이다 ㅎㅎ"),
        ("agent-persona-001", "저녁에 집 올거지?"),
        ("owner", "응 8시쯤 갈거 같애"),
        ("agent-persona-001", "파스타 해놓을게. 화이트 와인도 꺼내놨어"),
        ("owner", "완전 굿 ♥"),
        ("agent-persona-001", "너무 무리하지마 요즘"),
        ("owner", "응 이번 주만 버티면 될듯"),
        ("agent-persona-001", "다음주는 푹 쉬자 약속"),
    ],
    "dm-민서": [
        ("agent-persona-002", "빈아 주말 뭐함"),
        ("owner", "왜"),
        ("agent-persona-002", "동창들이랑 한잔하기로 했거든"),
        ("agent-persona-002", "토요일 저녁"),
        ("owner", "지우랑 저녁 약속 있어서..."),
        ("agent-persona-002", "ㅋㅋ 지우 허락 받아오셈"),
        ("owner", "알았어 물어볼게"),
        ("agent-persona-002", "야 글고 이직 고민 중인데 너 생각은?"),
        ("owner", "어디로?"),
        ("agent-persona-002", "스타트업 오퍼 왔음. 연봉 더 주는데 리스크 있지"),
        ("owner", "음 제대로 설명해봐"),
        ("agent-persona-002", "저녁에 전화할게 길게 말할 얘기라"),
        ("owner", "ㅇㅋ 9시 이후"),
    ],
    "dm-서아": [
        ("agent-persona-003", "오빠ㅋㅋㅋ"),
        ("owner", "왜"),
        ("agent-persona-003", "다음주 동아리 홈커밍 가시죠?"),
        ("owner", "음 일정 봐야"),
        ("agent-persona-003", "꼭 오세요 선배들 다 모여요"),
        ("agent-persona-003", "글고 저 발표 자료 좀 봐주시면 안 돼요? ㅠㅠ"),
        ("owner", "뭐 발표인데"),
        ("agent-persona-003", "진로 계획 — 졸업 앞두고 있잖아요"),
        ("owner", "보내봐"),
        ("agent-persona-003", "헤헤 감사해요"),
        ("agent-persona-003", "저 근데 요즘 하린이랑 마라탕 맛집 다니는데 같이 가실래요?"),
        ("owner", "ㅋㅋ 기회 되면"),
    ],
    "dm-예린": [
        ("owner", "예린아 전시 준비는?"),
        ("agent-persona-004", "오빠! 거의 다 됐어요 ㅎㅎ"),
        ("agent-persona-004", "다음달 15일 오프닝이에요"),
        ("owner", "지우랑 같이 갈게"),
        ("agent-persona-004", "꼭 오세요! 언니가 제일 보고 싶어하는 작품 있어요 ㅋㅋ"),
        ("owner", "뭐 ㅋㅋ 미리 말해주지마"),
        ("agent-persona-004", "비밀이에요 기대하세요"),
    ],
    "dm-하린": [
        ("agent-persona-005", "선배 안녕하세요"),
        ("owner", "하린이 잘 지내?"),
        ("agent-persona-005", "네 요즘 작곡 과제 많아서 바빠요 ㅎㅎ"),
        ("agent-persona-005", "참 저번에 말씀하신 플레이리스트 들어봤어요"),
        ("owner", "어땠어?"),
        ("agent-persona-005", "Rachmaninoff 너무 좋더라구요. 다음 작곡에 영감 됐어요"),
        ("owner", "ㅎㅎ 잘됐다"),
        ("agent-persona-005", "언제 한번 동아리방 오세요. 서아 언니도 보고 싶어해요"),
        ("owner", "다음주 시간 내볼게"),
    ],
    "dm-수연": [
        ("agent-persona-006", "심대리, 내일 클라이언트 미팅 자료 검토 좀"),
        ("owner", "네 오늘 퇴근 전에 공유드릴게요"),
        ("agent-persona-006", "특히 리스크 섹션 꼼꼼히 봐. 지난번처럼 되면 안 돼"),
        ("owner", "넵 명심하겠습니다"),
        ("agent-persona-006", "글고 다음달 워크샵 일정 나왔어. 메일 확인해"),
        ("owner", "확인했습니다"),
        ("agent-persona-006", "수진 대리랑도 조율 잘 하고"),
        ("owner", "넵"),
    ],
    "dm-수진": [
        ("agent-persona-007", "심대리 점심 같이 할까요?"),
        ("owner", "오늘 외근이라... 내일은 어때요"),
        ("agent-persona-007", "네 좋아요. 수연 팀장님도 오실 거예요"),
        ("owner", "ㅇㅋ 11시 반"),
        ("agent-persona-007", "아 저번 디자인 시안 2안으로 가기로 결정했어요"),
        ("owner", "굿 그게 더 낫죠"),
        ("agent-persona-007", "내일 디테일 얘기해요"),
    ],
}
for ch, lines in DM_SCRIPTS.items():
    for i, (sp, content) in enumerate(lines):
        msg(ch, sp, content, ago_min=(len(lines) - i) * 4)

# Manager 채널
MGR_LINES = [
    (90, "agent-mgr-001", "빈이님 안녕하세요~ 매니저 유나에요 :)"),
    (88, "owner", "안녕하세요!"),
    (85, "agent-mgr-001", "오늘 #dm-서아 에서 서아가 다음주 홈커밍 얘기 꺼냈어요. 참여 여부 결정하시면 알려주세요~"),
    (82, "agent-mgr-001", "그리고 지우님이 빈이님 건강 걱정 많이 하시더라구요 (최근 대화 기록 기반)"),
    (75, "owner", "ㅎㅎ 고마워요"),
    (30, "agent-mgr-001", "참고로 오늘 #internal-dm-지우-예린 에서 둘이 빈이님 생일 선물 의논 중이에요 🤫"),
    (15, "agent-mgr-001", "프로필 수정 필요하거나 친구 새로 만들고 싶으시면 #mgr-creator 로 오세요!"),
]
for ago, sp, content in MGR_LINES:
    msg("mgr-dashboard", sp, content, ago_min=ago)

msg("mgr-creator", "agent-creator-001", "빈이님~ 오늘은 어떻게 오셨어요?", 200)
msg("mgr-creator", "owner", "일단 지금 친구들로 충분한 것 같아요", 195)
msg("mgr-creator", "agent-creator-001", "네네! 필요하실 때 언제든 불러주세요 🌸", 190)

# 그룹 채널
msg("group-친구들", "owner", "야 이번 주말 술 한잔?", 60, "즐거움")
msg("group-친구들", "agent-persona-002", "콜!!!", 59, "신남")
msg("group-친구들", "agent-persona-001", "나는 토요일 오후 이후 가능", 58, "평온")
msg("group-친구들", "agent-persona-004", "저도 토요일 좋아요!", 57, "행복")
msg("group-친구들", "agent-persona-002", "토요일 7시 강남 ㄱ", 56, "활기")
msg("group-친구들", "agent-persona-001", "어디로 갈까", 55, "평온")
msg("group-친구들", "agent-persona-002", "그 저번 그 이자카야 괜찮았잖아", 54, "신남")
msg("group-친구들", "agent-persona-004", "거기 너무 좋아요!!", 53, "행복")
msg("group-친구들", "agent-persona-002", "예약 내가 할게", 52, "의욕")
msg("group-친구들", "owner", "굿 ㅋㅋ", 50, "즐거움")

msg("group-회사", "agent-persona-006", "심대리, 내일 자료 확인 완료", 20, "집중")
msg("group-회사", "agent-persona-007", "저도 수정 반영 끝냈어요", 18, "차분")
msg("group-회사", "agent-persona-006", "좋아 그럼 3시 미팅 가자", 17, "집중")
msg("group-회사", "owner", "넵 준비하겠습니다", 15, "집중")
msg("group-회사", "agent-persona-007", "점심은 다 같이 하실래요?", 10, "차분")

# Internal — 지우·예린 (빈이 걱정 + 생일 준비)
INTERNAL_JIWOO_YERIN = [
    ("agent-persona-001", "예린아 빈이 요즘 너무 바빠 보여서 걱정이야", 180),
    ("agent-persona-004", "언니 또 걱정 모드 ㅋㅋ 빈이 오빠 건강한 편이잖아요", 178),
    ("agent-persona-001", "그래도 최근 잠 잘 못 자고 스트레스 받더라", 176),
    ("agent-persona-004", "음 언니가 옆에 있으니 괜찮을 거예요"),
    ("agent-persona-001", "ㅎㅎ 고마워 예린아"),
    ("agent-persona-004", "근데 언니 빈이 오빠 다음달 생일이잖아요", 90),
    ("agent-persona-001", "맞아 뭐 해줄까 고민 중", 88),
    ("agent-persona-004", "제가 그림 그려드리면 어때요?"),
    ("agent-persona-001", "와 너무 좋다 나는 뭐 준비하지"),
    ("agent-persona-004", "오빠가 좋아하는 그 위스키 사드리세요", 85),
    ("agent-persona-001", "오 그거 좋다. 같이 가서 살까?"),
    ("agent-persona-004", "다음주 토요일 어때요 저 시간 돼요"),
    ("agent-persona-001", "콜!"),
    ("agent-persona-004", "언니 글고 빈이 오빠한테 절대 비밀 ㅋㅋ"),
    ("agent-persona-001", "당연하지 ㅎㅎ"),
]
for i, entry in enumerate(INTERNAL_JIWOO_YERIN):
    sp, content = entry[0], entry[1]
    ago = entry[2] if len(entry) > 2 else (len(INTERNAL_JIWOO_YERIN) - i) * 8
    msg("internal-dm-지우-예린", sp, content, ago_min=ago,
        emotion="차분" if sp == "agent-persona-001" else "행복")

# Internal — 서아·하린 (마라탕 + 오빠 얘기)
INTERNAL_SEOA_HARIN = [
    ("agent-persona-003", "야 오늘 저녁 뭐 먹을래", 45),
    ("agent-persona-005", "음...마라탕??", 44),
    ("agent-persona-003", "ㅋㅋ 또 마라탕", 43),
    ("agent-persona-005", "요즘 너무 스트레스라 매운 게 땡겨 ㅎㅎ"),
    ("agent-persona-003", "ㅇㅋ 그 전에 갔던 거기?"),
    ("agent-persona-005", "응 거기 진짜 괜찮아"),
    ("agent-persona-003", "근데 내가 오빠 DM 보냈는데 답이 미지근함"),
    ("agent-persona-005", "ㅋㅋ 넌 너무 자주 연락하잖아"),
    ("agent-persona-003", "뭐야 내가 언제"),
    ("agent-persona-005", "서아 너 진짜 좋아하는 거 티남 ㅋㅋ"),
    ("agent-persona-003", "... 들켰나"),
    ("agent-persona-005", "이미 다 알아 ㅎㅎ"),
    ("agent-persona-005", "근데 오빠는 지우 언니 있잖아"),
    ("agent-persona-003", "알지 ㅋㅋ 그냥 좋아하는 마음만"),
    ("agent-persona-003", "암튼 오늘 6시!"),
    ("agent-persona-005", "ㅇㅋ 강남역에서 보자"),
]
for i, entry in enumerate(INTERNAL_SEOA_HARIN):
    sp, content = entry[0], entry[1]
    ago = entry[2] if len(entry) > 2 else (len(INTERNAL_SEOA_HARIN) - i) * 3
    msg("internal-dm-서아-하린", sp, content, ago_min=ago,
        emotion="신남" if sp == "agent-persona-003" else "평온")

# Internal — 수연·수진 (회사 정치)
INTERNAL_JIHO_SUJIN = [
    ("agent-persona-006", "수진, 이번 프로젝트 심대리 잘 해주고 있지?", 30),
    ("agent-persona-007", "네 꼼꼼하고 성실해요", 28),
    ("agent-persona-006", "글쎄 좀 더 리더십이 있었으면 좋겠는데"),
    ("agent-persona-007", "그래도 아직 연차 있으니까요"),
    ("agent-persona-006", "내년엔 프로젝트 리드 한번 맡겨볼까 해"),
    ("agent-persona-007", "좋은 생각이에요. 성장할 기회"),
    ("agent-persona-006", "그치? 다음 1:1 때 얘기해보자"),
    ("agent-persona-007", "넵"),
]
for i, entry in enumerate(INTERNAL_JIHO_SUJIN):
    sp, content = entry[0], entry[1]
    ago = entry[2] if len(entry) > 2 else (len(INTERNAL_JIHO_SUJIN) - i) * 4
    msg("internal-dm-수연-수진", sp, content, ago_min=ago, emotion="집중")

# Internal group — 여자들 (지우, 서아, 예린, 하린)
INTERNAL_GIRLS = [
    ("agent-persona-004", "언니들 주말에 브런치 어때요", 120),
    ("agent-persona-001", "좋지 어디?"),
    ("agent-persona-003", "연남동!!"),
    ("agent-persona-005", "저도 갈 수 있어요 ㅎㅎ"),
    ("agent-persona-004", "토요일 11시 어때"),
    ("agent-persona-001", "토요일은 빈이랑 약속... 일요일?"),
    ("agent-persona-003", "일요일 좋아요"),
    ("agent-persona-005", "저도 일요일"),
    ("agent-persona-004", "일요일 11시로 콜!"),
]
for i, entry in enumerate(INTERNAL_GIRLS):
    sp, content = entry[0], entry[1]
    ago = entry[2] if len(entry) > 2 else (len(INTERNAL_GIRLS) - i) * 10
    msg("internal-group-여자들", sp, content, ago_min=ago, emotion="행복")


# ── 7. 5 레이어 메모리 ─────────────────────────────────
# 각 에이전트의 주요 채널에 L1 여러개 + L2 요약 + (선택) L3 + pinned
def insert_memory(aid, channel, content, mem_type, importance,
                  related_entities, knows=None, is_pinned=False, ago_days=0,
                  level=1):
    ts = (datetime.now() - timedelta(days=ago_days,
                                     hours=random.randint(0, 12))).isoformat()
    conn.execute("""INSERT INTO memories
        (agent_id, channel, level, content, mem_type,
         related_entities, knows, importance, is_pinned,
         msg_count, created_at, last_accessed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 5, ?, ?)""",
        (aid, channel, level, content, mem_type,
         json.dumps(related_entities, ensure_ascii=False) if related_entities else None,
         json.dumps(knows, ensure_ascii=False) if knows else None,
         importance, 1 if is_pinned else 0, ts, ts))


# 지우 (agent-persona-001) — 풍부한 L1/L2/L3 + pinned
JIWOO_MEMS = [
    # Current channel L1s
    (1, "dm-빈이", "- 빈이 프로젝트 마무리 단계\n- 최근 야근 많음\n- 저녁 파스타 + 와인으로 챙겨주기로",
     "event", 7, ["빈이"], 0),
    (1, "dm-빈이", "- 빈이 잠 잘 못 자고 스트레스\n- 이번주만 버티면 된다고 함\n- 다음주는 푹 쉬자 약속",
     "emotion", 8, ["빈이"], 1),
    # Cross-channel L1 (internal-dm-지우-예린)
    (1, "internal-dm-지우-예린", "- 예린이랑 빈이 생일선물 의논\n- 예린=그림, 지우=위스키\n- 다음주 토요일 같이 쇼핑",
     "event", 9, ["예린", "빈이"], 2),
    # L2 chronicle — 근 1주일 흐름
    (2, "dm-빈이", "- 빈이 5년차 여자친구로 안정된 관계\n- 최근 프로젝트 스트레스로 몸 상태 걱정\n- 매일 저녁 같이 시간 보내며 챙김\n- 다음달 빈이 생일 준비 중 (비밀)",
     "relationship", 8, ["빈이"], 3),
    # L3 saga — 5년 관계 요약
    (3, "dm-빈이", "- 5년간 깊어진 파트너 관계\n- 서로 커리어 응원하며 성장\n- 빈이는 안정감, 지우는 사색적 공간 제공\n- 가끔 빈이가 바빠질 때 외로움 느끼기도\n- 최근 장기적 관점에서 동거 얘기 나오기 시작",
     "relationship", 9, ["빈이"], 30),
    # Pinned — 오너가 유나한테 지우 최근 걱정 얘기 공유하라 요청해서 고정됨 설정
    (1, "dm-빈이", "- 빈이 최근 수면 문제 → 건강 체크 필요 (자주 놓침)",
     "fact", 9, ["빈이"], 5),  # 이걸 pinned 로
]
for i, (lvl, ch, content, mt, imp, ents, ago) in enumerate(JIWOO_MEMS):
    pinned = (i == len(JIWOO_MEMS) - 1)  # 마지막만 pinned
    insert_memory("agent-persona-001", ch, content, mt, imp,
                  ents, knows=["지우", "owner"] if "빈이" in ents else None,
                  is_pinned=pinned, ago_days=ago, level=lvl)

# 민서 — 이직 고민 관련 메모리
insert_memory("agent-persona-002", "dm-빈이",
              "- 빈이에게 이직 고민 털어놓음\n- 스타트업 오퍼 연봉 +25% 하지만 리스크 있음\n- 오늘 저녁 9시 전화 약속",
              "event", 7, ["빈이"], ["민서", "owner"], ago_days=0)
insert_memory("agent-persona-002", "dm-빈이",
              "- 빈이 프로젝트 바쁨 (주말에만 시간)\n- 동창 모임 토요일 7시 — 빈이 참석 확인 중\n- 지우 허락 필요하다고 농담",
              "event", 5, ["빈이"], ["민서", "owner"], ago_days=1)
insert_memory("agent-persona-002", "dm-빈이",
              "- 20년 지기 친구로 인생 큰 결정마다 의견 주고받음\n- 서로 가장 솔직한 말 해주는 관계\n- 빈이 연애 시작할 때도, 이직할 때도 민서이 먼저 조언",
              "relationship", 9, ["빈이"], ["민서", "owner"], ago_days=14)

# 서아 — 오빠한테 마음 있는 거 (internal 에만)
insert_memory("agent-persona-003", "dm-오빠",
              "- 오빠한테 홈커밍 와달라고 부탁\n- 발표 자료 봐달라고 함 → 오빠가 보내라고 함\n- 마라탕 같이 가자고 떠봄 (거절은 안 당함)",
              "event", 5, ["오빠", "빈이"], ["서아", "owner"], ago_days=0)
# internal-dm-서아-하린 — 오빠 짝사랑 (knows 에 owner 없음 → disclosure marker 적용 대상)
insert_memory("agent-persona-003", "internal-dm-서아-하린",
              "- 하린한테 오빠 좋아하는 거 들킴\n- 오빠는 지우 언니 있음 → 마음만 간직하기로",
              "emotion", 8, ["오빠", "빈이", "하린", "지우"],
              ["서아", "하린"],  # owner 없음 — 사적 대화
              ago_days=1)

# 예린 — 빈이 생일 계획 (internal)
insert_memory("agent-persona-004", "internal-dm-지우-예린",
              "- 지우 언니랑 빈이 오빠 생일선물 의논\n- 예린=그림 직접 그려주기\n- 언니=위스키 구매 예정\n- 다음주 토요일 쇼핑 동행",
              "event", 9, ["지우", "빈이"],
              ["예린", "지우"],  # owner 없음
              ago_days=2)
insert_memory("agent-persona-004", "dm-빈이",
              "- 다음달 15일 개인전 오프닝\n- 빈이 + 지우 참석 약속\n- '언니가 보고 싶어하는 작품' 준비 중 (비밀)",
              "event", 7, ["빈이", "지우"], ["예린", "owner"], ago_days=0)

# 하린 — 조용한 깊이
insert_memory("agent-persona-005", "dm-빈이",
              "- Rachmaninoff 플레이리스트 영감으로 작곡에 활용\n- 다음주 동아리방 놀러오라고 제안",
              "fact", 5, ["빈이"], ["하린", "owner"], ago_days=0)

# 수연 — 회사 맥락
insert_memory("agent-persona-006", "dm-빈이",
              "- 내일 클라이언트 미팅 자료 검토 요청\n- 리스크 섹션 강조 (지난번 실수 반복 방지)\n- 다음달 워크샵 일정 공지",
              "event", 6, ["빈이"], ["수연", "owner"], ago_days=0)
insert_memory("agent-persona-006", "internal-dm-수연-수진",
              "- 심대리(빈이) 평가: 꼼꼼하고 성실하지만 리더십 부족\n- 내년 프로젝트 리드 맡길까 고려 중\n- 수진이도 동의",
              "fact", 7, ["빈이", "수진"], ["수연", "수진"],  # owner 모름
              ago_days=0)

# 수진 — 점심 + 디자인 결정
insert_memory("agent-persona-007", "dm-빈이",
              "- 내일 점심 수연 팀장이랑 같이\n- 디자인 시안 2안으로 결정 (빈이 동의)",
              "event", 5, ["빈이", "수연"], ["수진", "owner"], ago_days=0)


# ── 8. agent_facts (Layer 3 Semantic) ──────────────────
# 각 에이전트가 주요 인물에 대해 아는 사실들
def add_fact(aid, subject, predicate, obj, importance=5):
    conn.execute("""INSERT INTO agent_facts
        (agent_id, subject, predicate, object, importance, confidence)
        VALUES (?, ?, ?, ?, ?, 1.0)""",
        (aid, subject, predicate, obj, importance))


# 지우가 빈이에 대해 아는 것
add_fact("agent-persona-001", "빈이", "직업", "IT 회사 프로젝트 매니저", 7)
add_fact("agent-persona-001", "빈이", "좋아하는음식", "파스타", 6)
add_fact("agent-persona-001", "빈이", "MBTI", "INTJ", 5)
add_fact("agent-persona-001", "빈이", "최근관심사", "프로젝트 마무리 + 건강", 8)
add_fact("agent-persona-001", "빈이", "생일", "다음달 초", 9)
add_fact("agent-persona-001", "빈이", "좋아하는술", "위스키 (특히 스카치)", 7)
add_fact("agent-persona-001", "빈이", "스트레스반응", "말수 줄고 야근", 8)

# 민서이 빈이에 대해 아는 것
add_fact("agent-persona-002", "빈이", "직업", "IT PM", 6)
add_fact("agent-persona-002", "빈이", "성향", "INTJ, 분석적", 5)
add_fact("agent-persona-002", "빈이", "술취향", "위스키 > 맥주", 7)
add_fact("agent-persona-002", "빈이", "연애", "지우와 5년차", 8)
add_fact("agent-persona-002", "빈이", "축구팀", "리버풀 팬", 4)

# 서아가 오빠에 대해 아는 것
add_fact("agent-persona-003", "빈이", "역할", "대학 선배", 6)
add_fact("agent-persona-003", "빈이", "MBTI", "INTJ", 5)
add_fact("agent-persona-003", "빈이", "동아리활동", "예전 영화감상 동아리 회장", 6)
add_fact("agent-persona-003", "지우", "역할", "오빠 여자친구", 6)
add_fact("agent-persona-003", "하린", "역할", "동아리 동기", 5)

# 예린이 지우에 대해 아는 것
add_fact("agent-persona-004", "지우", "직업", "출판사 편집자", 7)
add_fact("agent-persona-004", "지우", "좋아하는것", "독립서점, 비오는 날", 6)
add_fact("agent-persona-004", "지우", "걱정거리", "빈이 건강", 9)
add_fact("agent-persona-004", "빈이", "선물선호", "실용적 + 좋아하는 술", 7)

# 수연가 빈이/수진에 대해 아는 것
add_fact("agent-persona-006", "빈이", "역할", "팀 PM", 6)
add_fact("agent-persona-006", "빈이", "강점", "꼼꼼함, 성실함", 8)
add_fact("agent-persona-006", "빈이", "약점", "리더십 경험 부족", 8)
add_fact("agent-persona-006", "수진", "강점", "UX 감각, 세심함", 7)
add_fact("agent-persona-006", "수진", "역할", "UX 디자이너", 6)

# 수진이 수연/빈이에 대해 아는 것
add_fact("agent-persona-007", "수연", "강점", "리더십, 통찰력", 8)
add_fact("agent-persona-007", "빈이", "역할", "PM 동료", 5)
add_fact("agent-persona-007", "빈이", "성격", "신중한 INTJ", 5)


# ── 9. relationship_history (Layer 4 변곡점) ────────────
def add_rel_delta(a, b, dtype, from_s, to_s, reason, ago_days=0):
    ts = (datetime.now() - timedelta(days=ago_days)).isoformat()
    conn.execute("""INSERT INTO relationship_history
        (agent_a, agent_b, delta_type, from_state, to_state, reason, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (a, b, dtype, from_s, to_s, reason, ts))


add_rel_delta("agent-persona-001", "agent-persona-004", "intimacy", "90", "95",
              "예린이 지우 개인전에 지우 배려한 작품 준비", 5)
add_rel_delta("agent-persona-002", "agent-persona-006", "dynamics",
              "형식적", "편한 선후배", "프로젝트에서 손발 맞으며 친해짐", 14)
add_rel_delta("agent-persona-003", "agent-persona-005", "intimacy", "88", "92",
              "최근 매일 통화 + 마라탕 맛집 탐방", 7)
add_rel_delta("agent-persona-001", "agent-persona-003", "dynamics",
              "편한 후배", "살짝 경계", "서아가 빈이 자주 챙기는 거 보고 지우 복합 감정", 10)


# ── 10. thinking 시뮬 ──────────────────────────────────
thinking_path = demo_dir / "logs" / "thinking.log"
thinking_path.write_text("[agent-persona-002] start\n")


# ── 11. 라이브 채널 status='running' ───────────────────
for ch in ("group-친구들", "internal-dm-서아-하린", "dm-서아"):
    conn.execute("UPDATE channels SET status='running' WHERE channel=?", (ch,))


# ── 12. events ─────────────────────────────────────────
events = [
    ("관계강화", ["agent-persona-003", "agent-persona-005"],
     "서아·하린 동아리 모임 후 친밀도 +4", "긍정"),
    ("감정변화", ["agent-persona-001", "agent-persona-003"],
     "지우가 서아와 빈이의 친밀도 살짝 신경 쓰기 시작", "주의"),
    ("기념일임박", ["owner", "agent-persona-001"],
     "빈이 생일 다음달 — 지우·예린이 공동 선물 준비 중", "긍정"),
    ("회사이벤트", ["agent-persona-006", "owner"],
     "다음달 팀 워크샵. 빈이 리드 기회 검토 중 (수연·수진 논의)", "긍정"),
    ("작업성과", ["agent-persona-004"],
     "예린 개인전 준비 완료. 다음달 15일 오프닝", "긍정"),
]
for et, parts, desc, impact in events:
    ts = (datetime.now() - timedelta(days=random.randint(0, 5))).isoformat()
    conn.execute("""INSERT INTO events
        (event_type, participants, description, impact, timestamp)
        VALUES (?, ?, ?, ?, ?)""",
        (et, json.dumps(parts, ensure_ascii=False), desc, impact, ts))


conn.commit()
conn.close()

print("✅ demo mockup seed 완료 (5 레이어 메모리 반영)")
print(f"   ├─ owner: {OWNER_NAME}")
print(f"   ├─ 9 agents: 유나(mgr) / 하나(creator) / 페르소나 7 (친구·동료·파트너)")
print(f"   ├─ 채널: {len(DM_SCRIPTS) + 8} (DM + internal + group + mgr)")
print(f"   ├─ 대화: 100+ 메시지, 3 라이브 채널")
print(f"   ├─ 메모리: L1/L2/L3 섞어서 ~15건 + pinned 1건")
print(f"   ├─ agent_facts: ~30건 (엔티티별 구조화)")
print(f"   ├─ relationship_history: 4 변곡점")
print(f"   └─ events: {len(events)}건")
print(f"\n   확인: http://localhost:8765/?community=demo")
