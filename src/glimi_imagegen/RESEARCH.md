# Glimi 이미지 생성 — 연구·시행착오 기록 (2026-04-30 ~ 2026-05-02)

ChatGPT 수동 → 로컬 자동화 파이프라인 구축까지의 의사결정·실패·해결 모음.
타깃: Mac M3 base / 24GB / Python 3.12 / diffusers 0.37 / torch 2.11 (MPS).

## 0. 시작점

- 프로필 이미지를 ChatGPT 로 수동 생성 중 → 자동화 필요
- 톤: anime slice-of-life, soft cel shading, pastel gradient bg, bust-up
- 1차 목표: 80%+ 매치, 즉시 가능 / 2차 목표: 99% 매치

## 1. 모델 후보 평가

| 후보 | 평가 | 결정 |
|------|------|------|
| SDXL base 1.0 | 사실적 톤 강함, anime 약함 | ✗ |
| Anything V5 (SD1.5) | anime OK, 디테일 부족 | ✗ |
| **Animagine XL 4.0** | slice-of-life anime 학습, fp16 ~6.5GB, M3 24GB OK | ✓ |
| Illustrious-XL | 더 webtoon 톤, alternative format 후보 | 보류 |

## 2. 첫 시도 (iter1-2): pure prompt

**문제 1 — NSFW 드리프트.** "korean young woman" 만으로도 cleavage / glamorous / 진한 화장 톤으로 끌림.

**해결**: 강한 negative prompt:
```
cleavage, voluptuous, sexy, mature female, thick lipstick, glossy lips,
heavy makeup, bare shoulders, low cut, deep v-neck, exposed skin
```
→ iter3 부터 거의 사라짐.

**문제 2 — CLIP 77 토큰 truncation.** 자연어 prompt 119+ 토큰 → 뒤쪽 (스타일 앵커) 잘림.

**해결**: 태그 스타일 + 캐릭터 디테일 앞쪽 배치.

## 3. IP-Adapter 시도 (iter3-4)

레퍼런스 이미지로 스타일 강제 → IP-Adapter Plus SDXL ViT-H.

**문제 — 인코더 미스매치.** `pipe.load_ip_adapter(...)` 만으로는 default BigG (1664-dim) 인코더 로드, ViT-H (1280) 모델과 충돌.

**해결**: `CLIPVisionModelWithProjection.from_pretrained(..., subfolder="models/image_encoder")` 명시 로드.

**스케일 조정 결과**:
- scale=0.55: 스타일 강하게 잡지만 캐릭터 머리색/길이도 ref 평균에 끌려감 (gentle 의 검정 긴머리가 갈색 웨이브로 변형)
- scale=0.30: 캐릭터 살리면서 스타일 hint — 균형점
- scale=0.0: pure prompt → NSFW 드리프트 발생

**iter3 결론**: scale=0.30 으로 80-85% 매치. 그러나 새 캐릭터 prompt 받을 때마다 ref 영향이 일관성 깨뜨림 → **production 부적합**.

## 4. Style LoRA 학습 결정

목표: ref 없이 prompt 만으로 일관된 스타일. 학습 1회로 99% 매치.

### 데이터 셋업

- 첫 데이터 (`training/data/`, 10장): 원본 ChatGPT 생성 이미지 + 캡션. 캡션 형식 비통일 (긴 자연어, 짧은 태그 혼재).
- 통일 데이터 (`training/data_v2/`, 10장): **모든 캡션을 동일 wrap 으로 정형화**:
  ```
  glimistyle, korean female with {HAIR}, {OUTFIT}, {EXPRESSION},
  clean delicate thin lineart, soft cel shading, pastel gradient background,
  bust-up portrait, wholesome slice-of-life anime
  ```
- LoRA 가 학습할 패턴이 일관됨 → trigger token `glimistyle` 효과 강화.

### v1 (rank=32, 300 steps, lr=5e-5, original captions)

- **결과**: under-trained. 모든 캐릭터가 "갈색 long wavy hair + 눈 감고 미소" 로 수렴.
- 원인: 캡션 비통일 + step 부족.

### v2 (rank=32, 600 steps, lr=5e-5, unified captions)

- **결과**: 캐릭터 디테일 정확 (mgr 의 줄무늬 빨간 타이, lively 의 half-up bun, gentle 의 lavender bg).
- 학습시간: M3 base ~2.5h.
- ref 재현성 가장 높음. **단점**: 학습 본 캐릭터에 약간 over-fit — 새 prompt (intense+sharp 등) 의 personality cue 가 무뎌짐.

### v3 (rank=16, 800 steps, lr=6e-5, unified captions)

- **목표**: rank 낮춰서 generalization 개선 + step 늘려 톤 lock 보강.
- **결과**:
  - 학습 캐릭터: v2 와 거의 동등 (mgr 의 타이가 약간 partial).
  - **새 prompt: v2 보다 우세** — intense+sharp 가 실제로 smirk 짓고, geek+glasses 가 messy hair + side ponytail 로 personality 살림.
- 학습시간: M3 base ~2:43:49 (avg 12.8s/it).
- ETA 87s/it 우려는 **QA runner 이 GPU 점유 안 하고 I/O wait 일 때** 안 일어남 → 기우.

### 학습 환경 함정

- `--mixed_precision="no"` 필수 (M3 MPS 의 fp16/bf16 unstable).
- `gradient_checkpointing` + `train_batch_size=1` + `gradient_accumulation_steps=2` → 24GB 한계 안 밟음.
- `resolution=512` (1024 학습은 OOM).
- `--report_to="tensorboard"` 는 install 필요한데 없어도 학습은 진행됨 (warning 만).

