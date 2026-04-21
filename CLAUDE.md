# Project Glimi — CLAUDE.md

## 프로젝트 개요
에이전트 소셜 시뮬레이션. 고유 페르소나를 가진 에이전트들이 디스코드를 통해 오너(개발자)와 1:1/그룹으로 소통하고, 에이전트끼리도 자체적으로 대화하며 관계를 형성하는 커뮤니티 시스템.

**한 줄 피칭**: AI 친구들이 오너 없이도 자기들끼리 살아가는 커뮤니티. 오너가 돌아오면 그사이 무슨 일이 있었는지 알려준다.

## 🚨 개발 세션 필독
**`docs/dev_guide.md` 를 먼저 읽어라.** 타깃·설계 락인·현재 스프린트·파일 참조 맵·금지 사항이 정리되어 있다.

## 🔌 아키텍처 원칙 — Discord 는 "인터페이스 어댑터" 이지 코어 아님

**현재 디스코드를 쓰는 이유는 채팅 UI 를 자체 구현하는 공수가 크기 때문.** 최종 목표는 웹 대시보드(·추후 앱)에 자체 채팅을 넣고 디스코드를 떼는 것. 따라서:

- **코어 로직 (에이전트 두뇌·메모리·감정·씬·도구 실행) 은 디스코드를 몰라야 한다.** 메시지 형태·채널 개념·사용자 식별은 플랫폼 중립적 타입으로 표현.
- **디스코드는 "출구" 레이어.** `src/bot/` = Discord 어댑터. 나중에 `src/adapters/telegram/`, `src/adapters/web_chat/` 이 붙을 자리.
- **새 기능 설계 시 질문**: "이 로직을 Telegram·자체웹채팅에서도 그대로 재사용할 수 있나?" NO 면 그 기능은 잘못된 레이어에 있는 것.
- **금지**: `src/core/*` 에서 `import discord`. `Webhook`, `TextChannel`, `guild` 등 Discord 타입이 코어 시그니처에 새는 것.
- **허용 (과도기)**: `src/core/sync.py` 처럼 본질이 "Discord↔DB 동기화" 인 모듈은 discord import 해도 됨 — 이건 어댑터 책임이지 코어 비즈니스 로직이 아님. 단, 이런 모듈은 추후 `src/adapters/discord/sync.py` 로 이동 예정.
- **추상화 목표**: 메시지 송신은 `outbox.send(channel_id, speaker, text, ...)` 추상 인터페이스를 두고, 디스코드 webhook / 텔레그램 API / 자체 웹 WebSocket 이 각자 구현하는 구조.

현재 현황 + 분리 공수 추정은 **`analysis/platform_decoupling_review.md`** 참조 (없으면 해당 세션에서 새로 작성).

## 전략 로드맵 (내부, gitignored)
- `analysis/zeta_vs_glimi_analysis.md` — 제타 경쟁 분석 + 갭 매트릭스
- `analysis/glimi_roadmap_todo.md` — Phase 0-4 로드맵 + 체크박스 + 제거 리스트
- `analysis/business_strategy.md` — 사업 전략 + 단위경제
- `analysis/pending_decisions.md` — 확정·보류 결정 체크리스트
- **타깃**: 20대 초반 여성 감성 유저 (B 세그먼트, 장기관계·힐링·케어)
- **현재 스프린트**: **Phase 0 — 감정 Application Layer** (EmotionSupervisor / 프롬프트 감정 강제 / 케어 루프 / 대시보드 감정 뷰)
- **다음**: P1 씬 다각화 (birthday > healing > milestone) → P1-2 오너 부재 시뮬레이션 → P1-5 기억 일관성

## 기술 스택
- Python 3.11+ / discord.py
- 에이전트 두뇌: Claude Code CLI (`claude` 명령어) subagent 방식
- 페르소나/매니저/Creator: claude-sonnet-4-6 / Dev Runner: Opus / Supervisors: Haiku
- DB: SQLite (`communities/{id}/community.db`)
- 프로필: DB 기반 (레거시는 `legacy/`에 보관)
- 멀티 커뮤니티: `src/community.py`로 관리
- 도구 호출: `<tools>` 인라인 XML (`src/core/tools/`) — CMD/QUERY/ACTION 태그 시스템 대체
- 웹 대시보드: 순수 Python HTTP + Cytoscape.js (`scripts/web_dashboard.py`, `:8765`)

