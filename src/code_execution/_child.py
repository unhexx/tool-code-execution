"""Sandbox child: reads code from stdin, runs it with restricted builtins, prints a JSON result.

Started by server.run() as `python -I -S _child.py` under rlimits; stdlib only, no package imports.
"""
import ast
import io
import json
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout

_ALLOWED_IMPORT_ROOTS = {
    "math", "statistics", "json", "re", "datetime", "collections",
    "itertools", "functools", "decimal", "fractions", "string",
    "textwrap", "unicodedata", "hashlib", "base64", "csv",
    "copy", "operator", "typing", "dataclasses", "enum", "numbers",
}
_BLOCKED_NAMES = {"__import__", "eval", "exec", "compile", "open", "input", "breakpoint",
                  "globals", "locals", "vars", "getattr", "setattr", "delattr"}


class _Guard(ast.NodeVisitor):
    def visit_Import(self, node):  # noqa: N802
        for alias in node.names:
            if alias.name.split(".", 1)[0] not in _ALLOWED_IMPORT_ROOTS:
                raise ValueError(f"import blocked: {alias.name}")

    def visit_ImportFrom(self, node):  # noqa: N802
        if node.level or (node.module or "").split(".", 1)[0] not in _ALLOWED_IMPORT_ROOTS:
            raise ValueError(f"import blocked: {node.module}")

    def visit_Attribute(self, node):  # noqa: N802
        if node.attr.startswith("_"):
            raise ValueError("private/dunder attribute access blocked")
        self.generic_visit(node)

    def visit_Name(self, node):  # noqa: N802
        if node.id in _BLOCKED_NAMES or node.id.startswith("__"):
            raise ValueError(f"name blocked: {node.id}")


def _safe_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
    if level or name.split(".", 1)[0] not in _ALLOWED_IMPORT_ROOTS:
        raise ImportError(f"import blocked: {name}")
    return __import__(name, globals, locals, fromlist, level)


def main() -> None:
    code = sys.stdin.read()
    out, err = io.StringIO(), io.StringIO()
    try:
        tree = ast.parse(code, mode="exec")
        _Guard().visit(tree)
    except (SyntaxError, ValueError) as exc:
        print(json.dumps({"stdout": "", "stderr": str(exc), "ok": False, "error": str(exc)}))
        return
    b = __builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)
    names = ["abs", "all", "any", "bool", "dict", "divmod", "enumerate", "filter", "float",
             "format", "frozenset", "int", "isinstance", "iter", "len", "list", "map", "max",
             "min", "next", "pow", "print", "range", "repr", "reversed", "round", "set",
             "slice", "sorted", "str", "sum", "tuple", "zip", "Exception", "ValueError",
             "TypeError", "KeyError", "IndexError", "ZeroDivisionError", "StopIteration"]
    safe = {n: b[n] for n in names}
    safe["__import__"] = _safe_import
    glb = {"__builtins__": safe, "__name__": "__sandbox__"}
    try:
        with redirect_stdout(out), redirect_stderr(err):
            exec(compile(tree, "<sandbox>", "exec"), glb, glb)  # noqa: S102
        res = {"stdout": out.getvalue()[-8000:], "stderr": err.getvalue()[-2000:], "ok": True}
    except BaseException as exc:  # noqa: BLE001
        tb = traceback.format_exception_only(type(exc), exc)
        res = {"stdout": out.getvalue()[-2000:], "stderr": (err.getvalue() + "".join(tb))[-4000:],
               "ok": False, "error": f"{type(exc).__name__}: {exc}"}
    sys.__stdout__.write(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
