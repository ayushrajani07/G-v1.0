# Python 3.14 runtime (no venv) – Windows setup

This project is standardized to run on a single system-wide Python (target: 3.14) without a virtual environment. VS Code tasks now execute via the currently selected interpreter.

## What you need
- Windows with Python 3.14 installed (via the official installer or the Python Launcher for Windows).
- VS Code with the Python extension enabled.

## One-time install
1) Select Python 3.14 in VS Code
- Click the interpreter in the Status Bar (bottom-right) and choose your Python 3.14 interpreter.

2) Install dependencies for the selected interpreter
- Open a terminal in this workspace, then:
  - Using the Python Launcher (recommended):
    - py -3.14 -m pip install --upgrade pip
    - py -3.14 -m pip install -r requirements.txt
  - Or using the selected interpreter directly:
    - python -m pip install --upgrade pip
    - python -m pip install -r requirements.txt

## Running tests
- From Command Palette: "Tasks: Run Task" → "Run full pytest"
  - Under the hood this runs: python -m pytest -q using your selected interpreter.
- Quick/subset:
  - "Run pytest" → runs all tests quietly
  - "Run pytest (subset severity_disabled)" → focused subset used during debugging

## Notes and tips
- Interpreter control: All Python tasks use ${command:python.interpreterPath}. Make sure VS Code is set to Python 3.14.
- Package compatibility: If a dependency is not yet available for Python 3.14 on Windows, pip may fail to install it. Let us know which package failed and we’ll pin/adjust as needed.
- No venv expected: The codebase and tasks no longer reference .venv. If you used one previously, you can safely delete it.

### Torch (PyTorch) for LSTM exporters
- Torch wheels for Windows + Python 3.14 are published on the official PyTorch index (CPU builds).
- Install via task: "ML: Install Torch (CPU)" or run:
  - py -3.14 -m pip install torch --index-url https://download.pytorch.org/whl/cpu
- We intentionally do not add torch directly to requirements.txt to avoid cross-platform wheel resolution issues.

## Troubleshooting
- pytest not found: Ensure you installed dependencies with the same interpreter you selected in VS Code.
- Multiple Pythons installed: Prefer the Python Launcher (py -3.14 ...) to avoid PATH confusion.
