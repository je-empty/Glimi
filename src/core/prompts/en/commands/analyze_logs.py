"""`!분석` — ask Yuna to analyze a batch of recent conversation logs."""
from __future__ import annotations


def analyze_logs_prompt(log_text: str) -> str:
    """Ask Yuna to analyze a batch of recent conversation logs.

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


__all__ = ["analyze_logs_prompt"]
