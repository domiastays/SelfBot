#!/usr/bin/env bash
set -euo pipefail
# One-time local setup: creates .venv with Freqtrade + Anthropic SDK.
#   ./setup.sh && source .venv/bin/activate
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
mkdir -p user_data/data user_data/logs user_data/backtest_results
echo
echo "Done. Next:"
echo "  source .venv/bin/activate"
echo "  export GITHUB_TOKEN=github_pat_...    # optional & free (token with Models: read) - enables AI review + gate"
echo "  ./backtest.sh"