## 디렉토리 구조
```
Glimi/
├── CLAUDE.md           ← 이 파일
├── scripts/
│   ├── run.sh          ← 메인 실행 (봇 + 개발 루프)
│   ├── start.sh        ← 통합 실행 (세팅 + 대시보드)
│   ├── stop.sh         ← 봇 종료
│   ├── dev.sh          ← 터미널 개발 요청
│   ├── qa.sh           ← E2E QA 자동화
│   ├── web_dashboard.py ← 웹 대시보드 (Cytoscape 그래프)
│   └── seed_demo_mockup.py ← demo 커뮤니티 목업 시드
├── communities/        ← 커뮤니티별 데이터 (.gitignore)
│   ├── registry.toml   ← 커뮤니티 목록 + default
│   └── {id}/           ← 커뮤니티 하나
│       ├── .env        ← DISCORD_BOT_TOKEN
│       ├── community.db ← SQLite DB
│       ├── profile_images/ ← 에이전트 프로필 이미지
│       └── logs/
├── communities.example/ ← 템플릿 (git tracked)
├── assets/
│   ├── profile_images/        ← 기본 프로필 이미지 (init 시 복사)
│   └── sample_profile_images/ ← 하나가 추천할 샘플 프로필 이미지 카탈로그
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
    │   ├── memory.py     ← 5 레이어 메모리 (raw→L1/L2/L3 + facts + relationship + pinned)
    │   ├── monitor.py    ← 대시보드용 스냅샷/디테일 API
    │   ├── conversation.py ← 에이전트간 자동 대화
    │   └── tools/        ← <tools> 프로토콜
    │       ├── parser.py     ← XML 파싱
    │       ├── registry.py   ← 도구 정의 + 메타데이터
    │       ├── dispatcher.py ← 호출 → 핸들러 디스패치
    │       ├── validator.py  ← 인자 검증
    │       ├── reference.py  ← LLM용 도구 레퍼런스 빌드
    │       └── result.py     ← 결과 직렬화
    ├── bot/              ← 디스코드 봇 모듈
    │   ├── __init__.py   ← 공유 상태 + Bot 인스턴스
    │   ├── core.py       ← Webhook, 채널 매핑, 유틸리티
    │   ├── formatting.py ← 에이전트 응답 → 디스코드 네이티브 변환 (#channel → <#id>)
    │   ├── mgr_system.py ← Manager 도구 핸들러 (`<tools>` 실행)
    │   ├── tool_handlers.py ← 도구 → yuna_* 브릿지 + recall_memory/pin_memory
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
- Webhook으로 에이전트별 프로필 이미지/이름 전송 (Discord SDK 경계에서만 `avatar` 키워드 사용)
- `handle_dm`: 1:1 채널 처리 (채널별 asyncio.Lock)
- `handle_group`: 그룹채팅 (GROUP_PARTICIPANTS로 참여자 관리, 전원 응답)
- 매니저/Creator 응답에서 `<tools>` 블록 파싱 → `core/tools/dispatcher`가 실행
- 도구 결과는 자연어 피드백으로 LLM 에 다시 주입 (최대 N회 연쇄)
- 개발 요청: `dev_request` 도구 → pending.json 생성 → exit(42) → scripts/run.sh가 Opus dev_runner 실행
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
- agents: id, type, name, name_i18n(JSON), status, current_emotion, emotion_intensity, last_active, birth_year, age, gender, mbti, enneagram, background, profile_image_filename, version, created_at
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

**DB 하나 = 커뮤니티 하나.** `communities/{id}/community.db`에 위치. `community.export_community()` / `community.import_community()`로 DB+프로필 이미지 통째 이전 가능. `db.export_agents()` / `db.import_agents()`로 에이전트 정의만 추출/이전도 가능.

### core/memory.py — 5 레이어 기억 시스템 (진행 중)

**확정 설계 (락인)**: 각 에이전트마다 **통합 메모리 1개** + 엔티티 태그로 "누구에 관한 건지" 관리 (사람처럼). 저장은 영구, 주입만 budget 기반 선별.

**5 레이어:**
- **Layer 0 — Raw Archive** (영구): `conversations` 테이블, 평소 미주입
- **Layer 1 — Working Window**: 최근 10-15개 verbatim, 매 턴 주입
- **Layer 2 — Episodic Chronicle** (영구): L1 (5 msg → 글머리표) → L2 (5 L1 → 단락) → L3 (5 L2 → 월단위). 저장 cap 없음, 주입만 score 기준 top-N
- **Layer 3 — Semantic Facts** (영구, entity-indexed): `agent_facts` 테이블. (subject, predicate, object) + Zep식 supersession (`valid_to` 닫고 새 row)
- **Layer 4 — Relationship State**: `relationships` (현재 snapshot) + `relationship_history` (변곡점 delta 영구)
- **Layer 5 — Pinned Memories**: `memories.is_pinned=1`, 오너/유나가 `pin_memory` 도구로 고정, 항상 주입

**핵심 필드 (memories 테이블):**
- `related_entities` (JSON) — 이 기억이 누구에 관한 것인지
- `knows` (JSON) — 이 기억을 직접 아는 사람 배열 (disclosure 제어)
  - `dm-X` → [X, "owner"] / `internal-dm-A-B` → [A, B]
- `importance` (1-10) — retrieval 스코어
- `parent_memory_id` — L2/L3 origin 링크

**Disclosure 룰:**
- 주입 시 `owner ∉ knows` (internal 출처)인 메모리도 포함하되 "이 내용은 사적 대화 — 자발적으로 꺼내지 마" 마커 부착
- 에이전트가 자발적으로 공유하면 → 새 메모리 생성 (knows에 owner 추가)

**Cross-channel raw peek (실시간 awareness):**
- A가 참여 중인 다른 running 채널의 최근 5개 raw를 매 턴 주입
- 3개 채널 동시 대화 중일 때 A가 internal-dm-A-B 대화를 dm-A에서 자연스럽게 이어갈 수 있음

**Retrieval scoring:**
```
score = 0.4·semantic + 0.3·importance + 0.2·recency_decay + 0.1·relational
recency_decay = exp(-days/30)
```

**주입 Budget (~800 토큰/턴):**
- Pinned ~100 / Relationship ~50 / Working ~200 / Episodic(현) ~150 /
  Episodic(retrieved) ~100 / Facts ~100 / Cross-channel peek ~100

**추가 도구:**
- `recall_memory(query, entity, time_range)` — 에이전트가 직접 deep search
- `pin_memory(memory_id, reason)` — 오너/유나가 고정

**Async extraction:**
- 메시지 저장 즉시 반환 → 백그라운드 Haiku worker가 큐 처리
- 단일 패스 JSON 추출: summary + mem_type + related_entities + importance + facts + relationship_delta

**진행 상황 (2026-04-20 세션 완료):**
- ✅ DB 스키마 + 마이그레이션 + 헬퍼 (commit `6c7aa1e`)
- ✅ memory.py 5 레이어 재작성 완료:
  - async Haiku worker (`enqueue_extraction`, 데몬 스레드, 큐 기반)
  - 단일 패스 JSON 추출 (`_single_pass_extract`) — summary + type + entities + importance + facts[] + relationships[]
  - L2/L3 rollup (`_try_l2_rollup`, `_try_l3_rollup`) — 5→1 압축
  - budget 기반 주입 (`get_memory_context`) — Pinned / Relationship / Episodic(current) / Episodic(retrieved) / Facts
  - retrieval scoring (entity overlap + importance + recency + relational)
  - disclosure 마커 (internal-* → owner 채널 주입 시 🔒사적 부착)
  - `recall_memory` + `pin_memory` API
- ✅ recall_memory / pin_memory 도구 (registry + handler + applies_to 설정)
- ✅ 대시보드 메모리 뷰 확장:
  - `monitor.get_agent_detail()` → `pinned_memories`, `agent_facts`, `relationship_history` 필드 추가
  - 웹 대시보드: 📌 Pinned 블록 + Facts (subject별 그룹) + Relationship History + CSS (importance/entities/pinned 뱃지)
  - TUI 대시보드: `📌 Pinned` / `📚 Facts · subject` / `📈 Relationship Deltas` 패널 + 레벨별 색상 코딩
- ✅ QA bot 여자 에이전트만 요청 제약 (`tests/e2e/test_user_bot.py` persona에 Character creation constraint 섹션)
- ✅ QA 스모크 통과 (29 메시지 → L1 4건 + facts 5건 자동 추출 확인)
- ✅ DB 인덱스 버그 fix — `idx_mem_importance` / `idx_mem_pinned` 를 `init_db().executescript`에서 제거하고 `_migrate_schema()` 로만 생성 (신규 컬럼 의존성)

**진행 상황 (2026-04-20 후반 세션):**
- ✅ 커뮤니티 격리 감사 + fix:
  - 웹 대시보드 avatar API 가 잘못 모든 community profile_images/ 스캔하던 fallback 제거 (security/privacy 위반)
  - `_set_active_community` 가 profile 캐시 (`_profile_cache`, `_user_profile_cache`, `_user_summary_cache`) 와 webhook 캐시 invalidate 하도록 수정
  - 이전: private→qa 전환 시 유나(demo)의 이름이 서유나(qa) 로 캐시 누설
  - 이후: 각 community 전환 시 모든 캐시 clear → 정확한 이름/프로필 반환
- ✅ 커뮤니티 격리 검증 테스트 (`tests/unit/test_community_isolation.py` 4 케이스): snapshot / agent_detail / avatar / profile 캐시 — 4 커뮤니티 (demo/dev/private/qa) 전환 교차 테스트 통과
- ✅ 대시보드 메모리 UI 용어 재설계: "Memory · 5 Layer" / "Facts (L3 Semantic)" / "Relationship History" 별도 섹션 → 하나의 **🧠 기억** 섹션으로 통합. "L1·E" 축약어 폐기, `최근/중기/장기` + `사건/사실/감정/관계` 풀 네이밍 + 아이콘
- ✅ dashboard state leakage 방지: `_STARTUP_COMMUNITY` 저장 후 `?community=` 없는 요청은 startup default 로 reset
- ✅ demo 커뮤니티 목업 재구축 (`scripts/seed_demo_mockup.py`):
  - 에이전트 9명 전원 여자 (도윤→민서, 지호→수연 성별 전환; 샘플 이미지 여자만 있음)
  - 가족 관계 없음, 친구/동료/파트너 범주만
  - L1/L2/L3 메모리 + agent_facts 29건 + relationship_history 4건 + pinned 1건
  - 채널 16개, 대화 141건, 3 라이브 채널
  - 쇼케이스 URL: `http://localhost:8765/?community=demo`
