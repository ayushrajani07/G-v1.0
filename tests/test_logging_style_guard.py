import ast
import os
from pathlib import Path

LEVELS = {"debug", "info", "warning", "error", "critical"}


def _attr_chain_name(node: ast.AST) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _is_logger_call(call: ast.Call) -> bool:
    # Match logger.<level>(...)
    if not isinstance(call.func, ast.Attribute):
        return False
    method = call.func.attr
    if method not in LEVELS:
        return False
    base = _attr_chain_name(call.func.value)
    # Accept common logger bases: logger, self.logger, _logger, log (rare)
    return base.endswith("logger") or base in {"logger", "log", "_logger"}


def _first_arg_is_fstring(call: ast.Call) -> bool:
    if not call.args:
        return False
    first = call.args[0]
    # f"..." compiles to ast.JoinedStr
    if isinstance(first, ast.JoinedStr):
        return True
    # Also catch concatenations starting with an f-string
    if isinstance(first, ast.BinOp) and isinstance(first.left, ast.JoinedStr):
        return True
    return False


def _iter_python_files(root: Path):
    for p in root.rglob("*.py"):
        # Skip tests and archived/external code explicitly
        rel = p.as_posix().lower()
        if "/tests/" in rel or rel.endswith("/tests"):
            continue
        if "/external/" in rel or "/g6_.archived/" in rel:
            continue
        yield p


def test_no_eager_logging_fstrings_in_src():
    repo_root = Path(__file__).resolve().parents[1]
    src_dir = repo_root / "src"
    assert src_dir.exists(), f"src directory not found at {src_dir}"

    violations = []
    for py_file in _iter_python_files(src_dir):
        try:
            text = py_file.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(py_file))
        except Exception:
            # If a file can't be parsed here, don't fail this style test
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_logger_call(node) and _first_arg_is_fstring(node):
                # Capture a short snippet (the line where the call starts)
                try:
                    line = text.splitlines()[node.lineno - 1].strip()
                except Exception:
                    line = "<unavailable>"
                violations.append((str(py_file.relative_to(repo_root)), node.lineno, line))

    if violations:
        details = "\n".join(f" - {path}:{lineno}: {line}" for path, lineno, line in violations[:25])
        more = "" if len(violations) <= 25 else f"\n... and {len(violations)-25} more"
        raise AssertionError(
            "Eager f-string logging detected. Use lazy logging like logger.info('msg %s', arg).\n" + details + more
        )
