#!/usr/bin/env bash
set -euo pipefail
# Paper-trade SelfBot with fake money (dry_run) and the Claude gate.
#   CLAUDE_GATE=advisory ./dryrun.sh   # Claude comments on each entry, never blocks (default)
#   CLAUDE_GATE=enforce  ./dryrun.sh   # Claude can veto entries
#   CLAUDE_GATE=off      ./dryrun.sh   # pure mechanical strategy
# Claude decisions are logged to user_data/logs/claude_gate.jsonl
cd "$(dirname "$0")"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
CONFIG_FILE="${CONFIG_FILE:-config.sample.json}"

if [ "$(python3 -c "import json;print(json.load(open('$CONFIG_FILE'))['dry_run'])")" != "True" ]; then
  echo "Refusing to start: $CONFIG_FILE has dry_run=false. This script is for paper trading only."
  exit 1
fi
export CLAUDE_GATE="${CLAUDE_GATE:-advisory}"
echo "Starting SelfBot in DRY RUN (Claude gate: $CLAUDE_GATE). Ctrl+C to stop."
exec freqtrade trade -c "$CONFIG_FILE" --logfile user_data/logs/selfbot.log
