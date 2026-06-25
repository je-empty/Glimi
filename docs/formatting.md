# 메시지 포맷팅

에이전트 응답의 평문 토큰을 채널 mention 으로 렌더링.

**저장/로그/DB 는 원문 유지** — 에이전트는 `#channel-name` 평문을 그대로 쓰고, 클라이언트 렌더링 시점에만 변환한다.

## 현재 규칙 (웹)
웹 클라이언트가 `#channel` / `#mention` 스타일을 네이티브로 렌더링한다.
- `#channel-name` → 클릭 가능한 채널 링크. 못 찾으면 `**#name**` 볼드 폴백
- `@owner-name` → 오너 mention 강조

> 레거시 메모: `<#channel_id>` / `<@owner_id>` 형태는 과거 부트스트랩 어댑터(은퇴)에서 쓰던 syntax 였다. 웹은 위 평문 토큰을 직접 렌더링하므로 더 이상 ID 치환이 필요 없다.

## 규칙 확장
`_RULES` 테이블에 `(pattern, resolver)` 추가. resolver = match + ctx dict → 치환 문자열 (또는 None = 변환 안 함).

## 한글 지원
regex 는 Python 3 기본 유니코드 `\w` 사용 — `#dm-서유나`, `#internal-dm-서유나-한유진` 전부 매칭.

## 에이전트 가이드
`profile.py._build_common_prompt` 에 "Style Guide — 대화 전반" 섹션으로 주입. 에이전트는 `#channel` 그대로 쓰도록 학습 (백틱/괄호/볼드 감싸지 말라고 명시).

## 테스트
`python -m tests.unit.test_formatting` (11 케이스)
