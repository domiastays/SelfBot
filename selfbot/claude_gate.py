"""
Claude trade gate for SelfBot.

Before the bot opens a position (dry-run or live only), the strategy sends
Claude the last 30 daily candles plus indicators and asks for a JSON verdict.

The model comes from selfbot/llm.py: Claude if ANTHROPIC_API_KEY is set,
otherwise Gemini's free tier if GEMINI_API_KEY is set.

The mode can be changed while the bot runs: it is re-read before every entry from
user_data/selfbot_control.json ({"gate_mode": "..."}), which the SelfBot control
panel (selfbot/panel.py) writes. CLAUDE_GATE is only the starting default.

Modes (env CLAUDE_GATE):
  off       - never call a model (also the result when no provider is configured)
  advisory  - ask the model, log its verdict, but always let the trade through (default)
  enforce   - the model can veto entries. Any error -> trade is blocked (fail closed)

Other env vars:
  ANTHROPIC_API_KEY / GEMINI_API_KEY - one of them is needed unless CLAUDE_GATE=off
  CLAUDE_MODEL / GEMINI_MODEL      - model overrides, see selfbot/llm.py
  CLAUDE_GATE_LOG     - JSONL decision log, default user_data/logs/claude_gate.jsonl
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are the risk officer for SelfBot, a long-only daily BTC/USDT trend-following bot.
The mechanical strategy has already produced an entry signal (fast EMA above slow EMA,
price above the trend SMA, RSI not overbought). Your job is a second opinion, not a forecast.

Approve unless you see a concrete reason to skip, for example:
- the move that triggered the signal is a single outsized candle likely to mean-revert
- ATR (volatility) has spiked far above its recent range
- price is extremely stretched above the slow EMA / trend SMA
- the signal contradicts the last few candles (e.g. lower highs into the trigger)

Reply with ONLY a JSON object:
{"approve": true|false, "confidence": 0-1, "reason": "<one sentence>"}"""


MODES = ("off", "advisory", "enforce")
CONTROL_FILE = Path(os.getenv("SELFBOT_CONTROL", "user_data/selfbot_control.json"))


def read_control() -> dict:
    try:
        return json.loads(CONTROL_FILE.read_text())
    except Exception:
        return {}


def write_control(**changes) -> dict:
    data = read_control()
    data.update(changes)
    CONTROL_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONTROL_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(CONTROL_FILE)
    return data


def current_mode() -> str:
    mode = str(read_control().get("gate_mode") or os.getenv("CLAUDE_GATE", "advisory")).lower()
    return mode if mode in MODES else "advisory"


@dataclass
class ClaudeGate:
    model: str
    log_path: Path

    @property
    def mode(self) -> str:
        return current_mode()

    @classmethod
    def from_env(cls) -> "ClaudeGate | None":
        from selfbot.llm import model_name, provider

        if provider() is None:
            logger.warning("ClaudeGate: no ANTHROPIC_API_KEY or GEMINI_API_KEY set - gate disabled.")
            return None

        gate = cls(
            model=model_name(),
            log_path=Path(os.getenv("CLAUDE_GATE_LOG", "user_data/logs/claude_gate.jsonl")),
        )
        logger.info("ClaudeGate ready: mode=%s model=%s", gate.mode, gate.model)
        return gate

    def review_entry(self, pair: str, rate: float, entry_tag: str | None, snapshot) -> bool:
        verdict = {"approve": None, "confidence": None, "reason": None, "error": None}
        mode = self.mode
        if mode == "off":
            verdict["reason"] = "AI gate switched off - entry allowed without review"
            self._log(pair, rate, entry_tag, verdict, True, mode)
            return True
        try:
            table = snapshot.round(2).to_csv(index=False)
            from selfbot.llm import complete

            text, _ = complete(
                SYSTEM_PROMPT,
                f"Pair: {pair}\nProposed entry price: {rate}\nSignal: {entry_tag}\n\n"
                f"Last 30 daily candles with indicators (CSV):\n{table}",
                max_tokens=1024,
            )
            text = text.strip()
            start, end = text.find("{"), text.rfind("}")
            verdict.update(json.loads(text[start:end + 1]))
        except Exception as exc:  # network, parsing, quota...
            verdict["error"] = repr(exc)
            logger.error("ClaudeGate error: %s", exc)

        if mode == "enforce":
            allowed = verdict["approve"] is True
        else:
            allowed = True

        self._log(pair, rate, entry_tag, verdict, allowed, mode)
        logger.info("ClaudeGate %s %s -> approve=%s allowed=%s (%s)",
                    pair, entry_tag, verdict["approve"], allowed, verdict["reason"] or verdict["error"])
        return allowed

    def _log(self, pair, rate, entry_tag, verdict, allowed, mode):
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a") as fh:
                fh.write(json.dumps({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "mode": mode, "model": self.model,
                    "pair": pair, "rate": rate, "entry_tag": entry_tag,
                    "allowed": allowed, **verdict,
                }) + "\n")
        except Exception as exc:
            logger.warning("ClaudeGate could not write log: %s", exc)
