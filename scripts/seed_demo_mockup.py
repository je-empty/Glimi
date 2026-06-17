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

import-safe: 모든 부작용은 `seed()` 안에서만 일어난다. import 만 하면 아무 것도
안 한다 (첫 실행 자동 시딩에서 ensure_demo_seeded 가 import → seed() 호출).
"""
import json
import os
import random
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _copy_seed_avatars(dest_dir: Path) -> None:
    """demo 프로필 이미지 디렉터리에 아바타 복사 (best-effort, never crash).

    소스 우선순위:
      1) communities/private/profile_images  (개발 머신에만 있음 — gitignore)
      2) 커밋된 폴백: assets/sample_profile_images, assets/profile_images
    셋 다 없으면 그냥 스킵 (아바타는 serve_avatar 가 placeholder SVG 로 폴백).
    신선한 클론(communities/·data/ 없음)에서도 깨지지 않아야 한다.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in dest_dir.glob("*.png"):
        try:
            f.unlink()
        except OSError:
            pass

    candidates = [
        ROOT / "communities" / "private" / "profile_images",
        ROOT / "assets" / "sample_profile_images",
        ROOT / "assets" / "profile_images",
    ]
    src_dir = next((c for c in candidates if c.exists()), None)
    if src_dir is None:
        return
    for src in src_dir.glob("*.png"):
        try:
            shutil.copy(src, dest_dir / src.name)
        except OSError:
            pass


