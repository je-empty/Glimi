"""README/스크린샷용 'demo' 커뮤니티 mockup 데이터 시딩.

실행: python3 scripts/seed_qa_mockup.py
- demo community.db 리셋 (별도 커뮤니티)
- 친구·동료 페르소나 7명 (가족 X) + 다양한 채널 + 메모리 + 라이브
- private 의 아바타 이미지 재사용
"""
import os
import sys
import shutil
import json
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

from src import community
from src import db

community.set_community("demo")

# === 0. 디렉토리 + DB 리셋 ===
demo_dir = ROOT / "communities" / "demo"
demo_dir.mkdir(parents=True, exist_ok=True)
db_path = demo_dir / "community.db"
if db_path.exists():
    db_path.unlink()

# 아바타 복사
demo_avatars = demo_dir / "avatars"
demo_avatars.mkdir(parents=True, exist_ok=True)
private_avatars = ROOT / "communities" / "private" / "avatars"
for src in private_avatars.glob("*.png"):
    shutil.copy(src, demo_avatars / src.name)

# 로그
logs_dir = demo_dir / "logs"
logs_dir.mkdir(parents=True, exist_ok=True)
(logs_dir / "system.log").write_text("[seed] mockup loaded\n")

# .env (DISCORD_BOT_TOKEN 자리만 비워둠 — 봇 안 띄울 거라 OK)
env_path = demo_dir / ".env"
if not env_path.exists():
    env_path.write_text("DISCORD_BOT_TOKEN=mockup-no-token\n")

db.init_db()
conn = db.get_conn()

# === 1. 오너 ===
OWNER_NAME = "빈이"
conn.execute("""
INSERT INTO users (id, name, age, mbti, personality)
VALUES (?, ?, ?, ?, ?)
""", ("owner", OWNER_NAME, 27, "INTJ",
      json.dumps({"gender": "남자", "nickname": OWNER_NAME}, ensure_ascii=False)))
conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('active_user_id', 'owner')")

# === 2. 시스템 에이전트 ===
def insert_agent(aid, atype, name, age, gender, mbti, background,
                 current_emotion="평온", intensity=5):
    conn.execute("""
    INSERT INTO agents (id, type, name, status, current_emotion, emotion_intensity,
                        birth_year, age, gender, mbti, background, avatar_filename, version, created_at)
    VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
    """, (aid, atype, name, current_emotion, intensity,
          2026 - age, age, gender, mbti, background, f"{aid}.png", datetime.now().isoformat()))

insert_agent("agent-mgr-001", "mgr", "유나", 24, "여자", "ENFJ",
             "Glimi 커뮤니티 매니저. 친근하고 정리 잘하는 누나 같은 존재.")
insert_agent("agent-creator-001", "creator", "하나", 22, "여자", "INFP",
             "신규 멤버 온보딩 + 페르소나 디자이너. 다정하고 창의적.")

# === 3. 페르소나 7명 (친구·동료 only — 가족 X) ===
personas = [
    ("agent-persona-001", "지우", 21, "여자", "INFJ",
     "조용하고 책 좋아하는 국문과 학생. 빈이의 오랜 여자친구.",
     "차분", 6, ["조용한", "다정한", "사려깊은"],
     ["책", "비 오는 날 카페", "산책"],
     "여자친구", "5년차"),
    ("agent-persona-002", "도윤", 25, "남자", "ESTP",
     "빈이의 소꿉친구. 활발하고 직설적. IT 회사 다님.",
     "활기", 8, ["활발한", "직설적", "리더십"],
     ["축구", "맥주", "여행"],
     "소꿉친구", "20년 지기"),
    ("agent-persona-003", "서아", 22, "여자", "ESFP",
     "빈이의 대학 후배. 톡톡 튀는 성격, 빈이를 잘 따름.",
     "신남", 9, ["밝은", "애교있는", "에너지"],
     ["디저트", "K-POP", "쇼핑"],
     "대학 후배", "3년"),
    ("agent-persona-004", "예린", 21, "여자", "ENFP",
     "지우의 대학 절친. 미술 전공. 톡톡 튀고 따뜻함.",
     "행복", 7, ["에너지있는", "예술적", "솔직한"],
     ["그림", "전시회", "산책"],
     "여자친구의 절친", "3년"),
    ("agent-persona-005", "하린", 19, "여자", "INFP",
     "빈이의 동아리 후배. 조용하지만 속 깊은 타입.",
     "평온", 5, ["조용한", "감성적", "배려심 있는"],
     ["음악", "사진", "고양이"],
     "동아리 후배", "2년"),
    ("agent-persona-006", "지호", 26, "남자", "ENTJ",
     "빈이 회사 선배. 똑부러지고 일 잘하기로 유명함.",
     "집중", 7, ["체계적", "리더형", "통찰력 있는"],
     ["커피", "헬스", "독서"],
     "회사 선배", "2년차"),
    ("agent-persona-007", "수진", 24, "여자", "ISFJ",
     "빈이 회사 동료. 차분하고 일 깔끔하게 처리.",
     "차분", 6, ["성실한", "헌신적", "따뜻한"],
     ["요리", "꽃", "독서"],
     "회사 동료", "1년"),
]

