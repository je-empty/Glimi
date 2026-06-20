"""glimi_imagegen — Glimi profile image generation.

Quick usage:
    from glimi_imagegen import generate_profile

    generate_profile(
        prompt="korean female with shoulder-length brown wavy hair half-up, "
               "white knit, warm welcoming smile with crescent eyes, "
               "soft pink gradient background",
        full_path="assets/profile_images/agent-foo-001-full.png",
        crop_path="assets/profile_images/agent-foo-001.png",
        version="v3",   # or "v2"
        seed=42,
    )

The function builds a 832x1216 portrait + 1024² face-centered 1:1 crop
and writes both to disk. See SKILL_prompts.md for prompt format guidance.
"""
from .generate import generate_profile, GlimiImageGen

__all__ = ["generate_profile", "GlimiImageGen"]
