# runtime.py 대화 엔진 → Ollama 연결 계획

> **상태**: ✅ 구현 완료 (B안 provider 분기). 작성·구현 2026-05-30.
> **목적**: AI 친구들의 실제 디스코드 대화를 로컬 Ollama 모델로 돌리기.
>
> **구현 요약**:
> - `runtime.py`: `_provider_for()`/`_ollama_model_arg()`/`_backend_available()` 헬퍼 추가,
>   가용성 게이트 3곳 일반화, 스트리밍 라인 처리를 `_consume_response_stream()` 공유 헬퍼로 추출,
>   blocking용 `_ollama_blocking()` 추가, 5개 호출 지점(handoff·force·_call_claude_code·streaming·a2a)에 ollama 분기.
> - `ollama.py`: `_think_setting()` — 기본 `think=false` (추론이 num_predict 예산을 다 먹어 답이 빈 채 잘리는 문제 fix). `GLIMI_OLLAMA_THINK=auto/true` 로 제어.
> - **검증**: provider 라우팅·헬퍼·stream_lines·think:false 단위 통과 + 실제 persona(강서율) 스트리밍 end-to-end 통과 (로컬 Gemma, 캐릭터 유지, 누출 없음).
> - **재시작**: `community/core/runtime.py`(봇) + `community/llm/ollama.py`(봇+플랫폼 양쪽 import) 수정 → `run.bat` 으로 봇+플랫폼 재시작.
> - **남은 것**: 라이브 디스코드 턴 (오너 직접 대화) 최종 수용 테스트 — 일반대화/a2a/유나 `<tools>` 정확도 확인.
> - **롤백**: `.env` 에서 `GLIMI_LLM_BACKEND` 제거 → 즉시 Claude 복귀.
>
> **후속 (2026-05-30 추가)**:
> - `achievements/judge.py`: 도전과제 판정도 `community.llm` 경유로 이전 → ollama 라우팅. (검증: gemma 판정 정확)
> - `core/dev_dispatch.py`: 자동 dev 코드 수정(Opus claude) **비활성화** — claude subprocess 주석 처리(삭제 X) + 가드로 안전 차단. `GLIMI_DEV_DISPATCH=1` + 주석 해제로 재활성화.
> - 남은 직접 claude 호출: **없음** (dev_dispatch 는 의도적 비활성, runtime 의 claude 경로는 provider 분기라 ollama 모드선 미사용).

## 배경 — 왜 필요한가

`.env`에 `GLIMI_LLM_BACKEND=ollama`를 넣어도 **실제 페르소나 대화는 여전히 `claude` CLI를 탄다.**

- `community/llm/` = 나중에 만든 백엔드 추상화 (claude_cli / anthropic_sdk / ollama). `_select_backend`가 env 기반으로 백엔드 고름.
- 하지만 핵심 대화 엔진 `community/core/runtime.py`는 이 추상화를 **안 거치고** `claude` CLI를 직접 subprocess로 호출. 모델 레지스트리의 ollama 항목도 주석 처리("Phase 2").
- 현재 `GLIMI_LLM_BACKEND=ollama`로 실제 바뀐 건 **메모리 추출(`community/core/memory.py`)뿐.** (memory.py는 `from community.llm import generate` 사용.)

### 참고: LLM/CLI 미사용 경로 (혼동 방지)
- **페이지 실행** (`run.bat` → FastAPI/uvicorn): 순수 파이썬, CLI 불필요.
- **디스코드 연결/동기화**: 디스코드 토큰만 필요, CLI 불필요.
- 오직 "친구들이 발화를 생성하는 순간"만 LLM 필요 → 그게 runtime.py에서 Claude에 묶여 있음.

## 현재 구조 (조사 결과)

`runtime.py`에 `claude` CLI 직접 호출 **5곳**, 전부 `CLAUDE_AVAILABLE` 게이트 뒤:

| # | 라인 | 메서드 | 방식 | 특징 |
|---|------|--------|------|------|
| 1 | 502 | `_build_handoff_summary` | 블로킹 | 모델 전환 시 요약, `claude-haiku-4-5` 하드코딩 |
| 2 | 809 | `generate_response_force` | 블로킹 | 강제 지시, `<tools>` 파싱 |
| 3 | 962 | `_call_claude_code` | 블로킹 | 일반 응답(배치), 2회 재시도 |
| 4 | 1100 | `generate_response_streaming` | **스트리밍** | **메인 경로**, watchdog kill, 타입별 타임아웃, tool 버퍼 |
| 5 | 1444 | agent-to-agent | 블로킹 | 친구끼리 대화, 2회 재시도 |

- `_build_prompt()` → `(full_prompt, system_prompt, model)` 반환.
- 후처리(`parse_tools_in_output`, `_parse_response`, reasoning leak 필터, 이름 prefix 제거, dedup, `max_messages`)는 **백엔드 무관하게 공유**돼야 함.
- 가용성 게이트: `CLAUDE_AVAILABLE = shutil.which("claude")` — line 899·1054·1433에서 체크, 실패 시 placeholder.

## 설계 선택

### A. 전면 추상화
5곳 전부 `community.llm.generate/stream_lines`로 교체, 직접 subprocess 제거.
- 장점: 아키텍처 원칙(코어 플랫폼 중립)에 부합, 깔끔.
- 단점: runtime의 검증된 로직(2회 재시도·watchdog kill·`_looks_like_claude_error`·타입별 타임아웃)이 백엔드 레이어에 아직 없음 → **Claude 경로 회귀 위험.**

