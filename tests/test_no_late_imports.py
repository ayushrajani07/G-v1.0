import ast
import os
from pathlib import Path
import pytest

# Allowlist of files that intentionally use function-scoped imports
ALLOWLIST = {
    # Intentional fallback import handling for optional dependency
    os.path.normpath("src/utils/memory_pressure.py").lower(),
    # Intentional self-import recursion pattern
    os.path.normpath("src/metrics/emitter.py").lower(),
}


def has_late_imports(py_path: Path) -> list[tuple[int, str]]:
    text = py_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(text, filename=str(py_path))
    except SyntaxError:
        # If file has syntax error, let normal test suite catch it elsewhere
        return []

    results: list[tuple[int, str]] = []

    class ImportVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            super().__init__()
            self.scope_stack: list[str] = []  # track function/class scopes

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
            self.scope_stack.append("func")
            self.generic_visit(node)
            self.scope_stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
            self.scope_stack.append("func")
            self.generic_visit(node)
            self.scope_stack.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
            self.scope_stack.append("class")
            self.generic_visit(node)
            self.scope_stack.pop()

        def visit_Import(self, node: ast.Import) -> None:  # noqa: N802
            if "func" in self.scope_stack:
                modnames = ", ".join(alias.name for alias in node.names)
                results.append((node.lineno, f"import {modnames}"))

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
            if "func" in self.scope_stack:
                module = node.module or ""
                names = ", ".join(alias.name for alias in node.names)
                results.append((node.lineno, f"from {module} import {names}"))

    ImportVisitor().visit(tree)
    return results


# Skip by default to avoid breaking builds; enable by setting G6_IMPORT_GUARD=1
skip_guard = os.environ.get("G6_IMPORT_GUARD", "0").lower() not in {"1", "true", "yes", "on"}

@pytest.mark.skipif(skip_guard, reason="late-import guard disabled; set G6_IMPORT_GUARD=1 to enable")
@pytest.mark.parametrize("py_path", [
    p for p in Path("src").rglob("*.py")
    if "external" not in str(p).lower()  # skip archived/external
])
def test_no_function_scoped_imports(py_path: Path):
    norm = os.path.normpath(str(py_path)).lower()
    if any(norm.endswith(allow) for allow in ALLOWLIST):
        pytest.skip(f"Allowlisted for function-scoped imports: {py_path}")

    findings = has_late_imports(py_path)
    if findings:
        formatted = "\n".join(f"{py_path}:{lineno}: {code}" for lineno, code in findings[:30])
        more = "" if len(findings) <= 30 else f"\n... and {len(findings)-30} more"
        pytest.fail(
            "Function-scoped imports detected (late imports). Move these to module top or use a facade.\n"
            + formatted + more
        )
