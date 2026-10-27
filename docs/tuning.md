# Tuning SelfBot

Change **one** thing at a time, re-run the backtest, compare. Claude's review
(`selfbot/claude_review.py`) applies the same rubric automatically.

## First-pass targets (daily BTC/USDT)

| Metric | Target |
|---|---|
| Total profit | positive; compare with BTC buy-and-hold ("Market change") |
| Max drawdown | < 20–25% |
| Profit factor | > 1.3–1.6 |
| Win rate | ~45–60% (lower is OK if winners are much bigger than losers) |
| Trades / year | ~8–30; fewer is too little evidence |
| Concentration | profit shouldn't come from 1–2 lucky trades |

## Order and ranges

1. **EMA** `ema_short` 5–15, `ema_long` 20–50 (8–10/20–30 = faster; 10–12/30–50 = more selective)
2. **RSI** `rsi_buy_max` 50–70, `rsi_sell_min` 55–75
3. **ATR stop** `atr_multiplier` 2.0–4.0 (higher = fewer stop-outs, bigger single losses)
4. **ROI** `minimal_roi` in the strategy (currently wide on purpose so trends can run)
5. **Exposure** `max_open_trades`, `stake_amount` in the config

## Symptom → change

| Symptom | Try |
|---|---|
| Good profit, high drawdown | raise `atr_multiplier`, lower stake, stricter entry |
| Very few trades | narrower EMA gap, higher `rsi_buy_max` |
| Too many trades / whipsaw | wider EMA gap, lower `rsi_buy_max` |
| Many small stop-outs | raise `atr_multiplier` |
| High win rate, tiny wins | exits too early: raise `rsi_sell_min` |

## Manual override of a parameter

Create `user_data/strategies/FreqtradeDailyHybridStrategy.json`:

```json
{"strategy_name": "FreqtradeDailyHybridStrategy",
 "params": {"buy": {"ema_short": 10, "ema_long": 30, "rsi_buy_max": 65},
            "sell": {"rsi_sell_min": 70, "atr_multiplier": 3.0}}}
```

## Automated search (after the manual baseline)

```bash
freqtrade hyperopt -c config.sample.json --spaces buy --hyperopt-loss SharpeHyperOptLossDaily \
  --timerange 20230101-20241231 -e 200
```

Then **test the winner on a different period** — hyperopt on daily data overfits easily.
