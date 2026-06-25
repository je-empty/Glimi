# Sample Profile Images

하나(Creator)가 새 친구 만들 때 먼저 제안할 샘플 프로필 이미지들.

**일관된 아트 스타일 가이드**: [`docs/profile_image_style.md`](../../docs/profile_image_style.md) —
모든 `gen_prompt` 는 이 문서 기준. 새 샘플 생성 시 참고.

## 파일명 컨벤션

```
agent-persona-{gender}-{age}-{mbti}-{vibe1}-{vibe2}.png
agent-persona-{gender}-{age}-{mbti}-{vibe1}-{vibe2}-full.png
```

- `{gender}` — `f` / `m`
- `{age}` — 숫자. **최소 19세** (성인 기준)
- `{mbti}` — 소문자 4글자 (`infj`, `enfp` 등)
- `{vibe1}` — 에너지/태도 (아래 controlled vocab)
- `{vibe2}` — 성격 톤/분위기 (아래 controlled vocab)
- `-full` 버전 — 상반신까지 세로 이미지 (대시보드 lightbox 용도)

예: `agent-persona-f-21-infj-quiet-gentle.png` + `agent-persona-f-21-infj-quiet-gentle-full.png`

## vibe controlled vocabulary

| 슬롯 | 축 | 어휘 |
|---|---|---|
| `vibe1` (에너지/태도) | 외부에서 본 첫인상 | `quiet`, `calm`, `shy`, `reserved`, `cheerful`, `energetic`, `lively`, `playful`, `intense`, `serious` |
| `vibe2` (성격 톤/분위기) | 내면 색채 | `gentle`, `warm`, `caring`, `mature`, `dreamy`, `bold`, `sharp`, `cool`, `grounded`, `mysterious` |

- 각 슬롯당 정확히 1단어
- vibe1 ≠ vibe2 (중복 금지)
- 새 어휘 추가 시 이 표를 먼저 업데이트

## 구조

`catalog.json` — 각 샘플의 메타데이터 + 생성 프롬프트. 이미지 파일은 이 디렉토리에 같은 이름(`.png`)으로.

항목별 필드:
- `file` — 이미지 파일명 (디렉토리 기준 상대 경로, 1:1 버전)
- `gender` — `"male"` / `"female"`
- `age`, `age_range` — 숫자 + "20대 초반" 같은 범위 문자열 (age ≥ 19)
- `mbti_primary` — 이 이미지가 어울리는 MBTI 2~3개 (e.g. `["ENFP", "ENTP"]`)
- `vibe1`, `vibe2` — controlled vocab (위 참조)
- `vibe_tags` — 성격·분위기 태그 (한국어, 4~5개)
- `appearance_tags` — 외모 특징 태그
- `description` — 한 줄 설명 (하나가 읽음)
- `gen_prompt` — 이 이미지를 **재생성/신규 생성**할 때 쓸 영어 프롬프트 (DALL-E, Midjourney 등)
- `status` — `"ready"` (이미지 파일 있음 — 하나에게 노출) / `"placeholder"` (파일 없음 — 하나에게 숨김)
- `tags` — 레거시 태그 배열 (구버전 호환)

## 새 샘플 추가

1. `catalog.json`에 항목 추가 (`status: "placeholder"`)
2. `gen_prompt`를 ChatGPT/DALL-E 등에 넣어 이미지 생성 (1:1 + 상반신 full 각각)
3. 결과 PNG를 `file` 이름 + `{base}-full.png` 로 저장
4. `status`를 `"ready"`로 변경
5. 하나가 다음 세션부터 이 샘플 추천 가능

## 이미지 스펙

- 해상도: 512x512 이상 (웹 프로필 아바타 권장)
- full 버전: 세로 긴 사이즈 (예: 768x1024), 상반신 포함
- 포맷: PNG (투명 배경 아님, 배경 있어도 됨)
- 스타일: 일관성 위해 `Anime-style profile illustration ... bust-up shot` 유지
