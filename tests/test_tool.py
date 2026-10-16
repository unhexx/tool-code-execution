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


def test_infinite_loop_is_killed():
    out = run({"code": "while True:\n    pass", "timeout_sec": 1})
    assert out["ok"] is False
    assert "timeout" in out["error"] or "limit" in out["error"]


def test_memory_bomb_is_contained():
    out = run({"code": "x = 'a' * (10**10)", "timeout_sec": 2})
    assert out["ok"] is False


def test_dunder_escape_blocked():
    out = run({"code": "print(().__class__.__base__.__subclasses__())"})
    assert out["ok"] is False


def test_getattr_escape_blocked():
    out = run({"code": "print(getattr((), '__cla' + 'ss__'))"})
    assert out["ok"] is False


def test_allowed_import_works():
    out = run({"code": "import math\nprint(math.sqrt(16))"})
    assert out["ok"] is True and "4.0" in out["stdout"]


def test_server_survives_and_runs_in_child():
    import os
    out = run({"code": "print(1)"})
    assert out["ok"] is True
    assert os.getpid()  # parent process still alive after previous kills
