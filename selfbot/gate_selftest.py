"""
Smoke-test the AI trade gate on real candles, without running the bot.

    python -m selfbot.gate_selftest --data user_data/data/binance/BTC_USDT-1d.feather

Builds the same 30-candle snapshot the strategy sends before an entry, asks the
configured model (Gemini / Claude) for a verdict, and prints it. Exit code 1 if the
model could not be reached or did not return a valid JSON verdict.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "user_data" / "strategies"))
from FreqtradeDailyHybridStrategy import atr, ema, rsi  # noqa: E402

from selfbot.claude_gate import ClaudeGate  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    args = ap.parse_args()

    df = pd.read_feather(args.data)
    df["ema_9"], df["ema_21"] = ema(df["close"], 9), ema(df["close"], 21)
    df["sma_trend"] = df["close"].rolling(100).mean()
    df["rsi"], df["atr"] = rsi(df["close"]), atr(df)
    snap = df.tail(30)[["date", "open", "high", "low", "close", "volume", "rsi", "atr", "sma_trend", "ema_9", "ema_21"]]

    log = Path(tempfile.mkdtemp()) / "gate.jsonl"
    os.environ.update(CLAUDE_GATE="enforce", CLAUDE_GATE_LOG=str(log))
    gate = ClaudeGate.from_env()
    if gate is None:
        print("::warning title=AI gate test::No GEMINI_API_KEY / ANTHROPIC_API_KEY - gate disabled, skipped.")
        return 0

    gate.review_entry(pair="BTC/USDT", rate=float(df["close"].iloc[-1]), entry_tag="selftest", snapshot=snap)
    v = json.loads(log.read_text().splitlines()[-1])
    ok = v.get("error") is None and isinstance(v.get("approve"), bool)
    msg = (f"model={v['model']} | last candle {str(df['date'].iloc[-1])[:10]} close={v['rate']:.0f} | "
           f"approve={v.get('approve')} confidence={v.get('confidence')} | "
           f"{v.get('reason') or v.get('error')}")
    print(f"::{'notice' if ok else 'error'} title=AI gate test ({'OK' if ok else 'FAILED'})::{msg}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
