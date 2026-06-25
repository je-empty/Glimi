# Glimi — CLAUDE.md

> 이 파일은 Claude Code 가 이 repo 에서 자동 로드한다. **외부 기여자 / 다른 사람의 Claude Code 세션도 이 파일을 자동 읽는다** — 즉 여기 적힌 모든 규칙이 모든 contributor 의 작업에 자동 적용됨.

## 한 줄 피칭
Glimi = 살아있는 멀티 에이전트 하네스 (Glimi Core, 라이브러리) + AI 친구 커뮤니티 sim (Glimi Community, flagship 앱). 모노레포.

## 🚨 세션 시작 시 필독
**처음 들어오는 contributor 라면 `docs/START_HERE.html` 먼저 열어봐** — 프로젝트 정체, 셋업, 첫 task, 브랜치 전략, 워크플로우 다 거기 있음.
협업 규약 (영역 오너십·커밋/PR 양식·웹 업로드 금지)은 **`docs/COLLAB_GUIDE.html`**.
유지보수 작업 / 스프린트 컨텍스트는 **`docs/dev_guide.md`** — 타깃, 설계 락인, 금지 사항.

## 🌳 브랜치 전략 — 외부 기여자 포함 모두 적용
- `main` = 안정판. 외부 사용자가 보는 기본 브랜치. **직접 작업 / 직접 push 절대 금지**.
- `develop` = working 브랜치. 모든 일반 작업의 통합 지점. 메인테이너가 안정화 사이클에서 main 으로 fast-forward.
- 새 작업은 **반드시 `develop` 에서 새 브랜치 분기**: `feat/<name>`, `fix/<name>`, `docs/<name>`, `refactor/<name>` 등. PR base = `develop`.
- `dev-requests/run-{ts}` = 자동 dev 시스템 (Sena → Opus) 전용. 사람이 직접 만들지 말 것.
- `claude/*` = 과거 임시 브랜치. 더 이상 사용 안 함 (2026-05-17 정리).

## 🤖 Claude Code 로 작업할 때
- **여러 단계 task → TodoWrite / TaskCreate 사용**. 진행 상황 추적이 사용자에게도 보이고, 컨텍스트 손실 시 복구 쉬움.
- 큰 검색 / 탐색은 Agent (Explore) 로 위임 — 메인 컨텍스트 보호.
- 작업 전 의도 1-2 줄로 공유. 끝낸 후 변경 요지 1-2 줄로 마무리. 그 사이는 침묵 OK.
- 절대 안 함: 묻지 않은 작업 추가, AI co-author trailer, `--no-verify`, main 직접 push.

## 🖥 로컬 실서비스 운영 (개인 환경)
이 repo 가 개인 머신에서 **다른 서비스와 한 호스트를 공유하며 실서비스로 운영**되는 경우(공유 ollama/메모리/제어 레이어),
그 계약·조율 규약은 gitignore 된 **`CLAUDE.local.md`** 에 있다 — 있으면 반드시 따른다 (직접 launchd/포트 만지지 말고 `serverctl` 경유, 공유자원 변경은 조율 로그에 기록). 외부 기여자/CI 와 무관(로컬 전용).

## 🔌 아키텍처 원칙 — transport = 어댑터, 웹이 정본
**웹 채팅이 라이브·정본 transport (`GLIMI_TRANSPORT=web`). 코어는 transport 를 모른다 — 플랫폼 중립 타입만 사용.**

- **코어 로직** (에이전트 두뇌·메모리·감정·씬·도구 실행) 은 어떤 transport 도 몰라야 함. 플랫폼 중립 타입만 사용
- **transport = 어댑터 레이어** — `community/adapters/web/` = 웹 어댑터(라이브). 같은 자리에 `community/adapters/telegram/` 등이 붙는다. 모든 어댑터는 `community/core/channel_adapter.py` 의 `ChannelAdapter` 프로토콜을 구현
- **새 기능 설계 질문**: "이 로직을 다른 transport(텔레그램 등)에서 재사용 가능한가?" NO 면 잘못된 레이어
- **금지**: `community/core/*` 에서 특정 채팅 SDK 타입(`Webhook`·`TextChannel`·`guild` 류) 이 코어 시그니처에 새는 것
- **금지**: 코어 (`community/core/`·`community/llm/`) 에 특정 커뮤니티 콘텐츠 하드코딩 — 캐릭터명·실존 아티스트/IP·특정 언어 문구는 커뮤니티 데이터/설정에서 로드. 코어의 예시 텍스트는 가상·중립으로 ("내 커뮤니티에서 잘 돌게" 하는 수정은 데이터 레이어로)
- **추상화 타깃**: `outbox.send(channel_id, speaker, text, ...)` 추상 인터페이스 (`glimi-core/glimi/transport.py`). 웹 WebSocket / 텔레그램 API 가 각자 구현

