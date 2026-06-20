# glimi_imagegen

Glimi profile image generator. Animagine XL 4.0 + Glimi Style LoRA (v2/v3).

## Install

Copy this entire directory into your Glimi project:

```
cp -r glimi_imagegen /path/to/Glimi/src/
```

The LoRA weights (~93MB each, in `loras/`) are bundled. If checking into git, consider git LFS or `.gitignore` them and document a download step.

### Python deps

```
torch >= 2.1
diffusers >= 0.27
transformers >= 4.36
accelerate
opencv-python
Pillow
numpy
safetensors
```

First run downloads Animagine XL 4.0 base from HuggingFace (~6.5GB) into the HF cache.

## Usage

```python
from glimi_imagegen import generate_profile

result = generate_profile(
    prompt="korean female with high ponytail brown hair, freckles, "
           "navy track jacket with white stripes, "
           "energetic bright smile, sunny yellow gradient background",
    full_path="assets/profile_images/agent-runner-001-full.png",
    crop_path="assets/profile_images/agent-runner-001.png",
    version="v3",   # default — best for new characters
    seed=42,
)
print(result)
# {
#   "full_path": "assets/profile_images/agent-runner-001-full.png",
#   "crop_path": "assets/profile_images/agent-runner-001.png",
#   "crop_method": "face",
#   "prompt": "<final wrapped prompt>",
#   "seed": 42,
#   "version": "v3",
# }
```

The function:
1. Generates an 832×1216 portrait (Animagine + LoRA, EulerAncestral, 30 steps, cfg 5.0).
2. Detects the anime face and crops a 1024² 1:1 face-centered image (calibrated to match Glimi reference proportions).
3. Saves both files. Returns metadata.

## Versions

- **v3** (default) — rank=16, 800 steps. Best for new characters with personality cues.
- **v2** — rank=32, 600 steps. Strongest reference fidelity for the 3 anchor characters.

See [SKILL_prompts.md](SKILL_prompts.md) for prompt-writing guidance, and [RESEARCH.md](RESEARCH.md) for the full development history.

## Performance

| Step | Time (M3 base / 24GB / MPS) |
|------|-----------------------------|
| Pipeline load (first call) | 30-60 s |
| Pipeline load (cached) | ~5 s |
| Single image generation (832×1216, 30 steps) | ~6 min |
| Crop (CPU) | <1 s |

Reuse `GlimiImageGen.get(version)` across calls to avoid reloading.

## Public API

```python
from glimi_imagegen import generate_profile, GlimiImageGen

# One-shot:
generate_profile(prompt, full_path, crop_path, version="v3", seed=42)

# Manual control:
gen = GlimiImageGen.get("v3")
gen.generate(prompt, full_path, crop_path, seed=42, steps=30, guidance_scale=5.0)

# Advanced: caller-controlled prompt (no auto-wrap):
gen.generate(prompt=raw_prompt, full_path=..., crop_path=..., wrap_prompt=False)

# Free GPU memory:
GlimiImageGen.unload()        # all
GlimiImageGen.unload("v2")    # specific version
```

## File layout

```
glimi_imagegen/
├── __init__.py
├── generate.py              # main API
├── crop.py                  # face-centered 1:1 crop (calibrated)
├── lbpcascade_animeface.xml # OpenCV anime-face cascade
├── loras/
│   ├── glimi_style_v2.safetensors  # 93MB
│   └── glimi_style_v3.safetensors  # 93MB
├── README.md                # this file (human)
├── CLAUDE.md                # Claude Code dev guide
├── SKILL_prompts.md         # prompt-writing skill
└── RESEARCH.md              # development history / trial-and-error
```
