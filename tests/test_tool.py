from code_execution.server import run


def test_arithmetic():
    out = run({"code": "print(2+40)\nresult=42"})
    assert out["ok"] is True
    assert "42" in out["stdout"]


def test_blocks_os():
    out = run({"code": "import os\nprint(os.listdir('/'))"})
    assert out["ok"] is False or "blocked" in out.get("error", "").lower()


def test_blocks_open_name():
    try:
        out = run({"code": "open('/etc/passwd')"})
        assert out["ok"] is False
    except ValueError as exc:
        assert "blocked" in str(exc)
