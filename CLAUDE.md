# Project Glimi — CLAUDE.md

## 한 줄 피칭
AI 친구들이 오너 없이도 자기들끼리 살아가는 커뮤니티. 오너가 돌아오면 그사이 무슨 일이 있었는지 알려준다.

## 🚨 세션 시작 시 필독
**`docs/dev_guide.md` 먼저 읽어.** 타깃·설계 락인·현재 스프린트·금지 사항.

## 🔌 아키텍처 원칙 — Discord = 어댑터
**최종 목표는 웹 자체 채팅 + 앱. 디스코드는 현재 채팅 UI 직접 구현 공수 때문에 쓰는 임시 출구.**

- **코어 로직** (에이전트 두뇌·메모리·감정·씬·도구 실행) 은 Discord 를 몰라야 함. 플랫폼 중립 타입만 사용
- **Discord 는 "출구" 레이어** — `src/bot/` = Discord 어댑터. 나중에 `src/adapters/telegram/`, `src/adapters/web_chat/` 이 붙을 자리
- **새 기능 설계 질문**: "이 로직을 Telegram·웹채팅에서 재사용 가능한가?" NO 면 잘못된 레이어
- **금지**: `src/core/*` 에서 `import discord` / `Webhook`·`TextChannel`·`guild` 같은 Discord 타입이 코어 시그니처에 새는 것
- **허용 (과도기)**: `src/core/sync.py` 같은 "Discord↔DB 동기화" 는 discord import OK — 어댑터 책임. 추후 `src/adapters/discord/sync.py` 로 이동
- **추상화 타깃**: `outbox.send(channel_id, speaker, text, ...)` 추상 인터페이스. 디스코드 webhook / 텔레그램 API / 웹 WebSocket 이 각자 구현

현황 + 분리 공수는 **`analysis/platform_decoupling_review.md`** 참조.

## 📑 문서 참조 맵
- `docs/architecture.md` — 디렉토리 구조, 핵심 모듈, DB 스키마, `<tools>` 프로토콜, 채널 구조, ID 체계
- `docs/prompt_development.md` — **프롬프트 작성 규칙** (파일 배치 / i18n / 모델 dialect / decoupling / 메타 비대칭 / 체크리스트)
- `docs/memory_system.md` — 5 레이어 기억 (L0 raw → L3 facts + pinned + relationship)
- `docs/scenes_and_supervisors.md` — Scene / Achievement / Supervisor 시스템
- `docs/formatting.md` — `#channel` → `<#id>` 치환 규칙
- `docs/community_isolation.md` — 멀티 커뮤니티 격리 + demo 쇼케이스
- `docs/execution.md` — 실행 명령 + 플랫폼 CLI + QA 자동화
- `docs/yuna_knowledge.md` — 유나(mgr) 공개 FAQ (씬/도전과제 추가 시 반드시 갱신)
- `docs/edge_cases.md` — **특이 케이스 이력** (LLM placebo drift 등 재현 가능한 anomaly 분류 + fix 기록)
- `src/glimi_imagegen/README.md` + `SKILL_prompts.md` — 로컬 LoRA 프로필 이미지 생성 (Animagine XL 4.0). creator 도구 = `generate_profile_image` (~6분). 브릿지 = `src/core/profile_image.py`
- `analysis/` (.gitignore) — 전략 로드맵 / 경쟁분석 / 사업전략 / 결정 대기 목록

## ✍️ 프롬프트 작성 — 핵심만 (상세 `docs/prompt_development.md`)
- **위치 원칙**: 범용 = `src/core/prompts/en/` · scene 전용 = `src/scenes/{scene}/`
- **언어**: 영어 정본. 한국 특화 (ㅇㅇ/ㅋㅋ/카톡/호칭) = `src/core/prompts/locale.py` helper 로 주입. 구조적으로 다르면 `ko/{module}.py` override
- **모델 dialect**: `<tools>` / `<call>` 같은 syntax 하드코딩 금지. `src.core.prompts.model.tool_call_syntax_hint()` helper 호출
- **레거시 금지**: `[CMD:...]` / `[ACTION:...]` / `[QUERY:...]` 절대 쓰지 말 것 (전수 제거됨, 커밋 756f3b6)
- **decoupling**: `src/core/*` 에서 `import discord` 금지. `src/core/prompts/` 에서 `src/bot/` import 금지
- 상세 + 체크리스트는 `docs/prompt_development.md` 참조

## 🪶 문서화 원칙 (CLAUDE.md 용량 관리)
- **CLAUDE.md 에 상세 담지 말 것**. 세부 규칙은 별도 `docs/*.md` 에 두고 CLAUDE.md 는 **참조 링크 + 핵심 한 줄 요약**만.
- 매 세션 CLAUDE.md 가 context 에 자동 주입됨 → 길수록 토큰 낭비.
- 새 규칙 추가 시: "이거 CLAUDE.md 에 1줄 + docs/X.md 에 상세" 패턴.

## 작업 규칙
- 커밋 메시지 짧게 — 1줄 제목, 필요 시 핵심 1-2줄. 장황한 본문 금지
- **`Co-Authored-By: Claude` 또는 어떤 AI co-author trailer 도 절대 추가 금지** — author 는 프로젝트 git config (jbsim) 그대로
- 커밋 본문에 "Generated with Claude Code", 이모지(🤖) 등 AI 생성 표식 금지
- `--no-verify` / `--no-gpg-sign` 우회 사용 안 함 — pre-commit / signing hook 실패하면 원인 고치기
- main 직접 작업 X — develop 이 working 브랜치, dev_requests 자동 작업은 `dev-requests/run-{ts}` 별도 브랜치 → develop 으로 PR
- Only create commits when user explicitly requests

## 용어 규칙
- 사용자 보이는 텍스트에서 "에이전트", "멤버", "봇", "AI" 등 메타 용어 금지
- 시스템 프롬프트: 다른 사람은 이름/친구들/사람들 등 자연스러운 표현
- `<tools>` 블록은 `mgr-system-log` 에만 노출 (대화 채널에 절대 X)

## 주의사항
- 메모리/감정은 system prompt 에 안 넣음 — `agent_runtime` 이 user prompt 에 채널별 동적 주입
- 그룹채팅: 오너 메시지는 `handle_group` 에서 1회만 로깅 (`generate_response` 에 `log_user_message=False`)
- `conversation_engine` 도 `log_user_message=False` (내부 프롬프트가 오너 ID 로 로깅되는 버그 방지)
- 프로필 수정 시 `invalidate_cache` + `runtime.refresh_agent` 필수
- `dm-`/`mgr-` 채널은 삭제 보호됨
- **타임스탬프는 UTC-aware ISO** (`datetime.now(timezone.utc).isoformat()` 또는 `src.core.timeutil.now_utc_iso()`). SQLite `CURRENT_TIMESTAMP` 는 UTC naive — 둘 다 클라이언트가 로컬 tz 로 렌더