- ✅ private DB 마이그레이션 확인: 스키마 최신 + 레거시 241 메모리 중 110건 related_entities 백필 (regex 이름 매칭)

**알려진 이슈 (다음 세션 후보):**
- test_user_bot 이 mgr-creator 채널로 이동을 감지 못하고 튜토리얼 완료로 잘못 판단하고 조기 종료. 포맷팅 시스템으로 일부 개선되겠지만 봇 자체 로직 수정 필요.
- L3 rollup 은 L2 5개 쌓여야 발동 (월 단위 스케일). 단기 테스트에서는 관찰 어려움.
- 격리 감사에서 발견된 중간 심각도 이슈들 (봇 프로세스 한정, 대시보드엔 영향 없음): `AgentRuntime._pending_tool_results` / `_extract_queue` / supervisor tick 등 global state 가 community 전환 시 이론적으로 leak 가능. 봇은 1 community/process 전제라 실제 영향 없지만 장기적으로 community_id 를 context 로 전파 필요.

**i18n 계획 (보류)**: 외국인 배포 결정 시 영어 wrapper 대신 `src/core/prompts/{ko,en,...}/` 언어별 prompt fragment 분리 + `_get_community_language()` 기반 선택. 영어 wrapper 단독 작업은 해결책의 25%만 된다고 판단.

