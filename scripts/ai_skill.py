# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Daniel Avrukin
"""Optional LLM access via LiteLLM (any provider). Never required.

Configuration is read from the environment only; nothing is written to disk:
  LLM_MODEL    a LiteLLM model string, e.g. "openai/<model>", "gemini/<model>", "ollama/<model>"
  LLM_API_KEY  optional; LiteLLM also honours provider variables such as OPENAI_API_KEY
"""
from __future__ import annotations

import json
import os

try:
    import litellm

    litellm.suppress_debug_info = True
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False


def ai_configured() -> bool:
    return bool(LLM_AVAILABLE and os.environ.get("LLM_MODEL"))


def _extract_json(text: str):
    """Pull the first JSON object out of a model reply, with or without code fences."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in reply")
    return json.loads(text[start : end + 1])


def call_ai(prompt: str, timeout: int = 120):
    """Send a prompt and return the parsed JSON reply, or None on any failure."""
    if not ai_configured():
        if os.environ.get("LLM_MODEL") and not LLM_AVAILABLE:
            print("⚠️  LLM_MODEL is set but litellm is not installed (pip install litellm).")
        return None
    model = os.environ["LLM_MODEL"]
    api_key = os.environ.get("LLM_API_KEY") or None
    try:
        response = litellm.completion(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            api_key=api_key,
            timeout=timeout,
            drop_params=True,  # keeps one call signature working across providers
        )
        return _extract_json(response.choices[0].message.content)
    except Exception as exc:  # noqa: BLE001 - any provider error should degrade gracefully
        print(f"⚠️  AI call failed ({model}): {type(exc).__name__}: {exc}")
        return None
