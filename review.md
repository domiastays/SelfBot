# SelfBot backtest review

| Metric | Value |
|---|---|
| Period | 2024-01-01 00:00:00 → 2024-12-31 00:00:00 |
| Trades | 10 |
| Win rate | 30.00% |
| Total profit | 4.68% |
| BTC buy & hold (market change) | 112.50% |
| Max drawdown | 2.28% |
| Profit factor | 2.36 |
| Sharpe / Sortino | 0.14 / 1.08 |
| Best / worst trade | 40.0% / -8.12% |

## Verdict
NEEDS TUNING — While profitable (+4.68% in 2024) with tight risk management (2.28% max drawdown), the strategy drastically underperforms BTC buy & hold (+112.50%), produces few trades (10), and relies entirely on two large winners.

## What the numbers say
- **Vastly Underperformed Market:** Returned +4.68% ($46.75) in 2024 vs. BTC buy-and-hold gain of +112.50%.
- **Fragile Profit Distribution:** Top 2 trades generated $79.99 in ROI exits (171% of total net profits); the remaining 8 trades produced a net loss of -$33.24.
- **Low Win Rate & Low Frequency:** Achieved a 30.0% win rate across only 10 trades (3 wins, 7 losses), averaging 15 days per holding.
- **Solid Risk Control:** Max account drawdown was limited to 2.28% ($23.59), yielding a Profit Factor of 2.36 driven by the +40% ROI exits.

## Variant comparison
- **Winning Variant:** `baseline 9/21` is significantly better than `slower 10/35` across all tested periods.
- **Multi-Period Summary:**
  - `baseline 9/21`: +0.8271 total stake profit across 29 trades, 1 losing period (2025: -0.1306).
  - `slower 10/35`: +0.2215 total stake profit across 27 trades, 2 losing periods (2025: -0.0091, 2026 YTD: -0.0164).
- **Bull Market Capture:** Baseline delivered far superior gains in 2023 (+0.4364 vs +0.0933) and 2024 (+0.4675 vs +0.1537).
- **Decision:** **Do NOT adopt the 10/35 variant.** Retain `baseline 9/21` as the foundation for future testing.

## Next experiment
Slowing the EMAs (10/35) degraded performance, indicating the strategy needs earlier trend responsiveness rather than slower filtering. Following Tuning Step 1 (EMA parameters), test a faster short EMA by changing `ema_short` from 9 to 7 while holding `ema_long` at 21.

**Command:**
```bash
freqtrade backtesting --strategy FreqtradeDailyHybridStrategy --timerange 20240101-20241231 --timeframe 1d --override-param buy.ema_short=7
```
*(If single manual parameter adjustments continue to yield low trade volume, running `freqtrade hyperopt` restricted to the space `buy.ema_short` [5–15] and `buy.ema_long` [20–50] across 2023–2024 data is the best next step).*

## Before going live
- **Evaluate Multi-Year Stability:** Verify that parameter improvements hold across 2023–2026 multi-period runs, avoiding single-year overfitting.
- **Expand Asset Universe:** Test the logic on additional liquid pairs (e.g., ETH/USDT, SOL/USDT) to validate statistical significance beyond 10 daily BTC trades per year.
- **Reduce Single-Exit Dependence:** Refine trailing stops or profit-taking criteria so net profitability isn't dependent on hitting a +40% ROI ceiling twice a year.

_Review by: Gemini (gemini-3.5-flash, free tier)_


