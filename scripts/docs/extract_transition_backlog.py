"""Extract checklist-style tasks from transition docs into a single backlog.

Purpose
- Inventory tasks scattered across transition docs (migration, deprecations, cleanup, roadmaps).
- Produce a reviewable CSV/Markdown artifact to validate feasibility, prerequisites, and status.

This script intentionally has no third-party dependencies.

Usage
  C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/docs/extract_transition_backlog.py

Options
  --out-dir artifacts
  --include-archived
  --format csv|md|both
    --no-latest
    --verify-file-refs
    --verify-env-vars
    --verify-symbols
    --infer-status
    --review-queue
    --review-queue-top N
    --review-queue-high-signal

Notes
- By default, this script extracts:
  - Markdown checkboxes: `- [ ] ...`, `- [x] ...`
  - Bullets that appear under headings containing keywords like "next steps", "checklist", "action".
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as _dt
import os
import re
from pathlib import Path
from typing import Iterable, Sequence


HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)\s*$")
CHECKBOX_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+\[(?P<state>[ xX])\]\s+(?P<text>.+?)\s*$")
BULLET_RE = re.compile(r"^\s*[-*]\s+(?P<text>.+?)\s*$")


DEFAULT_DOCS: tuple[str, ...] = (
    "ANALYSIS_ACTION_PLAN.md",
    "ANALYSIS_SUMMARY.md",
    "CLEANUP_PLAN.md",
    "CODE_HEALTH_ROADMAP.md",
    "DEPRECATIONS.md",
    "DEPRECATION_SUMMARY.md",
    "ERROR_ROUTING.md",
    "ADVISOR_OBSERVABILITY.md",
    "MIGRATION.md",
    "CHANGELOG_STABILIZATION.md",
    "CHANGELOG_DASHBOARDS.md",
    "ENHANCED_COLLECTOR_RETIREMENT.md",
    "BACKOFF_SCHEDULING_MODERNIZATION.md",
    "ISSUE_REMOVE_LEGACY_PANELS_BRIDGE.md",
    "QUICK_RESUME_PHASE3.md",
)


HEADING_KEYWORDS: tuple[str, ...] = (
    "next steps",
    "checklist",
    "action items",
    "actionable",
    "todo",
    "to-do",
    "plan",
    "migration",
    "deprecation",
    "removal",
    "rollout",
)


@dataclasses.dataclass(frozen=True)
class TaskItem:
    doc_path: str
    line: int
    heading_path: str
    item_type: str  # checkbox|bullet
    status: str  # open|done|unknown
    text: str


@dataclasses.dataclass(frozen=True)
class FileRefCheck:
    ref: str
    exists: bool
    resolved_path: str


@dataclasses.dataclass(frozen=True)
class RefCheck:
    ref: str
    found: bool


@dataclasses.dataclass(frozen=True)
class InferredTask:
    doc_path: str
    line: int
    heading_path: str
    item_type: str
    explicit_status: str
    inferred_status: str
    reasons: str
    text: str


def _normalize_text(text: str) -> str:
    # Remove trailing punctuation and excessive whitespace.
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _heading_is_interesting(heading_path: str) -> bool:
    lowered = heading_path.lower()
    return any(k in lowered for k in HEADING_KEYWORDS)


def extract_tasks_from_markdown(path: Path, *, include_bullets: bool = True) -> list[TaskItem]:
    tasks: list[TaskItem] = []
    heading_stack: list[str] = []

    try:
        raw = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raw = path.read_text(encoding="utf-8", errors="replace")

    for idx, line in enumerate(raw.splitlines(), start=1):
        heading_match = HEADING_RE.match(line)
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()

            while len(heading_stack) >= level:
                heading_stack.pop()
            heading_stack.append(title)
            continue

        heading_path = " > ".join(heading_stack)

        checkbox_match = CHECKBOX_RE.match(line)
        if checkbox_match:
            state = checkbox_match.group("state")
            status = "done" if state.strip().lower() == "x" else "open"
            text = _normalize_text(checkbox_match.group("text"))
            tasks.append(
                TaskItem(
                    doc_path=path.as_posix(),
                    line=idx,
                    heading_path=heading_path,
                    item_type="checkbox",
                    status=status,
                    text=text,
                )
            )
            continue

        if not include_bullets:
            continue

        # Only include non-checkbox bullets under relevant headings.
        if not heading_stack or not _heading_is_interesting(heading_path):
            continue

        bullet_match = BULLET_RE.match(line)
        if bullet_match:
            text = bullet_match.group("text")
            # Skip if it looks like a checkbox (already handled) or a pure link section.
            if text.lstrip().startswith("[") and "](" in text:
                continue
            text = _normalize_text(text)
            if not text or text in {"-", "*"}:
                continue
            tasks.append(
                TaskItem(
                    doc_path=path.as_posix(),
                    line=idx,
                    heading_path=heading_path,
                    item_type="bullet",
                    status="unknown",
                    text=text,
                )
            )

    return tasks


def iter_docs(
    repo_root: Path,
    doc_names: Sequence[str],
    *,
    include_archived: bool,
) -> Iterable[Path]:
    for name in doc_names:
        p = repo_root / name
        if p.exists():
            yield p

        if include_archived:
            archived = repo_root / ".archived" / name
            if archived.exists():
                yield archived


def write_csv(out_path: Path, tasks: Sequence[TaskItem]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "doc_path",
                "line",
                "heading_path",
                "item_type",
                "status",
                "text",
            ],
        )
        w.writeheader()
        for t in tasks:
            w.writerow(dataclasses.asdict(t))


def write_inferred_csv(out_path: Path, inferred: Sequence[InferredTask]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "doc_path",
                "line",
                "heading_path",
                "item_type",
                "explicit_status",
                "inferred_status",
                "reasons",
                "text",
            ],
        )
        w.writeheader()
        for t in inferred:
            w.writerow(dataclasses.asdict(t))


def write_inferred_markdown(out_path: Path, inferred: Sequence[InferredTask]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    counts: dict[str, int] = {}
    for it in inferred:
        counts[it.inferred_status] = counts.get(it.inferred_status, 0) + 1

    lines: list[str] = []
    lines.append("# Transition Backlog: Inferred Status\n")
    lines.append(
        "This file is generated by `scripts/docs/extract_transition_backlog.py`. "
        "It uses heuristics to flag likely-done / stale / dependency-blocked tasks.\n"
    )

    lines.append("## Summary\n")
    lines.append(f"- Total items: **{len(inferred)}**")
    for k in sorted(counts.keys()):
        lines.append(f"- {k}: **{counts[k]}**")
    lines.append("")

    # Focus review on non-trivial statuses.
    focus = [
        "stale_missing_target",
        "likely_done_doc_claims_done",
        "likely_done_target_missing",
        "blocked_dependency_wording",
    ]
    for status in focus:
        items = [i for i in inferred if i.inferred_status == status]
        if not items:
            continue
        lines.append(f"## {status}\n")
        for it in items[:200]:
            reasons = f" ({it.reasons})" if it.reasons else ""
            lines.append(f"- {it.doc_path}#L{it.line}: {it.text}{reasons}")
        if len(items) > 200:
            lines.append(f"- ... {len(items) - 200} more")
        lines.append("")

    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _theme_for(task: InferredTask) -> str:
    """Best-effort theme classifier for backlog review."""

    s = f"{task.doc_path} {task.heading_path} {task.text}".lower()
    if any(k in s for k in ("deprecat", "retire", "remov", "tombstone", "legacy")):
        return "deprecations-removals"
    if any(k in s for k in ("grafana", "dashboard", "panel", "prometheus", "alert")):
        return "dashboards-observability"
    if any(k in s for k in ("error", "retry", "backoff", "routing", "throttle")):
        return "reliability-error-handling"
    if any(k in s for k in ("perf", "latency", "throughput", "benchmark", "profil")):
        return "performance"
    if any(k in s for k in ("config", "env ", "g6_", "settings", "flag")):
        return "config-env-flags"
    if any(k in s for k in ("pytest", "test", "fixture", "ci ", "coverage")):
        return "tests-ci"
    if any(k in s for k in ("ml", "ann", "advisor", "forecast")):
        return "ml-advisor"
    if any(k in s for k in ("doc", "readme", "guide", "runbook", "manual")):
        return "docs"
    return "other"


def _score_for_review_queue(task: InferredTask) -> int:
    """Heuristic scoring for prioritizing tasks in the Top-N shortlist."""

    score = 0
    text = task.text.lower()
    heading = (task.heading_path or "").lower()
    doc = task.doc_path.lower()

    if task.item_type == "checkbox":
        score += 6
    if task.explicit_status == "open":
        score += 3
    if task.inferred_status == "blocked_dependency_wording":
        score += 4

    if _REMOVAL_VERBS_RE.search(task.text):
        score += 2

    if any(k in text for k in ("pytest", "test", "fixture", "ci", "gate")):
        score += 2
    if any(k in text for k in ("config", "env", "flag", "g6_")):
        score += 2
    if any(k in text for k in ("legacy loop", "unified_main", "collection_loop")):
        score += 2
    if any(k in text for k in ("retry", "backoff", "error", "routing")):
        score += 2
    if any(k in text for k in ("grafana", "dashboard", "panel", "prometheus", "alert")):
        score += 2

    # Slight preference for core planning docs.
    if any(k in doc for k in ("analysis_action_plan", "migration", "deprecations", "code_health_roadmap")):
        score += 1
    if "next steps" in heading or "checklist" in heading:
        score += 1

    return score


def write_review_queue_markdown(out_path: Path, inferred: Sequence[InferredTask]) -> None:
    """Write a short actionable review queue grouped by theme and doc."""

    out_path.parent.mkdir(parents=True, exist_ok=True)

    actionable_statuses = {"open_unchecked", "unknown", "blocked_dependency_wording"}
    exclude_statuses = {
        "done_checked",
        "likely_done_doc_claims_done",
        "likely_done_target_missing",
        "stale_missing_target",
    }

    queue = [t for t in inferred if t.inferred_status in actionable_statuses and t.inferred_status not in exclude_statuses]

    # Group by theme -> doc.
    grouped: dict[str, dict[str, list[InferredTask]]] = {}
    for t in queue:
        theme = _theme_for(t)
        grouped.setdefault(theme, {}).setdefault(t.doc_path, []).append(t)

    # Stable ordering.
    for theme_docs in grouped.values():
        for doc, items in theme_docs.items():
            items.sort(key=lambda x: (x.doc_path, x.line))

    lines: list[str] = []
    lines.append("# Transition Backlog: Review Queue (Actionable)\n")
    lines.append("This file is generated by `scripts/docs/extract_transition_backlog.py`.\n")
    lines.append("Rules: includes `open_unchecked`, `unknown`, and dependency-blocked items; excludes likely-done and stale items.\n")
    lines.append(f"- Actionable items: **{len(queue)}**\n")

    for theme in sorted(grouped.keys()):
        theme_count = sum(len(v) for v in grouped[theme].values())
        lines.append(f"## {theme} ({theme_count})\n")
        for doc in sorted(grouped[theme].keys()):
            items = grouped[theme][doc]
            lines.append(f"### {doc} ({len(items)})\n")
            for it in items[:80]:
                tag = it.inferred_status
                lines.append(f"- [{tag}] {doc}#L{it.line}: {it.text}")
            if len(items) > 80:
                lines.append(f"- ... {len(items) - 80} more")
            lines.append("")

    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_review_queue_top_markdown(
    out_path: Path,
    inferred: Sequence[InferredTask],
    *,
    top_n: int,
    high_signal: bool,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    actionable_statuses = {"open_unchecked", "unknown", "blocked_dependency_wording"}
    exclude_statuses = {
        "done_checked",
        "likely_done_doc_claims_done",
        "likely_done_target_missing",
        "stale_missing_target",
    }

    queue = [t for t in inferred if t.inferred_status in actionable_statuses and t.inferred_status not in exclude_statuses]
    if high_signal:
        queue = [t for t in queue if (t.item_type == "checkbox" or t.inferred_status == "blocked_dependency_wording")]

    scored = [(_score_for_review_queue(t), t) for t in queue]
    scored.sort(key=lambda x: (-x[0], x[1].doc_path, x[1].line, x[1].text))
    picked = [t for _, t in scored[: max(0, top_n)]]

    # Group by theme -> doc.
    grouped: dict[str, dict[str, list[InferredTask]]] = {}
    for t in picked:
        theme = _theme_for(t)
        grouped.setdefault(theme, {}).setdefault(t.doc_path, []).append(t)
    for theme_docs in grouped.values():
        for doc, items in theme_docs.items():
            items.sort(key=lambda x: (x.doc_path, x.line))

    lines: list[str] = []
    lines.append("# Transition Backlog: Review Queue (Top N)\n")
    lines.append("This file is generated by `scripts/docs/extract_transition_backlog.py`.\n")
    lines.append(f"- Requested top N: **{top_n}**")
    lines.append(f"- High-signal filter: **{high_signal}**")
    lines.append(f"- Items emitted: **{len(picked)}**\n")

    for theme in sorted(grouped.keys()):
        theme_count = sum(len(v) for v in grouped[theme].values())
        lines.append(f"## {theme} ({theme_count})\n")
        for doc in sorted(grouped[theme].keys()):
            items = grouped[theme][doc]
            lines.append(f"### {doc} ({len(items)})\n")
            for it in items:
                score = _score_for_review_queue(it)
                lines.append(f"- [score={score}; {it.inferred_status}] {doc}#L{it.line}: {it.text}")
            lines.append("")

    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_markdown(out_path: Path, tasks: Sequence[TaskItem], *, repo_root: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Simple grouping by doc.
    grouped: dict[str, list[TaskItem]] = {}
    for t in tasks:
        grouped.setdefault(t.doc_path, []).append(t)

    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    def rel(p: str) -> str:
        try:
            return str(Path(p).relative_to(repo_root).as_posix())
        except Exception:
            return p

    lines: list[str] = []
    lines.append("# Transition Backlog (Extracted)\n")
    lines.append(f"Generated: `{now}`\n")
    lines.append("This file is generated by `scripts/docs/extract_transition_backlog.py`.\n")

    total = len(tasks)
    open_count = sum(1 for t in tasks if t.status == "open")
    done_count = sum(1 for t in tasks if t.status == "done")
    unknown_count = total - open_count - done_count

    lines.append("## Summary\n")
    lines.append(f"- Total items: **{total}**")
    lines.append(f"- Open (unchecked): **{open_count}**")
    lines.append(f"- Done (checked): **{done_count}**")
    lines.append(f"- Unspecified (bullets): **{unknown_count}**\n")

    for doc_path in sorted(grouped.keys()):
        rel_path = rel(doc_path)
        items = grouped[doc_path]
        lines.append(f"## {rel_path}\n")
        for t in items:
            heading = t.heading_path or "(no heading)"
            checkbox = "[x]" if t.status == "done" else "[ ]" if t.status == "open" else "[?]"
            lines.append(f"- {checkbox} {t.text} (line {t.line}; {heading})")
        lines.append("")

    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


FILE_REF_RE = re.compile(r"`(?P<ref>[^`]+\.(?:py|md|ps1|bat|yml|yaml|json|txt))`")
BACKTICK_RE = re.compile(r"`(?P<ref>[^`]+)`")
ENV_VAR_RE = re.compile(r"\bG6_[A-Z0-9_]+\b")


def extract_file_refs(tasks: Sequence[TaskItem]) -> list[str]:
    refs: list[str] = []
    for t in tasks:
        for m in FILE_REF_RE.finditer(t.text):
            refs.append(m.group("ref"))
    # Stable unique order
    seen: set[str] = set()
    out: list[str] = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def extract_env_vars(tasks: Sequence[TaskItem]) -> list[str]:
    refs: list[str] = []
    for t in tasks:
        refs.extend(ENV_VAR_RE.findall(t.text))

    seen: set[str] = set()
    out: list[str] = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


_KNOWN_FILE_EXTS = (
    ".py",
    ".md",
    ".ps1",
    ".bat",
    ".yml",
    ".yaml",
    ".json",
    ".txt",
    ".sh",
)


def extract_backticked_symbols(tasks: Sequence[TaskItem]) -> list[str]:
    """Extract likely code symbols referenced in backticks.

    Heuristic: a backticked token that contains at least one dot (.) and
    does not look like a filepath (by extension).
    """

    refs: list[str] = []
    for t in tasks:
        for m in BACKTICK_RE.finditer(t.text):
            ref = m.group("ref").strip()
            if not ref or " " in ref:
                continue
            if "." not in ref:
                continue
            lowered = ref.lower()
            if lowered.endswith(_KNOWN_FILE_EXTS):
                continue
            # Skip common markdown patterns like `foo.bar()` if present; keep as-is.
            if len(ref) > 120:
                continue
            refs.append(ref)

    seen: set[str] = set()
    out: list[str] = []
    for r in refs:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def iter_repo_text_files(repo_root: Path) -> Iterable[Path]:
    """Yield a curated set of files to search for references.

    Intentionally avoids large/volatile directories.
    """

    skip_dirs = {
        ".git",
        ".venv",
        ".venv-ml",
        "venv",
        "env",
        "data",
        "artifacts",
        "_tmp",
        "logs",
        "results",
        "models",
        "scratch",
        "htmlcov",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "parity_snapshots",
    }

    exts = {".py", ".md", ".ps1", ".yml", ".yaml", ".json", ".txt", ".bat", ".sh"}
    for root, dirs, files in os.walk(repo_root):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fn in files:
            p = Path(root) / fn
            if p.suffix.lower() in exts:
                yield p


def _chunked(seq: Sequence[str], chunk_size: int) -> Iterable[list[str]]:
    for i in range(0, len(seq), chunk_size):
        yield list(seq[i : i + chunk_size])


def scan_repo_for_refs(repo_root: Path, refs: Sequence[str]) -> dict[str, bool]:
    """Return mapping of ref -> found by searching repo text files."""

    found: dict[str, bool] = {r: False for r in refs}
    if not refs:
        return found

    # Build a regex union in chunks to keep patterns manageable.
    # Use word boundaries only for env vars; for symbols, plain contains-match is ok.
    # Here we do contains-match for all by escaping references.
    patterns: list[re.Pattern[str]] = []
    for chunk in _chunked(list(refs), chunk_size=150):
        union = "|".join(re.escape(r) for r in chunk)
        patterns.append(re.compile(union))

    max_bytes = 2_000_000  # 2MB per file
    for p in iter_repo_text_files(repo_root):
        try:
            if p.stat().st_size > max_bytes:
                continue
        except OSError:
            continue

        try:
            content = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        for pat in patterns:
            for m in pat.finditer(content):
                ref = m.group(0)
                if ref in found:
                    found[ref] = True

        # Early exit if all found.
        if all(found.values()):
            break

    return found


def check_file_refs(repo_root: Path, refs: Sequence[str]) -> list[FileRefCheck]:
    checks: list[FileRefCheck] = []
    for ref in refs:
        ref_norm = ref.replace("\\", "/")
        candidate = (repo_root / ref_norm).resolve()
        exists = candidate.exists()
        if not exists:
            # Fallback: try basename search in repo root.
            base = os.path.basename(ref_norm)
            matches = list(repo_root.rglob(base))
            if matches:
                candidate = matches[0].resolve()
                exists = True

        checks.append(FileRefCheck(ref=ref, exists=exists, resolved_path=str(candidate)))
    return checks


def write_file_ref_report(out_path: Path, checks: Sequence[FileRefCheck]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    missing = [c for c in checks if not c.exists]
    lines: list[str] = []
    lines.append("# Transition Backlog: File Ref Verification\n")
    lines.append("This report checks whether backticked file references in tasks exist in the repo.\n")
    lines.append(f"- Total refs: **{len(checks)}**")
    lines.append(f"- Missing refs: **{len(missing)}**\n")
    if missing:
        lines.append("## Missing file references\n")
        for c in missing:
            lines.append(f"- `{c.ref}` (resolved: `{c.resolved_path}`)")
        lines.append("")
    lines.append("## All references\n")
    for c in checks:
        status = "OK" if c.exists else "MISSING"
        lines.append(f"- **{status}** `{c.ref}`")
    lines.append("")
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_ref_report(out_path: Path, title: str, checks: Sequence[RefCheck]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    missing = [c for c in checks if not c.found]
    lines: list[str] = []
    lines.append(f"# {title}\n")
    lines.append("This report checks whether referenced identifiers appear in the repo text/code.\n")
    lines.append(f"- Total refs: **{len(checks)}**")
    lines.append(f"- Missing refs: **{len(missing)}**\n")
    if missing:
        lines.append("## Missing references\n")
        for c in missing:
            lines.append(f"- `{c.ref}`")
        lines.append("")
    lines.append("## All references\n")
    for c in checks:
        status = "OK" if c.found else "MISSING"
        lines.append(f"- **{status}** `{c.ref}`")
    lines.append("")
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_task_drift_report(
    out_path: Path,
    tasks: Sequence[TaskItem],
    *,
    missing_files: set[str],
    missing_env: set[str],
    missing_symbols: set[str],
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    drifted: list[TaskItem] = []
    for t in tasks:
        text = t.text
        file_refs = {m.group("ref") for m in FILE_REF_RE.finditer(text)}
        env_refs = set(ENV_VAR_RE.findall(text))
        sym_refs = set(extract_backticked_symbols([t]))
        if file_refs & missing_files:
            drifted.append(t)
            continue
        if env_refs & missing_env:
            drifted.append(t)
            continue
        if sym_refs & missing_symbols:
            drifted.append(t)
            continue

    lines: list[str] = []
    lines.append("# Transition Backlog: Drifted Tasks (Likely Doc Staleness)\n")
    lines.append("A task is listed here if it references a missing file/env var/symbol.\n")
    lines.append(f"- Tasks scanned: **{len(tasks)}**")
    lines.append(f"- Drifted tasks: **{len(drifted)}**\n")

    for t in drifted:
        lines.append(
            f"- {t.doc_path}#L{t.line}: {t.text} (heading: {t.heading_path or '(no heading)'})"
        )

    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


_REMOVAL_VERBS_RE = re.compile(
    r"\b(remove|delete|retire|drop|eliminate|deprecate|disable)\b", re.IGNORECASE
)
_DONE_CUES_RE = re.compile(r"\b(complete|completed|resolved|removed)\b", re.IGNORECASE)
_DEPENDENCY_CUES_RE = re.compile(r"\b(after|before|requires|prereq|prerequisite|depends on)\b", re.IGNORECASE)


def infer_task_status(
    task: TaskItem,
    *,
    missing_files: set[str],
    missing_env: set[str],
    missing_symbols: set[str],
) -> InferredTask:
    explicit = task.status
    inferred = "unknown"
    reasons: list[str] = []

    # Preserve explicit checkbox signal.
    if explicit == "done":
        inferred = "done_checked"
        return InferredTask(
            doc_path=task.doc_path,
            line=task.line,
            heading_path=task.heading_path,
            item_type=task.item_type,
            explicit_status=explicit,
            inferred_status=inferred,
            reasons="",
            text=task.text,
        )
    if explicit == "open":
        inferred = "open_unchecked"

    text = task.text
    file_refs = {m.group("ref") for m in FILE_REF_RE.finditer(text)}
    env_refs = set(ENV_VAR_RE.findall(text))
    sym_refs = set(extract_backticked_symbols([task]))

    missing_targets = bool((file_refs & missing_files) or (env_refs & missing_env) or (sym_refs & missing_symbols))
    has_removal_verb = bool(_REMOVAL_VERBS_RE.search(text))
    doc_claims_done = bool(_DONE_CUES_RE.search(text))
    dep_cue = bool(_DEPENDENCY_CUES_RE.search(text)) or ("after:" in (task.heading_path or "").lower())

    if explicit in {"open", "unknown"} and doc_claims_done:
        inferred = "likely_done_doc_claims_done"
        reasons.append("done-cue")

    if missing_targets:
        if has_removal_verb:
            inferred = "likely_done_target_missing"
            reasons.append("target-missing + removal-verb")
        else:
            inferred = "stale_missing_target"
            reasons.append("target-missing")

    if inferred == "unknown" and dep_cue:
        inferred = "blocked_dependency_wording"
        reasons.append("dependency-cue")

    if inferred == "unknown" and explicit == "open":
        inferred = "open_unchecked"

    return InferredTask(
        doc_path=task.doc_path,
        line=task.line,
        heading_path=task.heading_path,
        item_type=task.item_type,
        explicit_status=explicit,
        inferred_status=inferred,
        reasons="; ".join(reasons),
        text=task.text,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract transition backlog from docs")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).resolve().parents[2]),
        help="Repo root (default: inferred)",
    )
    parser.add_argument(
        "--out-dir",
        default="artifacts",
        help="Output directory (relative to repo root)",
    )
    parser.add_argument(
        "--format",
        choices=("csv", "md", "both"),
        default="both",
        help="Output format",
    )
    parser.add_argument(
        "--include-archived",
        action="store_true",
        help="Also include matching docs under .archived/",
    )
    parser.add_argument(
        "--no-bullets",
        action="store_true",
        help="Only extract checkboxes (skip bullets under headings)",
    )
    parser.add_argument(
        "--no-latest",
        action="store_true",
        help="Do not write transition_backlog_latest.(csv|md) alongside timestamped outputs",
    )
    parser.add_argument(
        "--verify-file-refs",
        action="store_true",
        help="Write a file-reference verification report (backticked file paths in tasks)",
    )
    parser.add_argument(
        "--verify-env-vars",
        action="store_true",
        help="Write an env-var verification report (G6_* identifiers referenced in tasks)",
    )
    parser.add_argument(
        "--verify-symbols",
        action="store_true",
        help="Write a code-symbol verification report (backticked dotted identifiers in tasks)",
    )
    parser.add_argument(
        "--infer-status",
        action="store_true",
        help="Write inferred-status reports (flags likely-done/stale/blocked tasks using heuristics)",
    )
    parser.add_argument(
        "--review-queue",
        action="store_true",
        help="Write a short actionable review queue grouped by theme and doc (requires --infer-status)",
    )
    parser.add_argument(
        "--review-queue-top",
        type=int,
        default=80,
        help="Also write a Top-N review queue shortlist (default: 80; set 0 to disable)",
    )
    parser.add_argument(
        "--review-queue-high-signal",
        action="store_true",
        help="For Top-N shortlist: keep only checkboxes + dependency-blocked items",
    )
    parser.add_argument(
        "--docs",
        nargs="*",
        default=list(DEFAULT_DOCS),
        help="Doc filenames to scan (default: curated transition set)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    repo_root = Path(args.repo_root).resolve()
    out_dir = (repo_root / args.out_dir).resolve()

    docs = list(iter_docs(repo_root, args.docs, include_archived=bool(args.include_archived)))
    if not docs:
        raise SystemExit("No docs found. Pass --docs or check --repo-root")

    tasks: list[TaskItem] = []
    for p in docs:
        tasks.extend(extract_tasks_from_markdown(p, include_bullets=not args.no_bullets))

    # Stable order: doc then line.
    tasks.sort(key=lambda t: (t.doc_path, t.line, t.text))

    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    csv_path = out_dir / f"transition_backlog_{stamp}.csv"
    md_path = out_dir / f"transition_backlog_{stamp}.md"

    latest_csv = out_dir / "transition_backlog_latest.csv"
    latest_md = out_dir / "transition_backlog_latest.md"
    latest_verify = out_dir / "transition_backlog_file_refs_latest.md"
    latest_env_verify = out_dir / "transition_backlog_env_vars_latest.md"
    latest_sym_verify = out_dir / "transition_backlog_symbols_latest.md"
    latest_drift = out_dir / "transition_backlog_drifted_tasks_latest.md"
    latest_inferred_md = out_dir / "transition_backlog_inferred_status_latest.md"
    latest_inferred_csv = out_dir / "transition_backlog_inferred_status_latest.csv"
    latest_review_queue = out_dir / "transition_backlog_review_queue_latest.md"
    latest_review_queue_top = out_dir / "transition_backlog_review_queue_top_latest.md"

    if args.format in {"csv", "both"}:
        write_csv(csv_path, tasks)
        if not args.no_latest:
            write_csv(latest_csv, tasks)

    if args.format in {"md", "both"}:
        write_markdown(md_path, tasks, repo_root=repo_root)
        if not args.no_latest:
            write_markdown(latest_md, tasks, repo_root=repo_root)

    if args.verify_file_refs:
        refs = extract_file_refs(tasks)
        checks = check_file_refs(repo_root, refs)
        write_file_ref_report(latest_verify, checks)

    env_missing: set[str] = set()
    sym_missing: set[str] = set()
    file_missing: set[str] = set()

    if args.verify_env_vars:
        envs = extract_env_vars(tasks)
        found = scan_repo_for_refs(repo_root, envs)
        checks = [RefCheck(ref=k, found=v) for k, v in found.items()]
        checks.sort(key=lambda c: c.ref)
        write_ref_report(latest_env_verify, "Transition Backlog: Env Var Verification", checks)
        env_missing = {c.ref for c in checks if not c.found}

    if args.verify_symbols:
        symbols = extract_backticked_symbols(tasks)
        found = scan_repo_for_refs(repo_root, symbols)
        checks = [RefCheck(ref=k, found=v) for k, v in found.items()]
        checks.sort(key=lambda c: c.ref)
        write_ref_report(latest_sym_verify, "Transition Backlog: Symbol Verification", checks)
        sym_missing = {c.ref for c in checks if not c.found}

    if args.verify_file_refs:
        # Recompute missing set from file checks.
        refs = extract_file_refs(tasks)
        checks = check_file_refs(repo_root, refs)
        file_missing = {c.ref for c in checks if not c.exists}

    if (args.verify_file_refs or args.verify_env_vars or args.verify_symbols) and (
        file_missing or env_missing or sym_missing
    ):
        write_task_drift_report(
            latest_drift,
            tasks,
            missing_files=file_missing,
            missing_env=env_missing,
            missing_symbols=sym_missing,
        )

    if args.infer_status:
        inferred = [
            infer_task_status(
                t,
                missing_files=file_missing,
                missing_env=env_missing,
                missing_symbols=sym_missing,
            )
            for t in tasks
        ]
        write_inferred_markdown(latest_inferred_md, inferred)
        write_inferred_csv(latest_inferred_csv, inferred)

        if args.review_queue:
            write_review_queue_markdown(latest_review_queue, inferred)

        if args.review_queue and args.review_queue_top and args.review_queue_top > 0:
            write_review_queue_top_markdown(
                latest_review_queue_top,
                inferred,
                top_n=int(args.review_queue_top),
                high_signal=bool(args.review_queue_high_signal),
            )

    print(f"Docs scanned: {len(docs)}")
    print(f"Items extracted: {len(tasks)}")
    if args.format in {"csv", "both"}:
        print(f"CSV: {csv_path}")
    if args.format in {"md", "both"}:
        print(f"MD: {md_path}")
    if not args.no_latest:
        if args.format in {"csv", "both"}:
            print(f"Latest CSV: {latest_csv}")
        if args.format in {"md", "both"}:
            print(f"Latest MD: {latest_md}")
    if args.verify_file_refs:
        print(f"File ref report: {latest_verify}")
    if args.verify_env_vars:
        print(f"Env var report: {latest_env_verify}")
    if args.verify_symbols:
        print(f"Symbol report: {latest_sym_verify}")
    if (args.verify_file_refs or args.verify_env_vars or args.verify_symbols) and (
        file_missing or env_missing or sym_missing
    ):
        print(f"Drifted tasks: {latest_drift}")
    if args.infer_status:
        print(f"Inferred status: {latest_inferred_md}")
        print(f"Inferred status (CSV): {latest_inferred_csv}")
        if args.review_queue:
            print(f"Review queue: {latest_review_queue}")
            if args.review_queue_top and args.review_queue_top > 0:
                print(f"Review queue (Top N): {latest_review_queue_top}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