**레거시 드롭**: private 서버 DB는 다음 봇 시작 시 `init_db()` 의 `_migrate_schema()` 가 자동 마이그레이션. 레거시 코드는 유지 안 함.

## 메시지 포맷팅 시스템 (`src/bot/formatting.py`)

에이전트 응답의 평문 토큰을 디스코드 네이티브 렌더링으로 변환. **저장/로그/DB 는 원문 유지**, 디스코드 전송 직전에만 (`_raw_send_as_agent`) 변환.

**현재 규칙**:
- `#channel-name` → `<#channel_id>` (클릭 가능한 채널 mention). guild 에서 채널명을 못 찾으면 `**#name**` 볼드 폴백.
- `@owner-name` → `<@owner_id>` (오너만. 에이전트는 웹훅이라 mention 불가 — 이름만 그대로).

**규칙 확장**: `src/bot/formatting.py` 의 `_RULES` 테이블에 `(pattern, resolver)` 추가. resolver 는 match 객체 + ctx dict 받아서 치환 문자열 (또는 None = 변환 안 함) 반환.

**한글 채널명 지원**: regex 는 Python 3 기본 유니코드 `\w` 사용 — `#dm-서유나`, `#internal-dm-서유나-한유진` 전부 매칭.

**에이전트 가이드**: `profile.py._build_common_prompt` 에 "Style Guide — 대화 전반" 섹션으로 주입됨. 에이전트는 `#channel` 그대로 쓰도록 학습 (백틱·괄호·볼드 감싸지 말라고 명시).

