# Glimi 개발 가이드 (개발 세션 필독)

> 이 문서는 **Glimi 프로젝트에서 개발 작업을 하는 Claude Code 세션이 가장 먼저 확인해야 하는 문서**다.
> 작성: 2026-04-21 · 갱신 규칙: 설계 락인·타깃·우선순위 변경 시 즉시 갱신.

---

## 🎯 한 장 요약 — 모든 개발 판단의 기준

| 항목 | 확정값 |
|------|--------|
| **타깃** | 20대 초반 여성 감성 유저 (B 세그먼트) · 장기관계·힐링·케어 선호 |
| **제품 한 줄** | "AI 친구들이 당신 없이도 자기들끼리 살아가는 커뮤니티" |
| **플랫폼** | 자체 웹 채팅 = 라이브 (유일 transport, `GLIMI_TRANSPORT=web`) / 웹 PWA = 진행 / 모바일 네이티브 = 15개월+ |
| **연령** | 17+ |
| **콘텐츠** | Phase A-B SFW 전용 / Phase C 부터 Community-scoped + Opt-in 이중 잠금 |
| **현재 스프린트** | **Phase 0 — 감정 Application Layer** (EmotionSupervisor / 프롬프트 감정 강제 / 케어 루프) |

---

## 🔒 설계 락인 — 바뀌지 않는 원칙

모든 코드 변경·기능 추가는 이 6가지를 위반하지 않는지 **먼저** 확인.

1. **타깃은 B 단독** — 20대 여성, 장기관계·힐링·케어. 10대 서브컬처 / 하드 drama / 폭력·배신 씬 절대 금지.
2. **감정은 퍼스트클래스** — 새 기능 설계 시 "이 기능이 친구의 감정 delta 를 남기는가" 체크. NO 면 우선순위 낮춤.
3. **드라마는 해결 구조만** — 갈등은 "발생→중재→화해". 파괴적 엔딩 금지.
4. **도구 폭주 금지** — 신규 `<tools>` 도구 추가 시 "타깃 B 감정 접점이 있나" 심사. 지금 44개인데 실제 플레이는 10개 미만 사용.
5. **transport 중립 유지** — 채팅 출구는 어댑터다. 코어 로직은 특정 채팅 SDK 를 몰라야 하고, 새 transport 는 `community/core/channel_adapter.py` (`ChannelAdapter` Protocol) + `glimi-core/glimi/transport.py` (`Outbox`/`Speaker`) 시 seam 에 꽂는다. 라이브 어댑터 = `community/adapters/web/`.
6. **메타 용어 금지** — 사용자 노출 텍스트에 "AI / 봇 / 에이전트" 단어 금지. 친구·사람·이름으로.

---

## 📋 개발 작업 시작 전 체크리스트

새 기능·변경 작업 시작 전에 아래를 **순서대로** 확인.

### Step 1. 전략 일치 확인
- [ ] `analysis/pending_decisions.md` — 관련 결정이 "확정" 인가 "보류" 인가
- [ ] `analysis/glimi_roadmap_todo.md` — 현재 Phase 와 맞는가, 더 높은 우선순위 선행 작업이 있나
- [ ] 설계 락인 6 가지 통과하는가

### Step 2. 현재 구조 파악
- [ ] `CLAUDE.md` — 프로젝트 구조·컨벤션 최신판
- [ ] 관련 디렉터리 README 또는 모듈 docstring
- [ ] 기존 유사 패턴 검색 (`community/supervisors/`, `community/scenes/tutorial/` 등 레퍼런스)

### Step 3. 타깃 B 관점 심사
- [ ] 이 기능이 20대 여성 감성 유저 첫 5분 / 첫 1일 / 첫 1주 경험에 도움되는가
- [ ] 감정 delta 를 남기는가 (친구 감정 변화·오너 케어 피드백)
- [ ] 드라마 구조가 "해결형" 인가

### Step 4. 비용·안전 심사
- [ ] LLM 비용 폭주 경로 있나 (자율 대화 빈도·턴 상한 고려)
- [ ] 커뮤니티 격리 위반 없나 (global state 변경 시 `tests/unit/test_community_isolation.py` 통과 확인)
- [ ] 메타 자각 노출 위험 없나 (`<tools>` 블록 노출, "AI" 언급 등)

---

## 🗂️ 기능별 파일 참조 맵

개발할 기능 유형에 따라 어디부터 읽어야 하는지.

### 에이전트 두뇌·응답 생성
- `community/core/runtime.py` — `generate_response`, `_call_claude_code`, `_parse_response`
- `community/core/profile.py` — `_build_persona_prompt`, `_build_mgr_prompt`, `_build_creator_prompt`
- `community/core/conversation.py` — 에이전트간 자동 대화
- 모델 선택: persona/mgr/creator = Sonnet / dev_runner = Opus / supervisor = Haiku

