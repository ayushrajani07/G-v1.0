from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ModuleStats:
    name: str
    py_files: int
    total_lines: int
    except_exception: int
    todo_fixme_xxx: int
    type_ignore: int
    noqa: int


@dataclass(frozen=True)
class FileStats:
    rel_path: str
    module: str
    total_lines: int
    except_exception: int
    todo_fixme_xxx: int
    type_ignore: int
    noqa: int


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def compute_module_stats(src_dir: Path) -> list[ModuleStats]:
    modules = sorted(
        p.name
        for p in src_dir.iterdir()
        if p.is_dir() and not p.name.startswith("__") and p.name != "__pycache__"
    )

    out: list[ModuleStats] = []
    for name in modules:
        base = src_dir / name
        py_files = [p for p in base.rglob("*.py") if p.name != "__init__.py"]

        total_lines = 0
        except_exception = 0
        todo_fixme_xxx = 0
        type_ignore = 0
        noqa = 0

        for fp in py_files:
            text = _read_text(fp)
            if text:
                total_lines += text.count("\n") + 1
            except_exception += text.count("except Exception")
            todo_fixme_xxx += sum(text.count(x) for x in ("TODO", "FIXME", "XXX"))
            type_ignore += text.count("type: ignore")
            noqa += text.count("noqa")

        out.append(
            ModuleStats(
                name=name,
                py_files=len(py_files),
                total_lines=total_lines,
                except_exception=except_exception,
                todo_fixme_xxx=todo_fixme_xxx,
                type_ignore=type_ignore,
                noqa=noqa,
            )
        )

    return out


def compute_file_stats(src_dir: Path) -> list[FileStats]:
    out: list[FileStats] = []
    for fp in src_dir.rglob("*.py"):
        if fp.name == "__init__.py":
            continue

        rel = fp.relative_to(src_dir).as_posix()
        module = rel.split("/", 1)[0]
        text = _read_text(fp)
        total_lines = text.count("\n") + (1 if text else 0)
        out.append(
            FileStats(
                rel_path=rel,
                module=module,
                total_lines=total_lines,
                except_exception=text.count("except Exception"),
                todo_fixme_xxx=sum(text.count(x) for x in ("TODO", "FIXME", "XXX")),
                type_ignore=text.count("type: ignore"),
                noqa=text.count("noqa"),
            )
        )
    return out


def to_markdown(stats: list[ModuleStats], top_n: int = 20) -> str:
    by_lines = sorted(stats, key=lambda s: s.total_lines, reverse=True)[:top_n]
    by_except = sorted(stats, key=lambda s: s.except_exception, reverse=True)[:top_n]

    def table(rows: list[ModuleStats]) -> str:
        lines = [
            "| module | py_files | lines | except Exception | TODO/FIXME/XXX | type: ignore | noqa |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for s in rows:
            lines.append(
                f"| {s.name} | {s.py_files} | {s.total_lines} | {s.except_exception} | {s.todo_fixme_xxx} | {s.type_ignore} | {s.noqa} |"
            )
        return "\n".join(lines)

    return "\n".join(
        [
            "# Maintainability Audit: Module Stats",
            "",
            f"Generated from `{os.getcwd()}`.",
            "",
            "## Top Modules by LOC",
            "",
            table(by_lines),
            "",
            "## Top Modules by `except Exception` Count",
            "",
            table(by_except),
            "",
        ]
    )


def hotspots_to_markdown(file_stats: list[FileStats], top_n: int = 50) -> str:
    by_lines = sorted(file_stats, key=lambda s: s.total_lines, reverse=True)[:top_n]
    by_except = sorted(file_stats, key=lambda s: s.except_exception, reverse=True)[:top_n]
    by_ignores = sorted(file_stats, key=lambda s: s.type_ignore, reverse=True)[:top_n]

    def table(rows: list[FileStats]) -> str:
        lines = [
            "| file | module | lines | except Exception | TODO/FIXME/XXX | type: ignore | noqa |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
        for s in rows:
            lines.append(
                f"| {s.rel_path} | {s.module} | {s.total_lines} | {s.except_exception} | {s.todo_fixme_xxx} | {s.type_ignore} | {s.noqa} |"
            )
        return "\n".join(lines)

    return "\n".join(
        [
            "# Maintainability Audit: File Hotspots",
            "",
            "These are *entry points for refactors* (largest files, most catch-all exceptions, most typing ignores).",
            "",
            "## Top Files by LOC",
            "",
            table(by_lines),
            "",
            "## Top Files by `except Exception` Count",
            "",
            table(by_except),
            "",
            "## Top Files by `type: ignore` Count",
            "",
            table(by_ignores),
            "",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Quick maintainability stats per src/* module")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--out", default="artifacts/maintainability/module_stats.md")
    parser.add_argument("--out-json", default="artifacts/maintainability/module_stats.json")
    parser.add_argument("--out-hotspots", default="artifacts/maintainability/file_hotspots.md")
    parser.add_argument("--out-hotspots-json", default="artifacts/maintainability/file_hotspots.json")
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    src_dir = repo_root / "src"
    if not src_dir.exists():
        raise SystemExit(f"src dir not found: {src_dir}")

    stats = compute_module_stats(src_dir)
    file_stats = compute_file_stats(src_dir)

    out_path = (repo_root / args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(to_markdown(stats, top_n=args.top), encoding="utf-8")

    out_json_path = (repo_root / args.out_json).resolve()
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(
        json.dumps([s.__dict__ for s in stats], indent=2, sort_keys=True),
        encoding="utf-8",
    )

    out_hotspots_path = (repo_root / args.out_hotspots).resolve()
    out_hotspots_path.parent.mkdir(parents=True, exist_ok=True)
    out_hotspots_path.write_text(hotspots_to_markdown(file_stats, top_n=args.top), encoding="utf-8")

    out_hotspots_json_path = (repo_root / args.out_hotspots_json).resolve()
    out_hotspots_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_hotspots_json_path.write_text(
        json.dumps([s.__dict__ for s in file_stats], indent=2, sort_keys=True),
        encoding="utf-8",
    )

    print(f"Wrote: {out_path}")
    print(f"Wrote: {out_json_path}")
    print(f"Wrote: {out_hotspots_path}")
    print(f"Wrote: {out_hotspots_json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
