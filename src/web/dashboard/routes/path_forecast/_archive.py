from __future__ import annotations

from typing import Optional
from pathlib import Path

from src.services.archival import (
    archive_config as _archive_config,
    archive_forecast_bands as _archive_bands,
    archive_forecast_q50 as _archive_q50,
)
from src.services.calibration import clamp_non_negative as _clamp_non_negative


def _resolve_project_root() -> Path:
    """Resolve project_root with compatibility for tests.

    Some tests monkeypatch `src.web.dashboard.routes.path_forecast._router._project_root`
    to redirect filesystem side-effects into a tmp directory.
    """

    try:
        import sys

        mod = sys.modules.get("src.web.dashboard.routes.path_forecast._router")
        if mod is not None:
            pr = getattr(mod, "_project_root", None)
            if callable(pr):
                root = pr()
                if isinstance(root, Path):
                    return root
                return Path(str(root))
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            raise
        pass

    from src.web.dashboard.core.paths import project_root

    return project_root()


def _apply_calibration_and_archive(
    idx_norm: str,
    ref_now_ms: int,
    rows: list[dict],
    times: list[int],
    qmap: dict,
    diag: dict,
    profile: Optional[str],
    mode_used: str,
    bucket_ms: int,
):
    # Calibration and clamping
    try:
        if True:  # preserve flag structure; calibrate handled by caller
            pass
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            raise
        pass

    # Clamp non-negative
    try:
        qmap = _clamp_non_negative(qmap)
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            raise
        pass

    # Archive best-effort
    try:
        from typing import Dict, Sequence, cast

        arch_dir = _resolve_project_root() / "data" / "ml" / "path_forecasts"
        _acfg = _archive_config(arch_dir)
        meta_for_archive = dict(diag)
        meta_for_archive.update({"mode": mode_used})
        qmap_cast = cast(
            Dict[float, Sequence[float]],
            {k: (tuple(v) if isinstance(v, list) else v) for k, v in qmap.items()},
        )
        _archive_q50(_acfg, index=idx_norm, gen_ms=ref_now_ms, times=times, qmap=qmap_cast, meta=meta_for_archive)
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            raise
        pass

    try:
        from typing import Dict, Sequence, cast

        arch_dir = _resolve_project_root() / "data" / "ml" / "path_forecasts"
        _acfg2 = _archive_config(arch_dir)
        qmap_cast2 = cast(
            Dict[float, Sequence[float]],
            {k: (tuple(v) if isinstance(v, list) else v) for k, v in qmap.items()},
        )
        meta_for_bands2 = dict(diag)
        try:
            if profile:
                meta_for_bands2["profile"] = str(profile).lower()
        except BaseException as e:
            if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                raise
            pass
        meta_for_bands2["mode"] = mode_used
        _archive_bands(_acfg2, index=idx_norm, gen_ms=ref_now_ms, times=times, qmap=qmap_cast2, meta=meta_for_bands2)
    except BaseException as e:
        if isinstance(e, (KeyboardInterrupt, SystemExit, GeneratorExit)):
            raise
        pass

    return qmap
