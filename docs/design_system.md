# Glimi Design System

> Glimi 의 모든 사용자 화면(웹 대시보드 · 첫 실행 setup wizard · 웹챗 MVP)이 공유하는 디자인 언어.
> 단일 토큰 소스: [`community/platform/static/css/tokens.css`](../community/platform/static/css/tokens.css).
> 새 화면은 **반드시** 이 문서의 규칙 + 토큰을 따른다. 임의 색/그림자/폰트 하드코딩 금지.

## 1. 철학 (tone)

**ink-forward 미니멀** 계열. 핵심 정서:

- **종이 같은 차분함** — 흰/회 paper 레이어 위에 잉크 텍스트. 형광색·그라데이션 배경·네온 금지.
- **네이비 accent 하나** — 강조는 navy(`--accent`) 한 색으로 절제. 무지개 팔레트 X.
- **콘텐츠가 주인공** — 구분은 보더가 아니라 **면(面)의 단차**로. UI 가 콘텐츠를 누르지 않는다.
- **"AI 가 뽑은 템플릿" 느낌 회피** — 카드 왼쪽 풀하이트 색 바, 과한 글래스모피즘, 보라-청록 그라데이션, 둥둥 뜬 이모지 장식 = 전부 지양. 정보는 **배지/점**으로 절제해 표현.
- **밀도 있는 정보** — 한 화면에 충분한 정보. 폰트는 작고 또렷하게(13–14px 본문), letter-spacing 살짝 음수.

> 한 줄 규칙: *"이거 너무 AI 스럽나?" 싶으면 한 단계 덜어내라.*

### 1.1 금지선 (불변 — 디자인 원칙 §0, 2026-06)

- **그림자 금지가 기본.** 허용은 화이트리스트로만: 모달/플로팅(`--shadow-lg` — 면 단차로 분리 불가한 떠 있는 레이어), 1px 미세 분리(`0 1px 2px` — pill thumb 류). 카드·버튼·헤더에 그림자 추가 금지.
- **hover 에 transform/scale 금지** — 색·배경 단차 변화만. (`translateY(-1px)` 류 들썩임 전부 제거 대상.)
- **serif 도입 금지** — `--font-serif` 토큰 자체를 두지 않는다. 2026 'warm minimalism' 세리프 유행은 AI 산출물 표식이 된 문법이라 의도적 비채택.
- **컴포넌트별 `[data-theme="dark"]` 오버라이드 금지** — 토큰을 쓰면 필요 없다. 예외는 정체성 고정색(모델 family 칩 등 브랜드 시그널)뿐이며 주석으로 사유 명시.
- 스타일은 css 파일에만 — **템플릿 인라인 `<style>` 블록에 컴포넌트 스타일 두지 않는다** (점진 회수 대상).

## 2. 색 토큰

라이트/다크 두 테마. `:root[data-theme="light|dark"]` 로 전환. **항상 의미 토큰을 쓰고 hex 직접 쓰지 않는다.**

### Surfaces (레이어드 paper)
| 토큰 | light | 용도 |
|---|---|---|
| `--bg` | `#fafafa` | 페이지 바탕 |
| `--panel` | `#ffffff` | 카드·패널 기본 (paper) |
| `--panel-2` | `#f6f7f9` | hover · 보조 면 |
| `--panel-3` | `#eceef2` | 깊은 hover · 입력 트랙 |
| `--bg-elev` | `#ffffff` | 떠오른 면(모달 등) |

### Lines
| 토큰 | light | 용도 |
|---|---|---|
| `--border` | `#e5e7eb` | 표준 경계 |
| `--border-soft` | `#eef0f3` | 약한 분할선 |

### Ink (텍스트)
| 토큰 | light | 용도 |
|---|---|---|
| `--text` | `#14161a` | 본문 |
| `--text-dim` | `#4a4e57` | 보조 |
| `--text-faint` | `#8a8e98` | 캡션·placeholder |

