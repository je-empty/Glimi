# Sample Avatars

하나(Creator)가 새 친구 만들 때 먼저 제안할 샘플 프로필 이미지들.

**일관된 아트 스타일 가이드**: [`docs/avatars_format.md`](../../docs/avatars_format.md) —
모든 `gen_prompt` 는 이 문서 기준. 새 샘플 생성 시 참고.

## 구조

`catalog.json` — 각 샘플의 메타데이터 + 생성 프롬프트. 이미지 파일은 이 디렉토리에 같은 이름(`.png`)으로.

항목별 필드:
- `file` — 이미지 파일명 (디렉토리 기준 상대 경로)
- `gender` — `"male"` / `"female"`
- `age`, `age_range` — 숫자 + "20대 초반" 같은 범위 문자열
- `mbti_primary` — 이 이미지가 어울리는 MBTI 2~3개 (e.g. `["ENFP", "ENTP"]`)
- `vibe_tags` — 성격·분위기 태그 (4~5개)
- `appearance_tags` — 외모 특징 태그
- `description` — 한 줄 설명 (하나가 읽음)
- `gen_prompt` — 이 이미지를 **재생성/신규 생성**할 때 쓸 영어 프롬프트 (DALL-E, Midjourney 등)
- `status` — `"ready"` (이미지 파일 있음 — 하나에게 노출) / `"placeholder"` (파일 없음 — 하나에게 숨김)
- `tags` — 레거시 태그 배열 (구버전 호환)

## 새 샘플 추가

1. `catalog.json`에 항목 추가 (`status: "placeholder"`)
2. `gen_prompt`를 ChatGPT/DALL-E 등에 넣어 이미지 생성
3. 결과 PNG를 `file` 이름으로 저장
4. `status`를 `"ready"`로 변경
5. 하나가 다음 세션부터 이 샘플 추천 가능

## 현재 placeholder 목록 (이미지 필요)

`catalog.json`에서 `status == "placeholder"` 인 항목들. 남성 8개 + 여성 4개 추가됨.
각 항목의 `gen_prompt`를 사용해서 생성.

## 이미지 스펙

- 해상도: 512x512 이상 (Discord webhook avatar 권장)
- 포맷: PNG (투명 배경 아님, 배경 있어도 됨)
- 스타일: 일관성 위해 `Anime-style profile illustration ... bust-up shot` 유지
