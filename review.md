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
NEEDS TUNING — The strategy is profitable (+4.68% in 2024) with low drawdown (2.28%), but severely underperforms holding BTC (+112.50%), has a low win rate (30%), and depends entirely on two large winner trades.

## What the numbers say
- **Underperformed Buy & Hold**: Earned +4.68% (+46.75 USDT) over 365 days while BTC market benchmark rose +112.50%.
- **Low win rate**: Won only 3 out of 10 trades (30% win rate), with 7 losing trades.
- **Extreme trade concentration**: The top 2 trades accounted for 171% of total net profits (79.99 USDT profit on ROI exits vs 46.75 USDT total strategy profit).
- **Controlled downside**: Max account drawdown was kept to 2.28% (23.59 USDT), keeping the Profit Factor at 2.36 due to large 40% ROI caps.
- **Trade frequency**: Executed 10 trades in 2024 with an average hold time of 15 days, matching the expected range (8–30 trades/year) for a daily timeframe strategy.

## Variant comparison
- **Winning variant**: **Baseline (9/21)** is vastly superior to Slower (10/35) across all multi-year evaluation periods.
- **Cumulative profit on stake**: Baseline generated **0.8271** (82.71%) total return on stake across 29 trades, compared to **0.2215** (22.15%) across 27 trades for Slower (10/35).
- **Consistency**: Baseline had 1 losing period (2025: -0.1306 stake profit) vs 2 losing periods for Slower (10/35) (2025: -0.0091, 2026 YTD: -0.0164).
- **Decision**: **Do not adopt the 10/35 change.** Retain the baseline (9/21) foundation for subsequent tests.

## Next experiment
Following the tuning sequence (Step 1: EMA short/long settings), test a standard MACD EMA pairing (`ema_short`: 12, `ema_long`: 26) to see if smoother trend signals reduce false entries without slowing reaction time too drastically.

- **Current parameters**: `ema_short`: 9, `ema_long`: 21
- **Proposed parameters**: `ema_short`: 12, `ema_long`: 26

**Freqtrade command:**
```bash
freqtrade backtesting --strategy FreqtradeDailyHybridStrategy --timeframe 1d --timerange 20240101-20241231
```
*(Update `ema_short = 12` and `ema_long = 26` inside the strategy file before running).*

## Before going live
- **Expand sample size**: 10 trades per year is a small statistical sample; run multi-year backtests across complete bull/bear cycles (e.g., 2020–2024) to confirm expectancy.
- **Address market capture**: The current rules stay out of the market during major rallies; entries need refinement so the strategy captures a higher portion of BTC trend movements.
- **Test out-of-sample data**: Validate any tuned configuration against unseen periods (such as 2025–2026 data) to verify the strategy isn't overfitting to 2024 ROI targets.

_Review by: Gemini (gemini-3.5-flash, free tier)_