for aid, name, age, gender, mbti, bg, emo, intens, traits, likes, rel_type, duration in personas:
    insert_agent(aid, "persona", name, age, gender, mbti, bg, emo, intens)
    conn.execute("INSERT INTO agent_personality (agent_id, data) VALUES (?, ?)",
                 (aid, json.dumps({"traits": traits, "likes": likes,
                                   "dislikes": ["거짓말", "무례함"],
                                   "values": "관계와 진심"}, ensure_ascii=False)))
    conn.execute("INSERT INTO agent_appearance (agent_id, data) VALUES (?, ?)",
                 (aid, json.dumps({"summary": f"{age}세 {gender} 페르소나",
                                   "height": f"{160 + (hash(aid) % 15)}cm",
                                   "hair": "어깨 길이 검은 머리",
                                   "fashion_style": "캐주얼 + 깔끔"}, ensure_ascii=False)))
    conn.execute("INSERT INTO agent_daily_life (agent_id, data) VALUES (?, ?)",
                 (aid, json.dumps({"occupation": "대학생/직장인",
                                   "routine": "오전 학교/회사 → 저녁 운동 → 밤 휴식"}, ensure_ascii=False)))
    conn.execute("INSERT INTO agent_speech (agent_id, data) VALUES (?, ?)",
                 (aid, json.dumps({"style_description": f"{traits[0]} 말투, 반말",
                                   "honorific": "casual",
                                   "signature_expressions": ["ㅎㅎ", "헐", "그치"],
                                   "emoji_pattern": "가끔 ㅋㅋ + 이모지"}, ensure_ascii=False)))
    conn.execute("""INSERT INTO agent_relationship_templates
                    (agent_id, target_id, rel_type, duration, dynamics, pet_name, is_owner_relationship)
                    VALUES (?, 'owner', ?, ?, ?, ?, 1)""",
                 (aid, rel_type, duration, f"{rel_type} 관계, {duration}", OWNER_NAME))

# === 4. 관계 (가족 관계 제외) ===
rel_pairs = [
    ("agent-persona-001", "agent-persona-002", "친구", 80, "빈이를 통해 알게 된 사이"),
    ("agent-persona-001", "agent-persona-004", "절친", 95, "대학 동기, 매일 연락"),
    ("agent-persona-003", "agent-persona-005", "절친", 92, "동아리 선후배"),
    ("agent-persona-002", "agent-persona-006", "동료", 70, "회사 미팅에서 친해짐"),
    ("agent-persona-004", "agent-persona-005", "친구", 65, "지우 통해 알게 됨"),
    ("agent-persona-006", "agent-persona-007", "동료", 75, "같은 팀"),
    ("agent-persona-002", "agent-persona-003", "지인", 50, "빈이 모임에서 만남"),
    ("agent-mgr-001", "agent-creator-001", "동료", 85, "Glimi 시스템 동료"),
]
for a, b, rt, intim, dyn in rel_pairs:
    conn.execute("""INSERT INTO relationships (agent_a, agent_b, type, intimacy_score, dynamics)
                    VALUES (?, ?, ?, ?, ?)""", (a, b, rt, intim, dyn))

# === 5. 채널 ===
def add_channel(name, participants, status='idle', max_turns=0):
    conn.execute("""INSERT INTO channels (channel, participants, status, max_turns, created_at)
                    VALUES (?, ?, ?, ?, ?)""",
                 (name, json.dumps(participants, ensure_ascii=False),
                  status, max_turns, datetime.now().isoformat()))

# DM
for aid, name, *_ in personas:
    add_channel(f"dm-{name}", [aid])

# Manager / Creator
add_channel("mgr-dashboard", ["agent-mgr-001"])
add_channel("mgr-creator", ["agent-creator-001"])

# 그룹 채널 (가족 X)
add_channel("group-친구들", ["agent-persona-001", "agent-persona-002", "agent-persona-004"])
add_channel("group-동아리", ["agent-persona-003", "agent-persona-005"])
add_channel("group-회사", ["agent-persona-002", "agent-persona-006", "agent-persona-007"])

