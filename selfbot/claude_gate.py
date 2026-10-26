"""
Claude trade gate for SelfBot.

Before the bot opens a position (dry-run or live only), the strategy sends
Claude the last 30 daily candles plus indicators and asks for a JSON verdict.

Modes (env CLAUDE_GATE):
  off       - never call Claude (default if ANTHROPIC_API_KEY is missing)
  advisory  - ask Claude, log its verdict, but always let the trade through (default)
  enforce   - Claude can veto entries. Any error -> trade is blocked (fail closed)

Other env vars:
  ANTHROPIC_API_KEY   - required unless CLAUDE_GATE=off
  CLAUDE_MODEL        - default "claude-sonnet-5-5"
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


@dataclass
class ClaudeGate:
    mode: str
    model: str
    log_path: Path
    _client: object = None

    @classmethod
    def from_env(cls) -> "ClaudeGate | None":
        mode = os.getenv("CLAUDE_GATE", "advisory").lower()
        if mode == "off":
            return None
        if not os.getenv("ANTHROPIC_API_KEY"):
            logger.warning("ClaudeGate: ANTHROPIC_API_KEY not set - gate disabled.")
            return None
        import anthropic  # imported lazily so backtests don't need it

        gate = cls(
            mode=mode,
            model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
            log_path=Path(os.getenv("CLAUDE_GATE_LOG", "user_data/logs/claude_gate.jsonl")),
        )
        gate._client = anthropic.Anthropic()
        logger.info("ClaudeGate enabled: mode=%s model=%s", gate.mode, gate.model)
        return gate

    def review_entry(self, pair: str, rate: float, entry_tag: str | None, snapshot) -> bool:
        verdict = {"approve": None, "confidence": None, "reason": None, "error": None}
        try:
            table = snapshot.round(2).to_csv(index=False)
            msg = self._client.messages.create(
                model=self.model,
                max_tokens=300,
                system=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": f"Pair: {pair}\nProposed entry price: {rate}\nSignal: {entry_tag}\n\n"
                               f"Last 30 daily candles with indicators (CSV):\n{table}",
                }],
            )
            text = msg.content[0].text.strip()
            start, end = text.find("{"), text.rfind("}")
            verdict.update(json.loads(text[start:end + 1]))
        except Exception as exc:  # network, parsing, quota...
            verdict["error"] = repr(exc)
            logger.error("ClaudeGate error: %s", exc)

        if self.mode == "enforce":
            allowed = verdict["approve"] is True
        else:
            allowed = True

        self._log(pair, rate, entry_tag, verdict, allowed)
        logger.info("ClaudeGate %s %s -> approve=%s allowed=%s (%s)",
                    pair, entry_tag, verdict["approve"], allowed, verdict["reason"] or verdict["error"])
        return allowed

    def _log(self, pair, rate, entry_tag, verdict, allowed):
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a") as fh:
                fh.write(json.dumps({
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "mode": self.mode, "model": self.model,
                    "pair": pair, "rate": rate, "entry_tag": entry_tag,
                    "allowed": allowed, **verdict,
                }) + "\n")
        except Exception as exc:
            logger.warning("ClaudeGate could not write log: %s", exc)
