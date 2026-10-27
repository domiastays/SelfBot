"""
Review the latest Freqtrade backtest and recommend the next tuning step.

Usage:
    python -m selfbot.claude_review                 # latest result in user_data/backtest_results
    python -m selfbot.claude_review --out review.md

The written review comes from the first available provider (see selfbot/llm.py):
Claude if ANTHROPIC_API_KEY is set, otherwise the free GitHub Models tier via
GITHUB_TOKEN. If neither works, a rule-based verdict against the same targets is
written instead, so every run gets a verdict and no paid key is required.
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


def ask_llm(summary: dict) -> tuple[str, str]:
    from selfbot.llm import complete

    return complete(RUBRIC, "Backtest results (JSON):\n" + json.dumps(summary, default=str, indent=1))


def rule_based_review(s: dict) -> str:
    """Score the backtest against the rubric targets without any AI call."""
    def f(k):
        v = s.get(k)
        return v if isinstance(v, (int, float)) else None

    profit, market = f("profit_total"), f("market_change")
    dd, pf, wr, n = f("max_drawdown_account"), f("profit_factor"), f("winrate"), f("total_trades")
    top2 = f("share_of_profit_from_top2_trades")
    checks = []  # (passed or None, text)
    checks.append((profit is not None and profit > 0,
                   f"Total profit {profit * 100:.2f}%" if profit is not None else "Total profit unknown"))
    if profit is not None and market is not None:
        checks.append((profit >= market, f"vs BTC buy & hold {market * 100:.2f}%"
                       + (" (beat it)" if profit >= market else " (lagged it)")))
    if dd is not None:
        checks.append((dd < 0.25, f"Max drawdown {dd * 100:.2f}% (target under 20-25%)"))
    if pf is not None:
        checks.append((pf >= 1.3, f"Profit factor {pf:.2f} (target 1.3-1.6+)"))
    if wr is not None:
        checks.append((wr >= 0.35, f"Win rate {wr * 100:.1f}% (target ~45-60%, lower OK if winners are big)"))
    if n is not None:
        checks.append((n >= 8, f"{n} trades (want ~8-30 per year on a daily strategy)"))
    if top2 is not None:
        checks.append((top2 <= 0.8, f"Top 2 trades made {top2 * 100:.0f}% of profit"
                       + (" - too dependent on a few trades" if top2 > 0.8 else "")))

    fails = [t for ok, t in checks if not ok]
    if profit is None or profit <= 0 or (dd is not None and dd >= 0.35):
        verdict = "REJECT"
    elif fails:
        verdict = "NEEDS TUNING"
    else:
        verdict = "PASS"

    if n is not None and n < 8:
        nxt = "Too few trades. Shorten the fast EMA (ema_short 9 -> 7) so the strategy trades more often."
    elif dd is not None and dd >= 0.25:
        nxt = "Drawdown too deep. Tighten the ATR trailing stop (atr_multiplier 3.0 -> 2.5)."
    elif pf is not None and pf < 1.3:
        nxt = "Weak profit factor. Tighten the RSI entry filter (rsi_buy_max 65 -> 60)."
    elif profit is not None and market is not None and profit < market:
        nxt = "Lagging buy & hold. Hold trends longer: lengthen the slow EMA (ema_long 21 -> 30) or loosen the ATR stop (atr_multiplier 3.0 -> 3.5)."
    else:
        nxt = "Re-run on a different year (e.g. 20230101-20231231) to check the result holds out of sample."

    out = [f"## Verdict\n**{verdict}** (rule-based check against the targets)\n", "## What the numbers say"]
    out += [f"- {'OK' if ok else 'FAIL'}: {t}" for ok, t in checks]
    out += ["", "## Next experiment", nxt,
            "Change one thing, then re-run the workflow (or `./backtest.sh`).", "",
            "## Before going live",
            "- Confirm the result on at least one other year of data.",
            "- Run in dry-run mode for a few weeks before using real money."]
    return "\n".join(out) + "\n"


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
    review, source = None, None
    try:
        review, source = ask_llm(summary)
    except Exception as exc:
        detail = str(exc)
        body = getattr(exc, "read", None)
        if callable(body):
            try:
                detail += " - " + body().decode(errors="replace")[:300]
            except Exception:
                pass
        print(f"AI review unavailable ({detail}); using rule-based review.", file=sys.stderr)
        source_note = f" - AI unavailable: {detail}"
    else:
        source_note = ""
    if not review:
        review, source = rule_based_review(summary), "built-in rules (no AI)" + source_note
    report += review + f"\n\n_Review by: {source}_\n"

    if summary.get("trades"):
        report += "\n\n### Trades\n\n| Open | Close | Profit | Exit reason |\n|---|---|---|---|\n"
        for t in summary["trades"]:
            report += (f"| {str(t['open_date'])[:10]} | {str(t['close_date'])[:10]} | "
                       f"{(t['profit_ratio'] or 0) * 100:.2f}% | {t['exit_reason']} |\n")

    print(report)
    if args.out:
        Path(args.out).write_text(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