**테스트**: `python -m tests.unit.test_formatting` (11 케이스).

## 커뮤니티 격리 (multi-community isolation)

**원칙**: `communities/{id}/` 는 완전히 독립. 한 community 의 agent/profile_image/memory/channel 이 다른 community 요청에서 **절대** 노출되면 안 됨.

**전역 state 위험 지점**:
- `src.community._current_id` (env `GLIMI_COMMUNITY`)
- `src.db.DB_PATH` cached
- `src.core.profile._profile_cache` / `_user_profile_cache` / `_user_summary_cache`
- `src.bot._webhook_cache`
- `src.core.memory._extract_queue` (background worker)
- `src.core.runtime.AgentRuntime._active_agents` / `_pending_tool_results`

**웹 대시보드 방어 (`scripts/web_dashboard.py`)**:
- `_COMMUNITY_LOCK` 로 community 전환 + API 호출 직렬화
- `_with_community(path, fn)` — `?community=` 명시 시 전환, 없으면 `_STARTUP_COMMUNITY` 로 reset (state leak 방지)
- `_set_active_community(cid)` — env 설정 + `set_community()` + `DB_PATH=None` + `profile.invalidate_cache()` + `webhook_cache.clear()`
- **`_serve_avatar` 는 현재 community 디렉터리에서만 이미지 찾음** (cross-community 스캔 금지)

**봇 프로세스 한정**: `run.sh` 는 1 community/process 로만 동작. AgentRuntime / memory worker 등의 global state 는 프로세스 수명 동안 community 고정이라 leak 없음. 그러나 코드 레벨에서 community_id 를 명시적 context 로 전파하는 게 장기적으로 더 안전 (향후 과제).

**검증 테스트**: `python -m tests.unit.test_community_isolation` — 4 case (snapshot/agent/avatar/profile 캐시 invalidation) 전부 통과.

## demo 커뮤니티 쇼케이스 (`scripts/seed_demo_mockup.py`)

`http://localhost:8765/?community=demo` 로 프로젝트 진가 노출하는 목업. 디스코드 채널 없이 **DB 만** 구성 (봇 실행 불필요). 스크립트 실행 시 `communities/demo/community.db` 리셋 + 재시딩.