### 감정 시스템 (P0 작업 시)
- `community/db.py` — `agents.current_emotion`, `emotion_intensity`, `conversations.context_emotion`
- `community/core/runtime.py:201` — 프롬프트 감정 주입 지점
- 도구: `set_emotion` (`community/core/mgr_actions.py`, `community/core/tools/registry.py`)
- **P0 신규 작업**: `community/supervisors/emotion.py` 신설, `profile.py._build_persona_prompt` 감정 강제 섹션 추가

### 메모리 시스템 (5 레이어)
- `community/core/memory.py` — 전체 파이프라인
- 테이블: `memories`, `agent_facts`, `relationship_history`, `conversations`
- 도구: `recall_memory`, `pin_memory`
- **금지**: 메모리 저장 로직을 system prompt 에 넣지 말 것 (user prompt 에 동적 주입)
- 장기 관측 필요: L3 rollup (L2 5개 쌓여야 발동)

### 씬(Scene) 시스템
- `community/scenes/base.py` — Scene base class, phase 관리, set_phase 훅
- 레퍼런스 구현: `community/scenes/tutorial/` (scene.py + supervisor.py + handlers.py + prompts.py)
- 신규 씬 추가 시: 위 4개 파일 + `docs/yuna_knowledge.md` 갱신
- 타깃 B 우선순위: birthday > healing > relationship_milestone > group_outing

### Supervisor 시스템
- `community/supervisors/base.py` — SupervisorPool, 3 kind (scene/channel/system)
- 네이밍: `{Scope}{Role}Supervisor` / id = `scope.role` / label = `범주 · 서브`
- Lifecycle trigger: 런타임 ready / `db.set_channel_status` / `Scene.set_phase` / tick loop
- 신규 system supervisor 추가 시 `SupervisorPool.sync()` 에 등록

### 도구(`<tools>`) 추가
- `community/core/tools/registry.py` — 도구 정의 (이름·설명·인자·예시)
- `community/core/mgr_actions.py` — 매니저 도구 핸들러 구현
- `community/core/tools/dispatcher.py` — 호출 → 핸들러 연결
- **심사 기준**: 타깃 B 감정 접점 있나 / 기존 도구로 대체 불가 / 보안상 파괴적이지 않나

### 웹 채팅 어댑터 레이어 (라이브 transport)
- `community/platform/web_runtime.py` — 커뮤니티별 런타임 엔트리 (플랫폼 supervisor 가 구동, subprocess 없음)
- `community/adapters/web/channels.py` — 라이브 채널 어댑터 (DM/그룹/internal 메시지 처리, 채널 매핑)
- `community/core/channel_adapter.py` — `ChannelAdapter` Protocol (transport 중립 seam)
- `glimi-core/glimi/transport.py` — `Outbox`/`Speaker` 추상 (새 transport 가 꽂는 자리)
- 포맷팅: `#channel`/`@owner` 멘션은 웹 클라이언트가 네이티브 렌더 (`docs/formatting.md`)

### 튜토리얼·온보딩
- `community/scenes/tutorial/` — 전체 플로우
- 현재 이슈: `handlers.py:56,106,122` 의 `asyncio.sleep(15)` (침묵 45초) / `prompts.py:67-83` 기계적 프로필 수집
- 개선 방향: 선택지 UI, 실시간 로딩 피드백, 감정적 훅 삽입

### Achievement 시스템
- `community/achievements/definitions.py` — 과제 정의 7개
- `community/achievements/engine.py` — 자동 갱신 로직
- 훅: `db.add_message_hook(engine._on_message)`
- 신규 과제 추가 시 타깃 B 초기 1일 경험에서 달성 가능한지 확인

### 커뮤니티·DB·격리
- `community/community.py` — 커뮤니티 컨텍스트
- `community/db.py` — SQLite CRUD, 스키마, `_migrate_schema`
- `tests/unit/test_community_isolation.py` — 격리 검증
- **주의**: `AgentRuntime._pending_tool_results` / `_extract_queue` 등 global state 존재. 1 community/process 전제 깨질 시 `community_id` context 전파 필요.

### 대시보드
- `community/platform/` — FastAPI + Jinja2 + static (`:8000`)
- `community/platform/dashboard/` (api.py, actions.py, context.py) — 로직 계층
- `community/platform/templates/dashboard/index.html` — HTML 셸 (Jinja)
- `community/platform/static/css/dashboard.css` + `static/js/dashboard.js` — 프론트엔드
- `community/core/monitor.py` — `get_snapshot`, `get_agent_detail` 데이터 단일 소스
- **필수**: 재시작 시 `--host 0.0.0.0` 옵션 (run.sh 기본값)

---

## 📚 문서 참조 포인터

