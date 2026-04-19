# Project Glimi — CLAUDE.md

## 프로젝트 개요
에이전트 소셜 시뮬레이션. 고유 페르소나를 가진 에이전트들이 디스코드를 통해 오너(개발자)와 1:1/그룹으로 소통하고, 에이전트끼리도 자체적으로 대화하며 관계를 형성하는 커뮤니티 시스템.

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
    │   ├── memory.py     ← 3단계 메모리 (raw→L1→L2)
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
    │   ├── mgr_system.py ← Manager 도구 핸들러 (`<tools>` 실행)
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

**알려진 이슈 (다음 세션 후보):**
- test_user_bot 이 mgr-creator 채널로 이동을 감지 못하고 온보딩 완료로 잘못 판단하고 조기 종료. 포맷팅 시스템으로 일부 개선되겠지만 봇 자체 로직 수정 필요.
- L3 rollup 은 L2 5개 쌓여야 발동 (월 단위 스케일). 단기 테스트에서는 관찰 어려움.

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
- `OnboardingFlowSupervisor` id=`onboarding.flow` label=`온보딩 · 흐름` kind=scene
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
- **OnboardingFlowSupervisor** (scene) — `src/scenes/onboarding/supervisor.py`: 온보딩 phase 전이·재촉·auto-finish
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
