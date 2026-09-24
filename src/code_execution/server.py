"""Local code_execution drop-in: restricted Python eval, no network, no FS writes."""
from __future__ import annotations

import ast
import io
import os
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
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
            "timeout_sec": {"type": "integer", "description": "Soft timeout hint (seconds)", "default": 5},
        },
        "required": ["code"],
    },
}

_FORBIDDEN = {
    "os", "sys", "subprocess", "socket", "shutil", "pathlib", "ctypes",
    "multiprocessing", "threading", "signal", "importlib", "builtins",
    "posix", "nt", "fcntl", "pty", "resource", "http", "urllib", "requests",
    "webbrowser", "tempfile", "pickle", "marshal", "code", "codeop",
}

_ALLOWED_IMPORT_ROOTS = {
    "math", "statistics", "json", "re", "datetime", "collections",
    "itertools", "functools", "decimal", "fractions", "string",
    "textwrap", "unicodedata", "hashlib", "base64", "csv", "io",
    "copy", "operator", "typing", "dataclasses", "enum", "numbers",
}


class _Guard(ast.NodeVisitor):
    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
        for alias in node.names:
            root = alias.name.split(".", 1)[0]
            if root in _FORBIDDEN or root not in _ALLOWED_IMPORT_ROOTS:
                raise ValueError(f"import blocked: {alias.name}")

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        root = (node.module or "").split(".", 1)[0]
        if root in _FORBIDDEN or root not in _ALLOWED_IMPORT_ROOTS:
            raise ValueError(f"import blocked: {node.module}")

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if isinstance(node.attr, str) and node.attr.startswith("__"):
            raise ValueError("dunder attribute access blocked")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        if node.id in {"__import__", "eval", "exec", "compile", "open", "input", "breakpoint"}:
            raise ValueError(f"name blocked: {node.id}")


def run(arguments: dict[str, Any]) -> dict[str, Any]:
    code = arguments.get("code")
    if not isinstance(code, str) or not code.strip():
        raise ValueError("code is required")
    if len(code) > 40_000:
        raise ValueError("code too large")
    tree = ast.parse(code, mode="exec")
    try:
        _Guard().visit(tree)
    except ValueError as exc:
        return {"stdout": "", "stderr": str(exc), "ok": False, "error": str(exc)}
    compiled = compile(tree, "<sandbox>", "exec")
    stdout = io.StringIO()
    stderr = io.StringIO()
    glb: dict[str, Any] = {"__builtins__": {
        "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
        "enumerate": enumerate, "float": float, "int": int, "len": len,
        "list": list, "max": max, "min": min, "pow": pow, "print": print,
        "range": range, "repr": repr, "round": round, "set": set,
        "sorted": sorted, "str": str, "sum": sum, "tuple": tuple, "zip": zip,
    }}
    try:
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exec(compiled, glb, glb)  # noqa: S102
        return {
            "stdout": stdout.getvalue()[-8000:],
            "stderr": stderr.getvalue()[-2000:],
            "ok": True,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "stdout": stdout.getvalue()[-2000:],
            "stderr": (stderr.getvalue() + traceback.format_exc())[-4000:],
            "ok": False,
            "error": str(exc),
        }


def main() -> None:
    serve(TOOL, SCHEMA, run)


if __name__ == "__main__":
    main()
