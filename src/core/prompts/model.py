"""Model-aware prompt snippets — LLM-dialect analog of `locale.py`.

Purpose
-------
Different LLM backends use different tool-calling syntaxes, response conventions, and
system-prompt quirks. Hardcoding Claude's `<tools>` / `<call>` grammar into every prompt
makes it brittle when we later add local LLMs (ollama / vllm / llama.cpp) or other
cloud providers. This module centralizes those variants behind small helpers.

Design mirrors `locale.py`:
  - Prompts call helper functions (e.g. `tool_call_syntax_hint()`) instead of hardcoding.
  - Helper looks up the currently-active model's provider via a ContextVar.
  - Runtime (`AgentRuntime.activate_agent`) sets the active model before building the
    system prompt, so each agent's prompt reflects its actual backend.

Provider dispatch uses the `provider` field from `AVAILABLE_MODELS` in runtime.py:
  "claude"    — Anthropic Claude (native `<tools>` / `<call>` markup)
  "ollama"    — ollama-served models (generic JSON-after-reply convention)
  "vllm"      — vllm-served models (same generic JSON convention)
  "llamacpp"  — llama.cpp-served models (same)
  "openai"    — OpenAI API (native function_call schema)

Unknown / unset → falls back to "claude" (current default backend).
"""
from __future__ import annotations

from contextvars import ContextVar


# ── Active-model context ────────────────────────────────────────────────────

# Set by AgentRuntime.activate_agent right before build_system_prompt. ContextVar is used
# (not a module global) so parallel FastAPI requests serving different agents see each
# their own model in flight — matches the i18n `_lang()` pattern.
_active_model_id: ContextVar[str | None] = ContextVar("active_model_id", default=None)


def set_active_model(model_id: str):
    """Set the active model for downstream prompt helpers. Returns a token you must
    pass to `reset_active_model(token)` in a `finally` block to avoid leakage."""
    return _active_model_id.set(model_id)


def reset_active_model(token) -> None:
    try:
        _active_model_id.reset(token)
    except (ValueError, LookupError):
        pass


def active_model_id() -> str | None:
    """Currently-active model id, or None if not set."""
    return _active_model_id.get()


def _active_provider() -> str:
    """Provider of the currently-active model. Defaults to 'claude' when unset/unknown.

    Looks up `AVAILABLE_MODELS` in runtime.py — so adding a new local model only needs
    that catalog entry + its provider, no changes here.
    """
    mid = _active_model_id.get()
    if not mid:
        return "claude"
    try:
        from src.core.runtime import AVAILABLE_MODELS
        for m in AVAILABLE_MODELS:
            if m.get("id") == mid:
                return m.get("provider", "claude")
    except Exception:
        pass
    # id not catalogued — pattern-match as a last resort (for experimental models)
    if mid.startswith("claude-"):
        return "claude"
    if mid.startswith(("ollama:", "ollama-")):
        return "ollama"
    if mid.startswith(("vllm:", "vllm-")):
        return "vllm"
    if mid.startswith(("llamacpp:", "llama-")):
        return "llamacpp"
    if mid.startswith(("gpt-", "openai-")):
        return "openai"
    return "claude"


# ── Tool-calling syntax hint ────────────────────────────────────────────────
# This is the single largest model-specific variation. Each provider family expects a
# different tool-invocation grammar; the prompt must tell the LLM which one to emit.

def tool_call_syntax_hint() -> str:
    """'Here's how to emit tool calls' — injected into prompt rules."""
    p = _active_provider()
    if p == "claude":
        return (
            "Tool calls go in a `<tools>` block at the END of your reply.\n"
            'Each call: `<call id="1" name="tool_name">{JSON args}</call>`.\n'
            "Multiple calls share one `<tools>` block with incrementing `id`s."
        )
    if p in ("ollama", "vllm", "llamacpp"):
        return (
            "Tool calls: after your reply, output one JSON object per call on its own line.\n"
            'Format: {"tool": "tool_name", "args": {...}}\n'
            "Do NOT mix tool JSON into the chat body."
        )
    if p == "openai":
        return (
            "Emit tool calls via OpenAI function-calling schema "
            "(the runtime handles the `tool_calls` field; just describe the call naturally)."
        )
    return ""  # unknown — skip the hint rather than mislead


def tool_results_format_hint() -> str:
    """'Tool results will look like this' — injected so the LLM recognizes them next turn."""
    p = _active_provider()
    if p == "claude":
        return "Tool results arrive in the next user message as a `<tool_results>` block."
    if p in ("ollama", "vllm", "llamacpp"):
        return "Tool results arrive in the next user message as JSON."
    if p == "openai":
        return "Tool results arrive via the `tool` role message in the next turn."
    return ""


def tools_block_end_rule() -> str:
    """Cross-provider rule: tool invocations always at the END of the reply, never mid-chat."""
    # Applies to every provider we support.
    return "Always emit tool invocations at the END of your reply, never mid-sentence or mixed with chat lines."


# ── Inline code / markdown conventions ──────────────────────────────────────
# Some models (smaller local ones) lose track of backticks. Helper reserved for later.

def markdown_caveats_hint() -> str:
    p = _active_provider()
    if p in ("ollama", "vllm", "llamacpp"):
        return "Do not overuse markdown — keep formatting minimal (no deep nested lists)."
    return ""


__all__ = [
    "set_active_model",
    "reset_active_model",
    "active_model_id",
    "tool_call_syntax_hint",
    "tool_results_format_hint",
    "tools_block_end_rule",
    "markdown_caveats_hint",
]
