# Backtesting for SelfBot

This is the safe first step in the SelfBot lifecycle: validate the daily strategy with historical data before enabling live trading.

What you need
- Freqtrade installed locally: https://www.freqtrade.io/en/stable/installation/
- Crypto data available to Freqtrade for your exchange
- The strategy file present in `user_data/strategies/FreqtradeDailyHybridStrategy.py`

Important
- Keep BOT_MODE=dry_run until you are satisfied with the backtest and paper-trading results.
- Start with BTC/USDT before adding more pairs.
- Use a daily timeframe and a limited timerange for early testing.

Recommended first run
```bash
./backtest.sh 20240101 20241231
```

Small test run
```bash
./backtest.sh 20240601 20240630
```

Direct freqtrade command
```bash
freqtrade backtesting \
  --strategy FreqtradeDailyHybridStrategy \
  --config config.sample.json \
  --timerange 20240101-20241231
```

Notes
- If the repo is used as-is, make sure the strategy file is copied into the Freqtrade project under `user_data/strategies/`.
- Use stable, liquid pairs like BTC/USDT before broadening the universe.
- After a successful backtest, run the bot in dry-run mode and monitor results before switching to live.

Typical tuning order
1. EMA short/long settings
2. RSI thresholds
3. ATR stop multiplier
4. ROI and drawdown constraints

Recommended first live scope
- 1 primary pair only: BTC/USDT
- 1–2 open trades max
- daily loss ceiling of 3–5%
- no live execution until the dry-run period is stable
