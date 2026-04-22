"""Prompts used by manual Discord commands (src/bot/commands.py).

Extracted from src/bot/commands.py (Phase 2-B pure move).

Builders:
  - create_agent_prompt:  `!캐릭터생성` -> ask Hana for a full JSON profile
  - profile_image_prompt: external image-gen LLM prompt (ChatGPT/Gemini copy-paste)
  - analyze_logs_prompt:  `!분석` -> ask Yuna for a recent-conversation analysis
"""
from __future__ import annotations


def create_agent_prompt(new_id: str, concept: str) -> str:
    """Ask Hana to produce a JSON profile for a new persona agent."""
    return (
        f"Create a new persona agent.\n"
        f"Agent ID: {new_id}\n"
        f"Concept: {concept}\n\n"
        f"Output a complete JSON profile — same structure as existing agent profiles. "
        f"Output JSON ONLY, no other text."
    )


def profile_image_prompt(age, outfit_hint: str, char_detail: str) -> str:
    """External image-generation LLM prompt (ChatGPT / Gemini).

    Wraps the character detail Hana designed into an art-direction instruction.
    The target here is a diffusion/multimodal model that expects English — do not
    localize this one.
    """
    base_prompt = (
        f"Anime-style profile illustration, Korean girl, age {age}, "
        f"{outfit_hint}, clean lineart, soft cel shading, "
        f"pastel gradient background, bust-up shot, slightly asymmetrical natural pose, "
        f"subtle catchlight in eyes, consistent art style similar to modern slice-of-life anime "
        f"(like Horimiya or Oregairu visual style)"
    )
    return f"{base_prompt}\n{char_detail}"


def analyze_logs_prompt(log_text: str) -> str:
    """Ask Yuna to analyze a batch of recent conversation logs (`!분석` command).

    Yuna's speech style (teenage girl) is established by her system prompt and the
    [LANGUAGE: X] block — we only describe the reporting task here.
    """
    return (
        f"Analyze the recent conversation log and report back:\n\n"
        f"{log_text}\n\n"
        f"1. Estimate each agent's current state / emotion.\n"
        f"2. Note any notable relationship changes.\n"
        f"3. Flag any third parties mentioned in the conversation.\n"
        f"4. Decide whether it would be good to add a new agent. If so, suggest what kind of character.\n\n"
        f"Report in your own voice."
    )
