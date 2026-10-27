"""
SelfBot control panel: one local page that shows what the bot is doing and lets you step in.

    python -m selfbot.panel                    # http://127.0.0.1:8081
    (./dryrun.sh starts it for you)

It talks to the running bot through Freqtrade's REST API (login read from
user_data/config.private.json) and to the AI gate through user_data/selfbot_control.json.
Standard library only. It listens on 127.0.0.1, so only this computer can open it,
and every action needs a token that is only embedded in the page it serves.
"""

from __future__ import annotations

import argparse
import base64
import json
import secrets
import sys
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from selfbot import claude_gate

TOKEN = secrets.token_urlsafe(24)
ARGS: argparse.Namespace


# ----------------------------------------------------------------- Freqtrade API client
def _ft_settings() -> tuple[str, str, str]:
    api = {}
    for path in (ARGS.config, ARGS.private_config):
        try:
            api.update(json.loads(Path(path).read_text()).get("api_server", {}))
        except Exception:
            pass
    base = f"http://127.0.0.1:{api.get('listen_port', 8080)}/api/v1"
    return base, api.get("username", ""), api.get("password", "")


def ft(method: str, path: str, body: dict | None = None, timeout: int = 8):
    base, user, pw = _ft_settings()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method, headers={
        "Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode(),
        "Content-Type": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


def _safe(path: str):
    try:
        return ft("GET", path), None
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code}"
    except Exception as exc:
        return None, str(exc)


def gate_decisions(limit: int = 40) -> list[dict]:
    path = Path(ARGS.gate_log)
    if not path.exists():
        return []
    rows = []
    with path.open() as fh:
        for line in deque(fh, maxlen=limit):
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    return rows[::-1]


def state() -> dict:
    from selfbot import llm

    ping, err = _safe("/ping")
    out = {"online": ping is not None, "error": err}
    if ping is not None:
        for key, path in (("config", "/show_config"), ("open", "/status"), ("profit", "/profit"),
                          ("balance", "/balance"), ("trades", "/trades?limit=30"), ("logs", "/logs?limit=80"),
                          ("whitelist", "/whitelist")):
            out[key], _ = _safe(path)
    p = llm.provider()
    out["gate"] = {
        "mode": claude_gate.current_mode(),
        "provider": p,
        "model": llm.model_name(p) if p else None,
        "decisions": gate_decisions(),
    }
    return out


def act(payload: dict) -> dict:
    action = payload.get("action")
    if action == "gate":
        mode = payload.get("mode")
        if mode not in claude_gate.MODES:
            raise ValueError(f"unknown mode {mode!r}")
        claude_gate.write_control(gate_mode=mode)
        return {"message": f"AI gate set to {mode}. Applies from the next entry signal."}
    if action == "start":
        return ft("POST", "/start")
    if action == "stop":
        return ft("POST", "/stop")
    if action == "pause":
        try:
            return ft("POST", "/stopentry")
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
            return ft("POST", "/stopbuy")  # older Freqtrade versions
    if action == "resume":
        return ft("POST", "/reload_config")
    if action == "close":
        return ft("POST", "/forceexit", {"tradeid": str(int(payload["trade_id"])), "ordertype": "market"})
    if action == "buy":
        return ft("POST", "/forceenter", {"pair": str(payload["pair"]), "side": "long"})
    raise ValueError(f"unknown action {action!r}")


# ------------------------------------------------------------------------ HTTP server
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the terminal quiet
        pass

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        return host in ("127.0.0.1", "localhost")

    def _send(self, code: int, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, {"error": "forbidden"})
        if self.path == "/":
            html = PAGE.replace("__TOKEN__", TOKEN).encode()
            return self._send(200, html, "text/html; charset=utf-8")
        if self.path == "/api/state":
            return self._send(200, state())
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self._host_ok() or self.headers.get("X-Panel-Token") != TOKEN:
            return self._send(403, {"error": "forbidden"})
        if self.path != "/api/action":
            return self._send(404, {"error": "not found"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"{}")
            self._send(200, {"ok": True, "result": act(payload)})
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:300]
            self._send(502, {"ok": False, "error": f"Bot answered HTTP {exc.code}: {detail}"})
        except urllib.error.URLError:
            self._send(502, {"ok": False, "error": "The bot is not running (could not reach its API)."})
        except Exception as exc:
            self._send(400, {"ok": False, "error": str(exc)})


def main() -> int:
    global ARGS
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8081)
    ap.add_argument("--config", default="config.sample.json")
    ap.add_argument("--private-config", default="user_data/config.private.json")
    ap.add_argument("--gate-log", default="user_data/logs/claude_gate.jsonl")
    ARGS = ap.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", ARGS.port), Handler)
    print(f"SelfBot panel: http://127.0.0.1:{ARGS.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


PAGE = (Path(__file__).with_name("panel.html")).read_text()

if __name__ == "__main__":
    sys.exit(main())
