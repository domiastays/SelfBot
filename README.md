# SelfBot

Autonomous daily BTC/USDT trading bot: a Freqtrade trend-following strategy with an AI
backtest analyst and (optionally) a second-opinion gate on every trade.

**No paid API key needed.** The AI parts use Google Gemini's free tier (a free key from
[Google AI Studio](https://aistudio.google.com/apikey), no card). Without any key the bot
still writes a rule-based verdict. Add an `ANTHROPIC_API_KEY` only if you want Claude instead.

**Status: backtest / paper-trading only.** `config.sample.json` is locked to `dry_run: true`.

## How the AI is wired in

Provider is picked automatically (`selfbot/llm.py`): **Claude** if `ANTHROPIC_API_KEY` is set →
otherwise **Gemini** (free) if `GEMINI_API_KEY` is set → otherwise a built-in rule-based verdict.

| Where | What the AI does | File |
|---|---|---|
| GitHub Actions / `./backtest.sh` | Reads the backtest stats and returns a verdict + the single next tuning experiment | `selfbot/claude_review.py` |
| Dry-run / live bot | Before each entry, sees the last 30 daily candles + indicators and approves or vetoes | `selfbot/claude_gate.py` |

The AI is **never called during backtests or hyperopt** (fast, free, reproducible).
Gate modes (`CLAUDE_GATE`): `advisory` (default — logs only), `enforce` (can veto; errors block the trade), `off`.

## Quick start — on GitHub (no install)

1. Get a free key at https://aistudio.google.com/apikey (Google account, no card).
2. Repo **Settings → Secrets and variables → Actions → New repository secret**:
   `GEMINI_API_KEY` = that key.
3. **Actions → Backtest + AI review → Run workflow** (pick timerange).
4. Open the run: the summary page shows the Freqtrade metrics and the written review
   (the last line says which model wrote it).

Skip steps 1-2 and you still get a rule-based verdict. Optional: a repo variable `GEMINI_MODEL`
picks a different Gemini model; a secret `ANTHROPIC_API_KEY` switches to Claude.

It also runs automatically whenever the strategy, config or `selfbot/` code changes.

## Quick start — on your computer

```bash
git clone https://github.com/domiastays/SelfBot.git && cd SelfBot
./setup.sh && source .venv/bin/activate
export GEMINI_API_KEY=...                # optional & free, from aistudio.google.com
./backtest.sh 20240101 20241231          # downloads data, backtests, AI review
./dryrun.sh                              # paper trading with the AI gate
```

## Strategy (`user_data/strategies/FreqtradeDailyHybridStrategy.py`)

- **Entry:** close > 100-day SMA (market-health gate), EMA9 > EMA21, fresh EMA cross-up or
  price reclaiming EMA9, RSI(14) < 65
- **Exit:** EMA9 crosses below EMA21, or RSI was > 70 and price falls back under EMA9
- **Risk:** ATR(14) × 3.0 trailing stop, hard stop −10%, 1 open trade, 100 USDT stake,
  cooldown / stoploss-guard / 20% max-drawdown protections

All parameters are hyperopt-ready — see [docs/tuning.md](docs/tuning.md).

## Road to live (don't skip steps)

1. Backtest 2024 → tune one parameter at a time (docs/tuning.md)
2. Validate on a period you did **not** tune on (e.g. 2023, or 2025)
3. Dry-run for at least 2–4 weeks with `CLAUDE_GATE=advisory`, compare Claude's calls with outcomes
4. Only then copy to a git-ignored `config.live.json`, add trade-only (no withdrawal) API keys, small stake