| 문서 | 위치 | 목적 |
|------|------|------|
| 프로젝트 컨벤션 | `CLAUDE.md` | 구조·모듈·규칙 전체 |
| 이 파일 | `docs/dev_guide.md` | 개발 세션 시작 가이드 |
| 유나 공개 FAQ | `docs/yuna_knowledge.md` | 씬·도전과제·유나 권한 공개 설명 (유나 prompt 에 자동 로드) |
| QA 플레이북 | `docs/qa_playbook.md` | E2E 테스트 자율 수행 절차 |
| **전략 문서 (git ignored)** | | |
| 제타 경쟁 분석 | `analysis/zeta_vs_glimi_analysis.md` | 갭 매트릭스·리스크·해자 |
| 사업 전략 | `analysis/business_strategy.md` | 타깃·가격·수익모델·컴플라이언스 근거 |
| 로드맵 | `analysis/glimi_roadmap_todo.md` | Phase 0~4 + 제거 리스트 |
| 결정 체크리스트 | `analysis/pending_decisions.md` | 확정·보류 결정사항 |

---

## ⚠️ 금지 사항 (개발하지 말 것)

- ❌ 10대 서브컬처 타깃 씬 (이세계·하드 판타지·학원 배틀물)
- ❌ 폭력·배신·파괴적 갈등 결말 씬
- ❌ 특정 채팅 SDK 직접 의존 (transport 중립 — 코어 로직은 `ChannelAdapter` seam 만 알아야 함)
- ❌ 메모리·감정을 system prompt 에 넣기 (user prompt 에 동적 주입해야 함)
- ❌ 사용자 노출 텍스트에 "AI / 봇 / 에이전트" 단어
- ❌ `<tools>` 블록을 대화 채널에 노출 (런타임 툴 로그는 `communities/<id>/logs/system.log` 파일로)
- ❌ dm-/mgr- 채널 삭제 (보호됨)
- ❌ `--host 0.0.0.0` 없이 대시보드 재시작
- ❌ 커밋 메시지에 Claude Co-Authored-By 넣기
- ❌ `--no-verify` 로 pre-commit 우회 (사용자 명시 요청 외)

---

## 🧪 품질 체크 — 변경 후 실행

```bash
# 커뮤니티 격리 검증 (global state 만진 경우 필수)
python -m tests.unit.test_community_isolation

# 포맷팅 (formatting.py 변경 시)
python -m tests.unit.test_formatting

# E2E QA (튜토리얼·웹 채팅 플로우 변경 시)
./scripts/qa.sh

# UI/대시보드 변경 시
# 반드시 브라우저에서 실제 확인 (타입체킹만으론 검증 불충분)
```

---

## 🚦 현재 스프린트 — Phase 0 (2주)

**목표**: 친구 감정이 실시간으로 반영·변화하는 application layer 구축.

### P0-1. EmotionSupervisor
- 파일: `community/supervisors/emotion.py` (신설)
- 패턴 참조: `community/supervisors/orchestrator.py`, `community/scenes/tutorial/supervisor.py`
- Haiku 로 감정 감지 → `set_emotion` 자동 호출

### P0-2. Persona 프롬프트 감정 강제
- 파일: `community/core/profile.py._build_persona_prompt`
- intensity 구간별 톤 가이드 (1-3 / 4-6 / 7-8 / 9-10) few-shot 추가

### P0-3. 케어 피드백 루프
- 오너 위로 발화 N회 누적 → 대상 intensity 감쇠 + 자연어 반응
- Achievement `empathy_conversation` 신규

### P0-4. 대시보드 감정 뷰
- 파일: `community/platform/dashboard/` (api.py, actions.py), `community/platform/templates/dashboard/index.html`, `community/platform/static/{css,js}/dashboard.*`, `community/core/monitor.py`
- 에이전트 노드 감정 뱃지 + 커뮤니티 감정 타임라인

**P0 완료 검증**: 테스트 유저 "힘들어" → 30초 내 친구가 감정 인지 응답 / 오너 위로 3회 누적 → 친구 "좀 나아졌어" 류 반응.

---

## 📈 현재 스프린트 이후 (참고)

상세는 `analysis/glimi_roadmap_todo.md` 참조.

- **P1** (4~6주): 씬 다각화 (birthday > healing > milestone) · 오너 부재 시뮬레이션 · 자동 사건 엔진 · Disclosure 그래프 · 기억 일관성 감시자 · 튜토리얼 UX 개선
- **P2** (2~3주): 유저 hijack 가드 · 장소/시간 컨티뉴티 · 대화 주도권 밸런스 · 마케팅 뱃지
- **P3** (6~8주): 세계관/로어북 · 이미지 생성 · 내레이션 모드 · 커뮤니티 갤러리
- **P4** (장기): 자체 웹 PWA (12개월) · i18n · 마켓플레이스 · 보이스

---

## 🔄 이 문서 갱신 규칙

다음 변경 시 즉시 이 문서 갱신:
- 설계 락인 6 가지 중 하나 변경
- 타깃 세그먼트 변경
- 현재 스프린트 Phase 전환
- 신규 필수 참조 파일 등장
- 금지 사항 추가·해제