## 5. 크롭 — 여러 번 갈아엎음

### 시도 1 — heuristic bust-up (위쪽 38% 정사각)

빠른 시작용. 832×1216 의 위쪽 38% (~462px) 정사각 → 1024 resize.
**문제**: 캐릭터마다 face 위치가 달라서 어떤 건 머리 잘리고 어떤 건 어깨 위주.

### 시도 2 — MediaPipe face

`mediapipe.solutions.face_detection` 시도.
**문제**: anime 얼굴은 실사 모델 학습이라 reliably 못 잡음. 신 API 호환성도 이슈.

### 시도 3 — lbpcascade_animeface (haar cascade)

OpenCV 의 anime-face cascade. Robust 하고 빠름.
**문제**: closed-eye smile / 비정형 styling (white aura) 에서 가끔 실패 → reflect-pad heuristic fallback 추가.

### 시도 4 — calibration with reference assets

Glimi 의 기존 9장 (full, crop) 페어로 template-matching → 실제 ref 의 crop 비율 측정:
- `face_to_crop_ratio` = 0.68 (face 가 crop 의 68% 차지)
- `head_room_ratio` = 0.59 (face center 가 crop 위에서 59%)
- `horiz_off` = -0.08 (face 가 crop 가로 중심 8% 왼쪽)

**처음 적용 (0.55 / 0.50)**: 너무 헐렁 — 가슴/어깨까지 보임 → 프로필로 부적합.
**최종 적용 (0.68 / 0.59 / -0.08)**: ref 와 매치. 14/15 face-detection 성공 (1 실패는 v0 의 비정형 baseline 출력).

## 6. 생성 파라미터 (확정)

```
width = 832, height = 1216  (SDXL portrait native bucket — M3 24GB OK)
steps = 30
guidance_scale = 5.0  (5.5 도 OK; 6.0+ 은 burned/saturated)
scheduler = EulerAncestralDiscreteScheduler
fp16 / MPS
seed: int (재현 가능)
```

생성 시간: 832×1216, 30 step, M3 base = **~6분/이미지**.

## 7. 알 수 없었던 발견

### 7-1. trigger token 의 실제 효과

`glimistyle` 가 prompt 어디 있든 LoRA 가 잘 작동하는데, **wrap 의 첫 부분에 두면** 가장 일관된 효과. 끝에 두면 약간 약함 (CLIP attention bias).

### 7-2. NEW prompt 에서 v2 vs v3 차이의 원인

처음엔 "v3 가 그냥 800 step → 더 학습됐으니 좋겠지" 가설. 실제는:
- v3 의 **rank=16 (v2 의 절반)** 이 weight space 를 덜 점유 → base model 의 generalization 보존
- v2 는 rank=32 로 base 의 cognitive flexibility 를 더 덮어씀 → 학습 본 패턴 강화 / 새 패턴 약화
- 즉 **production 신 캐릭터** 가 주 use case 면 rank 낮은 v3 우세

### 7-3. negative prompt 누적 효과

negs 길어질수록 vs 짧으면서 핵심만? 실험 결과: 12-15 phrase 까지는 도움, 그 이상은 attention dilution. 현 default 가 이 sweet spot.

### 7-4. seed=42 에서 lively 가 조용한 미소

seed=42 는 모든 character 에서 **약간 차분한** 표정 경향. seed=7777 은 더 활기. 같은 prompt 라도 seed 가 personality dial 역할. 캐릭터별 best seed 다를 수 있음.

## 8. 미해결 / 다음 단계

- [ ] face-centered crop fallback 의 정확도 — heuristic 이 v0 의 비정형 출력에서만 발동되니 production 에서는 큰 문제 X. 더 robust 한 face detector (YOLOv8-face) 시도 가능.
- [ ] LoRA 두 개 동시 fuse (`lora_scale_v2=0.5, lora_scale_v3=0.5`) 로 hybrid? 미실험.
- [ ] ComfyUI HTTP API 서버 패턴 — Glimi 메인 코드는 HTTP POST 만, 백엔드 격리. 미구현.
- [ ] 라이선스 — Animagine XL 4.0 의 Fair AI Public License 1.0-SD: 상용 허용 (도출물 공개시 restrictions). 상용 직전 재확인.

## 9. 디렉토리

- 학습 코드 / 데이터: `~/glimi-imagegen-test/training/`
- 추론 스크립트 / 비교: `~/glimi-imagegen-test/scripts/`
- 출력: `~/glimi-imagegen-test/outputs/` (full), `~/glimi-imagegen-test/outputs_1x1/` (crop)
- Glimi 통합 패키지: `~/glimi-imagegen-test/glimi_imagegen/` (이 폴더 — 그대로 Glimi 프로젝트로 복사)

## 10. 비교 그리드 (생성 결과 시각화)

- `grids/COMPARE_full_v0v1v2v3.png` — 4 버전 × 5 prompt 풀 비교
- `grids/COMPARE_crop_v0v1v2v3.png` — 4 버전 × 5 prompt 1:1 크롭 비교
- `grids/CHAR_{name}.png` — 캐릭터별 close-up
- `grids/CROP_VERIFY_LABELED.png` — 크롭 캘리브레이션 검증 (top row = ref)
- `grids/COMPARE_new3_v2_vs_v3.png` — 학습 안 본 새 캐릭 3명 v2/v3 비교 (생성 후)
