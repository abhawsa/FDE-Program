"""Minimal Anthropic client wrapper used only for test-draft generation.

Kept deliberately thin: one function, one job. Raises LLMUnavailable
whenever a real LLM call cannot be made so callers (test_generator.py) can
fall back to a template draft instead of guessing or pretending.
"""
from __future__ import annotations

from .config import Settings


class LLMUnavailable(Exception):
    """Raised when no credentialed LLM backend is available."""


def generate_with_claude(prompt: str, settings: Settings, max_tokens: int = 1400) -> str:
    if not settings.anthropic_api_key:
        raise LLMUnavailable("ANTHROPIC_API_KEY is not set")

    try:
        import anthropic
    except ImportError as exc:
        raise LLMUnavailable("the 'anthropic' package is not installed") from exc

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    try:
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:  # network/auth/rate-limit errors all fall back to the template
        raise LLMUnavailable(f"Anthropic API call failed: {exc}") from exc

    text_parts = [block.text for block in response.content if getattr(block, "type", None) == "text"]
    text = "\n".join(text_parts).strip()
    if not text:
        raise LLMUnavailable("Anthropic API returned an empty response")
    return text