def seed(community_id: str = "demo") -> None:
    """demo mockup 데이터를 community_id 커뮤니티에 시딩한다 (DB·env·아바타·대화).

    멱등성: community.db 를 매번 리셋하므로 재호출 시 같은 결과로 덮어쓴다.
    호출 측(ensure_demo_seeded)은 디렉터리 존재 여부로 재시드를 가드한다.
    """
    from src import community
    from src import db

    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    community.set_community(community_id)

    # ── 0. 디렉터리 + DB 리셋 ─────────────────────────────────
    demo_dir = ROOT / "communities" / community_id
    demo_dir.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-shm", "-wal"):
        p = demo_dir / f"community.db{suffix}"
        if p.exists():
            p.unlink()

    # 프로필 이미지 복사 (private 우선, 없으면 커밋된 assets 폴백)
    demo_profile_images = demo_dir / "profile_images"
    _copy_seed_avatars(demo_profile_images)

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

    # ── 1. 오너 (사용자) ────────────────────────────────────────
    OWNER_NAME = "사용자"
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
                 "신규 멤버 튜토리얼 + 페르소나 디자이너. 다정하고 창의적.")


    # ── 3. 페르소나 7명 (순수 친구 관계만 — 연인/동료/가족 X) ─────────
    personas = [
        {
            "id": "agent-persona-001", "name": "소은", "age": 24, "gender": "여자",
            "mbti": "INFJ", "enneagram": "2",
            "bg": "독서 모임에서 알게 된 친구. 책·글쓰기 좋아함. 조용하고 깊이 있게 대화하는 스타일.",
            "emotion": "차분", "intensity": 6,
            "traits": ["조용한", "다정한", "사려깊은", "공감능력 좋음"],
            "likes": ["책", "비 오는 날 카페", "산책", "독립서점"],
            "dislikes": ["시끄러운 곳", "거짓말"],
            "rel_owner": "친구", "duration": "3년", "pet_name": "사용자",
            "occupation": "출판사 편집자",
            "routine": "아침 책방 → 오후 작업 → 저녁 친구들이랑 카페",
        },
        {
            "id": "agent-persona-002", "name": "민서", "age": 27, "gender": "여자",
            "mbti": "ESTP", "enneagram": "7",
            "bg": "초등학교부터 친구. 옆 동네 살아서 자주 붙어다님. 편하게 반말·욕설까지 가능.",
            "emotion": "활기", "intensity": 8,
            "traits": ["활발한", "직설적", "의리파", "솔직한"],
            "likes": ["러닝", "크래프트 맥주", "여행", "보드게임"],
            "dislikes": ["위선", "복잡한 설명"],
            "rel_owner": "소꿉친구", "duration": "20년 지기", "pet_name": "야",
            "occupation": "백엔드 개발자",
            "routine": "오전 작업 → 저녁 러닝 or 친구들 → 주말 여행",
        },
        {
            "id": "agent-persona-003", "name": "서아", "age": 22, "gender": "여자",
            "mbti": "ESFP", "enneagram": "7",
            "bg": "대학 후배로 학과 행사에서 알게 됨. 활발하고 밝음. 모임 분위기 메이커.",
            "emotion": "신남", "intensity": 9,
            "traits": ["밝은", "애교있는", "에너지", "즉흥적"],
            "likes": ["디저트", "K-POP", "쇼핑", "사진"],
            "dislikes": ["우울한 분위기"],
            "rel_owner": "친구", "duration": "3년", "pet_name": "사용자",
            "occupation": "대학생 (4학년)",
            "routine": "학교 → 카페 공부 → 친구들과",
        },
        {
            "id": "agent-persona-004", "name": "예린", "age": 24, "gender": "여자",
            "mbti": "ENFP", "enneagram": "4",
            "bg": "소은 통해 알게 된 친구. 일러스트레이터, 프리랜서. 작년 개인전 열었음. 감성적이고 수다스러움.",
            "emotion": "행복", "intensity": 7,
            "traits": ["에너지있는", "예술적", "솔직한", "감성적"],
            "likes": ["그림", "전시회", "산책", "수채화"],
            "dislikes": ["정해진 틀"],
            "rel_owner": "친구", "duration": "3년", "pet_name": "사용자",
            "occupation": "프리랜서 일러스트레이터",
            "routine": "아침 작업 → 오후 카페/전시 → 저녁 소은랑 가끔",
        },
        {
            "id": "agent-persona-005", "name": "하린", "age": 20, "gender": "여자",
            "mbti": "INFP", "enneagram": "9",
            "bg": "대학 동아리에서 알게 된 후배 친구. 작곡 공부 중. 조용하지만 속 깊음. 서아랑 친함.",
            "emotion": "평온", "intensity": 5,
            "traits": ["조용한", "감성적", "배려심 있는", "깊이있는"],
            "likes": ["음악", "사진", "고양이", "밤 산책"],
            "dislikes": ["강요"],
            "rel_owner": "친구", "duration": "2년", "pet_name": "선배",
            "occupation": "대학생 (3학년)",
            "routine": "학교 → 작곡 연습 → 서아랑 자주 통화",
        },
        {
            "id": "agent-persona-006", "name": "수연", "age": 30, "gender": "여자",
            "mbti": "ENTJ", "enneagram": "8",
            "bg": "헬스장·필라테스 모임에서 알게 된 언니 친구. 깐깐하지만 조언해주는 스타일. 배울 점 많음.",
            "emotion": "집중", "intensity": 7,
            "traits": ["체계적", "리더형", "통찰력 있는", "정직한"],
            "likes": ["커피", "필라테스", "독서", "캠핑"],
            "dislikes": ["준비 안 된 만남", "말만 앞섬"],
            "rel_owner": "친구", "duration": "2년", "pet_name": "사용자",
            "occupation": "프로젝트 매니저",
            "routine": "06시 필라테스 → 저녁 독서/캠핑 계획",
        },
        {
            "id": "agent-persona-007", "name": "수진", "age": 26, "gender": "여자",
            "mbti": "ISFJ", "enneagram": "6",
            "bg": "브런치 모임에서 알게 된 친구. 꼼꼼하고 세심함. 요리·빵 좋아하고 같이 맛집 탐방 자주.",
            "emotion": "차분", "intensity": 6,
            "traits": ["성실한", "헌신적", "따뜻한", "신중한"],
            "likes": ["요리", "꽃", "독서", "브런치"],
            "dislikes": ["성급한 결정"],
            "rel_owner": "친구", "duration": "1년", "pet_name": "사용자",
            "occupation": "UX 디자이너",
            "routine": "작업 → 점심 친구들과 → 저녁 자기계발",
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
        # (a, b, type, intimacy, dynamics) — 모두 친구 계열만
        ("agent-persona-001", "agent-persona-004", "절친", 95, "대학 동기, 매일 연락"),
        ("agent-persona-001", "agent-persona-002", "친구", 72, "사용자 통해 알게 됨. 민서 직설적이라 가끔 부담"),
        ("agent-persona-002", "agent-persona-006", "친구", 68, "러닝·필라테스 모임에서 친해짐. 서로 존중"),
        ("agent-persona-003", "agent-persona-005", "절친", 92, "동아리 선후배, 거의 매일 통화"),
        ("agent-persona-004", "agent-persona-005", "친구", 60, "소은 통해 만남. 예린이 하린 작품 좋아함"),
        ("agent-persona-006", "agent-persona-007", "친구", 82, "브런치·필라테스 모임 같이 다니는 사이"),
        ("agent-persona-001", "agent-persona-003", "지인", 45, "사용자 모임에서 몇 번 — 소은가 서아 스타일 살짝 불편"),
        ("agent-persona-002", "agent-persona-003", "지인", 50, "사용자 모임에서 만남. 서아가 민서 재밌다고 함"),
        ("agent-persona-001", "agent-persona-007", "지인", 55, "사용자 모임에서 만남. 둘 다 조용한 타입 공감"),
        ("agent-mgr-001", "agent-creator-001", "친구", 88, "Glimi 매니저·크리에이터, 서로 의지"),
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
    add_channel("internal-dm-소은-예린", ["agent-persona-001", "agent-persona-004"])
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


    # DM — 소은 (여자친구, 안정적 · 최근 사용자 바쁨 걱정)
    DM_SCRIPTS = {
        "dm-소은": [
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
            ("owner", "소은랑 저녁 약속 있어서..."),
            ("agent-persona-002", "ㅋㅋ 소은 허락 받아오셈"),
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
            ("owner", "소은랑 같이 갈게"),
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
        (90, "agent-mgr-001", "사용자님 안녕하세요~ 매니저 유나에요 :)"),
        (88, "owner", "안녕하세요!"),
        (85, "agent-mgr-001", "오늘 #dm-서아 에서 서아가 다음주 홈커밍 얘기 꺼냈어요. 참여 여부 결정하시면 알려주세요~"),
        (82, "agent-mgr-001", "그리고 소은님이 사용자님 건강 걱정 많이 하시더라구요 (최근 대화 기록 기반)"),
        (75, "owner", "ㅎㅎ 고마워요"),
        (30, "agent-mgr-001", "참고로 오늘 #internal-dm-소은-예린 에서 둘이 사용자님 생일 선물 의논 중이에요 🤫"),
        (15, "agent-mgr-001", "프로필 수정 필요하거나 친구 새로 만들고 싶으시면 #mgr-creator 로 오세요!"),
    ]
    for ago, sp, content in MGR_LINES:
        msg("mgr-dashboard", sp, content, ago_min=ago)

    msg("mgr-creator", "agent-creator-001", "사용자님~ 오늘은 어떻게 오셨어요?", 200)
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

    # Internal — 소은·예린 (사용자 걱정 + 생일 준비)
    INTERNAL_JIWOO_YERIN = [
        ("agent-persona-001", "예린아 사용자 요즘 너무 바빠 보여서 걱정이야", 180),
        ("agent-persona-004", "언니 또 걱정 모드 ㅋㅋ 사용자 오빠 건강한 편이잖아요", 178),
        ("agent-persona-001", "그래도 최근 잠 잘 못 자고 스트레스 받더라", 176),
        ("agent-persona-004", "음 언니가 옆에 있으니 괜찮을 거예요"),
        ("agent-persona-001", "ㅎㅎ 고마워 예린아"),
        ("agent-persona-004", "근데 언니 사용자 오빠 다음달 생일이잖아요", 90),
        ("agent-persona-001", "맞아 뭐 해줄까 고민 중", 88),
        ("agent-persona-004", "제가 그림 그려드리면 어때요?"),
        ("agent-persona-001", "와 너무 좋다 나는 뭐 준비하지"),
        ("agent-persona-004", "오빠가 좋아하는 그 위스키 사드리세요", 85),
        ("agent-persona-001", "오 그거 좋다. 같이 가서 살까?"),
        ("agent-persona-004", "다음주 토요일 어때요 저 시간 돼요"),
        ("agent-persona-001", "콜!"),
        ("agent-persona-004", "언니 글고 사용자 오빠한테 절대 비밀 ㅋㅋ"),
        ("agent-persona-001", "당연하지 ㅎㅎ"),
    ]
    for i, entry in enumerate(INTERNAL_JIWOO_YERIN):
        sp, content = entry[0], entry[1]
        ago = entry[2] if len(entry) > 2 else (len(INTERNAL_JIWOO_YERIN) - i) * 8
        msg("internal-dm-소은-예린", sp, content, ago_min=ago,
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
        ("agent-persona-005", "근데 오빠는 소은 언니 있잖아"),
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

    # Internal group — 여자들 (소은, 서아, 예린, 하린)
    INTERNAL_GIRLS = [
        ("agent-persona-004", "언니들 주말에 브런치 어때요", 120),
        ("agent-persona-001", "좋지 어디?"),
        ("agent-persona-003", "연남동!!"),
        ("agent-persona-005", "저도 갈 수 있어요 ㅎㅎ"),
        ("agent-persona-004", "토요일 11시 어때"),
        ("agent-persona-001", "토요일은 사용자랑 약속... 일요일?"),
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


    # 소은 (agent-persona-001) — 북카페 친구, 일상/취향 중심 (사적·업무 정보 없음)
    JIWOO_MEMS = [
        # Current channel L1s
        (1, "dm-사용자", "- 사용자가 얼마 전 읽은 김애란 단편집 얘기 길게 나눔\n- 다음엔 정세랑 SF 추천해줄 생각\n- 사용자 밑줄 긋는 스타일 좋아한다고",
         "event", 6, ["사용자"], 0),
        (1, "dm-사용자", "- 사용자가 최근 고양이 카페 처음 가봄 → 생각보다 좋았다고\n- 다음에 같이 가자고 제안\n- 사용자 은근 동물 좋아하는 타입",
         "event", 5, ["사용자"], 1),
        (1, "dm-사용자", "- 사용자 요즘 LP 사 모으는 중 (재즈·락 7-80년대)\n- 다음에 카페에 가져오라 함\n- 나도 턴테이블 하나 살까 고민",
         "event", 5, ["사용자"], 2),
        # L2 chronicle
        (2, "dm-사용자", "- 사용자가 알바 시작할 때부터 단골 → 친구로 발전\n- 책·커피·음악 취향 비슷해서 대화 편함\n- 주 3-4번 카톡, 주말엔 가끔 만남",
         "relationship", 8, ["사용자"], 10),
        # Cross-channel
        (1, "internal-dm-소은-예린", "- 예린이랑 사용자 생일 선물 아이디어\n- 예린: 일러스트 그려주기 / 소은: 사용자가 찜해둔 LP 한 장\n- 다음주 쇼핑 동행",
         "event", 7, ["예린", "사용자"], 2),
        # Pinned — 걱정 공유용
        (1, "dm-사용자", "- 사용자가 요즘 잠 잘 못 자서 새벽 산책 한다고\n- 한강 쪽 걷는 루트 공유\n- 가끔 같이 나가자고 얘기",
         "fact", 7, ["사용자"], 3),
        (1, "dm-사용자", "- 사용자가 추천한 독립서점 '책다락' 갔다 옴 → 분위기 엄청 좋았다고\n- 같이 다시 가기로\n- 거기서 본 사진집 하나 사왔다고 자랑",
         "event", 5, ["사용자"], 4),
    ]
    for i, (lvl, ch, content, mt, imp, ents, ago) in enumerate(JIWOO_MEMS):
        # pinned: '새벽 산책' 항목만 (index 5)
        pinned = (i == 5)
        insert_memory("agent-persona-001", ch, content, mt, imp,
                      ents, knows=["소은", "owner"] if "사용자" in ents else None,
                      is_pinned=pinned, ago_days=ago, level=lvl)

    # 민서 — 이직 고민 관련 메모리
    insert_memory("agent-persona-002", "dm-사용자",
                  "- 사용자에게 이직 고민 털어놓음\n- 스타트업 오퍼 연봉 +25% 하지만 리스크 있음\n- 오늘 저녁 9시 전화 약속",
                  "event", 7, ["사용자"], ["민서", "owner"], ago_days=0)
    insert_memory("agent-persona-002", "dm-사용자",
                  "- 사용자 프로젝트 바쁨 (주말에만 시간)\n- 동창 모임 토요일 7시 — 사용자 참석 확인 중\n- 소은 허락 필요하다고 농담",
                  "event", 5, ["사용자"], ["민서", "owner"], ago_days=1)
    insert_memory("agent-persona-002", "dm-사용자",
                  "- 20년 지기 친구로 인생 큰 결정마다 의견 주고받음\n- 서로 가장 솔직한 말 해주는 관계\n- 사용자 연애 시작할 때도, 이직할 때도 민서이 먼저 조언",
                  "relationship", 9, ["사용자"], ["민서", "owner"], ago_days=14)

    # 서아 — 오빠한테 마음 있는 거 (internal 에만)
    insert_memory("agent-persona-003", "dm-오빠",
                  "- 오빠한테 홈커밍 와달라고 부탁\n- 발표 자료 봐달라고 함 → 오빠가 보내라고 함\n- 마라탕 같이 가자고 떠봄 (거절은 안 당함)",
                  "event", 5, ["오빠", "사용자"], ["서아", "owner"], ago_days=0)
    # internal-dm-서아-하린 — 오빠 짝사랑 (knows 에 owner 없음 → disclosure marker 적용 대상)
    insert_memory("agent-persona-003", "internal-dm-서아-하린",
                  "- 하린한테 오빠 좋아하는 거 들킴\n- 오빠는 소은 언니 있음 → 마음만 간직하기로",
                  "emotion", 8, ["오빠", "사용자", "하린", "소은"],
                  ["서아", "하린"],  # owner 없음 — 사적 대화
                  ago_days=1)

    # 예린 — 사용자 생일 계획 (internal)
    insert_memory("agent-persona-004", "internal-dm-소은-예린",
                  "- 소은 언니랑 사용자 오빠 생일선물 의논\n- 예린=그림 직접 그려주기\n- 언니=위스키 구매 예정\n- 다음주 토요일 쇼핑 동행",
                  "event", 9, ["소은", "사용자"],
                  ["예린", "소은"],  # owner 없음
                  ago_days=2)
    insert_memory("agent-persona-004", "dm-사용자",
                  "- 다음달 15일 개인전 오프닝\n- 사용자 + 소은 참석 약속\n- '언니가 보고 싶어하는 작품' 준비 중 (비밀)",
                  "event", 7, ["사용자", "소은"], ["예린", "owner"], ago_days=0)

    # 하린 — 조용한 깊이
    insert_memory("agent-persona-005", "dm-사용자",
                  "- Rachmaninoff 플레이리스트 영감으로 작곡에 활용\n- 다음주 동아리방 놀러오라고 제안",
                  "fact", 5, ["사용자"], ["하린", "owner"], ago_days=0)

    # 수연 — 회사 맥락
    insert_memory("agent-persona-006", "dm-사용자",
                  "- 내일 클라이언트 미팅 자료 검토 요청\n- 리스크 섹션 강조 (지난번 실수 반복 방지)\n- 다음달 워크샵 일정 공지",
                  "event", 6, ["사용자"], ["수연", "owner"], ago_days=0)
    insert_memory("agent-persona-006", "internal-dm-수연-수진",
                  "- 심대리(사용자) 평가: 꼼꼼하고 성실하지만 리더십 부족\n- 내년 프로젝트 리드 맡길까 고려 중\n- 수진이도 동의",
                  "fact", 7, ["사용자", "수진"], ["수연", "수진"],  # owner 모름
                  ago_days=0)

    # 수진 — 점심 + 디자인 결정
    insert_memory("agent-persona-007", "dm-사용자",
                  "- 내일 점심 수연 팀장이랑 같이\n- 디자인 시안 2안으로 결정 (사용자 동의)",
                  "event", 5, ["사용자", "수연"], ["수진", "owner"], ago_days=0)


    # ── 8. agent_facts (Layer 3 Semantic) ──────────────────
    # 각 에이전트가 주요 인물에 대해 아는 사실들
    def add_fact(aid, subject, predicate, obj, importance=5):
        conn.execute("""INSERT INTO agent_facts
            (agent_id, subject, predicate, object, importance, confidence)
            VALUES (?, ?, ?, ?, ?, 1.0)""",
            (aid, subject, predicate, obj, importance))


    # 소은가 사용자에 대해 아는 것 — 취향/일상 중심 (업무·사적 정보 X)
    add_fact("agent-persona-001", "사용자", "좋아하는음악", "재즈·7-80년대 락 · LP 수집", 7)
    add_fact("agent-persona-001", "사용자", "좋아하는책", "김애란·박완서·정세랑", 6)
    add_fact("agent-persona-001", "사용자", "카페취향", "조용한 곳 · 아메리카노 진하게", 6)
    add_fact("agent-persona-001", "사용자", "취미", "독립서점 탐방 · 필사", 5)
    add_fact("agent-persona-001", "사용자", "동물", "고양이 좋아함 (아직 안 키움)", 5)
    add_fact("agent-persona-001", "사용자", "주말루틴", "한강 산책 · 카페 책 읽기", 6)
    add_fact("agent-persona-001", "사용자", "술취향", "위스키 스트레이트", 5)
    add_fact("agent-persona-001", "사용자", "좋아하는음식", "파스타 · 담백한 거", 5)
    add_fact("agent-persona-001", "사용자", "최근고민", "수면 부족 · 새벽 산책", 8)
    add_fact("agent-persona-001", "사용자", "생일", "다음달 초", 7)
    add_fact("agent-persona-001", "예린", "역할", "친한 친구 · 대학 동기", 6)

    # 민서이 사용자에 대해 아는 것
    add_fact("agent-persona-002", "사용자", "직업", "IT PM", 6)
    add_fact("agent-persona-002", "사용자", "성향", "INTJ, 분석적", 5)
    add_fact("agent-persona-002", "사용자", "술취향", "위스키 > 맥주", 7)
    add_fact("agent-persona-002", "사용자", "연애", "소은와 5년차", 8)
    add_fact("agent-persona-002", "사용자", "축구팀", "리버풀 팬", 4)

    # 서아가 오빠에 대해 아는 것
    add_fact("agent-persona-003", "사용자", "역할", "대학 선배", 6)
    add_fact("agent-persona-003", "사용자", "MBTI", "INTJ", 5)
    add_fact("agent-persona-003", "사용자", "동아리활동", "예전 영화감상 동아리 회장", 6)
    add_fact("agent-persona-003", "소은", "역할", "오빠 여자친구", 6)
    add_fact("agent-persona-003", "하린", "역할", "동아리 동기", 5)

    # 예린이 소은에 대해 아는 것
    add_fact("agent-persona-004", "소은", "직업", "출판사 편집자", 7)
    add_fact("agent-persona-004", "소은", "좋아하는것", "독립서점, 비오는 날", 6)
    add_fact("agent-persona-004", "소은", "걱정거리", "사용자 건강", 9)
    add_fact("agent-persona-004", "사용자", "선물선호", "실용적 + 좋아하는 술", 7)

    # 수연가 사용자/수진에 대해 아는 것
    add_fact("agent-persona-006", "사용자", "역할", "팀 PM", 6)
    add_fact("agent-persona-006", "사용자", "강점", "꼼꼼함, 성실함", 8)
    add_fact("agent-persona-006", "사용자", "약점", "리더십 경험 부족", 8)
    add_fact("agent-persona-006", "수진", "강점", "UX 감각, 세심함", 7)
    add_fact("agent-persona-006", "수진", "역할", "UX 디자이너", 6)

    # 수진이 수연/사용자에 대해 아는 것
    add_fact("agent-persona-007", "수연", "강점", "리더십, 통찰력", 8)
    add_fact("agent-persona-007", "사용자", "역할", "PM 동료", 5)
    add_fact("agent-persona-007", "사용자", "성격", "신중한 INTJ", 5)


    # ── 9. relationship_history (Layer 4 변곡점) ────────────
    def add_rel_delta(a, b, dtype, from_s, to_s, reason, ago_days=0):
        ts = (datetime.now() - timedelta(days=ago_days)).isoformat()
        conn.execute("""INSERT INTO relationship_history
            (agent_a, agent_b, delta_type, from_state, to_state, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (a, b, dtype, from_s, to_s, reason, ts))


    add_rel_delta("agent-persona-001", "agent-persona-004", "intimacy", "90", "95",
                  "예린이 소은 개인전에 소은 배려한 작품 준비", 5)
    add_rel_delta("agent-persona-002", "agent-persona-006", "dynamics",
                  "형식적", "편한 선후배", "프로젝트에서 손발 맞으며 친해짐", 14)
    add_rel_delta("agent-persona-003", "agent-persona-005", "intimacy", "88", "92",
                  "최근 매일 통화 + 마라탕 맛집 탐방", 7)
    add_rel_delta("agent-persona-001", "agent-persona-003", "dynamics",
                  "편한 후배", "살짝 경계", "서아가 사용자 자주 챙기는 거 보고 소은 복합 감정", 10)


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
         "소은가 서아와 사용자의 친밀도 살짝 신경 쓰기 시작", "주의"),
        ("기념일임박", ["owner", "agent-persona-001"],
         "사용자 생일 다음달 — 소은·예린이 공동 선물 준비 중", "긍정"),
        ("회사이벤트", ["agent-persona-006", "owner"],
         "다음달 팀 워크샵. 사용자 리드 기회 검토 중 (수연·수진 논의)", "긍정"),
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


    # ── 13. meta + achievements — 튜토리얼 완료 + 일상 진행 상태 ─────
    db.set_meta("tutorial_phase", "complete")
    db.set_meta("yuna_greeted", "1")

    _DONE_ACH = [
        "tutorial_done", "first_friend_chat", "three_friends", "group_chat",
        "peek_internal", "agent_auto_chat", "late_night", "chatter",
        "secret_keeper", "many_friends",
    ]
    _UNLOCKED_ACH = ["long_relationship", "matchmaker", "room_master"]
    # 미달성 유지: meta_breach / first_conflict / reconciliation / confession

    for k in _DONE_ACH:
        db.upsert_achievement("owner", k, state="done", mark_unlocked=True, mark_completed=True)
    for k in _UNLOCKED_ACH:
        db.upsert_achievement("owner", k, state="unlocked", mark_unlocked=True)


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


if __name__ == "__main__":
    seed()
