# Contributing to Glimi

처음이라면 **`START_HERE.html`** (프로젝트 정체·셋업·첫 task) → **`COLLAB_GUIDE.html`** (협업 규약 전체) 순서로.

## 핵심 규칙 5줄

1. **브랜치**: `develop` 에서 `feat/*`·`fix/*` 분기 → PR base = `develop`. `main`/`develop` 직접 push 금지.
2. **GitHub 웹 "Upload files" 금지** — 반드시 로컬 클론 → 브랜치 → push → PR. (git 이 어려우면 Claude Code 에게 "브랜치 만들어서 커밋하고 PR 올려줘" 라고 하면 됨)
3. **커밋**: `타입: 요약` 1줄 (`feat:`/`fix:`/`docs:`/`style:`/`refactor:`). AI co-author trailer 금지.
4. **구역**: 콘텐츠 (catalog·씬) 는 자유, 코어 포함 나머지는 리뷰 필수, 인프라·시크릿은 메인테이너 전용 — 상세는 `COLLAB_GUIDE.html` §1.
5. **코어 중립**: `src/core/`·`src/llm/` 에 특정 커뮤니티 콘텐츠 (캐릭터명·실존 IP·특정 언어 문구) 하드코딩 금지 — 커뮤니티 데이터는 데이터 레이어로.

## 바이브코딩 (Claude Code)

이 repo 는 Claude Code 친화적 — 로컬 클론에서 열면 `CLAUDE.md` 가 자동 로드되어 위 규칙을 Claude 가 알고 시작한다. 개발 판단 기준 (타깃·설계 락인) 은 `docs/dev_guide.md`.
