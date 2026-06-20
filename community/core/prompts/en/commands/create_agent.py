"""`!캐릭터생성` — ask Hana (creator) to produce a new persona JSON profile."""
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


__all__ = ["create_agent_prompt"]