**구성**:
- 오너 "빈이" + 에이전트 9명 (유나 mgr, 하나 creator, 페르소나 7 — **전원 여자** · 샘플 이미지 제약)
- 가족 관계 없음, 친구/동료/파트너만 (여자친구 = 파트너 카테고리로 유지)
- 5 레이어 메모리 전부 활용: L1/L2/L3 + agent_facts + relationship_history + pinned
- 채널 16개 (DM + internal-dm + internal-group + mgr + group)
- 대화 141건, 라이브 채널 3개 (status=running)
- 드라마틱 서브플롯: 빈이 생일 선물 비밀 (지우·예린 internal), 서아 짝사랑 (internal-dm-서아-하린), 지호 대체된 수연의 회사 정치 (internal-dm-수연-수진), 빈이 리드 기회 검토 등

**재실행 시**: DB 파일 + `-shm`/`-wal` 전부 삭제 → `init_db()` (스키마 마이그레이션) → 시딩. 이후 대시보드에서 즉시 확인 가능.


### core/conversation.py
- `start_conversation`: 에이전트간 자동 대화 (턴 제한, 종료 감지)
- `detect_room_request`: 톡방 생성 의도 패턴 감지

## `<tools>` 프로토콜 (구 CMD/QUERY/ACTION 대체)
매니저/Creator 응답 끝에 인라인 XML 블록:
```
(자연어 응답)

<tools>
  <call id="1" name="create_room">
    <arg name="participants">["서아", "지우"]</arg>
    <arg name="topic">주말 약속</arg>
  </call>
</tools>
```
- 도구 정의: `src/core/tools/registry.py` (이름·설명·인자 스키마·예시)
- 핸들러: `src/bot/mgr_system.py`의 `_h_*` 함수들 (예: `_h_create_room`, `_h_update_profile`)
- 별칭 해석: 사람 이름 → agent_id 자동 매핑
- 결과는 자연어 피드백으로 다시 LLM 에 주입 (연쇄 호출 가능)
- 주요 도구: `create_room`, `start_conversation`, `delete_channel`, `rename_channel`, `set_topic`, `purge_messages`, `restore_discord`, `set_emotion`, `update_profile`, `update_relationship`, `clear_channel`, `clear_conversations`, `reset_agent`, `dev_request`, `list_channels`, `query_log`, `search`, `get_profile`, `get_relationship`, `list_events`, `set_profile_image` 등

## 에이전트 ID 체계
- persona: agent-persona-001, 002, ...
- mgr: agent-mgr-001 (유나)
- creator: agent-creator-001 (하나)

## 채널 구조
- dm-{이름}: 1:1 채널 (`glimi-dm` 카테고리)
- group-{이름들}: 그룹 채팅 — 오너 + 에이전트 (`glimi-group`, GROUP_PARTICIPANTS로 참여자 추적)
- internal-dm-{A}-{B}: 에이전트간 1:1 비밀 DM (`glimi-internal-dm`, 오너 읽기전용)
- internal-group-{이름들}: 에이전트간 비밀 그룹 (`glimi-internal-group`, 오너 읽기전용)
- mgr-dashboard: 유나 관리 채널 (`glimi-mgr`)
- mgr-creator: 에이전트 생성 채널 (`glimi-mgr`)
- mgr-system-log: 시스템 로그/도구 호출 기록 (`glimi-mgr`)

## Scene 시스템 (`src/scenes/`)

**Scene = 세계관 상의 에피소드**. 시작·진행·종료 조건이 명확한 스토리 단위. 강제성 있음 — 진행 중엔 supervisor 가 흐름 감시·복원.

**현재 구현된 씬**:
- `tutorial` (`src/scenes/tutorial/`) — 오너 첫 방문 1회성. phase: `greet` → `collect_profile` → `channels_setup` → `channels_done` → `complete`. 완료 시 `meta.tutorial_phase = "complete"` + `logs/.tutorial-complete` 플래그.

**앞으로 추가 예정**:
- `birthday` — 멤버 생일 이벤트
- `conflict` — 멤버간 갈등 중재
- `party` — 단톡방 모임
- `outing` — 외출/여행 시나리오
- 공통 특성: 여러 에이전트 참여 + 시간축 + 엔딩 조건 + 메모리에 에피소드로 누적

