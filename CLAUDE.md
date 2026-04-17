# Project Glimi — CLAUDE.md

## 프로젝트 개요
에이전트 소셜 시뮬레이션. 고유 페르소나를 가진 에이전트들이 디스코드를 통해 오너(개발자)와 1:1/그룹으로 소통하고, 에이전트끼리도 자체적으로 대화하며 관계를 형성하는 커뮤니티 시스템.

## 기술 스택
- Python 3.11+ / discord.py
- 에이전트 두뇌: Claude Code CLI (`claude` 명령어) subagent 방식
- 페르소나 에이전트: claude-sonnet-4-6 / 개발자 에이전트: claude-opus-4-2025
- DB: SQLite (`communities/{id}/community.db`)
- 프로필: DB 기반 (레거시는 `legacy/`에 보관)
- 멀티 커뮤니티: `src/community.py`로 관리

## 디렉토리 구조
```
Glimi/
├── CLAUDE.md           ← 이 파일
├── scripts/
│   ├── run.sh          ← 메인 실행 (봇 + 개발 루프)
│   ├── start.sh        ← 통합 실행 (세팅 + 대시보드)
│   ├── stop.sh         ← 봇 종료
│   └── dev.sh          ← 터미널 개발 요청
├── communities/        ← 커뮤니티별 데이터 (.gitignore)
│   ├── registry.toml   ← 커뮤니티 목록 + default
│   └── {id}/           ← 커뮤니티 하나
│       ├── .env        ← DISCORD_BOT_TOKEN
│       ├── community.db ← SQLite DB
│       ├── avatars/    ← 아바타 이미지
│       └── logs/
├── communities.example/ ← 템플릿 (git tracked)
├── assets/
│   └── avatars/        ← 기본 아바타 (init 시 복사)
├── dev/
│   ├── pending.json    ← 개발 요청
│   └── result.json     ← 개발 결과
├── legacy/             ← 레거시 데이터 (.gitignore)
└── src/
    ├── __init__.py
    ├── community.py      ← 커뮤니티 컨텍스트 관리
    ├── db.py             ← SQLite CRUD
    ├── log_writer.py     ← 로그 기록
    ├── discord_bot.py    ← 봇 엔트리포인트
    ├── core/             ← 에이전트 두뇌
    │   ├── runtime.py    ← Claude CLI 호출 + 응답 생성
    │   ├── profile.py    ← 프로필 관리 + system prompt 빌드
    │   ├── memory.py     ← 3단계 메모리 (raw→L1→L2)
    │   └── conversation.py ← 에이전트간 자동 대화
    ├── bot/              ← 디스코드 봇 모듈
    │   ├── __init__.py   ← 공유 상태 + Bot 인스턴스
    │   ├── core.py       ← Webhook, 채널 매핑, 유틸리티
    │   ├── mgr_system.py ← Manager CMD/QUERY/ACTION 시스템
    │   ├── handlers.py   ← 메시지 처리 (DM/그룹)
    │   ├── commands.py   ← 슬래시 명령어
    │   ├── tasks.py      ← 백그라운드 태스크 + 이벤트
    │   └── supervisors.py ← Supervisor 시스템 (백그라운드 감시자)
    ├── tui/              ← 터미널 UI
    │   ├── wizard.py     ← 통합 관리 Wizard
    │   └── dashboard.py  ← 실시간 대시보드
    └── tools/            ← 도구
        ├── cli.py        ← CLI 테스트 인터페이스
        ├── dev_runner.py ← 개발자 에이전트 (Opus)
        └── migrate.py    ← 프로필 마이그레이션
```

## 핵심 모듈 요약

### discord_bot.py (메인)
- Webhook으로 에이전트별 아바타/이름 전송
- `handle_dm`: 1:1 채널 처리 (채널별 asyncio.Lock)
- `handle_group`: 그룹채팅 (GROUP_PARTICIPANTS로 참여자 관리, 전원 응답)
- 유나 자율 행동: `[CMD:...]` 태그 파싱 → execute_yuna_command
- 유나 데이터 조회: `[QUERY:...]` 태그 파싱 → execute_yuna_query → 결과 피드백 (최대 3회 연쇄)
- 개발 요청: `[CMD:개발요청 ...]` → req JSON 생성 → exit(42) → scripts/run.sh가 dev_runner 실행
- `_split_for_chat`: 응답을 카톡 스타일 짧은 메시지로 분할

