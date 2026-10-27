#!/usr/bin/env bash
set -euo pipefail
# One-time local setup: creates .venv with Freqtrade + Anthropic SDK.
#   ./setup.sh && source .venv/bin/activate
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
mkdir -p user_data/data user_data/logs user_data/backtest_results
# Freqtrade's web dashboard (FreqUI) + a private login for it and the SelfBot panel
.venv/bin/freqtrade install-ui
.venv/bin/python -m selfbot.private_config
echo
echo "Done. Next:"
echo "  source .venv/bin/activate"
echo "  export GEMINI_API_KEY=...   # optional & free (aistudio.google.com) - enables AI review + gate"
echo "  ./backtest.sh          # test the strategy on past data"
echo "  ./dryrun.sh            # paper trade + open the SelfBot panel at http://127.0.0.1:8081"
