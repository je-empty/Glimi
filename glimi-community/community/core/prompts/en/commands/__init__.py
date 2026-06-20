"""Prompts for manual !commands targeting Glimi agents.

These are i18n-sensitive (output reaches the user via an agent that responds in the
community's language). Split by command:
  - create_agent.py   — `!캐릭터생성` → ask Hana for a JSON profile
  - analyze_logs.py   — `!분석` → ask Yuna to analyze recent conversation

External-model prompts (DALL-E/Gemini image gen etc.) live in `src/core/prompts/en/external/`
because they target models that only accept English — never i18n'd.
"""
from .create_agent import create_agent_prompt
from .analyze_logs import analyze_logs_prompt

__all__ = ["create_agent_prompt", "analyze_logs_prompt"]