### core/runtime.py
- `generate_response(agent_id, channel, message, log_user_message=True)`
- `_call_claude_code`: system prompt(정적) + user prompt(동적: 감정+메모리+대화이력)
- `_parse_response`: 줄바꿈 기준 메시지 분리 + 중복 제거
- 에이전트 간 대화: `generate_agent_to_agent`

### core/profile.py
- DB 기반 프로필 로드/저장 (`load_profile` → `db.get_agent_profile`, `save_profile` → `db.save_agent_profile`)
- 프로필 캐시 (`_profile_cache`, `invalidate_cache`)
- `_build_persona_prompt`: 정적 프로필만 (감정/메모리는 runtime이 동적 주입)
- `_build_mgr_prompt`: 유나 전용 (CMD/QUERY 레퍼런스, 채널 현황)
- `_build_creator_prompt`: 에이전트 생성용

### db.py — 테이블
**코어:**
- agents: id, type, name, status, current_emotion, emotion_intensity, last_active, birth_year, age, mbti, enneagram, background, avatar_filename, version, created_at
- relationships: agent_a, agent_b, type, intimacy_score, dynamics (런타임 관계)
- conversations: channel, speaker, message, timestamp, context_emotion
- events: event_type, participants, description, impact
- memories: agent_id, channel, level(1/2), content, msg_id_from/to

**프로필 위성 (JSON blob):**
- agent_personality: agent_id, data (traits, likes, dislikes, values, keywords)
- agent_appearance: agent_id, data (summary, height, hair, fashion_style 등)
- agent_daily_life: agent_id, data (occupation, routine, habits 등)
- agent_speech: agent_id, data (style_description, signature_expressions, few_shot_examples 등)
- agent_relationship_templates: agent_id, target_id, rel_type, duration, dynamics, pet_name, is_owner_relationship (정적 관계 정의)
- agent_config: agent_id, config_json (mgr_config, creator_config)

**유저/메타:**
- users: id, name, birth_year, age, mbti, personality(JSON), appearance(JSON), speech(JSON) 등
- meta: key, value (active_user_id 등)

**DB 하나 = 커뮤니티 하나.** `communities/{id}/community.db`에 위치. `community.export_community()` / `community.import_community()`로 DB+아바타 통째 이전 가능. `db.export_agents()` / `db.import_agents()`로 에이전트 정의만 추출/이전도 가능.

### core/memory.py — 3단계 기억
- raw: 최근 15개 메시지 그대로 (user prompt에 주입)
- L1: 15개 메시지 → 1문장 요약 (최근 10개 유지)
- L2: L1 10개 → 1단락 요약 (최근 5개 유지)
- `get_memory_context(agent_id, channel)`: 현재 채널 메모리 (상세)
- `get_cross_channel_memory(agent_id, exclude_channel)`: 다른 채널 기억 (요약만)

### core/conversation.py
- `start_conversation`: 에이전트간 자동 대화 (턴 제한, 종료 감지)
- `detect_room_request`: 톡방 생성 의도 패턴 감지

## 유나 CMD/QUERY 시스템
유나(agent-mgr-001)의 응답에서 태그를 파싱:
- `[CMD:톡방 이름1 이름2 주제]` — 그룹채팅 생성
- `[CMD:대화시작 이름1 이름2 상황]` — 에이전트간 자동대화
- `[CMD:채널삭제/채널이름변경/채널토픽/메시지청소]` — 디스코드 채널 관리
- `[CMD:디코복구 채널명]` — DB 메시지를 디스코드에 재전송 (메시지청소 후 싱크용)
- `[CMD:감정/프로필수정/관계수정]` — 에이전트 상태 관리
- `[CMD:채널초기화/대화삭제/에이전트초기화]` — DB 정리
- `[CMD:개발요청 내용]` — 봇 종료 → Opus 코드 수정 → 재시작
- `[QUERY:채널목록/로그/검색/발화/프로필/관계/이벤트]` — DB 조회 → 결과 피드백

