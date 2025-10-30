import sys, runpy
from pathlib import Path

# Ensure workspace root is on sys.path so `scripts.*` imports resolve in tests
root = Path(__file__).resolve().parents[1]
if str(root) not in sys.path:
    sys.path.insert(0, str(root))

# Prepare argv for scripts/pytest_run.py
sys.argv = ["pytest_run.py", "fast-inner"]

# Execute the pytest runner script as __main__
runpy.run_path(str(root / "scripts" / "pytest_run.py"), run_name="__main__")
