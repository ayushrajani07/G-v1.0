# Dependencies and Environments

This repo now uses a split + locked dependency model for clarity and reproducibility.

## Install options

Pick the one that matches your use-case:

- Core runtime only:
  - pip install -r requirements.core.txt
- API server (includes core):
  - pip install -r requirements.api.txt
- Monitoring/observability (includes core):
  - pip install -r requirements.monitoring.txt
- ML extras (includes core; Torch optional):
  - pip install -r requirements.ml.txt
- Aggregate of all runtime extras (API + Monitoring + ML):
  - pip install -r requirements-all.txt
- Fully pinned, reproducible environment:
  - pip install -r requirements.lock.txt

Optional developer tools (linters, test tooling) are separate:
- pip install -r requirements-dev.txt

## Notes on PyTorch

PyTorch CPU wheels are installed from the official index. Use the VS Code task:
- "ML: Install Torch (CPU)" (installs torch from https://download.pytorch.org/whl/cpu)

## One-click tasks (VS Code)

In .vscode/tasks.json you will find:
- Deps: Install core/API/Monitoring/ML/all/lock
- Dev: Install test deps
- Deps: Refresh lock from venv (updates requirements.lock.txt based on current venv)

## Why split + lock?

- Split files keep concerns clear (runtime vs API/ML/monitoring vs developer tooling)
- The lock file ensures exact reproducibility across machines and CI

## Migration from legacy requirements.txt

The legacy monolithic requirements.txt is kept as a thin shim that delegates to requirements-all.txt to avoid breaking older docs.
Prefer the split files (or the lock file) going forward.