**이력**: Discord 가 첫 부트스트랩 어댑터로 이 transport seam 을 검증했고, 웹 패리티 달성 후 제거됨(2026-06-25). 자산은 seam(transport / `ChannelAdapter` / Outbox) 자체 — Discord 는 그 첫 인스턴스였을 뿐. 새 transport 는 같은 seam 에 꽂는다.

## 📑 문서 참조 맵
- `docs/architecture.md` — 디렉토리 구조, 핵심 모듈, DB 스키마, `<tools>` 프로토콜, 채널 구조, ID 체계
- `docs/design_system.md` — **디자인 시스템** (토큰 `static/css/tokens.css` · 색/타이포/컴포넌트 규약 · 안티패턴). 새 사용자 화면은 반드시 준수
- `docs/prompt_development.md` — **프롬프트 작성 규칙** (파일 배치 / i18n / 모델 dialect / decoupling / 메타 비대칭 / 체크리스트)
- `docs/memory_system.md` — 5 레이어 기억 (L0 raw → L3 facts + pinned + relationship)
- `docs/scenes_and_supervisors.md` — Scene / Achievement / Supervisor 시스템
- `docs/formatting.md` — `#channel` → `<#id>` 치환 규칙
- `docs/community_isolation.md` — 멀티 커뮤니티 격리 + demo 쇼케이스
- `docs/execution.md` — 실행 명령 + 플랫폼 CLI + QA 자동화
- `docs/yuna_knowledge.md` — 유나(mgr) 공개 FAQ (씬/도전과제 추가 시 반드시 갱신)
- `docs/edge_cases.md` — **특이 케이스 이력** (LLM placebo drift 등 재현 가능한 anomaly 분류 + fix 기록)
- `community/glimi_imagegen/README.md` + `SKILL_prompts.md` — 로컬 LoRA 프로필 이미지 생성 (Animagine XL 4.0). creator 도구 = `generate_profile_image` (~6분). 브릿지 = `community/core/profile_image.py`. **opt-in**: `./run.sh --imagegen` (= `GLIMI_IMAGEGEN=1`) — 기본 OFF (도구 미노출 + torch 미설치)
- `analysis/` (.gitignore) — 전략 로드맵 / 경쟁분석 / 사업전략 / 결정 대기 목록

## ✍️ 프롬프트 작성 — 핵심만 (상세 `docs/prompt_development.md`)
- **위치 원칙**: 범용 = `community/core/prompts/en/` · scene 전용 = `community/scenes/{scene}/`
- **언어**: 영어 정본. 한국 특화 (ㅇㅇ/ㅋㅋ/카톡/호칭) = `community/core/prompts/locale.py` helper 로 주입. 구조적으로 다르면 `ko/{module}.py` override
- **모델 dialect**: `<tools>` / `<call>` 같은 syntax 하드코딩 금지. `community.core.prompts.model.tool_call_syntax_hint()` helper 호출
- **레거시 금지**: `[CMD:...]` / `[ACTION:...]` / `[QUERY:...]` 절대 쓰지 말 것 (전수 제거됨, 커밋 756f3b6)
- **decoupling**: `community/core/*` 에서 특정 채팅 SDK import 금지(transport 중립). `community/core/prompts/` 에서 `community/adapters/*` import 금지
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
- `<tools>` 블록은 대화 채널에 절대 노출 안 함 — 런타임 툴 로그는 `communities/<id>/logs/system.log` 파일로 (구 `mgr-system-log` 채널은 2026-06-21 웹우선 전환에서 폐지; 모든 채널이 `dm-<이름>`/`group-`/`internal-`. 상세 = 메모리 [[project_channel_model]])

## 주의사항
- 메모리/감정은 system prompt 에 안 넣음 — `agent_runtime` 이 user prompt 에 채널별 동적 주입
- 그룹채팅: 오너 메시지는 `handle_group` 에서 1회만 로깅 (`generate_response` 에 `log_user_message=False`)
- `conversation_engine` 도 `log_user_message=False` (내부 프롬프트가 오너 ID 로 로깅되는 버그 방지)
- 프로필 수정 시 `invalidate_cache` + `runtime.refresh_agent` 필수
- `dm-`/`mgr-` 채널은 삭제 보호됨
- **타임스탬프는 UTC-aware ISO** (`datetime.now(timezone.utc).isoformat()` 또는 `community.core.timeutil.now_utc_iso()`). SQLite `CURRENT_TIMESTAMP` 는 UTC naive — 둘 다 클라이언트가 로컬 tz 로 렌더