### Accent (navy) + Status
| 토큰 | light | 용도 |
|---|---|---|
| `--accent` | `#2a4365` | 강조·링크·primary 버튼 |
| `--accent-2` | `#51678f` | 보조 강조(slate) |
| `--accent-fg` | `#ffffff` | accent 위 텍스트 |
| `--accent-soft` | `#eef2f8` | accent 틴트 면 |
| `--ok` | `#047857` | 성공 |
| `--warn` | `#b45309` | 경고 |
| `--err` | `#b91c1c` | 에러·위험 |

> 다크 테마는 같은 토큰이 밝게 매핑됨(navy → `#9fb8e0`). 새 색이 필요하면 두 테마 모두 정의할 것.

### Glimi 정체성 색 (브랜드 — 보존)
agent 사분면과 대화 상태. **이건 베이스 톤과 별개로 Glimi 고유 식별색이라 유지한다.** 단, 면을 가득 칠하지 말고 배지/링/점에 절제해 쓴다.

| 토큰 | 의미 | light |
|---|---|---|
| `--mgr` | 매니저 | `#dc2626` |
| `--creator` | 크리에이터 | `#ea580c` |
| `--persona` | 페르소나 | `#2563eb` |
| `--dev` | 개발 | `#16a34a` |
| `--user` | 사용자(오너) | `#db2777` |
| `--thinking` | 생각 중 | `#ca8a04` |
| `--speaking` | 말하는 중 | `#0891b2` |

## 3. 타이포그래피

- **본문/UI**: Pretendard Variable (한글 최적). `var(--font-sans)`
- **코드/모델명/수치**: JetBrains Mono. `var(--font-mono)`
- 스케일 토큰: `--fs-xs 11` · `--fs-sm 12.5` · `--fs-base 14` · `--fs-md 15` · `--fs-lg 17` · `--fs-xl 20` · `--fs-2xl 26`
- line-height 본문 1.55. 제목은 letter-spacing `-0.3px` 정도로 약간 조임.
- 무게: 본문 400–500, 제목/강조 600–700. 800 이상 지양.

## 4. 간격 · 반경 · 그림자 · 모션

- **간격**: 4px 베이스. `--sp-1..6` (4·8·12·16·24·32). 카드 내부 패딩 `--sp-3`~`--sp-4`.
- **반경**: `--r-sm 6` (배지·입력) · `--r-md 10` (버튼·작은 카드) · `--r-lg 14` (카드·패널) · `--r-pill` (칩·상태 pill).
- **그림자**: `--shadow`(기본, 거의 안 보이게) · `--shadow-lg`(떠오름/hover). 다크는 shadow 대신 border 로 분리.
- **모션**: `--ease` + `--dur-fast/dur/dur-slow`(0.12/0.2/0.3s). 짧고 차분하게. hover 는 **색·면 전환만**(0.15~0.2s) — transform/scale 금지 (§1.1). 진입 페이드(reveal)·리스트 stagger(40~70ms 케스케이드, 상한 캡)는 허용하되 `prefers-reduced-motion` 분기 필수. 숫자 카운트업은 마케팅 표면 한정 — 운영 수치는 정적이 정직하다.
- **터치 타깃**: 최소 `--tap-min`(40px). 웹챗/모바일 고려.

## 5. 컴포넌트 규약

기존 구현 클래스 기준(`base.css` / `dashboard.css`). 새 화면도 동일 패턴 재사용.

### 5.1 컨트롤 3문법 (헤더·툴바 통일)

화면 상단/툴바의 모든 컨트롤은 아래 셋 중 하나여야 한다. **보더 박스 버튼 금지.**

| 문법 | 모양 | 용도 |
|---|---|---|
| **quiet pill** | `--panel-2` 면 + 무보더 + `--r-pill`(또는 `--r-md`), hover `--panel-3` | 정보+클릭 (커뮤니티 전환, 상태 표시, 보조 액션) |
| **punched 아이콘** | `--panel-2` 원/라운드 + 아이콘 `--text-dim`, hover `--panel-3`+`--text` | 토글·유틸 (테마, 언어, supervisor 등). 활성(is-live) 시 `--accent` 채움+`--accent-fg` |
| **잉크 CTA** | `--accent` 채움 + `--accent-fg` | 화면당 주행동 **1개만** (예: 정지 상태의 "가동") |

