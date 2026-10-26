#!/usr/bin/env bash
set -euo pipefail

# Example backtest runner for SelfBot
# Usage:
#   ./backtest.sh 20240101 20241231
# or:
#   ./backtest.sh 20240601 20240630

START_DATE="${1:-20240101}"
END_DATE="${2:-20241231}"
CONFIG_FILE="${CONFIG_FILE:-config.sample.json}"
STRATEGY_NAME="${STRATEGY_NAME:-FreqtradeDailyHybridStrategy}"

if ! command -v freqtrade >/dev/null 2>&1; then
  echo "freqtrade is not installed or not in PATH."
  echo "Install it first: https://www.freqtrade.io/en/stable/installation/"
  exit 1
fi

if [ ! -f "$CONFIG_FILE" ]; then
  echo "Config file not found: $CONFIG_FILE"
  exit 1
fi

echo "Running backtest for strategy $STRATEGY_NAME from $START_DATE to $END_DATE"

freqtrade backtesting \
  --strategy "$STRATEGY_NAME" \
  --config "$CONFIG_FILE" \
  --timerange "$START_DATE-$END_DATE"
