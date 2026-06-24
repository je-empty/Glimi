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

    소스 (존재하는 dir 는 전부, 낮은 우선순위가 먼저 → 높은 우선순위가 덮어씀):
      1) 커밋된 샘플: <community assets>/sample_profile_images, .../profile_images
         (신선한 클론·공개 배포 glimi.iruyo.com 에 항상 존재). 남자 페르소나는
         여기 샘플 파일명(예: agent-persona-m-25-intj-calm-analytical.png)으로
         DB profile_image_filename 이 가리키므로 이 복사로 demo dir 가 자체 완결됨.
      2) communities/private/profile_images  (개발 머신에만 — gitignore).
         id 기반 파일명({aid}.png). 여자 페르소나 아바타가 여기서 온다.
    어느 것도 없으면 스킵 — serve_avatar 가 assets 폴백/placeholder SVG 로 해석.
    신선한 클론(communities/·data/ 없음)에서도 깨지지 않아야 한다.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    for f in dest_dir.glob("*.png"):
        try:
            f.unlink()
        except OSError:
            pass

    # community 패키지의 ASSETS_DIR(= glimi-community/assets) 가 정본. 3-repo split
    # 후 ROOT/"assets" 는 더 이상 존재하지 않는다(레포 분리). import 실패 시 ROOT 폴백.
    try:
        from community.community import ASSETS_DIR as _ASSETS
        assets_dir = Path(_ASSETS)
    except Exception:
        assets_dir = ROOT / "assets"

    # 낮은 우선순위 → 높은 우선순위 순서. 뒤에 복사되는 것이 같은 이름을 덮어쓴다.
    candidates = [
        assets_dir / "sample_profile_images",
        assets_dir / "profile_images",
        ROOT / "communities" / "private" / "profile_images",
    ]
    for src_dir in candidates:
        if not src_dir.exists():
            continue
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
    from community import community
    from community import db

    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    community.set_community(community_id)

    # ── 0. 디렉터리 + DB 리셋 ─────────────────────────────────
    # 3-repo split 후 정본 communities 디렉터리는 community.COMMUNITIES_DIR
    # (= glimi-community/communities, db.get_db_path 가 읽는 곳). ROOT/"communities"
    # 는 split 이전 repo-root 경로라, 신선한 클론에서 시더가 엉뚱한 dir 를 만들고
    # init_db() 가 FileNotFoundError 로 죽었다 (데모가 첫 실행에 안 뜸). 정본 dir 사용.
    demo_dir = community.get_community_dir()
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
                     current_emotion="평온", intensity=5, image=None):
        # profile_image_filename: 기본은 id 기반 ({aid}.png) — 개발 머신은
        # communities/private/profile_images 에 미리 {aid}.png 로 둔 아바타를
        # _copy_seed_avatars 가 그대로 복사한다. 하지만 신선한 클론/공개(glimi.iruyo.com)
        # 경로엔 그 dir 가 없으므로(gitignore) 커밋된 assets/sample_profile_images 의
        # 샘플 파일명을 그대로 저장하면 resolver(community.get_profile_image_path) 의
        # 샘플 폴백으로 바로 해석된다. image 가 주어지면 그 샘플 파일명을 쓰고,
        # sample_source_file 에도 기록한다.
        fname = image or f"{aid}.png"
        conn.execute("""
            INSERT INTO agents (id, type, name, status, current_emotion, emotion_intensity,
                                birth_year, age, gender, mbti, background,
                                profile_image_filename, sample_source_file, version, created_at)
            VALUES (?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (aid, atype, name, current_emotion, intensity,
              2026 - age, age, gender, mbti, background,
              fname, image, datetime.now().isoformat()))


    insert_agent("agent-mgr-001", "mgr", "유나", 24, "여자", "ENFJ",
                 "Glimi 커뮤니티 매니저. 친근하고 정리 잘하는 누나 같은 존재.")
    insert_agent("agent-creator-001", "creator", "하나", 22, "여자", "INFP",
                 "신규 멤버 튜토리얼 + 페르소나 디자이너. 다정하고 창의적.")


    # ── 3. 페르소나 7명 (순수 친구 관계만 — 연인/동료/가족 X) ─────────
    personas = [
        {
            "id": "agent-persona-001", "name": "소은", "age": 24, "gender": "여자",
            "image": "agent-persona-f-21-infj-quiet-gentle.png",
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
            "image": "agent-persona-f-26-enfp-energetic-bold.png",
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
            "image": "agent-persona-f-19-esfp-cheerful-playful.png",
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
            "image": "agent-persona-f-26-enfp-cheerful-warm.png",
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
            "image": "agent-persona-f-19-infp-shy-dreamy.png",
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
            "image": "agent-persona-f-34-esfj-calm-caring.png",
            "mbti": "ENTJ", "enneagram": "8",
            "bg": "헬스장·필라테스 모임에서 알게 된 언니 친구. 깐깐하지만 조언해주는 스타일. 배울 점 많음.",
            "emotion": "집중", "intensity": 7,
            "traits": ["체계적", "리더형", "통찰력 있는", "정직한"],
            "likes": ["커피", "필라테스", "독서", "캠핑"],
            "dislikes": ["준비 안 된 만남", "말만 앞섬"],
            "rel_owner": "친구", "duration": "2년", "pet_name": "사용자",
            "occupation": "필라테스 강사",
            "routine": "06시 필라테스 → 저녁 독서/캠핑 계획",
        },
        {
            "id": "agent-persona-007", "name": "수진", "age": 26, "gender": "여자",
            "image": "agent-persona-f-21-enfj-lively-warm.png",
            "mbti": "ISFJ", "enneagram": "6",
            "bg": "브런치 모임에서 알게 된 친구. 꼼꼼하고 세심함. 요리·빵 좋아하고 같이 맛집 탐방 자주.",
            "emotion": "차분", "intensity": 6,
            "traits": ["성실한", "헌신적", "따뜻한", "신중한"],
            "likes": ["요리", "꽃", "독서", "브런치"],
            "dislikes": ["성급한 결정"],
            "rel_owner": "친구", "duration": "1년", "pet_name": "사용자",
            "occupation": "동네 베이커리 운영",
            "routine": "새벽 빵 굽기 → 오후 가게 → 저녁 친구들과",
        },
        # ── 남자 페르소나 3명 (순수 친구 — 연인/동료/가족 X) ─────────
        # 커밋된 assets/sample_profile_images 의 남성 샘플 이미지와 1:1 매칭.
        # "image" = 그 샘플 파일명 → 공개 경로(glimi.iruyo.com)에서도 resolver 가 바로 해석.
        {
            "id": "agent-persona-008", "name": "준호", "age": 25, "gender": "남자",
            "mbti": "INTJ", "enneagram": "5",
            "bg": "대학원 스터디에서 알게 된 친구. 분석적이고 차분함. 같이 자료 정리하다 친해짐.",
            "emotion": "차분", "intensity": 5,
            "traits": ["분석적", "차분한", "논리적", "신중한"],
            "likes": ["체스", "다큐멘터리", "커피", "데이터"],
            "dislikes": ["즉흥적인 변경", "잡담"],
            "rel_owner": "친구", "duration": "2년", "pet_name": "사용자",
            "occupation": "대학원생 (데이터분석)",
            "routine": "오전 연구실 → 오후 스터디 → 저녁 책/체스",
            "image": "agent-persona-m-25-intj-calm-analytical.png",
        },
        {
            "id": "agent-persona-009", "name": "지훈", "age": 23, "gender": "남자",
            "mbti": "ENFP", "enneagram": "7",
            "bg": "동아리 후배. 밝고 에너지 넘침. 어디서든 분위기 띄우는 스타일.",
            "emotion": "신남", "intensity": 8,
            "traits": ["밝은", "에너지있는", "친화력 좋은", "즉흥적"],
            "likes": ["축구", "버스킹", "여행", "맛집"],
            "dislikes": ["눈치 보는 분위기", "지루함"],
            "rel_owner": "친구", "duration": "2년", "pet_name": "형",
            "occupation": "대학생 (3학년)",
            "routine": "학교 → 동아리 → 저녁 친구들이랑 풋살",
            "image": "agent-persona-m-23-enfp-warm-energetic.png",
        },
        {
            "id": "agent-persona-010", "name": "태경", "age": 28, "gender": "남자",
            "mbti": "ISTP", "enneagram": "9",
            "bg": "클라이밍 모임에서 알게 된 친구. 과묵하고 쿨함. 말은 적어도 챙길 건 챙김.",
            "emotion": "평온", "intensity": 5,
            "traits": ["과묵한", "쿨한", "손재주 좋은", "독립적인"],
            "likes": ["클라이밍", "오토바이", "캠핑", "기계"],
            "dislikes": ["과한 관심", "허세"],
            "rel_owner": "친구", "duration": "1년", "pet_name": "사용자",
            "occupation": "자동차 정비 엔지니어",
            "routine": "오전 정비소 → 저녁 클라이밍장 → 주말 캠핑",
            "image": "agent-persona-m-28-istp-cool-reserved.png",
        },
    ]

    for p in personas:
        insert_agent(p["id"], "persona", p["name"], p["age"], p["gender"],
                     p["mbti"], p["bg"], p["emotion"], p["intensity"],
                     image=p.get("image"))
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
        # 남자 친구들 — 운동·취미 모임으로 엮인 사이 (순수 친구)
        ("agent-persona-009", "agent-persona-010", "친구", 78, "풋살·클라이밍 모임 단골. 성격은 정반대지만 잘 맞음"),
        ("agent-persona-008", "agent-persona-009", "친구", 64, "운동모임에서 알게 됨. 준호가 지훈 에너지 신기해함"),
        ("agent-persona-002", "agent-persona-010", "친구", 70, "러닝·클라이밍 같이 다니는 운동 메이트"),
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


    # DM (owner ↔ agent). Keyed by agent_id — the web chat (_list_postable_channels)
    # synthesizes dm-<agent_id> and the WS write path stores under the same key, so
    # the DM channel key MUST be dm-<agent_id> for history to resolve.
    for p in personas:
        add_channel(f"dm-{p['id']}", [p["id"]])
    # Manager / Creator DMs (these surface in the web chat as DMs too).
    add_channel("dm-agent-mgr-001", ["agent-mgr-001"])
    add_channel("dm-agent-creator-001", ["agent-creator-001"])
    add_channel("mgr-system-log", ["agent-mgr-001"])
    # Group (owner 포함)
    add_channel("group-친구들", ["agent-persona-001", "agent-persona-002", "agent-persona-004"])
    add_channel("group-브런치", ["agent-persona-006", "agent-persona-007"])
    # 운동·취미 모임 (남자 친구들 + 운동파) — 혼성 친구 그룹
    add_channel("group-운동모임",
                ["agent-persona-002", "agent-persona-008",
                 "agent-persona-009", "agent-persona-010"])
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


    # DM — 채널 키는 dm-<agent_id> (웹 채팅이 dm-<agent_id> 로 조회 → 일치해야 보임).
    DM_SCRIPTS = {
        # 소은 (파트너, 안정적 · 최근 사용자 바쁨 걱정)
        "dm-agent-persona-001": [
            ("agent-persona-001", "오늘 하루 어땠어?"),
            ("owner", "그냥... 좀 정신없었어 ㅠㅠ"),
            ("agent-persona-001", "저번에 말한 거 아직 안 풀린 거야?"),
            ("owner", "어 어제 겨우 해결했어"),
            ("agent-persona-001", "다행이다 ㅎㅎ"),
            ("agent-persona-001", "저녁에 집 올거지?"),
            ("owner", "응 8시쯤 갈거 같애"),
            ("agent-persona-001", "파스타 해놓을게. 화이트 와인도 꺼내놨어"),
            ("owner", "완전 굿 ♥"),
            ("agent-persona-001", "너무 무리하지마 요즘"),
            ("owner", "응 이번 주만 버티면 될듯"),
            ("agent-persona-001", "다음주는 푹 쉬자 약속"),
        ],
        # 민서 (20년 지기 소꿉친구)
        "dm-agent-persona-002": [
            ("agent-persona-002", "빈아 주말 뭐함"),
            ("owner", "왜"),
            ("agent-persona-002", "동창들이랑 한잔하기로 했거든"),
            ("agent-persona-002", "토요일 저녁"),
            ("owner", "소은랑 저녁 약속 있어서..."),
            ("agent-persona-002", "ㅋㅋ 소은 허락 받아오셈"),
            ("owner", "알았어 물어볼게"),
            ("agent-persona-002", "야 글고 나 요즘 러닝 시작했는데 너도 같이 할래?"),
            ("owner", "오 갑자기?"),
            ("agent-persona-002", "한강 코스 진짜 좋아. 아침에 뛰면 개운함"),
            ("owner", "음 주말 아침이면 가능"),
            ("agent-persona-002", "콜 일요일 아침에 데리러 감"),
            ("owner", "ㅇㅋ ㅋㅋ"),
        ],
        # 서아 (대학 후배)
        "dm-agent-persona-003": [
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
        # 예린 (친구, 일러스트레이터)
        "dm-agent-persona-004": [
            ("owner", "예린아 전시 준비는?"),
            ("agent-persona-004", "오빠! 거의 다 됐어요 ㅎㅎ"),
            ("agent-persona-004", "다음달 15일 오프닝이에요"),
            ("owner", "소은랑 같이 갈게"),
            ("agent-persona-004", "꼭 오세요! 언니가 제일 보고 싶어하는 작품 있어요 ㅋㅋ"),
            ("owner", "뭐 ㅋㅋ 미리 말해주지마"),
            ("agent-persona-004", "비밀이에요 기대하세요"),
        ],
        # 하린 (후배 친구, 작곡)
        "dm-agent-persona-005": [
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
        # 수연 (필라테스 모임 언니 친구, 깐깐하지만 챙겨줌)
        "dm-agent-persona-006": [
            ("agent-persona-006", "야 너 요즘 운동 안 하지"),
            ("owner", "ㅋㅋㅋ어떻게 아셨어요"),
            ("agent-persona-006", "딱 보면 알아. 주말에 클래스 한번 나와"),
            ("owner", "토요일은 좀.. 일요일은요?"),
            ("agent-persona-006", "일요일 오전 비어. 11시 ㄱ"),
            ("owner", "넵 갈게요"),
            ("agent-persona-006", "글고 너 자세 안 좋더라. 거북목 심해"),
            ("owner", "아 진짜 요즘 목 아파요"),
            ("agent-persona-006", "그러니까 나오라고. 스트레칭부터 잡아줄게"),
            ("owner", "역시 누나밖에 없다 ㅎㅎ"),
            ("agent-persona-006", "담주에 캠핑도 갈건데 올래? 수진이도 와"),
            ("owner", "오 좋아요"),
        ],
        # 수진 (브런치 모임 친구, 동네 베이커리)
        "dm-agent-persona-007": [
            ("agent-persona-007", "오늘 스콘 구웠는데 좀 갖다줄까요?"),
            ("owner", "헐 완전 좋죠"),
            ("agent-persona-007", "이따 가게 들러요. 따뜻할 때 줄게"),
            ("owner", "ㅇㅋ 7시쯤 갈게요"),
            ("agent-persona-007", "글고 저번에 말한 그 파스타집 예약했어요"),
            ("owner", "오 거기 가보고 싶었는데"),
            ("agent-persona-007", "토요일 1시 어때요? 수연 언니도 온대요"),
            ("owner", "좋아요 ㅋㅋ"),
            ("agent-persona-007", "기대하세요 거기 진짜 맛집"),
        ],
        # 준호 (대학원 스터디 친구, INTJ·차분·분석적)
        "dm-agent-persona-008": [
            ("agent-persona-008", "이번 주 스터디 자료 정리해서 공유 드렸어요"),
            ("owner", "오 빠르다 ㅋㅋ 고마워"),
            ("agent-persona-008", "3장 데이터 부분은 제가 다시 검증해야 할 것 같아요"),
            ("owner", "그 부분 좀 애매하긴 했어"),
            ("agent-persona-008", "근거가 약하면 결론을 못 믿으니까요"),
            ("owner", "역시 꼼꼼하다"),
            ("agent-persona-008", "주말에 카페에서 같이 마저 볼래요?"),
            ("owner", "토욜 오후 괜찮아"),
            ("agent-persona-008", "그럼 2시에. 조용한 데로 잡아둘게요"),
        ],
        # 지훈 (동아리 후배, ENFP·밝고 에너지)
        "dm-agent-persona-009": [
            ("agent-persona-009", "형!! 오늘 풋살 오죠??"),
            ("owner", "ㅋㅋ 몇 시였지"),
            ("agent-persona-009", "8시요 늦지마요 진짜"),
            ("owner", "ㅇㅋ 갈게"),
            ("agent-persona-009", "끝나고 치맥도 콜?"),
            ("owner", "당연하지"),
            ("agent-persona-009", "역시 형밖에 없어 ㅋㅋㅋ"),
            ("agent-persona-009", "아 글고 다음주 동아리 공연 형도 보러와요"),
            ("owner", "오 뭐 하는데"),
            ("agent-persona-009", "저 버스킹 무대 서요 ㅎㅎ 기대하세요"),
        ],
        # 태경 (클라이밍 모임 친구, ISTP·과묵·쿨)
        "dm-agent-persona-010": [
            ("agent-persona-010", "오늘 클라이밍장 감?"),
            ("owner", "어 갈까 했는데"),
            ("agent-persona-010", "7시쯤 가면 안 붐벼"),
            ("owner", "ㅇㅋ 그때 보자"),
            ("agent-persona-010", "지난번 그 빨간 코스 다시 도전해봐"),
            ("owner", "그거 손에 힘 다 빠지던데 ㅋㅋ"),
            ("agent-persona-010", "그립 자세가 문제임. 가서 봐줄게"),
            ("owner", "오 고마워"),
            ("agent-persona-010", "담주에 캠핑도 갈 건데 올 거면 말해"),
        ],
    }
    for ch, lines in DM_SCRIPTS.items():
        for i, (sp, content) in enumerate(lines):
            msg(ch, sp, content, ago_min=(len(lines) - i) * 4)

    # Manager DM (유나) — 친구들 소식 브리핑
    MGR_LINES = [
        (90, "agent-mgr-001", "사용자님 안녕하세요~ 매니저 유나에요 :)"),
        (88, "owner", "안녕하세요!"),
        (85, "agent-mgr-001", "오늘 서아가 다음주 홈커밍 얘기 꺼냈어요. 갈지 정하시면 알려주세요~"),
        (82, "agent-mgr-001", "그리고 소은님이 사용자님 건강 걱정 많이 하시더라구요 (최근 대화 기록 기반)"),
        (75, "owner", "ㅎㅎ 고마워요"),
        (30, "agent-mgr-001", "참고로 요즘 소은이랑 예린이가 사용자님 생일 선물 의논 중이에요 🤫"),
        (15, "agent-mgr-001", "프로필 수정하거나 친구 새로 만들고 싶으시면 하나한테 말씀해 주세요!"),
    ]
    for ago, sp, content in MGR_LINES:
        msg("dm-agent-mgr-001", sp, content, ago_min=ago)

    # Creator DM (하나)
    msg("dm-agent-creator-001", "agent-creator-001", "사용자님~ 오늘은 어떻게 오셨어요?", 200)
    msg("dm-agent-creator-001", "owner", "일단 지금 친구들로 충분한 것 같아요", 195)
    msg("dm-agent-creator-001", "agent-creator-001", "네네! 필요하실 때 언제든 불러주세요 🌸", 190)

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

    msg("group-브런치", "agent-persona-007", "이번 주말 브런치 어디서 볼까요", 20, "차분")
    msg("group-브런치", "agent-persona-006", "연남동 그 집 어때. 거기 샐러드 좋더라", 18, "평온")
    msg("group-브런치", "agent-persona-007", "오 좋아요! 사용자도 부를까요?", 17, "차분")
    msg("group-브런치", "owner", "ㅋㅋ 불러주면 가야지", 15, "즐거움")
    msg("group-브런치", "agent-persona-006", "콜. 일요일 12시 ㄱ", 10, "평온")

    # 운동모임 (민서·준호·지훈·태경 + owner) — 혼성 친구 그룹
    msg("group-운동모임", "agent-persona-009", "이번 주말 풋살 ㄱㄱ?", 35, "신남")
    msg("group-운동모임", "agent-persona-002", "콜 난 무조건", 34, "활기")
    msg("group-운동모임", "agent-persona-010", "난 클라이밍 끝나고 합류 가능", 33, "평온")
    msg("group-운동모임", "agent-persona-008", "인원 몇 명이야? 코트 예약 내가 할게", 32, "차분")
    msg("group-운동모임", "owner", "나도 낄게 ㅋㅋ", 30, "즐거움")
    msg("group-운동모임", "agent-persona-009", "오 형 굿 ㅋㅋㅋ 그럼 5명", 29, "신남")
    msg("group-운동모임", "agent-persona-008", "토요일 8시 코트 잡았어", 25, "차분")
    msg("group-운동모임", "agent-persona-010", "ㅇㅋ", 24, "평온")

    # 더미 스레드 + 반응 (채팅 UI 의 스레드/반응 어포던스 데모용)
    def _msg_id(channel, speaker, content, ago_min=0, emotion=None):
        ts = (datetime.now() - timedelta(minutes=ago_min)).isoformat()
        cur = conn.execute("""INSERT INTO conversations
                        (channel, speaker, message, timestamp, context_emotion)
                        VALUES (?, ?, ?, ?, ?)""",
                     (channel, speaker, content, ts, emotion or '평온'))
        return cur.lastrowid

    def _reply(channel, speaker, content, root_id, ago_min=0, emotion=None):
        ts = (datetime.now() - timedelta(minutes=ago_min)).isoformat()
        conn.execute("""INSERT INTO conversations
                        (channel, speaker, message, timestamp, context_emotion, reply_to, thread_root)
                        VALUES (?, ?, ?, ?, ?, ?, ?)""",
                     (channel, speaker, content, ts, emotion or '평온', root_id, root_id))

    def _react(message_id, actor_id, emoji):
        ts = datetime.now().isoformat()
        conn.execute("""INSERT OR IGNORE INTO reactions (message_id, actor_id, emoji, created_at)
                        VALUES (?, ?, ?, ?)""", (message_id, actor_id, emoji, ts))

    _root = _msg_id("group-친구들", "agent-persona-002", "어제 러닝 인증 📸 한강 6km", 40, "신남")
    _reply("group-친구들", "agent-persona-001", "오 멋지다 ㅋㅋ", _root, 39, "평온")
    _reply("group-친구들", "owner", "다음엔 같이 가자", _root, 38, "즐거움")
    _reply("group-친구들", "agent-persona-004", "사진 잘 나왔어요 ㅎㅎ", _root, 37, "행복")
    _react(_root, "owner", "❤️")
    _react(_root, "agent-persona-001", "🔥")
    _react(_root, "agent-persona-004", "👍")
    # DM 에도 반응 하나 (소은 DM 마지막 메시지에)
    _dm_msg = _msg_id("dm-agent-persona-001", "agent-persona-001", "내일 책방 같이 갈래?", 30, "차분")
    _react(_dm_msg, "owner", "👍")

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

    # Internal — 수연·수진 (사용자 챙기기 + 생일 준비)
    INTERNAL_SUYEON_SUJIN = [
        ("agent-persona-006", "수진아, 사용자 요즘 좀 피곤해 보이지 않아?", 30),
        ("agent-persona-007", "맞아요 안색이 영..."),
        ("agent-persona-006", "운동을 안 해서 그래. 주말에 끌고 나와야겠어"),
        ("agent-persona-007", "ㅎㅎ 저는 빵이라도 챙겨줄게요"),
        ("agent-persona-006", "그래 우리가 좀 챙기자"),
        ("agent-persona-007", "참 사용자 생일 곧이잖아요. 뭐 해줄까 고민 중", 18),
        ("agent-persona-006", "오 그러네. 같이 준비할까?"),
        ("agent-persona-007", "좋아요!"),
    ]
    for i, entry in enumerate(INTERNAL_SUYEON_SUJIN):
        sp, content = entry[0], entry[1]
        ago = entry[2] if len(entry) > 2 else (len(INTERNAL_SUYEON_SUJIN) - i) * 4
        msg("internal-dm-수연-수진", sp, content, ago_min=ago, emotion="평온")

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

    # 민서 — 러닝·모임 관련 메모리
    insert_memory("agent-persona-002", "dm-사용자",
                  "- 사용자한테 같이 러닝하자고 꼬심\n- 일요일 아침 한강 코스 (민서가 데리러 감)\n- 사용자 운동 안 한다고 놀림",
                  "event", 6, ["사용자"], ["민서", "owner"], ago_days=0)
    insert_memory("agent-persona-002", "dm-사용자",
                  "- 사용자 요즘 바빠서 주말에만 시간\n- 동창 모임 토요일 7시 — 사용자 참석 확인 중\n- 소은 허락 필요하다고 농담",
                  "event", 5, ["사용자"], ["민서", "owner"], ago_days=1)
    insert_memory("agent-persona-002", "dm-사용자",
                  "- 20년 지기 친구로 인생 큰 결정마다 의견 주고받음\n- 서로 가장 솔직한 말 해주는 관계\n- 사용자 연애 시작할 때도 민서이 먼저 조언",
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

    # 수연 — 운동·챙김
    insert_memory("agent-persona-006", "dm-사용자",
                  "- 사용자 거북목·자세 안 좋은 거 지적\n- 일요일 오전 필라테스 클래스 오라고 함\n- 다음주 캠핑도 같이 가기로",
                  "event", 6, ["사용자"], ["수연", "owner"], ago_days=0)
    insert_memory("agent-persona-006", "internal-dm-수연-수진",
                  "- 사용자 요즘 피곤해 보임 → 수진이랑 같이 챙기기로\n- 주말에 운동 데리고 나갈 계획\n- 생일 선물도 같이 준비",
                  "fact", 6, ["사용자", "수진"], ["수연", "수진"],  # owner 모름
                  ago_days=0)

    # 수진 — 베이킹·약속
    insert_memory("agent-persona-007", "dm-사용자",
                  "- 스콘 구워서 가게에서 나눠주기로\n- 토요일 파스타집 예약 (수연도 함께)",
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
    add_fact("agent-persona-002", "사용자", "운동", "요즘 러닝 시작 (민서랑 같이)", 5)
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
    add_fact("agent-persona-006", "사용자", "운동", "거의 안 함 (잔소리 대상)", 6)
    add_fact("agent-persona-006", "사용자", "건강", "거북목 · 수면 부족", 7)
    add_fact("agent-persona-006", "사용자", "성격", "챙겨주면 잘 따라옴", 5)
    add_fact("agent-persona-006", "수진", "특기", "베이킹 · 맛집 탐방", 6)
    add_fact("agent-persona-006", "수진", "직업", "동네 베이커리 운영", 6)

    # 수진이 수연/사용자에 대해 아는 것
    add_fact("agent-persona-007", "수연", "직업", "필라테스 강사", 6)
    add_fact("agent-persona-007", "사용자", "취향", "담백한 음식 · 따뜻한 디저트", 5)
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
                  "형식적", "편한 사이", "러닝·필라테스 모임 같이 다니며 친해짐", 14)
    add_rel_delta("agent-persona-003", "agent-persona-005", "intimacy", "88", "92",
                  "최근 매일 통화 + 마라탕 맛집 탐방", 7)
    add_rel_delta("agent-persona-001", "agent-persona-003", "dynamics",
                  "편한 후배", "살짝 경계", "서아가 사용자 자주 챙기는 거 보고 소은 복합 감정", 10)


    # ── 10. thinking 시뮬 ──────────────────────────────────
    thinking_path = demo_dir / "logs" / "thinking.log"
    thinking_path.write_text("[agent-persona-002] start\n")


    # ── 11. 라이브 채널 status='running' ───────────────────
    for ch in ("group-친구들", "internal-dm-서아-하린", "dm-agent-persona-003"):
        conn.execute("UPDATE channels SET status='running' WHERE channel=?", (ch,))


    # ── 12. events ─────────────────────────────────────────
    events = [
        ("관계강화", ["agent-persona-003", "agent-persona-005"],
         "서아·하린 동아리 모임 후 친밀도 +4", "긍정"),
        ("감정변화", ["agent-persona-001", "agent-persona-003"],
         "소은가 서아와 사용자의 친밀도 살짝 신경 쓰기 시작", "주의"),
        ("기념일임박", ["owner", "agent-persona-001"],
         "사용자 생일 다음달 — 소은·예린이 공동 선물 준비 중", "긍정"),
        ("주말약속", ["agent-persona-006", "agent-persona-007", "owner"],
         "다음주 수연·수진이랑 브런치 + 한강 나들이 계획", "긍정"),
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
    print(f"   ├─ 12 agents: 유나(mgr) / 하나(creator) / 페르소나 10 (여7 + 남3, 순수 친구)")
    print(f"   ├─ 채널: {len(DM_SCRIPTS) + 8} (DM + internal + group + mgr)")
    print(f"   ├─ 대화: 100+ 메시지, 3 라이브 채널")
    print(f"   ├─ 메모리: L1/L2/L3 섞어서 ~15건 + pinned 1건")
    print(f"   ├─ agent_facts: ~30건 (엔티티별 구조화)")
    print(f"   ├─ relationship_history: 4 변곡점")
    print(f"   └─ events: {len(events)}건")
    print(f"\n   확인: http://localhost:8765/?community=demo")


if __name__ == "__main__":
    seed()