상태색(ok/err)은 **면을 채우지 말고 점·텍스트로만** — running 은 초록 dot, 위험 액션(정지)은 quiet pill + `--err` 텍스트.

- **버튼**: 기본 = `--panel-2` 배경 + `--border` 1px + `--r-md`. `button.primary` = `--accent` 채움 + `--accent-fg`. `button.danger` = 투명+`--err` 테두리, hover 시 채움. 높이 ≥ 36px.
- **입력(input/select)**: `--panel-2` 배경, `--border` 1px, `--r-sm`, focus 시 `outline: 2px var(--accent)`.
- **카드**: `--panel` + `--border-soft` 1px + `--r-lg` + `--shadow`. hover 는 `border-color: var(--accent)` + 살짝 들기. **왼쪽 색 바 금지** — 종류 구분은 내부 배지로.
- **배지(type-tag)**: 작은 라운드, `color-mix(타입색 15%, transparent)` 배경 + 타입색 텍스트. 대문자·letter-spacing. agent 종류 표기는 이걸로.
- **칩/pill**: `--r-pill`. 상태(running/stopped)는 pill, 필터/태그는 chip.
- **모달**: `--bg-elev` + `--shadow-lg` 또는 `--shadow-modal`, backdrop 은 약한 dim. 둥근 `--r-lg`.
- **탭**: 하단 밑줄로 active 표시(둥근 focus 박스 X). 라벨 앞 이모지 1개 허용(구분용), `.tab-emoji` 로.

## 5.5 수치·기간 표기 문법

- **raw 단위 노출 금지** — `42545s` 같은 초 단위 그대로 보여주지 않는다. 단일 휴머나이즈 헬퍼를 거친다:
  `<60s → "42s"` · `<1h → "12m"` · `<24h → "11h 49m"` · `그 외 → "2d 3h"`.
- 수치는 `font-variant-numeric: tabular-nums` + 필요 시 `--font-mono`.
- 상대시간("3m ago")과 절대시간(타임스탬프)을 한 표면에 섞지 않는다.

## 6. 아이콘 · 이모지 정책

- **기능 아이콘**: Tabler Icons webfont (`ti ti-*`). 단색 라인, 텍스트색 상속.
- **이모지**: 헤더 탭·섹션 구분처럼 **친근함이 필요한 곳에 1개씩**만. 장식용 남발 금지. 진지한 맥락(에러·결제·삭제)엔 이모지 X.

## 7. 토큰 부채 (정리 대상)

현재 토큰이 두 곳에 중복·발산해 있다. 신규 화면은 `tokens.css` 만 쓰고, 기존 파일은 점진 수렴한다.

| 의미 | `tokens.css`(정본) | `base.css`(레거시) |
|---|---|---|
| paper-2 | `--panel-2` | `--panel2` |
| paper-3 | `--panel-3` | `--panel3` |
| ink-muted | `--text-dim` | `--muted` |
| ink-faint | `--text-faint` | `--faint` |

→ 후속 작업: `base.css` 를 `tokens.css` alias 로 교체하거나 변수명 통일. (별도 task)

## 8. 적용 체크리스트 (새 화면 만들 때)

- [ ] `tokens.css` 를 첫 번째로 link (폰트 @import 가 최상단이어야 함)
- [ ] 색·간격·반경·폰트 전부 토큰 사용 (하드코딩 0)
- [ ] light/다크 둘 다 확인
- [ ] "AI 템플릿" 안티패턴 점검 (왼쪽 색 바·네온 그라데이션·과한 이모지)
- [ ] 모바일 폭(≈380px)에서 터치 타깃·줄바꿈 확인 (웹챗 대비)
