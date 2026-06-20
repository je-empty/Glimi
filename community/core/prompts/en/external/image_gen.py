"""Profile image generation prompt — targets external diffusion/multimodal LLM.

This prompt is **copy-pasted by the user into ChatGPT / Gemini / DALL-E** to generate a
character portrait. The target model only accepts English reliably, and the output is a
**raster image** — not a chat reply.

=> NEVER i18n this. Even in a Korean community this stays English.
"""
from __future__ import annotations


def profile_image_prompt(age, outfit_hint: str, char_detail: str) -> str:
    """Wrap Hana's character-design output into an art-direction instruction.

    Args:
        age: character age (used in the lead art prompt)
        outfit_hint: e.g. "school uniform" / "casual hoodie" — appearance-level hint
        char_detail: the long character description Hana produced

    Returns:
        A full prompt string ready to paste into ChatGPT / Gemini image mode.
    """
    base_prompt = (
        f"Anime-style profile illustration, Korean girl, age {age}, "
        f"{outfit_hint}, clean lineart, soft cel shading, "
        f"pastel gradient background, bust-up shot, slightly asymmetrical natural pose, "
        f"subtle catchlight in eyes, consistent art style similar to modern slice-of-life anime "
        f"(like Horimiya or Oregairu visual style)"
    )
    return f"{base_prompt}\n{char_detail}"


__all__ = ["profile_image_prompt"]
