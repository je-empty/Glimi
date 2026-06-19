# Contributing to Glimi

처음이라면 **`START_HERE.html`** (프로젝트 정체·셋업·첫 task) → **`COLLAB_GUIDE.html`** (협업 규약 전체) 순서로.

## 핵심 규칙 5줄

1. **브랜치**: `develop` 에서 `feat/*`·`fix/*` 분기 → PR base = `develop`. `main`/`develop` 직접 push 금지.
2. **GitHub 웹 "Upload files" 금지** — 반드시 로컬 클론 → 브랜치 → push → PR. (git 이 어려우면 Claude Code 에게 "브랜치 만들어서 커밋하고 PR 올려줘" 라고 하면 됨)
3. **커밋**: `타입: 요약` 1줄 (`feat:`/`fix:`/`docs:`/`style:`/`refactor:`). AI co-author trailer 금지.
4. **구역**: 콘텐츠 (catalog·씬) 는 자유, 코어 포함 나머지는 리뷰 필수, 인프라·시크릿은 메인테이너 전용 — 상세는 `COLLAB_GUIDE.html` §1.
5. **코어 중립**: `src/core/`·`src/llm/` 에 특정 커뮤니티 콘텐츠 (캐릭터명·실존 IP·특정 언어 문구) 하드코딩 금지 — 커뮤니티 데이터는 데이터 레이어로.

## 테스트

PR 전 절차는 `docs/testing.md` — E2E QA 는 최초 1회 `cp tests/e2e/qa.env.example communities/qa/.env` 후 **QA 페르소나에 자기 자신**을 넣는다 (gitignore 라 커밋 안 됨). CI 는 PR 에서 자동 실행.

## 할 일 (Todo)

전역 백로그 = [GitHub Issues](../../issues) — `part:core` / `part:community` / `part:platform` / `part:adapter` / `part:infra` 라벨로 파트 구분. 작업 시작 전 이슈를 집고, PR 본문에 `closes #N`.

## 라이선스 / 기여 권리

기여는 **누구나 환영** — Glimi 는 **AGPL-3.0-or-later** (강한 카피레프트). PR 을 보내면
그 기여는 같은 AGPL 로 들어간다. 이건 프로젝트가 **열린 채로** 발전하면서도, 누군가
**닫아서 독점/상업 제품으로 가져가는 것(free-riding)** 을 막아준다 — 가져다 쓰려면
반드시 소스 공개 + 저작자 표기 유지.

저작권은 원작자 (project owner) 가 보유한다. 향후 **듀얼 라이선스** (AGPL 공개 + 별도
상업 라이선스) 가능성을 위해, 외부 기여가 늘면 가벼운 **DCO(sign-off)** 또는 **CLA** 를
도입할 수 있다 (현재는 미적용 — 기여 장벽 최소화). 자세한 권리/상표는 루트 `NOTICE` 참고.

## 바이브코딩 (Claude Code)

이 repo 는 Claude Code 친화적 — 로컬 클론에서 열면 `CLAUDE.md` 가 자동 로드되어 위 규칙을 Claude 가 알고 시작한다. 개발 판단 기준 (타깃·설계 락인) 은 `docs/dev_guide.md`.
