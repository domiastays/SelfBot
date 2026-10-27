"""
Pick whichever LLM provider is available.

Order:
  1. Anthropic Claude - if ANTHROPIC_API_KEY is set (paid, optional)
  2. Google Gemini    - if GEMINI_API_KEY is set (free tier, key from aistudio.google.com)
  3. None             - callers fall back to rule-based logic

Env vars:
  LLM_PROVIDER   - force "anthropic", "gemini" or "none" (default: auto)
  CLAUDE_MODEL   - Anthropic model, default "claude-sonnet-5-5"
  GEMINI_MODEL   - Gemini model(s), comma-separated, tried in order.
                   Default "gemini-3.8-flash,gemini-2.5-flash". Busy/rate-limited
                   answers (429/500/503) are retried with backoff before moving on.

Gemini is called through its OpenAI-compatible endpoint with the standard
library only, so it needs no extra dependency.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


def provider() -> str | None:
    forced = os.getenv("LLM_PROVIDER", "auto").lower()
    if forced == "none":
        return None
    if forced in ("anthropic", "gemini"):
        return forced
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    return None


def model_name(p: str | None = None) -> str | None:
    p = p or provider()
    if p == "anthropic":
        return os.getenv("CLAUDE_MODEL") or "claude-sonnet-5-5"
    if p == "gemini":
        return os.getenv("GEMINI_MODEL") or "gemini-3.8-flash,gemini-2.5-flash"
    return None


def complete(system: str, user: str, max_tokens: int = 1500, timeout: int = 90) -> tuple[str, str]:
    """Return (text, label). Raises on any failure so callers can fall back."""
    p = provider()
    if p is None:
        raise RuntimeError("no LLM provider configured")
    model = model_name(p)

    if p == "anthropic":
        import anthropic

        msg = anthropic.Anthropic().messages.create(
            model=model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text, f"Claude ({model})"

    errors = []
    for m in [x.strip() for x in model.split(",") if x.strip()]:
        for attempt in range(3):
            try:
                return _gemini(m, system, user, max_tokens, timeout), f"Gemini ({m}, free tier)"
            except urllib.error.HTTPError as exc:
                errors.append(f"{m}: HTTP {exc.code}")
                if exc.code in (429, 500, 503) and attempt < 2:
                    time.sleep(15 * (attempt + 1))
                    continue
                break  # other errors (e.g. unknown model): try the next model
            except Exception as exc:
                errors.append(f"{m}: {exc}")
                break
    raise RuntimeError("Gemini unavailable - " + "; ".join(errors))


def _gemini(model: str, system: str, user: str, max_tokens: int, timeout: int) -> str:
    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(GEMINI_URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {os.environ['GEMINI_API_KEY']}",
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode(errors="replace")
    try:
        text = json.loads(raw)["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError(f"unexpected Gemini response: {raw[:300]!r}") from exc
    if not text:
        raise RuntimeError("Gemini returned an empty answer")
    return text
