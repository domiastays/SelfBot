"""
Ask Claude to review the latest Freqtrade backtest and recommend the next tuning step.

Usage:
    python -m selfbot.claude_review                 # latest result in user_data/backtest_results
    python -m selfbot.claude_review --out review.md

Without ANTHROPIC_API_KEY it still prints the metrics summary (no Claude call),
so it is safe to run anywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

RUBRIC = """You are reviewing a backtest for SelfBot, a long-only daily BTC/USDT trend-following
Freqtrade strategy (EMA fast/slow trend, RSI overbought filter, ATR trailing stop, SMA market gate).

Judge it against these first-pass targets:
- total profit positive and meaningful vs simply holding BTC (market change is given)
- max drawdown under 20-25%
- profit factor above 1.3-1.6
- win rate roughly 45-60% (trend followers can be lower if winners are much bigger than losers)
- enough trades to mean something (a daily strategy over 1 year: ~8-30 trades)
- results not dependent on one or two lucky trades

Tuning order (change ONE thing at a time): 1) EMA short/long (short 5-15, long 20-50)
2) RSI filters (buy max 50-70, sell min 55-75) 3) ATR multiplier (2.0-4.0) 4) ROI 5) exposure.

Write a short markdown report with these sections:
## Verdict  (one line: PASS / NEEDS TUNING / REJECT, and why)
## What the numbers say  (3-6 bullets, cite the numbers)
## Next experiment  (the single parameter change to test next, with exact values, and the
   freqtrade command to run it; mention hyperopt only if it is the better next step)
## Before going live  (2-3 bullets)
Be direct and do not invent numbers that are not in the data. Small samples deserve skepticism."""

KEYS = [
    "strategy_name", "timeframe", "backtest_start", "backtest_end", "backtest_days",
    "total_trades", "wins", "losses", "draws", "winrate", "profit_total", "profit_total_abs",
    "cagr", "sharpe", "sortino", "calmar", "profit_factor", "expectancy_ratio",
    "max_drawdown_account", "max_drawdown_abs", "market_change", "holding_avg",
    "max_consecutive_wins", "max_consecutive_losses", "starting_balance", "final_balance",
    "stake_amount", "max_open_trades", "exit_reason_summary",
]


def load_latest_stats(results_dir: Path) -> dict:
    from freqtrade.data.btanalysis import get_latest_backtest_filename, load_backtest_stats

    name = get_latest_backtest_filename(results_dir)
    stats = load_backtest_stats(results_dir / name)
    strategy = next(iter(stats["strategy"].values()))
    return strategy


def summarize(strategy: dict) -> dict:
    out = {k: strategy.get(k) for k in KEYS if k in strategy}
    trades = strategy.get("trades", [])
    if trades:
        profits = sorted(t.get("profit_ratio", 0) for t in trades)
        out["best_trade_pct"] = round(profits[-1] * 100, 2)
        out["worst_trade_pct"] = round(profits[0] * 100, 2)
        total = sum(t.get("profit_abs", 0) for t in trades)
        top2 = sum(sorted((t.get("profit_abs", 0) for t in trades), reverse=True)[:2])
        out["share_of_profit_from_top2_trades"] = round(top2 / total, 2) if total else None
        out["trades"] = [
            {k: t.get(k) for k in ("open_date", "close_date", "profit_ratio", "exit_reason", "trade_duration")}
            for t in trades
        ]
    return out


def ask_claude(summary: dict) -> str:
    import anthropic

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5"),
        max_tokens=1500,
        system=RUBRIC,
        messages=[{"role": "user", "content": "Backtest results (JSON):\n" + json.dumps(summary, default=str, indent=1)}],
    )
    return msg.content[0].text


def metrics_table(s: dict) -> str:
    def pct(v):
        return f"{v * 100:.2f}%" if isinstance(v, (int, float)) else "n/a"

    def num(v):
        return f"{v:.2f}" if isinstance(v, (int, float)) else "n/a"

    rows = [
        ("Period", f"{s.get('backtest_start')} → {s.get('backtest_end')}"),
        ("Trades", s.get("total_trades")),
        ("Win rate", pct(s.get("winrate"))),
        ("Total profit", pct(s.get("profit_total"))),
        ("BTC buy & hold (market change)", pct(s.get("market_change"))),
        ("Max drawdown", pct(s.get("max_drawdown_account"))),
        ("Profit factor", num(s.get("profit_factor"))),
        ("Sharpe / Sortino", f"{num(s.get('sharpe'))} / {num(s.get('sortino'))}"),
        ("Best / worst trade", f"{s.get('best_trade_pct')}% / {s.get('worst_trade_pct')}%"),
    ]
    lines = ["| Metric | Value |", "|---|---|"] + [f"| {a} | {b} |" for a, b in rows]
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results-dir", default="user_data/backtest_results")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    summary = summarize(load_latest_stats(Path(args.results_dir)))
    report = "# SelfBot backtest review\n\n" + metrics_table(summary) + "\n\n"
    if os.getenv("ANTHROPIC_API_KEY"):
        try:
            report += ask_claude(summary)
        except Exception as exc:
            report += f"_Claude review failed: {exc}_\n"
    else:
        report += "_ANTHROPIC_API_KEY not set — add it as a repo secret to get Claude's tuning recommendation._\n"

    print(report)
    if args.out:
        Path(args.out).write_text(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
