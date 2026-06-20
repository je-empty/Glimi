# 프롬프트 개발 규칙

Claude Code (이 AI) 가 이 프로젝트에서 프롬프트를 수정·추가할 때 반드시 따라야 할 규칙. CLAUDE.md 에서 참조되는 상세본.

---

## 1. 배치 원칙 — 어느 파일에 쓸지

```
community/core/prompts/        # cross-scene universal (어느 scene 에서든 쓰는 범용)
├── __init__.py          # build_system_prompt dispatch (lang fallback)
├── helpers.py           # DB/context 헬퍼 (format_speech, pet_name_section 등)
├── locale.py            # 언어 특화 snippet (ko 토큰·스타일)
├── model.py             # 모델 dialect (provider 기반 tool syntax)
├── en/                  # 정본 (순수 영어)
│   ├── common.py        # 모든 에이전트 공통
│   ├── persona.py / mgr.py / creator.py  # agent_type 별
│   ├── mgr_notifications.py              # mgr 에게 주입되는 이벤트 알림 5종
│   ├── persona_events.py                 # persona 에 주입되는 이벤트 (첫 인사)
│   ├── commands/        # 수동 !명령 (i18n 필요)
│   │   ├── create_agent.py
│   │   └── analyze_logs.py
│   ├── external/        # 외부 모델 대상 (영어 불변 — 절대 i18n X)
│   │   └── image_gen.py                  # DALL-E/Gemini 용
│   └── supervisor_judge.py               # cross-scene Haiku judge (stuck 등)
└── ko/                  # 한국 특화 override (있으면 우선, 없으면 en fallback)

community/scenes/{scene}/      # scene-scoped (해당 scene 만 의미 있음)
├── prompts.py           # phase별 system prompt fragment (매 턴 주입)
├── greeting.py          # one-shot user prompt (필요 시)
├── judge_prompts.py     # scene 전용 Haiku judge
├── scene.py / supervisor.py / handlers.py
```

### 결정 매트릭스

| 프롬프트 성격 | 위치 |
|---|---|
| agent_type 별 정적 system prompt | `community/core/prompts/en/{persona,mgr,creator}.py` |
| 모든 에이전트 공통 규칙 | `community/core/prompts/en/common.py` |
| 특정 scene 에서만 필요한 fragment | `community/scenes/{scene}/prompts.py` |
| 특정 scene 에서만 필요한 user prompt (1회성) | `community/scenes/{scene}/greeting.py` or `community/scenes/{scene}/events.py` |
| Cross-scene event notification (mgr) | `community/core/prompts/en/mgr_notifications.py` |
| Cross-scene event trigger (persona) | `community/core/prompts/en/persona_events.py` |
| 수동 !명령 | `community/core/prompts/en/commands/{name}.py` |
| 외부 이미지/오디오 모델 | `community/core/prompts/en/external/{name}.py` |
| Supervisor Haiku judge (cross-scene) | `community/core/prompts/en/supervisor_judge.py` |
| Supervisor Haiku judge (scene 전용) | `community/scenes/{scene}/judge_prompts.py` |

---

## 2. 언어 원칙 — 영어 정본 + 한국어 override

- **모든 LLM 지시문은 영어** (프롬프트 엔지니어링 표준). 대부분 LLM 은 영어로 최고 성능.
- **출력 언어는 `[LANGUAGE: X]` 블록**이 강제 (`community/core/prompts/en/common.py` 가 `community.get_language()` 기반 주입). 영어 프롬프트 + `[LANGUAGE: Korean]` → 한국어 응답 정상.
- **한국어 특화 토큰** (ㅇㅇ / ㅋㅋ / 카톡 / 톡방 / 호칭) 은 `community/core/prompts/locale.py` helper 로 주입. 영어 프롬프트가 `simple_ack_examples()` 같은 함수를 호출.
- **구조적으로 다른 문화 block** (예: 한국 존댓말·호칭 progression) 은 locale helper 로 전체 block 반환 (`korean_onboarding_hints()`) 또는 `community/core/prompts/ko/{module}.py` 전체 override.

### 판단 기준

| 상황 | 해결 |
|---|---|
| 단어 1~2개만 언어별 다름 (`"카톡"` vs `"Discord"`) | `locale.py` helper |
| 문장 1~2개 언어별 다름 | locale helper (긴 문자열 return) |
| block 5+ 줄 언어별 다름 | locale helper 가 block 전체 return (`korean_onboarding_hints()` 예시) |
| 프롬프트 **구조·순서** 자체가 다름 | `community/core/prompts/ko/{module}.py` 전체 override |

---

## 3. 모델 dialect — LLM 백엔드 호환성

- `community/core/prompts/model.py` 가 provider 기반 snippet 분기 (`claude` / `ollama` / `vllm` / `llamacpp` / `openai`).
- 새 프롬프트에 `<tools>` / `<call>` 같은 **모델-specific syntax 를 하드코딩하지 말 것**. `tool_call_syntax_hint()` / `tool_results_format_hint()` helper 호출.
- `runtime.activate_agent` 가 agent 의 resolved model 을 `ContextVar` 로 주입 → system prompt 빌드 시 해당 provider 에 맞는 dialect 자동 주입.