**구조**:
- `Scene` base (`src/scenes/base.py`) — phase 관리, set_phase 훅, pool 트리거
- 씬별 `scene.py` (싱글톤) + `supervisor.py` (scene-scoped) + `handlers.py` (phase 전환 액션) + `prompts.py` (phase×agent_type 프롬프트 조각)

## Achievement 시스템 (`src/achievements/`)

**Achievement = 유저 UX 진척도 플래그**. Scene 과 **완전히 별개 레이어**:
| | Scene | Achievement |
|--|--|--|
| 성격 | 세계관 에피소드 | 유저 가이드 |
| 강제성 | supervisor 가 유도 (필수) | 선택적 — 미해결 OK |
| 저장 | meta / flag / memory | `achievements` 테이블 |
| 끝 | phase=complete | state=done |

**테이블** (`db.py`): `achievements(user_id, key, state, progress_data, unlocked_at, completed_at)`. state: `locked` / `unlocked` / `done`.

**이벤트 훅**: `db.add_message_hook(engine._on_message)` — 메시지 로깅 시마다 `engine.recompute_all()` 호출로 자동 갱신 (엔진 내부에서 done 은 스킵해서 비용 낮음).

**기본 과제 7개** (`src/achievements/definitions.py`): 튜토리얼 수료 / 첫 대화 / 세 명의 친구 / 단톡방 체험 / 훔쳐보는 재미 / 자율 사교 / 지속되는 관계.

**대시보드**: `/api/achievements` 엔드포인트 + "Achievements" 탭 (진척도 바 + 카드 그리드).

## 유나 지식 베이스 (`docs/yuna_knowledge.md`)

유나(mgr)가 **"씬이 뭐야?" / "도전과제 어떻게 달성?" / "너 어디까지 볼 수 있어?"** 같은 사용자 질문에 답할 수 있도록 하는 공개 FAQ. `_build_mgr_prompt` 가 이 파일을 system prompt 에 자동 로드 (`_load_yuna_knowledge`, mtime 캐시).

**파일 구조**:
- 공개 가능 섹션 — 프로젝트 개요, 씬, 도전과제, 유나 권한, 친구 만드는 법 등
- 금지 섹션 — 내부 기술(메모리 레이어, LLM 모델명, DB 구조), supervisor 존재, QA/개발 내부 흐름
- 회피 예시 — 금지 주제 물어봤을 때 자연스러운 deflection 문구

**갱신 원칙** (중요):
- 씬·도전과제 추가/변경 시 **반드시 이 파일 갱신**
- 새 내부 기술 도입 시 "금지" 섹션에 추가
- 유나 도구 변경 시 "내 권한" 업데이트
- 소스코드 직접 참조는 금지 — 추상화 유지 + 노출 방지

## Supervisor 시스템 (`src/supervisors/`, `src/scenes/*/supervisor.py`)

### 정의
슈퍼바이저 = **백그라운드 감시자**. 관찰 → 감지 → 개입 루프. **Reactive 안전망**이지 content 생성자가 아님.
에이전트가 평소 흐름 주도, supervisor는 흐름 끊기면 복원 (재촉, 자동 전이, 강제 지시).
페르소나 에이전트는 supervisor 존재 모름. Haiku로 컨텍스트 판단 후 `generate_response_force`로 내면 생각처럼 nudge 주입.

### 3가지 종류 (kind)
| kind | scope | lifetime | cardinality |
|------|-------|----------|-------------|
| **scene** | 특정 씬 | 씬 시작~완료 | 씬 1개당 N개 가능 |
| **channel** | 특정 채널 | 채널 running~idle | running 채널 수만큼 (1:1) |
| **system** | 전역 | 봇 수명 | 싱글톤 |

### 네이밍 규칙
- Class: `{Scope}{Role}Supervisor` (scene-scoped) / `{Role}Supervisor` (system/channel)
- id: `scope.role` (scene) / `role:<instance_key>` (channel) / `role` (system)
- display (KR): `범주 · 서브` 스타일

예시:
- `TutorialFlowSupervisor` id=`tutorial.flow` label=`튜토리얼 · 흐름` kind=scene
- `ChatSupervisor` id=`chat:internal-dm-유나-하나` label=`대화 · 유나·하나` kind=channel
- `OrchestratorSupervisor` id=`orchestrator` label=`오케스트레이터` kind=system

