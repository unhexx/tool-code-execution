"""Minimal JSON HTTP surface shared by local tools (stdlib only)."""
from __future__ import annotations

import json
import os
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import urlparse


def _token() -> str:
    return os.environ.get("TOOL_TOKEN", "local")


def check_auth(header: str | None) -> None:
    expected = _token()
    if not expected:
        return
    if not header or not header.startswith("Bearer "):
        raise PermissionError("missing bearer token")
    if header.split(" ", 1)[1].strip() != expected:
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
                self._send(401, {"ok": False, "error": str(exc)})
            except Exception as exc:  # noqa: BLE001
                self._send(400, {"ok": False, "error": str(exc), "trace": traceback.format_exc()[-1500:]})

    return Handler


def serve(name: str, schema: dict[str, Any], invoke: Callable[[dict[str, Any]], Any]) -> None:
    host = os.environ.get("TOOL_HOST", "127.0.0.1")
    port = int(os.environ.get("TOOL_PORT", "8090"))
    httpd = ThreadingHTTPServer((host, port), make_handler(name, schema, invoke))
    print(f"{name} listening on http://{host}:{port}", flush=True)
    httpd.serve_forever()