### 하드코딩 금지 예시
```python
# ❌ 금지 — 모델 바뀌면 invalid
"Tool calls go in `<tools>` block with `<call name=...>`"

# ✅ 권장
from community.core.prompts.model import tool_call_syntax_hint
f"{tool_call_syntax_hint()}"
```

---

## 4. Decoupling 원칙

### community/core/* 에서 `import discord` 금지
platform adapter decoupling 원칙. core 는 Discord / Telegram / Web 중립. `community/bot/*` 만 Discord 의존 OK.

### community/core/prompts/ 는 community/bot/ 를 import 하면 안 됨
- 이전에 `community/core/prompts/helpers.formatting_guide()` 가 `community.bot.formatting` 을 lazy import 하던 누수 있었음 (Phase 2-C 에서 `community.core.formatting` 으로 이동 완료).

### scene-local 자료는 scene 폴더에
- `community/scenes/{scene}/` 에 prompts / greeting / judge_prompts / handlers / supervisor / scene 배치
- `community/core/prompts/` 는 **cross-scene universal** 만

---

## 5. CMD/ACTION/QUERY 레거시 금지

- 과거 `[CMD:...]`, `[ACTION:...]`, `[QUERY:...]` 태그 시스템은 **전부 제거됨** (커밋 `756f3b6`).
- 모든 도구 호출은 XML Tool Protocol (`<tools>` / `<call>`) 로 통일.
- 새 프롬프트에 `[CMD:...]` 식 언급 절대 금지. Tool 이름 직접 언급 (e.g. "call `update_profile` tool").

---

## 6. Profile 변경 시 에이전트 prompt 갱신

- `update_profile` 이나 `profile_autoextract` 로 **user/agent 프로필** 바뀔 때 반드시:
  1. `invalidate_cache()` 호출 — profile cache
  2. `runtime.refresh_agent(all_active_ids)` — system prompt 재빌드
- 안 하면 이전 system prompt 박힌 상태로 다음 응답 → 재질문 회귀 (커밋 `0d75538` 참조).

---

## 7. Memory extraction — fact 저장 규칙

- `community/core/memory.py` 의 `_validate_fact` 가 저장 전 방어:
  - **subject 는 실체 있는 사람만** (agents/users 테이블) — "새 멤버", "이 커뮤니티", "멤버들" 같은 추상 명사 drop
  - **predicate 정규화** — `PREDICATE_ALIASES` 에 동의어 매핑 (8가지 "원하는친구특성/타입/..." → `preferred_friend_type`)
  - **일시 상태 drop** — object 가 "오늘/지금/방금/오랜만/잠깐" 만 있으면
  - **자기 profile 중복 drop** — agent 자신 profile 필드와 같은 내용은 저장 안 함
- 새 extraction 프롬프트 추가 시 위 규칙 지시 포함 권장.

---

## 8. 유나·하나·persona 메타 레벨 비대칭

- **persona**: 자기를 평범한 사람으로 인지. 메타 용어 ("AI", "agent", "prompt") 절대 금지.
- **mgr (유나) / creator (하나)**: 하이브리드 — 인간 자아 + 에이전트 자각 공존. 자진 "나 AI 야" 고백 금지. 유저가 물으면 솔직 OK. Persona 앞에선 메타 용어 금지.
- 프롬프트 `community/core/prompts/en/common.py` 의 `core_identity_rules()` 에 정리되어 있음.

---

## 9. 체크리스트 (프롬프트 추가·수정 시)

- [ ] 위치 맞는 폴더? (universal = core/prompts/en/, scene-scoped = scenes/{scene}/)
- [ ] 영어로 작성? 한국 특화 부분은 locale helper 로 추출?
- [ ] `<tools>` / `<call>` 하드코딩 없음? `tool_call_syntax_hint()` 호출?
- [ ] `[CMD:...]` / `[ACTION:...]` / `[QUERY:...]` 없음?
- [ ] persona 프롬프트면 메타 용어 없음?
- [ ] 프롬프트 build 후 `agent_runtime.refresh_agent` 경로 확인?
- [ ] 신규 모듈이면 `community/core/prompts/__init__.py` 의 `_get_builder` dispatch 에서 lookup 가능?

---

## 10. 참조 커밋 (학습용)

- `cac7dc8` 프롬프트 빌더 `community/core/prompts/en/` 로 분리
- `8c86ff0` `community.bot.formatting` → `community.core.formatting` 이동 (decoupling)
- `756f3b6` CMD/ACTION/QUERY 레거시 전수 제거
- `41e6629` locale.py 신설 (한국어 snippet 중앙화)
- `1583c40` model.py 신설 (provider dialect)
- `ed765c8` tutorial 전용 프롬프트 scene 내부 이동
- `b106f11` mgr_feedback split → persona_events + mgr_notifications
- `4f197c9` commands 분할 + external/ (영어 불변)