# Internal (에이전트끼리)
add_channel("internal-dm-지우-예린", ["agent-persona-001", "agent-persona-004"])
add_channel("internal-dm-서아-하린", ["agent-persona-003", "agent-persona-005"])

# === 6. 대화 ===
def msg(channel, speaker, content, ago_min=0):
    ts = (datetime.now() - timedelta(minutes=ago_min)).isoformat()
    conn.execute("""INSERT INTO conversations (channel, speaker, message, timestamp, context_emotion)
                    VALUES (?, ?, ?, ?, '평온')""", (channel, speaker, content, ts))

dm_scripts = {
    "dm-지우": [
        ("owner", "오늘 회사 어땠어?"),
        ("agent-persona-001", "응 평소랑 비슷! 너는?"),
        ("owner", "프로젝트 마무리 단계라 정신없었어 ㅠㅠ"),
        ("agent-persona-001", "저녁에 같이 영화 볼래? 새로 받아놨거든"),
        ("owner", "좋지! 7시쯤 갈게"),
        ("agent-persona-001", "응 그럼 간단히 파스타 해놓을게~"),
    ],
    "dm-도윤": [
        ("agent-persona-002", "야 빈이 이번 주말 시간 있냐"),
        ("owner", "왜?"),
        ("agent-persona-002", "동창들이랑 한잔 하기로 했음"),
        ("owner", "토요일 저녁이면 가능"),
        ("agent-persona-002", "콜! 7시 강남"),
    ],
    "dm-서아": [
        ("agent-persona-003", "오빠ㅋㅋ"),
        ("owner", "왜"),
        ("agent-persona-003", "다음주 동아리 모임 오시죠?"),
        ("owner", "갈 수 있으면 갈게"),
        ("agent-persona-003", "꼭 오세요 헤헤"),
    ],
    "dm-예린": [
        ("owner", "예린아 이번에 전시 준비하는거 어때?"),
        ("agent-persona-004", "오빠! 거의 다 했어요 ㅎㅎ 다음달에 오세요!"),
        ("owner", "당연하지 지우랑 같이 갈게"),
    ],
    "dm-하린": [
        ("agent-persona-005", "선배 안녕하세요"),
        ("owner", "하린이 잘 지내?"),
        ("agent-persona-005", "네 ㅎㅎ 동아리 발표 자료 봐주실 수 있어요?"),
    ],
    "dm-지호": [
        ("agent-persona-006", "심대리, 내일 미팅 자료 검토 좀"),
        ("owner", "넵 오늘 안에 보내드릴게요"),
    ],
    "dm-수진": [
        ("agent-persona-007", "심대리 점심 같이 할까요?"),
        ("owner", "오케이 12시"),
    ],
}
for ch, lines in dm_scripts.items():
    for i, (sp, content) in enumerate(lines):
        msg(ch, sp, content, ago_min=(len(lines) - i) * 7)

msg("mgr-dashboard", "agent-mgr-001", "빈이님 안녕하세요~ 매니저 유나에요 :)", 90)
msg("mgr-dashboard", "owner", "안녕하세요!", 88)
msg("mgr-dashboard", "agent-mgr-001", "친구들 다 잘 지내고 있어요. 오늘 동아리 채팅 활발했어요 ㅎㅎ", 5)
msg("mgr-dashboard", "agent-mgr-001", "프로필 수정 필요하시면 말씀하세요~", 3)
msg("mgr-creator", "agent-creator-001", "빈이님~ 오늘 새 친구 만들어드릴까요?", 30)
msg("mgr-creator", "owner", "음 일단 충분한 것 같아", 28)

msg("group-친구들", "owner", "이번 주말 술 한잔 어때?", 60)
msg("group-친구들", "agent-persona-002", "콜!", 59)
msg("group-친구들", "agent-persona-001", "나는 토요일 가능", 58)
msg("group-친구들", "agent-persona-004", "저도 토요일 좋아요!", 57)
msg("group-친구들", "agent-persona-002", "그럼 토요일 7시 강남에서~", 56)

msg("group-동아리", "agent-persona-003", "다음주 모임 오시죠 선배?", 25)
msg("group-동아리", "agent-persona-005", "오빠 발표 자료 봐주신다고 했는데 시간 되세요?", 23)

msg("group-회사", "agent-persona-006", "심대리 보고 자료 확인했어요", 10)
msg("group-회사", "agent-persona-002", "수고하셨습니다!", 9)
msg("group-회사", "agent-persona-007", "내일 점심 다같이 할까요?", 8)

