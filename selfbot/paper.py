"""
SelfBot paper trader: runs the real strategy on live daily candles with fake money.

Designed to be called on a schedule (GitHub Actions, hourly). Each call:
  1. loads the downloaded BTC/USDT 1d candles (closed candles drive decisions;
     the still-forming candle is only used to show the live price)
  2. runs the strategy's own populate_* methods, so signals match backtests
  3. for every newly closed candle: updates the ATR trailing stop, checks stop /
     ROI / exit signal, then entry signal (asking the AI gate first)
  4. once per new candle asks the AI for a "daily read" of the market
  5. writes state.json (the paper account) and status.json (for the dashboard)

    python -m selfbot.paper -c config.sample.json --data user_data/data/binance/BTC_USDT-1d.feather \
        --state site/state.json --status site/status.json

Simplifications vs. the full bot: fills at the candle close (stops at the stop
price), 0.1% fee per side, one pair, one position.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "user_data" / "strategies"))
from FreqtradeDailyHybridStrategy import FreqtradeDailyHybridStrategy  # noqa: E402

FEE = 0.001
PAIR = "BTC/USDT"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_state(path: Path, wallet: float, start: str) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"version": 1, "started_at": now_iso(), "start_candle": start, "wallet_start": wallet,
            "cash": wallet, "position": None, "trades": [], "equity": [], "ai_log": [],
            "last_candle": None}


def roi_hit(strategy, entry_date: str, candle_date: pd.Timestamp, profit: float) -> bool:
    minutes = (candle_date - pd.Timestamp(entry_date)).total_seconds() / 60
    target = None
    for k, v in sorted(((int(k), v) for k, v in strategy.minimal_roi.items())):
        if minutes >= k:
            target = v
    return target is not None and profit >= target


def ai_check(row_idx: int, df: pd.DataFrame, cols: list[str], tag: str, mode: str) -> dict | None:
    """Ask the configured model (Gemini/Claude) via ClaudeGate; return the logged verdict."""
    from selfbot.claude_gate import ClaudeGate

    log = Path(tempfile.mkdtemp()) / "gate.jsonl"
    os.environ.update(CLAUDE_GATE=mode, CLAUDE_GATE_LOG=str(log))
    gate = ClaudeGate.from_env()
    if gate is None:
        return None
    snap = df.iloc[max(0, row_idx - 29): row_idx + 1][cols]
    allowed = gate.review_entry(pair=PAIR, rate=float(df["close"].iloc[row_idx]), entry_tag=tag, snapshot=snap)
    v = json.loads(log.read_text().splitlines()[-1])
    v["allowed"] = allowed
    return v


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="config.sample.json")
    ap.add_argument("--data", required=True)
    ap.add_argument("--state", required=True)
    ap.add_argument("--status", required=True)
    ap.add_argument("--exchange", default=os.getenv("EXCHANGE", "binance"))
    args = ap.parse_args()

    config = json.loads(Path(args.config).read_text())
    strat = FreqtradeDailyHybridStrategy(config)
    gate_mode = os.getenv("CLAUDE_GATE", "advisory")
    stake = float(config["stake_amount"])

    raw = pd.read_feather(args.data).sort_values("date").reset_index(drop=True)
    today = pd.Timestamp.now(tz="UTC").normalize()
    live = raw.iloc[-1] if raw["date"].iloc[-1] >= today else None  # forming candle, display only
    df = raw[raw["date"] < today].reset_index(drop=True)
    meta = {"pair": PAIR}
    df = strat.populate_indicators(df, meta)
    df = strat.populate_entry_trend(df, meta)
    df = strat.populate_exit_trend(df, meta)
    fast, slow = f"ema_{strat.ema_short.value}", f"ema_{strat.ema_long.value}"
    cols = ["date", "open", "high", "low", "close", "volume", "rsi", "atr", "sma_trend", fast, slow]

    state_path = Path(args.state)
    last_closed = df["date"].iloc[-1]
    st = load_state(state_path, float(config.get("dry_run_wallet", 1000)), str(last_closed))

    # Candles not processed yet (first run: only the latest one - paper trading starts now)
    if st["last_candle"] is None:
        new_idx = [len(df) - 1]
    else:
        new_idx = list(df.index[df["date"] > pd.Timestamp(st["last_candle"])])

    events = []
    for i in new_idx:
        row = df.iloc[i]
        d = row["date"]
        pos = st["position"]
        if pos:
            new_stop = max(pos["stop"], row["close"] - strat.atr_multiplier.value * row["atr"])
            exit_price, reason = None, None
            if row["low"] <= pos["stop"]:
                exit_price, reason = min(pos["stop"], row["open"]), "trailing_stop_loss"
            elif roi_hit(strat, pos["entry_date"], d, row["close"] / pos["entry_price"] - 1):
                exit_price, reason = row["close"], "roi"
            elif row.get("exit_long") == 1:
                exit_price, reason = row["close"], row.get("exit_tag") or "exit_signal"
            if exit_price:
                proceeds = pos["amount"] * exit_price * (1 - FEE)
                pnl = proceeds - pos["stake"]
                st["cash"] += proceeds
                st["trades"].append({**pos, "exit_date": str(d), "exit_price": round(float(exit_price), 2),
                                     "exit_reason": reason, "pnl": round(pnl, 2),
                                     "pnl_pct": round(pnl / pos["stake"], 4)})
                st["position"] = None
                events.append(f"{str(d)[:10]} SELL at {exit_price:.0f} ({reason}), P&L {pnl:+.2f} USDT")
            else:
                pos["stop"] = round(float(new_stop), 2)

        if st["position"] is None and row.get("enter_long") == 1:
            is_latest = i == len(df) - 1
            verdict = ai_check(i, df, cols, row.get("enter_tag") or "entry", gate_mode) if is_latest else None
            if verdict:
                st["ai_log"].append({"date": str(d), "kind": "entry", **verdict})
            if verdict is None or verdict["allowed"]:
                spend = min(stake, st["cash"])
                amount = spend * (1 - FEE) / row["close"]
                stop = max(row["close"] * (1 + strat.stoploss), row["close"] - strat.atr_multiplier.value * row["atr"])
                st["position"] = {"entry_date": str(d), "entry_price": round(float(row["close"]), 2),
                                  "amount": amount, "stake": spend, "stop": round(float(stop), 2),
                                  "entry_tag": row.get("enter_tag"),
                                  "ai": (verdict or {}).get("reason")}
                st["cash"] -= spend
                events.append(f"{str(d)[:10]} BUY at {row['close']:.0f}")
            else:
                events.append(f"{str(d)[:10]} entry signal VETOED by AI: {verdict.get('reason')}")

        mark = st["position"]["amount"] * row["close"] if st["position"] else 0
        st["equity"].append({"date": str(d), "equity": round(st["cash"] + mark, 2), "price": round(float(row["close"]), 2)})
        st["last_candle"] = str(d)

    # Daily AI read on the newest closed candle (once per candle)
    latest = df.iloc[-1]
    if new_idx and not any(a.get("date") == str(latest["date"]) for a in st["ai_log"]):
        v = ai_check(len(df) - 1, df, cols, "daily_read (no live signal, hypothetical entry)", "enforce")
        if v:
            st["ai_log"].append({"date": str(latest["date"]), "kind": "daily_read", **v})
    st["ai_log"] = st["ai_log"][-200:]
    st["events"] = (st.get("events", []) + events)[-200:]

    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(st, indent=1, default=str))

    # ---------------- dashboard payload
    price = float(live["close"]) if live is not None else float(latest["close"])
    pos = st["position"]
    equity_now = st["cash"] + (pos["amount"] * price if pos else 0)
    fast_v, slow_v = latest[fast], latest[slow]
    conditions = [
        {"name": f"Market healthy: close above {strat.trend_sma.value}-day SMA", "ok": bool(latest["close"] > latest["sma_trend"]),
         "detail": f"{latest['close']:.0f} vs {latest['sma_trend']:.0f}"},
        {"name": f"Uptrend: EMA{strat.ema_short.value} above EMA{strat.ema_long.value}", "ok": bool(fast_v > slow_v),
         "detail": f"{fast_v:.0f} vs {slow_v:.0f}"},
        {"name": f"Not overbought: RSI below {strat.rsi_buy_max.value}", "ok": bool(latest["rsi"] < strat.rsi_buy_max.value),
         "detail": f"RSI {latest['rsi']:.1f}"},
        {"name": "Trigger: fresh EMA cross-up or price reclaiming the fast EMA", "ok": bool(latest.get("enter_long") == 1),
         "detail": "fired on last candle" if latest.get("enter_long") == 1 else "not on last candle"},
    ]
    chart = df.tail(240)
    status = {
        "generated_at": now_iso(),
        "exchange": args.exchange,
        "pair": PAIR,
        "mode": "paper (dry run)",
        "ai_provider": (st["ai_log"][-1].get("model") if st["ai_log"] else None),
        "gate_mode": gate_mode,
        "params": {"ema_short": strat.ema_short.value, "ema_long": strat.ema_long.value,
                   "rsi_buy_max": strat.rsi_buy_max.value, "rsi_sell_min": strat.rsi_sell_min.value,
                   "atr_multiplier": strat.atr_multiplier.value, "trend_sma": strat.trend_sma.value,
                   "stoploss": strat.stoploss, "stake": stake},
        "price": price,
        "price_time": str(live["date"]) if live is not None else str(latest["date"]),
        "last_closed_candle": str(latest["date"]),
        "account": {"wallet_start": st["wallet_start"], "cash": round(st["cash"], 2), "equity": round(equity_now, 2),
                    "pnl": round(equity_now - st["wallet_start"], 2), "started_at": st["started_at"],
                    "start_price": st["equity"][0]["price"] if st["equity"] else None},
        "position": None if not pos else {
            **{k: pos[k] for k in ("entry_date", "entry_price", "stake", "stop", "entry_tag", "ai")},
            "amount": round(pos["amount"], 6), "value": round(pos["amount"] * price, 2),
            "unrealized": round(pos["amount"] * price * (1 - FEE) - pos["stake"], 2),
            "unrealized_pct": round(price / pos["entry_price"] - 1, 4)},
        "signal": {"conditions": conditions, "enter": bool(latest.get("enter_long") == 1),
                   "exit": bool(latest.get("exit_long") == 1)},
        "trades": st["trades"][-50:],
        "events": st["events"][-30:],
        "ai_log": st["ai_log"][-30:],
        "equity": st["equity"][-400:],
        "candles": [{"t": int(r["date"].timestamp()), "o": round(r["open"], 2), "h": round(r["high"], 2),
                     "l": round(r["low"], 2), "c": round(r["close"], 2), "f": round(r[fast], 2), "s": round(r[slow], 2),
                     "m": None if pd.isna(r["sma_trend"]) else round(r["sma_trend"], 2), "rsi": round(r["rsi"], 1),
                     "e": int(r.get("enter_long") == 1), "x": int(r.get("exit_long") == 1)}
                    for r in chart.to_dict("records")],
    }
    Path(args.status).write_text(json.dumps(status, default=str))
    print(json.dumps({k: status[k] for k in ("generated_at", "price", "account", "position")}, default=str, indent=1))
    for e in events:
        print(e)
    return 0


if __name__ == "__main__":
    sys.exit(main())