### SupervisorPool — 중앙 레지스트리
`src/supervisors/base.py` 의 싱글톤. 인스턴스 등록/해제/tick 관리.

**lifecycle triggers** — 이 시점에 `pool.sync()` 호출:
1. 봇 ready (초기화)
2. `db.set_channel_status(ch, status)` — running↔idle 변화
3. `Scene.set_phase(phase)` — 씬 phase 전환
4. tick loop (정기 정합성 보장, 매 N초)

**sync 로직**:
- scene-scoped: 활성 씬의 `supervisors()` 리스트 수집, 없으면 제거
- channel-scoped: `status=running` internal-* 채널들 → 각각 ChatSupervisor 인스턴스 보장
- system: 항상 존재

**tick 격리**: 각 supervisor `check()` 호출을 try/except 로 감싸서 1개 실패가 전체 영향 X.

### 현재 구현된 Supervisors
- **TutorialFlowSupervisor** (scene) — `src/scenes/tutorial/supervisor.py`: 튜토리얼 phase 전이·재촉·auto-finish
- **ChatSupervisor** (channel, per-instance) — `src/supervisors/chat.py`: running internal-* 채널별 stall 감지·재촉
- **OrchestratorSupervisor** (system) — `src/supervisors/orchestrator.py`: 에이전트 페어 스캔 → 자연스러운 대화 시작 결정 (유나가 직접 하지 않음)

### 채널 running/idle 결정
`internal-*` 채널의 `status` 전이 경로:
1. **유저 요청**: 오너가 유나한테 "재내 얘기좀 시켜봐" → Yuna가 `start_conversation` 도구 호출 → status=running
2. **에이전트 결심**: 에이전트가 `request_room` tool로 타인과 대화 요청 → 생성 + running
3. **오케스트레이터 자동**: `OrchestratorSupervisor` 가 주기적 스캔 (친밀도, idle 시간, 최근 대화 이력) → 자연스러운 페어 대화 시작 → running

idle 전이:
- `state.should_end(responses)` 감지 시 `db.set_channel_status(ch, "idle")`
- 최대 턴 도달
- 유저 수동 stop

### 시각화
- **Scene supervisor**: 씬 카드 안 뱃지
- **Channel supervisor**: 엣지(채널) 위 뱃지. peer 노드로 X
- **System supervisor**: 헤더/사이드 상시 표시

## 작업 규칙
- 커밋 메시지는 짧게 — 1줄 제목, 필요시 핵심 1-2줄. 장황한 본문 금지.

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
- `<tools>` 블록은 시스템 로그(mgr-system-log)에만 노출 (대화 채널에 절대 노출 금지)

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

**자율 수행 절차**: `docs/qa_playbook.md` — 유저가 "QA 진행해" 하면 이 문서 따라 자율 사이클 (실행 → 모니터 → 분석 → 수정 → 재실행).
**토큰 누적 기록**: `tests/e2e/results/token_usage.md` — 매 런의 델타 append.

```bash
python -m tests.e2e.runner              # 1회 실행
python -m tests.e2e.runner --runs 3     # 3회 반복
./scripts/qa.sh                         # tmux 세션으로 백그라운드 실행 (권장)
./scripts/qa.sh stop                    # 중단
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
2. Glimi 봇 시작 → 기존 디스코드 채널 삭제 → 튜토리얼 시작
3. 테스트 유저 봇 시작 → 신규 유저처럼 자연스럽게 대화
4. 튜토리얼 완료 or 타임아웃
5. 로그 수집 → 자동 판정 (프로필 중복, race condition, 태그 노출 등)

### 필요 설정
- `communities/qa/.env`에 `DISCORD_BOT_TOKEN`, `DISCORD_GUILD_ID`, `TEST_BOT_TOKEN` 설정
- 별도 디스코드 서버에 Glimi 봇 + 테스트 유저 봇 초대
- 테스트 유저 프로필 커스텀: 환경변수 `QA_USER_NAME`, `QA_USER_NICKNAME`, `QA_USER_AGE` 등
