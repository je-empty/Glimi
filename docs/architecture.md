# Architecture

## 기술 스택
- Python 3.11+ / discord.py (현재 유일 어댑터)
- 에이전트 두뇌: Claude Code CLI (`claude` 명령어) subagent 방식
- 페르소나/매니저/Creator: claude-sonnet-4-6 / Dev Runner: Opus / Supervisors: Haiku
- DB: SQLite (`communities/{id}/community.db`)
- 플랫폼(관리 UI): FastAPI + uvicorn (`src/platform/`, `:8765`)
- TUI: Textual (`src/tui/`, deprecated — 웹으로 이전 중)

## 디렉토리 구조
```
Glimi/
├── CLAUDE.md
├── scripts/
│   ├── run.sh              ← 메인 실행 (플랫폼 데몬)
│   ├── stop.sh
│   ├── qa.sh               ← E2E QA 자동화
│   ├── web_dashboard.py    ← 구 stdlib 대시보드 (플랫폼 이전 완료 시 제거)
│   ├── seed_demo_mockup.py ← demo 커뮤니티 목업
│   └── migrate_timestamps_to_utc.py
├── communities/            ← 커뮤니티별 데이터 (.gitignore)
│   ├── registry.toml
│   └── {id}/
│       ├── .env            ← DISCORD_BOT_TOKEN
│       ├── community.db    ← SQLite
│       ├── profile_images/
│       └── logs/
├── data/                   ← 플랫폼 레벨 (계정 DB + secret key)
│   └── platform.db
├── communities.example/
├── assets/
│   ├── profile_images/
│   └── sample_profile_images/
├── docs/                   ← 이 디렉토리
├── dev/
│   ├── pending.json        ← 개발 요청
│   └── result.json
├── legacy/
└── src/
    ├── community.py        ← 커뮤니티 컨텍스트
    ├── db.py               ← SQLite CRUD
    ├── log_writer.py
    ├── discord_bot.py      ← 봇 엔트리 (subprocess 로 돌아감)
    ├── core/               ← 에이전트 두뇌 (플랫폼 중립)
    │   ├── runtime.py
    │   ├── profile.py
    │   ├── memory.py
    │   ├── monitor.py
    │   ├── conversation.py
    │   ├── sync.py         ← Discord↔DB 동기화 (어댑터 책임)
    │   ├── timeutil.py
    │   └── tools/          ← <tools> XML 프로토콜
    ├── bot/                ← Discord 어댑터
    ├── platform/           ← FastAPI 플랫폼 (신규)
    ├── scenes/             ← Scene 시스템 (tutorial 등)
    ├── supervisors/        ← 백그라운드 감시자
    ├── achievements/
    ├── tui/                ← 터미널 UI (deprecated)
    └── tools/
        ├── cli.py
        ├── dev_runner.py   ← 개발자 에이전트 (Opus)
        └── migrate.py
```

## 핵심 모듈

### discord_bot.py
- Webhook 으로 에이전트별 프로필 이미지/이름 전송
- `handle_dm`: 1:1 채널 (채널별 asyncio.Lock)
- `handle_group`: 그룹채팅 (GROUP_PARTICIPANTS 로 참여자 관리)
- 매니저/Creator 응답의 `<tools>` 블록 파싱 → `core/tools/dispatcher` 실행
- 개발 요청: `dev_request` 도구 → pending.json → exit(42) → Opus dev_runner

### core/runtime.py
- `generate_response(agent_id, channel, message, log_user_message=True)`
- `_call_claude_code`: system prompt(정적) + user prompt(동적: 감정+메모리+대화이력)
- 에이전트 간 대화: `generate_agent_to_agent`

### core/profile.py
- DB 기반 프로필 로드/저장 (`_profile_cache`, `invalidate_cache`)
- `_build_persona_prompt` / `_build_mgr_prompt` / `_build_creator_prompt`
- **TODO**: `src/core/prompts/{lang}/` 로 분리 예정 (프롬프트 모듈 리팩터)

## DB 스키마

**코어:**
- `agents`: id, type, name, name_i18n(JSON), status, current_emotion, emotion_intensity, last_active, birth_year, age, gender, mbti, enneagram, background, profile_image_filename, version, created_at
- `relationships`: agent_a, agent_b, type, intimacy_score, dynamics
- `relationship_history`: 관계 변곡점 delta
- `conversations`: channel, speaker, message, timestamp, context_emotion
- `events`: event_type, participants, description, impact
- `memories`: agent_id, channel, level(1/2/3), content, msg_id_from/to, related_entities, knows, importance, parent_memory_id, is_pinned
- `agent_facts`: (subject, predicate, object) + Zep식 supersession (`valid_from`/`valid_to`)
- `achievements`: user_id, key, state, progress_data, unlocked_at, completed_at

**프로필 위성 (JSON blob):**
- `agent_personality` / `agent_appearance` / `agent_daily_life` / `agent_speech`
- `agent_relationship_templates`: 정적 관계 정의
- `agent_config`: mgr_config / creator_config

**유저/메타:**
- `users`: id, name, birth_year, age, mbti, personality(JSON), appearance(JSON), speech(JSON)
- `meta`: key, value (active_user_id 등)

**DB 하나 = 커뮤니티 하나.** `communities/{id}/community.db`. `community.export_community()` / `import_community()` 로 DB + 프로필 이미지 통째 이전 가능.

## `<tools>` 프로토콜

매니저/Creator 응답 끝에 인라인 XML:
```
(자연어 응답)

<tools>
  <call id="1" name="create_room">
    <arg name="participants">["서아", "지우"]</arg>
    <arg name="topic">주말 약속</arg>
  </call>
</tools>
```

- 도구 정의: `src/core/tools/registry.py`
- 핸들러: `src/bot/mgr_system.py` 의 `_h_*` 함수
- 별칭 해석: 사람 이름 → agent_id 자동 매핑
- 결과는 자연어 피드백으로 LLM 에 재주입 (연쇄 호출)
- 주요 도구: `create_room`, `start_conversation`, `delete_channel`, `rename_channel`, `set_topic`, `purge_messages`, `restore_discord`, `set_emotion`, `update_profile`, `update_relationship`, `clear_channel`, `reset_agent`, `dev_request`, `list_channels`, `query_log`, `search`, `get_profile`, `get_relationship`, `list_events`, `set_profile_image`, `recall_memory`, `pin_memory`

## 에이전트 ID 체계
- persona: `agent-persona-001, 002, ...`
- mgr: `agent-mgr-001` (유나)
- creator: `agent-creator-001` (하나)

## 채널 구조
- `dm-{이름}`: 1:1 (`glimi-dm` 카테고리)
- `group-{이름들}`: 그룹 (`glimi-group`, GROUP_PARTICIPANTS)
- `internal-dm-{A}-{B}`: 에이전트간 1:1 (`glimi-internal-dm`, 오너 읽기전용)
- `internal-group-{이름들}`: 에이전트간 그룹 (`glimi-internal-group`)
- `mgr-dashboard` / `mgr-creator` / `mgr-system-log`: 관리 채널 (`glimi-mgr`)

## 다국어 에이전트 이름
- `agents.name_i18n` TEXT (JSON: `{"ko": "서유나", "en": "Yuna"}`)
- `name`: 기본 이름 (항상 존재)
- `get_agent_display_name(agent_id)`: 현재 커뮤니티 언어 기준 이름
- 언어 추가 = JSON 키 추가 (컬럼 변경 불필요)