## 에이전트 ID 체계
- persona: agent-persona-001, 002, ...
- mgr: agent-mgr-001 (유나)
- creator: agent-creator-001 (하나)

## 채널 구조
- dm-{이름}: 1:1 채널
- group-{이름1}-{이름2}: 그룹 채팅 (GROUP_PARTICIPANTS로 참여자 추적)
- internal-{이름1}-{이름2}: 에이전트간 대화 (오너 읽기전용)
- mgr-dashboard: 유나 관리 채널
- mgr-creator: 에이전트 생성 채널

## 주의사항
- 메모리/감정은 system prompt에 넣지 않음 (agent_runtime이 user prompt에 채널별로 동적 주입)
- 그룹채팅에서 오너 메시지는 handle_group에서 1회만 로깅 (generate_response에 log_user_message=False)
- conversation_engine도 log_user_message=False (내부 프롬프트가 오너 ID로 로깅되는 버그 방지)
- 프로필 수정 시 invalidate_cache + runtime.refresh_agent 필수
- dm-/mgr- 채널은 삭제 보호됨

## 다국어 에이전트 이름
- DB `agents.name_i18n` TEXT (JSON blob: `{"ko": "서유나", "en": "Yuna"}`)
- `name`: 기본 이름 (항상 존재)
- `get_agent_display_name(agent_id)`: 현재 커뮤니티 언어에 맞는 이름 반환
- 언어 추가 시 JSON 키만 추가 (컬럼 변경 불필요)

## 용어 규칙
- 사용자에게 보이는 텍스트에서 "에이전트", "멤버", "봇", "AI" 등 메타 용어 금지
- 시스템 프롬프트에 명시: 다른 사람은 이름/친구들/사람들 등 자연스러운 표현 사용
- CMD/ACTION/QUERY 태그는 시스템 로그 채널에만 노출 (대화 채널에 절대 노출 금지)

## 멀티 서버 지원
- `.env`에 `DISCORD_GUILD_ID=서버ID` 설정 → 특정 서버만 사용
- `on_message`에서 guild 필터링 → 다른 서버 메시지 무시
- 미설정 시 `guilds[0]` 사용 (기존 동작)

## 실행
```bash
./scripts/run.sh                    # default 커뮤니티로 봇 실행
./scripts/run.sh my-server          # 지정 커뮤니티로 실행
./scripts/stop.sh                   # 봇 종료
./scripts/dev.sh "내용"             # 터미널에서 개발 요청
python -m src.community list  # 커뮤니티 목록
python -m src.community init my-server  # 새 커뮤니티 초기화
```

## QA 자동 테스트
```bash
python -m tests.e2e.runner              # 1회 실행
python -m tests.e2e.runner --runs 3     # 3회 반복
```

### 구조
```
tests/e2e/
├── runner.py           ← 테스트 오케스트레이터
├── test_user_bot.py    ← Claude Haiku 기반 테스트 유저 봇
└── results/            ← 실행 결과 (JSON + 로그)
```

### 동작
1. `qa` 커뮤니티 자동 생성/초기화 (DB + 유저 프로필 + `.clean-channels` 플래그)
2. Glimi 봇 시작 → 기존 디스코드 채널 삭제 → 온보딩 시작
3. 테스트 유저 봇 시작 → 신규 유저처럼 자연스럽게 대화
4. 온보딩 완료 or 타임아웃
5. 로그 수집 → 자동 판정 (프로필 중복, race condition, 태그 노출 등)

### 필요 설정
- `communities/qa/.env`에 `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `TEST_BOT_TOKEN` 설정
- 별도 디스코드 서버에 Glimi 봇 + 테스트 유저 봇 초대
- 테스트 유저 프로필 커스텀: 환경변수 `QA_USER_NAME`, `QA_USER_NICKNAME`, `QA_USER_AGE` 등
