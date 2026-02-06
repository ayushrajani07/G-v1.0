from __future__ import annotations

# NOTE:
# This is intentionally a behavior-preserving shim.
# The previous god-file `src.web.dashboard.routes.ml` was renamed to
# `src.web.dashboard.routes.ml_legacy` to allow gradual decomposition into
# handler modules under this package.

from ..ml_legacy import router  # re-export

__all__ = ["router"]
