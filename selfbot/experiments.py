"""
Backtest every variant in experiments.json on every period and write a comparison.

    python -m selfbot.experiments -c ci.config.json --out-json compare.json --out-md compare.md

Variant params are applied through Freqtrade's strategy-parameter file
(user_data/strategies/FreqtradeDailyHybridStrategy.json); an existing file is
backed up and restored afterwards. Market data must already be downloaded.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STRATEGY = "FreqtradeDailyHybridStrategy"
PARAMS_FILE = Path("user_data/strategies") / f"{STRATEGY}.json"
METRICS = ["total_trades", "winrate", "profit_total", "market_change", "max_drawdown_account",
           "profit_factor", "sharpe", "backtest_start", "backtest_end"]


def run_one(config: str, timerange: str, params: dict) -> dict:
    from freqtrade.data.btanalysis import get_latest_backtest_filename, load_backtest_stats

    PARAMS_FILE.write_text(json.dumps({"strategy_name": STRATEGY, "params": params}))
    outdir = Path(tempfile.mkdtemp(prefix="bt_"))
    proc = subprocess.run(
        ["freqtrade", "backtesting", "-c", config, "--strategy", STRATEGY, "--timerange", timerange,
         "--export", "trades", "--backtest-directory", str(outdir), "--cache", "none"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return {"error": (proc.stderr or proc.stdout)[-400:]}
    stats = load_backtest_stats(outdir / get_latest_backtest_filename(outdir))
    s = stats["strategy"][STRATEGY]
    out = {k: s.get(k) for k in METRICS}
    trades = s.get("trades", [])
    pnl = sorted((t.get("profit_abs", 0) for t in trades), reverse=True)
    total = sum(pnl)
    out["top2_share"] = round(sum(pnl[:2]) / total, 2) if total > 0 else None
    stake = s.get("stake_amount") if isinstance(s.get("stake_amount"), (int, float)) else None
    out["profit_on_stake"] = round(s.get("profit_total_abs", 0) / stake, 4) if stake else None
    return out


def pct(v, digits=1):
    return f"{v * 100:+.{digits}f}%" if isinstance(v, (int, float)) else "—"


def to_markdown(res: dict) -> str:
    lines = ["## Experiment comparison", "",
             "| Variant | Period | Trades | Win % | Profit (wallet) | Profit (on stake) | BTC hold | Max DD | Profit factor |",
             "|---|---|---|---|---|---|---|---|---|"]
    for v, periods in res["results"].items():
        for p, m in periods.items():
            if "error" in m:
                lines.append(f"| {v} | {p} | error | | | | | | |")
                continue
            pf = m.get("profit_factor")
            pf_s = f"{pf:.2f}" if isinstance(pf, (int, float)) else "—"
            lines.append(
                f"| {v} | {p} | {m['total_trades']} | {(m['winrate'] or 0) * 100:.0f}% | {pct(m['profit_total'], 2)} | "
                f"{pct(m['profit_on_stake'])} | {pct(m['market_change'])} | {(m['max_drawdown_account'] or 0) * 100:.1f}% | "
                f"{pf_s} |")
    lines += ["", "### Totals across all periods", "", "| Variant | Trades | Sum of profit (on stake) | Worst period | Losing periods |", "|---|---|---|---|---|"]
    for v, t in res["totals"].items():
        lines.append(f"| {v} | {t['trades']} | {pct(t['sum_profit_on_stake'])} | {pct(t['worst_period'])} | {t['losing_periods']} / {t['periods']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-c", "--config", default="config.sample.json")
    ap.add_argument("--file", default="experiments.json")
    ap.add_argument("--out-json", default="compare.json")
    ap.add_argument("--out-md", default="compare.md")
    args = ap.parse_args()

    spec = json.loads(Path(args.file).read_text())
    backup = None
    if PARAMS_FILE.exists():
        backup = PARAMS_FILE.with_suffix(".json.bak")
        shutil.copy(PARAMS_FILE, backup)
    results: dict = {}
    try:
        for vname, params in spec["variants"].items():
            results[vname] = {}
            for pname, tr in spec["periods"].items():
                print(f"Backtesting {vname} on {pname} ({tr}) ...", flush=True)
                results[vname][pname] = run_one(args.config, tr, params)
    finally:
        PARAMS_FILE.unlink(missing_ok=True)
        if backup:
            shutil.move(backup, PARAMS_FILE)

    totals = {}
    for v, periods in results.items():
        ok = [m for m in periods.values() if "error" not in m]
        ps = [m.get("profit_on_stake") or 0 for m in ok]
        totals[v] = {"trades": sum(m.get("total_trades") or 0 for m in ok), "sum_profit_on_stake": sum(ps),
                     "worst_period": min(ps) if ps else None, "losing_periods": sum(p < 0 for p in ps), "periods": len(ok)}

    res = {"generated_at": datetime.now(timezone.utc).isoformat(), "variants": spec["variants"],
           "periods": spec["periods"], "results": results, "totals": totals}
    Path(args.out_json).write_text(json.dumps(res, indent=1, default=str))
    md = to_markdown(res)
    Path(args.out_md).write_text(md)
    print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
