---
name: glimi-imagegen-prompt
description: Write prompts for Glimi profile image generation (Animagine XL 4.0 + glimi_style LoRA v2/v3). Use when generating new agent profile portraits via `glimi_imagegen.generate_profile`.
---

# Glimi Profile Prompt Skill

This module wraps every prompt with this template **automatically** (so you don't write it):

```
masterpiece, high score, great score, absurdres, best quality, glimistyle,
{YOUR CHARACTER BLOCK},
clean delicate thin lineart, soft cel shading, bust-up portrait,
wholesome slice-of-life anime, centered composition, face at center, symmetric framing
```

**You only write the CHARACTER BLOCK.** Pass it as `prompt=...` to `generate_profile()`. The wrap is the only thing the LoRA was trained on, so don't manually re-add `glimistyle`, `masterpiece`, etc. — they're inserted for you.

## Character block format

Always 3-5 short comma-separated phrases in this order:

```
korean female with {HAIR}, {OUTFIT}, {EXPRESSION}, {BACKGROUND}
```

### Slot guidance

**HAIR** — describe length + texture + color + (optional) accessory:
- ✓ "shoulder-length brown wavy hair half-up"
- ✓ "long straight black hair and bangs"
- ✓ "chin-length straight black hair, beige bucket hat"
- ✗ "pretty hair" (too vague)
- ✗ "hair with extensions and highlights and..." (overstuffed)

**OUTFIT** — top garment + accent piece (skip pants/skirt — bust-up only shows torso):
- ✓ "navy school blazer, white blouse, red striped tie"
- ✓ "cream turtleneck sweater"
- ✓ "soft beige cardigan"
- Add 1 small accessory if it defines personality: "small hoop earrings", "round glasses", "bucket hat"

**EXPRESSION** — emotion + face cue (eyes / smile / mouth):
- ✓ "warm welcoming smile with crescent eyes"
- ✓ "calm composed expression"
- ✓ "playful confident smirk"
- ✗ "happy" (LoRA generates default smile — be specific or it'll look generic)

**BACKGROUND** — color + pastel gradient phrase:
- ✓ "soft pink gradient background"
- ✓ "lavender pastel gradient background"
- ✓ "cool mint gradient background"
- Always pastel + gradient. Saturated colors fight the soft cel shading.

## Negative prompt — handled automatically

You don't need to add a negative prompt. The default blocks: NSFW drift (cleavage/glamorous/heavy makeup), realism (photo/3d), framing issues (full body, multiple people, side angle).

If your generation has a specific failure (e.g. unwanted glasses), pass `negative_prompt="...your additions..., {default_negs}"` — but try fixing the positive prompt first.

## Examples

### Existing characters (training set)

```python
generate_profile(
    prompt="korean female with shoulder-length brown wavy hair half-up, "
           "white knit, warm welcoming smile with crescent eyes, "
           "soft pink gradient background",
    full_path="assets/profile_images/agent-lively-001-full.png",
    crop_path="assets/profile_images/agent-lively-001.png",
    version="v3",
)
```

### Brand-new character

```python
generate_profile(
    prompt="korean female with high ponytail brown hair, freckles, "
           "navy track jacket with white stripes, "
           "energetic bright smile, sunny yellow gradient background",
    full_path="assets/profile_images/agent-runner-001-full.png",
    crop_path="assets/profile_images/agent-runner-001.png",
    version="v3",
)
```

## v2 vs v3 — which to pick

| Use case | Version |
|----------|---------|
| Reproducing the 3 anchor characters (lively / gentle / mgr) | **v2** — tightest reference fidelity (e.g. mgr's striped tie clearer) |
| Brand-new characters with personality cues (intense / geek / quirky) | **v3** — better generalization, captures expression nuance |
| Default for production | **v3** — generalizes to unseen prompts better |

`version="v3"` is the default if unspecified.

## Seed behavior

Same `(prompt, seed, version)` → identical output (reproducible).

For variations of the same character, vary the seed: `seed=42`, `seed=7777`, `seed=1234` — keep prompt constant.

## Constraints / limits (don't bypass)

1. **bust-up only** — never request "full body" or "from below". Crop assumes face in upper portion.
2. **single subject** — no group portraits. Multi-person prompts produce mush.
3. **gender = korean female** — current LoRA is trained on this prefix. Other prefixes work but quality drops.
4. **CLIP 77 token cap** — keep total prompt under ~50 of YOUR words (the wrap adds ~30 tokens). Sentence-style prompts get truncated and lose the style anchors at the end.
5. **don't add `glimistyle` yourself** — it's inserted. Adding twice causes attention dilution.

## Output paths convention

Match Glimi's existing assets layout:

- `assets/profile_images/agent-{role}-{id}-full.png` — 832×1216 full portrait
- `assets/profile_images/agent-{role}-{id}.png` — 1024² face-centered crop

The crop is what the UI renders. The full is for re-cropping or editing later.

## Cost notes

- First call: ~30-60s pipeline load + ~6 min/image (M3 base, MPS).
- Subsequent calls (same version): ~6 min/image.
- Switching `version` reloads the pipeline (~30s overhead).
- Run multiple generations of the same `version` together to amortize the load.
