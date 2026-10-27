#!/usr/bin/env bash
set -euo pipefail

# SelfBot backtest runner (local)
# Usage:
#   ./backtest.sh                      # 2024 full year
#   ./backtest.sh 20240601 20240630    # custom range
# Env overrides: CONFIG_FILE, STRATEGY_NAME
#
# Afterwards it writes a review: AI if GEMINI_API_KEY or ANTHROPIC_API_KEY is set, rule-based otherwise.

cd "$(dirname "$0")"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"

START_DATE="${1:-20240101}"
END_DATE="${2:-20241231}"
CONFIG_FILE="${CONFIG_FILE:-config.sample.json}"
STRATEGY_NAME="${STRATEGY_NAME:-FreqtradeDailyHybridStrategy}"

if ! command -v freqtrade >/dev/null 2>&1; then
  echo "freqtrade is not installed or not in PATH. Run ./setup.sh first (or activate .venv)."
  exit 1
fi
if [ ! -f "$CONFIG_FILE" ]; then
  echo "Config file not found: $CONFIG_FILE"
  exit 1
fi

# Download candles (plus ~300 warm-up days) if we don't have them yet. Re-running is cheap.
DL_START=$(python3 -c "import datetime as d;print((d.datetime.strptime('$START_DATE','%Y%m%d')-d.timedelta(days=300)).strftime('%Y%m%d'))")
echo "Downloading/refreshing daily candles from $DL_START ..."
freqtrade download-data -c "$CONFIG_FILE" --timerange "${DL_START}-" --timeframes 1d

echo "Running backtest for $STRATEGY_NAME from $START_DATE to $END_DATE"
freqtrade backtesting \
  --strategy "$STRATEGY_NAME" \
  --config "$CONFIG_FILE" \
  --timerange "$START_DATE-$END_DATE" \
  --export trades \
  --breakdown month

echo
python3 -m selfbot.claude_review --out claude_review.md