### B. provider 분기 (점진적) ← 추천
Claude 경로는 그대로 두고, `provider == ollama`일 때만 `community.llm` 호출하는 분기 추가. 후처리는 공유 헬퍼로 추출.
- 장점: Claude 경로 무손상, 낮은 위험, 즉시 사용 가능.
- 단점: 분기 공존 (나중에 A로 수렴).

→ **1차 B, ollama 검증 후 A로 통합.**

## 작업 단계 (B 기준)

### 1. 모델 레지스트리 + provider 헬퍼 (`runtime.py:38-78`)
- `AVAILABLE_MODELS`에 ollama 항목 활성화 (주석 해제):
  `{"id": "ollama:gemma4-26b-ablit", "label": "Gemma4 26B (local)", "kind": "local", "provider": "ollama", ...}`
- `_provider_for_model(model) -> "claude" | "ollama"` 헬퍼 추가 (model id prefix 또는 `GLIMI_LLM_BACKEND` 기준).

### 2. 가용성 게이트 일반화 ⚠️ 가장 중요
- 현재 Claude CLI 없으면 ollama 설정해도 **placeholder로 떨어짐** (line 899·1054·1433).
- → `_backend_available(provider)`로 교체. ollama면 `OllamaBackend().available()` 체크.

### 3. 공유 라인 처리 헬퍼 추출 (스트리밍 핵심)
- `generate_response_streaming`의 라인 루프(1144-1221: tool 버퍼링, leak 필터, dedup, name-strip, `max_messages`)를 **라인 이터레이터를 받는 헬퍼**로 분리.
- Claude면 `process.stdout`, ollama면 `community.llm.stream_lines(...)`를 먹임 — 둘 다 라인 단위라 인터페이스 동일.

### 4. 각 호출 지점에 ollama 분기 (5곳)
- 블로킹(1·2·3·5): `provider == ollama` → `community.llm.generate(system, user, model, agent_type, timeout)` 후 기존 `parse_tools_in_output`/`_parse_response`로 흘림.
- 스트리밍(4): `community.llm.stream_lines(...)` → 3번 헬퍼로 처리. **watchdog kill은 프로세스가 없으니** 타입별 타임아웃을 `stream_lines(timeout=...)`로 전달하는 방식으로 대체.

### 5. (선택) 보조 경로
- `judge.py`(도전과제 판정), `_build_handoff_summary`도 같은 패턴으로 전환하면 완전 로컬.

## 구현 시 함정

1. **placeholder 회귀** — 2번 안 하면 Claude CLI 미설치 환경에서 ollama 무시 + placeholder 노출. 반드시 처리.
2. **watchdog 부재** — ollama 스트림은 urllib 제너레이터라 `process.kill()` 불가. 타임아웃 기반 종료로 재설계.
3. **에러 감지 차이** — `_looks_like_claude_error`는 Claude 전용. ollama 에러는 `LLMResponse.error` / 스트림 조기 종료로 옴 → ollama용 분기 필요.
4. **`num_predict`** — `community.llm` 호출 시 `max_tokens` 적절히 (persona 짧게, creator 넉넉히). CLI엔 없던 개념.
5. **thinking 절약** — content는 이미 깨끗(검증됨)하지만, `ollama.py` payload에 `"think": false` 추가하면 추론 토큰 낭비/지연 제거 (작은 개선, 권장).
6. **`<tools>` 정확도** — Gemma가 `<tools>`/`<call>` 문법을 정확히 따를지 미검증. mgr/creator가 헷갈리면 `GLIMI_LLM_AGENT_MAP`으로 그 둘만 Claude 유지하는 탈출구 유지.

## 검증 계획
- **단위**: persona/mgr 각각 ollama 분기로 `generate` 호출 → 응답·tool 파싱 확인.
- **통합**: `run.bat` 재시작 후 디스코드에서 (a) 일반 대화 (b) agent-to-agent (c) 유나 `<tools>` 호출 로그 확인.
- **롤백**: `.env`에서 `GLIMI_LLM_BACKEND` 제거 → 즉시 Claude 복귀 (분기 추가라 안전).

## 영향 범위 / 재시작
- 수정 파일: `community/core/runtime.py` (주), `community/llm/ollama.py` (think 옵션), 선택적 `community/achievements/judge.py`.
- `community/core/*` 수정 → **봇만 재시작** 충분. judge.py 포함 시 봇+플랫폼 둘 다.

## 현재 .env 설정 (이미 적용됨)
`communities/myserver-new1/.env`:
```
GLIMI_LLM_BACKEND=ollama
GLIMI_OLLAMA_MODEL=gemma4-26b-ablit
```
→ 이 계획 완료 전까지는 memory.py만 ollama, 대화는 Claude.

## 관련 파일
- `community/core/runtime.py` — 대화 엔진 (이 계획의 주 대상)
- `community/llm/__init__.py` — `_select_backend` 백엔드 선택
- `community/llm/ollama.py` — Ollama 백엔드 (urllib, stdlib only)
- `community/llm/claude_cli.py` — Claude CLI 백엔드 (참고: runtime의 재시도/watchdog는 미포함)
- `docs/ollama_setup.md` — Ollama 설치 + GGUF 임포트 + .env 연결 절차
