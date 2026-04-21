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
- `docs/memory_system.md` — 5 레이어 기억 (L0 raw → L3 facts + pinned + relationship)
- `docs/scenes_and_supervisors.md` — Scene / Achievement / Supervisor 시스템
- `docs/formatting.md` — `#channel` → `<#id>` 치환 규칙
- `docs/community_isolation.md` — 멀티 커뮤니티 격리 + demo 쇼케이스
- `docs/execution.md` — 실행 명령 + 플랫폼 CLI + QA 자동화
- `docs/yuna_knowledge.md` — 유나(mgr) 공개 FAQ (씬/도전과제 추가 시 반드시 갱신)
- `analysis/` (.gitignore) — 전략 로드맵 / 경쟁분석 / 사업전략 / 결정 대기 목록

## 작업 규칙
- 커밋 메시지 짧게 — 1줄 제목, 필요 시 핵심 1-2줄. 장황한 본문 금지
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
