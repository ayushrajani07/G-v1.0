# Tests Runbook (local + VS Code)

This guide explains the fastest and most reliable ways to run tests locally on Windows (PowerShell) and via VS Code tasks.

## Quick start

- Preferred: use the VS Code tasks provided in `.vscode/tasks.json`.
- If you see exit code 1 in a task but direct runs pass, first install test deps and retry.

### Fastest green path in VS Code

1) Prepare dependencies (pytest, pytest-xdist, etc.)
   - Task: "Dev: Install test deps"
2) Run everything in two phases (parallel then serial)
   - Task: "Pytest: Fast all (two-phase)"

This sequence also runs automatically when you use:
- "CI: Lint + Typecheck + Tests (two-phase)"
- "Tests: Prepare + Full" (installs deps, then runs the full suite)

### One-shot from PowerShell (optional)

```powershell
# Parallel (non-serial)
python -m pytest -q -n auto --dist=loadgroup -m 'not serial'
# Serial-only phase
python -m pytest -q -m serial
# Full suite one-liner
python -m pytest -q
```

Tip: If `-n auto` errors, install xdist:
```powershell
python -m pip install pytest-xdist
```

## Common issues and fixes

- VS Code task fails with exit code 1 but the same command passes in a terminal
  - Ensure the same interpreter is selected in VS Code (bottom-right Python version) and in your terminal.
  - Run the "Dev: Install test deps" task to ensure pytest plugins are available.
  - Use the aggregate task "Tests: Prepare + Full" which installs deps first.

- Parallel phase hangs or conflicts
  - Some tests are marked `serial` and must run in a single worker; ensure you run the two phases in the recommended order.

- Environment-sensitive tests
  - If needed, set explicit env vars in the task definition or terminal before running. For one-off runs, prefix the command in PowerShell:
    ```powershell
    $env:G6_FORCE_NEW_REGISTRY="1"; python -m pytest -q
    ```

## Recommendations

- For routine checks during development, "Pytest: Fast all (two-phase)" is the best signal-to-time ratio.
- For pre-commit verification, use the CI aggregate task: "CI: Lint + Typecheck + Tests (two-phase)".
- If you’re editing storage backends or orchestrator logic, run affected subsets first using `-k` filters, then the fast two-phase suite.

## Notes

- Windows shell: commands above use PowerShell semantics.
- These tasks rely on the interpreter set by VS Code (`${command:python.interpreterPath}`).
- If you maintain a locked environment, prefer `requirements.lock.txt` and the task "Deps: Install lock (pinned)".
