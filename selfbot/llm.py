"""
Pick whichever LLM provider is available, cheapest first that actually works.

Order:
  1. Anthropic Claude   - if ANTHROPIC_API_KEY is set (paid, optional)
  2. GitHub Models      - if GITHUB_TOKEN is set (free tier; in GitHub Actions the
                          built-in token works when the job has `permissions: models: read`)
  3. None               - callers fall back to rule-based logic

Env vars:
  LLM_PROVIDER   - force "anthropic", "github" or "none" (default: auto)
  CLAUDE_MODEL   - Anthropic model, default "claude-sonnet-5-5"
  GITHUB_MODEL   - GitHub Models model id, default "openai/gpt-4o-mini"

Uses only the standard library for GitHub Models, so no extra dependency.
"""

from __future__ import annotations

import json
import os
import urllib.request

GITHUB_MODELS_URL = "https://models.github.ai/inference/chat/completions"


def provider() -> str | None:
    forced = os.getenv("LLM_PROVIDER", "auto").lower()
    if forced == "none":
        return None
    if forced in ("anthropic", "github"):
        return forced
    if os.getenv("ANTHROPIC_API_KEY"):
        return "anthropic"
    if os.getenv("GITHUB_TOKEN"):
        return "github"
    return None


def model_name(p: str | None = None) -> str | None:
    p = p or provider()
    if p == "anthropic":
        return os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
    if p == "github":
        return os.getenv("GITHUB_MODEL") or "openai/gpt-4o-mini"
    return None


def complete(system: str, user: str, max_tokens: int = 1500, timeout: int = 60) -> tuple[str, str]:
    """Return (text, label). Raises RuntimeError if no provider is configured."""
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

    body = json.dumps({
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }).encode()
    req = urllib.request.Request(GITHUB_MODELS_URL, data=body, method="POST", headers={
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.load(resp)
    return data["choices"][0]["message"]["content"], f"GitHub Models ({model}, free)"
