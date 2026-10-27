"""
Create user_data/config.private.json (git-ignored) with the settings that turn on
Freqtrade's web API + FreqUI dashboard, using a random password made on your machine.

    python -m selfbot.private_config          # create if missing, print login
    python -m selfbot.private_config --show   # just print the login

The file is layered on top of config.sample.json:
    freqtrade trade -c config.sample.json -c user_data/config.private.json
"""

from __future__ import annotations

import json
import secrets
import sys
from pathlib import Path

PATH = Path("user_data/config.private.json")


def load() -> dict:
    return json.loads(PATH.read_text())


def ensure() -> dict:
    if PATH.exists():
        return load()
    cfg = {
        "api_server": {
            "enabled": True,
            "listen_ip_address": "127.0.0.1",
            "listen_port": 8080,
            "verbosity": "error",
            "enable_openapi": False,
            "jwt_secret_key": secrets.token_hex(32),
            "ws_token": secrets.token_urlsafe(24),
            "CORS_origins": [],
            "username": "selfbot",
            "password": secrets.token_urlsafe(12),
        },
        # Lets you open a trade by hand from FreqUI or the SelfBot panel.
        "force_entry_enable": True,
    }
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(cfg, indent=2))
    try:
        PATH.chmod(0o600)
    except OSError:
        pass
    return cfg


def main() -> int:
    created = not PATH.exists()
    cfg = ensure() if "--show" not in sys.argv or not PATH.exists() else load()
    api = cfg["api_server"]
    if created:
        print(f"Created {PATH} (private, not committed).")
    print(f"FreqUI:        http://127.0.0.1:{api['listen_port']}   (user: {api['username']}  password: {api['password']})")
    print("SelfBot panel: http://127.0.0.1:8081   (logs in to the bot for you)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
