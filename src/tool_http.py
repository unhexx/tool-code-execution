"""Minimal JSON HTTP surface shared by local tools (stdlib only)."""
from __future__ import annotations

import hmac
import json
import os
import sys
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import urlparse


_INSECURE_TOKENS = {"", "local", "changeme"}


def _token() -> str:
    return os.environ.get("TOOL_TOKEN", "")


def require_token() -> None:
    """Refuse to start with a missing or well-known token unless explicitly allowed for dev."""
    if _token() in _INSECURE_TOKENS and os.environ.get("TOOL_ALLOW_INSECURE") != "1":
        raise SystemExit("TOOL_TOKEN is unset or insecure; set a random token (or TOOL_ALLOW_INSECURE=1 for local dev)")


def check_auth(header: str | None) -> None:
    expected = _token()
    if not expected and os.environ.get("TOOL_ALLOW_INSECURE") == "1":
        return
    if not header or not header.startswith("Bearer "):
        raise PermissionError("missing bearer token")
    if not expected or not hmac.compare_digest(header.split(" ", 1)[1].strip(), expected):
        raise PermissionError("invalid bearer token")


def make_handler(name: str, schema: dict[str, Any], invoke: Callable[[dict[str, Any]], Any]):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
            return

        def _send(self, code: int, payload: Any) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path.rstrip("/") or "/"
            if path in ("/healthz", "/health"):
                self._send(200, {"status": "ok", "tool": name, "mode": "local"})
                return
            if path == "/schema":
                self._send(200, schema)
                return
            self._send(404, {"error": "not_found", "path": path})

        def do_POST(self) -> None:  # noqa: N802
            path = urlparse(self.path).path.rstrip("/") or "/"
            if path not in ("/v1/invoke", "/invoke"):
                self._send(404, {"error": "not_found", "path": path})
                return
            try:
                check_auth(self.headers.get("Authorization"))
                length = int(self.headers.get("Content-Length") or "0")
                if length > 2_000_000:
                    raise ValueError("payload too large")
                body = self.rfile.read(length) if length else b"{}"
                data = json.loads(body.decode("utf-8") or "{}")
                arguments = data.get("arguments", data)
                if not isinstance(arguments, dict):
                    raise ValueError("arguments must be an object")
                result = invoke(arguments)
                self._send(200, {"ok": True, "tool": name, "result": result})
            except PermissionError as exc:
                self._send(401, {"ok": False, "error": {"type": "unauthorized", "message": str(exc)}})
            except (ValueError, json.JSONDecodeError) as exc:
                self._send(400, {"ok": False, "error": {"type": "bad_request", "message": str(exc)}})
            except Exception:  # noqa: BLE001
                print(traceback.format_exc(), file=sys.stderr, flush=True)  # trace stays server-side
                self._send(500, {"ok": False, "error": {"type": "internal", "message": "internal tool error"}})

    return Handler


def serve(name: str, schema: dict[str, Any], invoke: Callable[[dict[str, Any]], Any]) -> None:
    require_token()
    host = os.environ.get("TOOL_HOST", "127.0.0.1")
    port = int(os.environ.get("TOOL_PORT", "8090"))
    httpd = ThreadingHTTPServer((host, port), make_handler(name, schema, invoke))
    print(f"{name} listening on http://{host}:{port}", flush=True)
    httpd.serve_forever()
