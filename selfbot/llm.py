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
                   Default "gemini-3.8-flash". Busy/rate-limited answers (429/500/503)
                   and timeouts are retried with backoff. If all listed models fail,
                   other text "flash" models your key can use are tried (up to 3).

Gemini is called through its OpenAI-compatible endpoint with the standard
library only, so it needs no extra dependency.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_URL = GEMINI_BASE + "/chat/completions"
_SKIP = ("image", "tts", "audio", "embedding", "live", "vision", "native", "robotics", "computer")


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
        return os.getenv("GEMINI_MODEL") or "gemini-3.8-flash"
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

    errors: list[str] = []
    tried: list[str] = []
    for m in [x.strip() for x in model.split(",") if x.strip()]:
        tried.append(m)
        text = _try_model(m, system, user, max_tokens, timeout, errors)
        if text:
            return text, f"Gemini ({m}, free tier)"
    for m in _other_flash_models(tried, errors)[:3]:
        text = _try_model(m, system, user, max_tokens, timeout, errors)
        if text:
            return text, f"Gemini ({m}, free tier)"
    raise RuntimeError("Gemini unavailable - " + "; ".join(errors))


def _try_model(m, system, user, max_tokens, timeout, errors) -> str | None:
    for attempt in range(3):
        try:
            return _gemini(m, system, user, max_tokens, timeout)
        except urllib.error.HTTPError as exc:
            errors.append(f"{m}: HTTP {exc.code}")
            if exc.code not in (429, 500, 503):
                return None  # e.g. 404 unknown model: no point retrying
        except (TimeoutError, urllib.error.URLError) as exc:
            errors.append(f"{m}: {exc}")
        except Exception as exc:
            errors.append(f"{m}: {exc}")
            return None
        if attempt < 2:
            time.sleep(15 * (attempt + 1))
    return None


def _other_flash_models(tried: list[str], errors: list[str]) -> list[str]:
    """Ask Gemini which models this key can use; return text flash models, lite last."""
    try:
        req = urllib.request.Request(GEMINI_BASE + "/models", headers={
            "Authorization": f"Bearer {os.environ['GEMINI_API_KEY']}"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            ids = [d.get("id", "").removeprefix("models/") for d in json.load(resp).get("data", [])]
    except Exception as exc:
        errors.append(f"model list: {exc}")
        return []
    cands = [i for i in ids if "flash" in i and i not in tried and not any(k in i for k in _SKIP)]
    errors.append("found models: " + ", ".join(cands[:8]))
    return sorted(cands, key=lambda i: ("lite" in i, "preview" in i or "exp" in i))


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
