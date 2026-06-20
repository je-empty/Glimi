# glimi_imagegen — Claude Code Dev Notes

세션 시작 시 필독. 이 모듈을 수정하거나 Glimi 본체에 통합할 때.

## 한 줄 정리

`from glimi_imagegen import generate_profile` 하나로 prompt → (full + crop) 두 파일 저장. Animagine XL 4.0 + Glimi Style LoRA (v2 또는 v3).

## 모듈 구조

```
glimi_imagegen/
  __init__.py           # public exports: generate_profile, GlimiImageGen
  generate.py           # 파이프라인 lazy-singleton + 메인 API
  crop.py               # 1:1 face crop (calibrated 0.68/0.59/-0.08)
  lbpcascade_animeface.xml
  loras/
    glimi_style_v2.safetensors
    glimi_style_v3.safetensors
  README.md             # 사람용
  CLAUDE.md             # 이 파일
  SKILL_prompts.md      # prompt 작성 스킬 (Glimi 코드 짤 때 참고)
  RESEARCH.md           # 시행착오 기록
```

## API

```python
generate_profile(
    prompt="<character block only — wrap is auto>",
    full_path="path/to/full.png",
    crop_path="path/to/crop.png",
    version="v3" | "v2",   # default v3
    seed=42,
    # optional: width, height, steps, guidance_scale, negative_prompt,
    #           crop_target_size, wrap_prompt
)
```

Returns dict: `{full_path, crop_path, crop_method, prompt, seed, version}`.

## prompt 작성 — `SKILL_prompts.md` 참조

핵심:
- character block 만 쓰면 됨 (quality / trigger / style suffix 자동 wrap).
- 형식: `korean female with {HAIR}, {OUTFIT}, {EXPRESSION}, {BG} gradient background`
- bust-up + 1인 only. CLIP 77 토큰 cap 주의.

## v2 vs v3

- 신 캐릭터 (production 주 use case): **v3** (default).
- 기존 anchor 3 (lively/gentle/mgr) 정확 재현: **v2**.

## 주의사항

### 코어와의 decoupling

Glimi 의 `src/core/*` 는 디스코드를 모르듯, 이미지 생성 모듈은 Glimi 의 도메인 객체를 모름. 이 모듈은 **prompt + 두 path 만** 받음 — agent / community / channel 같은 것 import 금지. Glimi 측에서 wrapper 짜서 사용.

```python
# Glimi 측 wrapper 예시 (src/services/profile_image.py 같은 데)
from glimi_imagegen import generate_profile

def generate_for_agent(agent: Agent) -> dict:
    full = f"assets/profile_images/{agent.id}-full.png"
    crop = f"assets/profile_images/{agent.id}.png"
    return generate_profile(
        prompt=agent.persona.to_image_prompt_block(),
        full_path=full,
        crop_path=crop,
        version="v3",
        seed=agent.image_seed,
    )
```

### LoRA 파일 위치

`loras/` 안의 두 safetensors 는 git lfs 또는 `.gitignore` 처리 권장 (각 93MB). 다운로드 스크립트로 내려받게 할 수도 있음.

### 첫 실행 시 HuggingFace 다운로드

Animagine XL 4.0 base (~6.5GB) 가 `~/.cache/huggingface/hub/` 로 내려감. CI 에서는 캐시 보존 필요.

### M3 base 전제

- MPS device 사용 (`torch.backends.mps.is_available()`).
- fp16 (`torch.float16`).
- 이미지 1장 ~6분. CI 에 넣지 말 것.
- 24GB 경계: 832×1216 + 30 step + LoRA fused 가 마지노선. cuda / 더 큰 메모리에서는 1024²+ 가능.

### Glimi 의 `assets/profile_images/` 컨벤션

- `agent-{role}-{id}-full.png` — 832×1216 원본
- `agent-{role}-{id}.png` — 1024² 크롭 (UI 가 이걸 렌더)

이 모듈도 같은 컨벤션 따르도록 caller 가 path 지정.

### 메모리 해제

여러 caller 가 모듈 쓸 때 GPU 점유 누적되면:
```python
GlimiImageGen.unload()         # 모두 해제
GlimiImageGen.unload("v2")     # 특정 version 만
```

### dialect / lang

이 모듈은 영어 prompt 만 받음 (Animagine XL 4.0 학습이 영어). 한국 특화는 prompt 의 "korean" 키워드로 표현. Glimi 의 한글 persona → 영어 image prompt 변환은 caller 책임.

## 다음 작업 후보

- ComfyUI HTTP API 백엔드 패턴 (`tmux Glimi-ImageGen` + HTTP POST). 메모리 격리 + 메인 코드 간소화.
- LoRA 두 개 hybrid (`fuse_lora(scale=0.5)` 두 번) — 미실험.
- YOLOv8-face 로 crop 강화.

자세한 시행착오는 `RESEARCH.md`.
