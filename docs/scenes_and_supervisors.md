# Scenes, Achievements, Supervisors

## Scene 시스템 (`community/scenes/`)

**Scene = 세계관 상의 에피소드**. 시작·진행·종료 조건이 명확한 스토리 단위. 강제성 있음 — 진행 중엔 supervisor 가 흐름 감시·복원.

**구현된 씬:**
- `tutorial` — 오너 첫 방문 1회성. phase: `greet` → `collect_profile` → `channels_setup` → `channels_done` → `complete`

**예정:** `birthday`, `conflict`, `party`, `outing`
공통 특성: 여러 에이전트 참여 + 시간축 + 엔딩 조건 + 메모리에 에피소드로 누적

**구조:**
- `Scene` base (`community/scenes/base.py`) — phase 관리, set_phase 훅, pool 트리거
- 씬별 `scene.py` (싱글톤) + `supervisor.py` + `handlers.py` + `prompts.py`

## Achievement 시스템 (`community/achievements/`)

Scene 과 **완전히 별개 레이어**:

| | Scene | Achievement |
|--|--|--|
| 성격 | 세계관 에피소드 | 유저 가이드 |
| 강제성 | supervisor 유도 (필수) | 선택적 |
| 저장 | meta / flag / memory | `achievements` 테이블 |
| 끝 | phase=complete | state=done |

**테이블:** `achievements(user_id, key, state, progress_data, unlocked_at, completed_at)`. state: `locked` / `unlocked` / `done`.

**훅:** `db.add_message_hook(engine._on_message)` — 메시지 로깅 시마다 `engine.recompute_all()` (done 은 스킵).

**기본 과제 7개** (`community/achievements/definitions.py`): 튜토리얼 수료 / 첫 대화 / 세 명의 친구 / 단톡방 체험 / 훔쳐보는 재미 / 자율 사교 / 지속되는 관계.

---

## Supervisor 시스템

**정의:** 백그라운드 감시자. 관찰 → 감지 → 개입. **Reactive 안전망**이지 content 생성자 아님. 에이전트가 평소 흐름 주도, supervisor 는 흐름 끊기면 복원 (재촉, 자동 전이, 강제 지시). 페르소나 에이전트는 supervisor 존재 모름. Haiku 로 컨텍스트 판단 후 `generate_response_force` 로 내면 생각처럼 nudge 주입.

### 3가지 kind

| kind | scope | lifetime | cardinality |
|------|-------|----------|-------------|
| **scene** | 특정 씬 | 씬 시작~완료 | 씬 1개당 N개 |
| **channel** | 특정 채널 | 채널 running~idle | running 채널 수 (1:1) |
| **system** | 전역 | 봇 수명 | 싱글톤 |

### 네이밍
- Class: `{Scope}{Role}Supervisor` (scene) / `{Role}Supervisor` (system/channel)
- id: `scope.role` (scene) / `role:<instance_key>` (channel) / `role` (system)
- display (KR): `범주 · 서브`

### SupervisorPool (`community/supervisors/base.py`)
싱글톤 레지스트리. sync 트리거 시점:
1. 봇 ready
2. `db.set_channel_status(ch, status)` — running↔idle
3. `Scene.set_phase(phase)`
4. tick loop (정기 정합성)

### 구현된 Supervisors
- **TutorialFlowSupervisor** (scene) — 튜토리얼 phase 전이·재촉·auto-finish
- **ChatSupervisor** (channel, per-instance) — running internal-* 채널별 stall 감지·재촉
- **OrchestratorSupervisor** (system) — 에이전트 페어 스캔 → 자연스러운 대화 시작 결정

### 채널 running/idle 결정
`internal-*` 채널의 `status` 전이:
1. 유저 요청 (유나 `start_conversation` 도구)
2. 에이전트 결심 (`request_room` 도구)
3. OrchestratorSupervisor 자동 (친밀도/idle/최근 이력 기반)

idle 전이: `state.should_end()` / 최대 턴 / 유저 수동 stop

---

## 유나 지식 베이스 (`docs/yuna_knowledge.md`)

유나(mgr) 가 "씬이 뭐야?" / "도전과제 어떻게 달성?" / "너 어디까지 볼 수 있어?" 등 사용자 질문에 답할 수 있게 하는 공개 FAQ. `_build_mgr_prompt` 가 이 파일을 system prompt 에 자동 로드 (mtime 캐시).

**갱신 원칙:**
- 씬·도전과제 추가/변경 시 **반드시 갱신**
- 새 내부 기술 도입 시 "금지" 섹션에 추가
- 유나 도구 변경 시 "내 권한" 업데이트
- 소스코드 직접 참조 금지 — 추상화 유지
