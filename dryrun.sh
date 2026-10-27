#!/usr/bin/env bash
set -euo pipefail
# Paper-trade SelfBot with fake money (dry_run), with the dashboards switched on.
#   ./dryrun.sh                         # AI gate starts in "advisory" (comments, never blocks)
#   CLAUDE_GATE=enforce ./dryrun.sh     # AI gate starts able to veto entries
#   CLAUDE_GATE=off     ./dryrun.sh     # start with the AI gate off
# The gate mode can be changed live from the SelfBot panel; decisions are logged to
# user_data/logs/claude_gate.jsonl
#
# Opens two local web pages (only reachable from this computer):
#   SelfBot panel  http://127.0.0.1:8081  - what the bot is doing + controls + AI decisions
#   FreqUI         http://127.0.0.1:8080  - Freqtrade's full dashboard (charts, trades)
cd "$(dirname "$0")"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
CONFIG_FILE="${CONFIG_FILE:-config.sample.json}"
PRIVATE_CONFIG="user_data/config.private.json"

if [ "$(python3 -c "import json;print(json.load(open('$CONFIG_FILE'))['dry_run'])")" != "True" ]; then
  echo "Refusing to start: $CONFIG_FILE has dry_run=false. This script is for paper trading only."
  exit 1
fi
export CLAUDE_GATE="${CLAUDE_GATE:-advisory}"
mkdir -p user_data/logs
python3 -m selfbot.private_config

python3 -m selfbot.panel --config "$CONFIG_FILE" --private-config "$PRIVATE_CONFIG" &
PANEL_PID=$!
trap 'kill $PANEL_PID 2>/dev/null || true' EXIT

echo "Starting SelfBot in DRY RUN (AI gate: $CLAUDE_GATE). Ctrl+C to stop."
freqtrade trade -c "$CONFIG_FILE" -c "$PRIVATE_CONFIG" --logfile user_data/logs/selfbot.log
