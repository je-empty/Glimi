# 메시지 포맷팅 (`community/bot/formatting.py`)

에이전트 응답의 평문 토큰을 디스코드 네이티브 렌더링으로 변환.

**저장/로그/DB 는 원문 유지**, 디스코드 전송 직전 (`_raw_send_as_agent`) 에만 변환.

## 현재 규칙
- `#channel-name` → `<#channel_id>` (클릭 가능 mention). 못 찾으면 `**#name**` 볼드 폴백
- `@owner-name` → `<@owner_id>` (오너만. 에이전트는 웹훅이라 mention 불가)

## 규칙 확장
`_RULES` 테이블에 `(pattern, resolver)` 추가. resolver = match + ctx dict → 치환 문자열 (또는 None = 변환 안 함).

## 한글 지원
regex 는 Python 3 기본 유니코드 `\w` 사용 — `#dm-서유나`, `#internal-dm-서유나-한유진` 전부 매칭.

## 에이전트 가이드
`profile.py._build_common_prompt` 에 "Style Guide — 대화 전반" 섹션으로 주입. 에이전트는 `#channel` 그대로 쓰도록 학습 (백틱/괄호/볼드 감싸지 말라고 명시).

## 테스트
`python -m tests.unit.test_formatting` (11 케이스)
