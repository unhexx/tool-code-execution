import json
import os
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import tool_http


def _start(monkeypatch, invoke):
    monkeypatch.setenv("TOOL_TOKEN", "s3cret-test")
    srv = ThreadingHTTPServer(("127.0.0.1", 0), tool_http.make_handler("t", {"name": "t"}, invoke))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def _post(url, token, body):
    req = urllib.request.Request(url + "/v1/invoke", data=json.dumps(body).encode(), method="POST")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_refuses_default_token(monkeypatch):
    monkeypatch.setenv("TOOL_TOKEN", "local")
    monkeypatch.delenv("TOOL_ALLOW_INSECURE", raising=False)
    with pytest.raises(SystemExit):
        tool_http.require_token()


def test_auth_and_no_traceback(monkeypatch):
    def boom(_):
        raise RuntimeError("secret internals")
    srv, url = _start(monkeypatch, boom)
    try:
        assert _post(url, None, {})[0] == 401
        assert _post(url, "wrong", {})[0] == 401
        code, body = _post(url, "s3cret-test", {"arguments": {}})
        assert code == 500
        assert "trace" not in body and "secret internals" not in json.dumps(body)
        assert body["error"]["type"] == "internal"
    finally:
        srv.shutdown()
