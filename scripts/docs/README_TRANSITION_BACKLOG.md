# Transition Backlog Extraction

This repo has many "transition" documents (migration, deprecations, cleanup, roadmap). To validate feasibility, start by converting those docs into one inventory you can review, tag, and sequence.

## Generate the backlog

From repo root:

```powershell
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/docs/extract_transition_backlog.py --out-dir artifacts --format both --verify-file-refs --verify-env-vars --verify-symbols --infer-status --review-queue
```

Outputs (generated locally; ignored by git):
- `artifacts/transition_backlog_latest.md`
- `artifacts/transition_backlog_latest.csv`
- `artifacts/transition_backlog_file_refs_latest.md`
- `artifacts/transition_backlog_env_vars_latest.md`
- `artifacts/transition_backlog_symbols_latest.md`
- `artifacts/transition_backlog_drifted_tasks_latest.md`
- `artifacts/transition_backlog_inferred_status_latest.md`
- `artifacts/transition_backlog_inferred_status_latest.csv`
- `artifacts/transition_backlog_review_queue_latest.md`
- `artifacts/transition_backlog_review_queue_top_latest.md`

### Top-N tuning

- Default Top-N is **80**. Override with:

```powershell
python scripts/docs/extract_transition_backlog.py --infer-status --review-queue --review-queue-top 40
```

- To only include high-signal items (checkboxes + dependency-blocked):

```powershell
python scripts/docs/extract_transition_backlog.py --infer-status --review-queue --review-queue-high-signal
```

## How to use it (recommended workflow)

1. **Mark DONE only with evidence**: a changelog entry, removed symbol, or passing gate.
2. **Resolve contradictions first** (canonical entrypoint, legacy flags, removal status) before taking on refactors.
3. **Add prerequisites + DoD** to every OPEN task (tests, grep checks, dashboards updated, rollback plan).
4. **Pick a small sprint cut**: prioritize tasks that reduce operational risk (error routing, deprecation cleanup, backoff modernization).

## Tuning

- To include `.archived/` docs too:

```powershell
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/docs/extract_transition_backlog.py --include-archived
```

- To extract only explicit checkboxes (skip bullets under headings):

```powershell
C:/Users/Asus/Desktop/g6_reorganized/.venv/Scripts/python.exe scripts/docs/extract_transition_backlog.py --no-bullets
```
