"""Prompts targeting external models outside the Glimi agent system.

These prompts are sent to models like DALL-E, ChatGPT image gen, Gemini image, etc.
They expect English and **must never be localized** — the output there is an image or
artifact the user sees, not a chat message that needs a Korean reply.

Keep these decoupled from i18n flow so future translation work doesn't accidentally
break external model compatibility.
"""
from .image_gen import profile_image_prompt

__all__ = ["profile_image_prompt"]
