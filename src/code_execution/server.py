"""Local code_execution drop-in: Python in a separate rlimited process (CPU, memory, no file writes); run the container with network disabled."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
from typing import Any

from tool_http import serve

TOOL = "code_execution"
SCHEMA = {
    "type": "function",
    "name": "code_execution",
    "description": "Execute a short Python snippet in a local restricted sandbox (no network, no filesystem writes). Use for calculation, parsing, and transforms.",
    "parameters": {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python 3 source to execute"},
            "timeout_sec": {"type": "integer", "description": "Hard wall/CPU timeout in seconds (1..10)", "default": 5},
        },
        "required": ["code"],
    },
}

_CHILD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_child.py")
MAX_TIMEOUT_SEC = int(os.environ.get("CODE_EXEC_MAX_TIMEOUT", "10"))
MEM_LIMIT_MB = int(os.environ.get("CODE_EXEC_MEM_MB", "256"))
NPROC_LIMIT = int(os.environ.get("CODE_EXEC_NPROC", "64"))


def _limits(cpu_sec: int) -> None:  # runs in the child before exec
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (cpu_sec, cpu_sec))
    mem = MEM_LIMIT_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (mem, mem))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_NPROC, (NPROC_LIMIT, NPROC_LIMIT))
    os.setsid()


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    if proc.poll() is None:
        proc.kill()
    proc.wait()


def run(arguments: dict[str, Any]) -> dict[str, Any]:
    code = arguments.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code is required")
    if len(code) > 40_000:
        raise ValueError("code too large")
    try:
        timeout = int(arguments.get("timeout_sec", 5))
    except (TypeError, ValueError):
        timeout = 5
    timeout = max(1, min(timeout, MAX_TIMEOUT_SEC))
    with tempfile.TemporaryDirectory(prefix="sbx-") as cwd:
        proc = subprocess.Popen(  # noqa: S603
            [sys.executable, "-I", "-S", _CHILD],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            env={"PYTHONIOENCODING": "utf-8", "PATH": "/usr/bin:/bin"},
            preexec_fn=lambda: _limits(timeout),  # noqa: PLW1509
        )
        try:
            stdout, stderr = proc.communicate(code, timeout=timeout + 1)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            return {"stdout": "", "stderr": "", "ok": False, "error": f"timeout after {timeout}s"}
        finally:
            _kill_group(proc)  # reap any stray descendants in the session
    if proc.returncode != 0:
        if proc.returncode in (-9, -24):  # SIGKILL / SIGXCPU
            err = f"resource limit exceeded (cpu {timeout}s / mem {MEM_LIMIT_MB}MB)"
        else:
            err = f"sandbox exited with code {proc.returncode}"
        return {"stdout": "", "stderr": stderr[-2000:], "ok": False, "error": err}
    try:
        return json.loads(stdout)
    except json.JSONDecodeError:
        return {"stdout": "", "stderr": stderr[-2000:], "ok": False, "error": "sandbox produced invalid output"}


def main() -> None:
    serve(TOOL, SCHEMA, run)


if __name__ == "__main__":
    main()