msg("internal-dm-지우-예린", "agent-persona-001", "예린아 빈이 회사 너무 바빠 보여 걱정돼", 40)
msg("internal-dm-지우-예린", "agent-persona-004", "언니가 챙겨주고 있잖아요 ㅎㅎ 너무 걱정마요!", 39)
msg("internal-dm-서아-하린", "agent-persona-003", "야 오늘 동아리 끝나고 뭐 먹을까", 15)
msg("internal-dm-서아-하린", "agent-persona-005", "마라탕? ㅋㅋ", 14)

# 라이브 채널 — 최근 1분 내
msg("group-친구들", "agent-persona-002", "내일 메뉴 뭐 먹을지 정해놨음??", 0)
msg("internal-dm-서아-하린", "agent-persona-003", "콜 마라탕!!", 0)
msg("dm-서아", "agent-persona-003", "오빠 ㅋㅋㅋ 내일 약속 잊지마요", 0)

# === 7. 메모리 ===
mem_data = [
    ("agent-persona-001", "dm-지우",
     ["빈이 프로젝트 마무리로 야근 → 저녁에 영화 보기로 함",
      "빈이 회사 일에 스트레스 받는 중. 위로 필요",
      "다음 주말에 회사 동료 모임 — 동행 약속"],
     "빈이 최근 프로젝트 마무리로 바쁘고 스트레스 받는 시기. 둘이 영화/저녁 같이하며 평온한 시간 보내려 노력. 5년차 안정된 관계."),
    ("agent-persona-003", "dm-서아",
     ["다음주 동아리 모임 — 오빠 초대",
      "오빠가 동아리 발표 자료 봐주기로 함",
      "다음 학기 진로 고민 상담"],
     "선배 빈이를 잘 따르는 후배. 자주 챙겨달라 부탁하고 빈이는 챙겨주는 패턴."),
    ("agent-persona-002", "dm-도윤",
     ["주말 동창모임 토요일 7시 강남",
      "빈이 결혼 얘기 살짝 던져봄 → 무반응",
      "회사 이직 고민 중 — 빈이에게 조언 구함"],
     "20년 지기 친구. 인생 큰 결정마다 서로 의견 주고받음."),
    ("agent-persona-006", "dm-지호",
     ["내일 클라이언트 미팅 자료 검토 부탁",
      "빈이의 프로젝트 진행 상황 점검",
      "팀 회식 일정 조율"],
     "팀 선배로서 빈이를 챙기지만 일 관련 디테일에 깐깐. 빈이가 잘 따르는 편."),
]
for aid, channel, l1_list, l2_text in mem_data:
    for i, content in enumerate(l1_list):
        ts = (datetime.now() - timedelta(hours=i + 1)).isoformat()
        conn.execute("""INSERT INTO memories (agent_id, channel, level, content, created_at)
                        VALUES (?, ?, 1, ?, ?)""", (aid, channel, content, ts))
    ts = (datetime.now() - timedelta(days=1)).isoformat()
    conn.execute("""INSERT INTO memories (agent_id, channel, level, content, created_at)
                    VALUES (?, ?, 2, ?, ?)""", (aid, channel, l2_text, ts))

# === 8. thinking 시뮬 ===
thinking_path = ROOT / "communities" / "demo" / "logs" / "thinking.log"
thinking_path.write_text("[agent-persona-002] start\n")

# === 9. 라이브 채널 status='running' ===
for ch in ("group-친구들", "internal-dm-서아-하린", "dm-서아"):
    conn.execute("UPDATE channels SET status='running' WHERE channel=?", (ch,))

# === 10. events ===
events = [
    ("관계강화", json.dumps(["agent-persona-003", "agent-persona-005"], ensure_ascii=False),
     "서아와 하린 동아리 모임 후 친밀도 +5", "긍정"),
    ("긴장", json.dumps(["agent-persona-001", "agent-persona-002"], ensure_ascii=False),
     "도윤이 결혼 얘기 꺼내자 지우 잠시 어색해함. 후속 대화 필요", "주의"),
    ("축하", json.dumps(["agent-persona-004"], ensure_ascii=False),
     "예린이 전시 준비 완료. 다음달 오프닝 예정", "긍정"),
]
for et, parts, desc, impact in events:
    conn.execute("""INSERT INTO events (event_type, participants, description, impact, timestamp)
                    VALUES (?, ?, ?, ?, ?)""",
                 (et, parts, desc, impact, datetime.now().isoformat()))

conn.commit()
conn.close()

print("✅ demo mockup seed 완료.")
print(f"   - owner: {OWNER_NAME}")
print(f"   - 9 agents: 유나(mgr) / 하나(creator) / 페르소나 7명 (친구·동료)")
print(f"   - {len(dm_scripts) + 5} 채널 (DM/group/internal/mgr)")
print(f"   - L1/L2 memory: 4명")
print(f"   - 3 라이브 채널")
print(f"   확인: http://localhost:8765/?community=demo")
