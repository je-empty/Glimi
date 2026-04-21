# 커뮤니티 격리 (Multi-community Isolation)

**원칙:** `communities/{id}/` 는 완전 독립. 한 community 의 agent/profile_image/memory/channel 이 다른 community 요청에서 **절대** 노출되면 안 됨.

## 전역 state 위험 지점
- `src.community._current_id` (env `GLIMI_COMMUNITY`)
- `src.db.DB_PATH` cached
- `src.core.profile._profile_cache` / `_user_profile_cache` / `_user_summary_cache`
- `src.bot._webhook_cache`
- `src.core.memory._extract_queue` (background worker)
- `src.core.runtime.AgentRuntime._active_agents` / `_pending_tool_results`

## 웹 대시보드 방어
- `_COMMUNITY_LOCK` 로 community 전환 + API 호출 직렬화
- `_with_community(path, fn)` — `?community=` 명시 시 전환, 없으면 `_STARTUP_COMMUNITY` 로 reset
- `_set_active_community(cid)` — env 설정 + `set_community()` + `DB_PATH=None` + `profile.invalidate_cache()` + `webhook_cache.clear()`
- `_serve_avatar` 는 현재 community 디렉터리에서만 이미지 찾음

## 봇 프로세스 한정
`run.sh` 는 1 community/process. AgentRuntime / memory worker 등의 global state 는 프로세스 수명 동안 community 고정이라 leak 없음. 장기적으로 community_id 를 명시적 context 로 전파하는 게 더 안전 (향후 과제).

## 검증 테스트
`python -m tests.unit.test_community_isolation` — 4 case (snapshot/agent/avatar/profile 캐시 invalidation)

## demo 커뮤니티 쇼케이스 (`scripts/seed_demo_mockup.py`)

`http://localhost:8765/?community=demo` — 디스코드 없이 **DB 만** 구성 (봇 불필요).

**구성:**
- 오너 "빈이" + 에이전트 9명 (유나 mgr, 하나 creator, 페르소나 7 — 전원 여자)
- 친구/동료/파트너 (가족 없음)
- 5 레이어 메모리 전부 활용
- 채널 16개, 대화 141건, 라이브 채널 3개

**재실행:** DB + `-shm`/`-wal` 삭제 → `init_db()` → 시딩.
