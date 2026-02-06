from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Optional


def detect_quantile_columns(fieldnames: Sequence[str] | None) -> dict[int, str]:
    """Detect quantile columns named like q10/q50/q90.

    Returns mapping: {10: 'q10', 50: 'q50', 90: 'q90', ...} using the original
    case-preserving column name from the CSV.
    """

    out: dict[int, str] = {}
    for name in fieldnames or []:
        if not isinstance(name, str):
            continue
        n = name.strip()
        if len(n) < 2 or not n.lower().startswith("q"):
            continue
        tail = n[1:]
        if not tail.isdigit():
            continue
        try:
            q = int(tail)
        except (TypeError, ValueError):
            continue
        out[q] = n
    return out


def parse_int(row: dict, key: str) -> Optional[int]:
    v = row.get(key)
    if v in (None, ""):
        return None
    try:
        return int(str(v))
    except (TypeError, ValueError):
        return None


def parse_float(row: dict, key: str) -> Optional[float]:
    v = row.get(key)
    if v in (None, ""):
        return None
    try:
        return float(f"{v}")
    except (TypeError, ValueError):
        return None


def iter_dict_rows(path: Path) -> Iterator[dict[str, str]]:
    import csv

    with path.open("r", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        for row in rd:
            if isinstance(row, dict):
                yield row  # type: ignore[return-value]


def iter_bands_quantile_rows(
    path: Path,
    *,
    quantiles: Sequence[int],
    horizon_min: int | None = None,
    gen_ms_min: int | None = None,
    target_ms_max: int | None = None,
    profile: str | None = None,
) -> Iterator[tuple[int, int, int, dict[int, Optional[float]], Optional[float]]]:
    """Iterate rows from a *_bands.csv archive with common filtering.

    Returns tuples: (gen_ms, target_ms, horizon_min, {q: value_or_None}, band_scale_or_None).

    Notes:
    - Quantile columns are detected via :func:`detect_quantile_columns`.
    - If `profile` is provided, it is only enforced when a 'profile' column exists.
    - `band_scale` is included when a 'band_scale' column exists.
    """

    import csv

    qset = [int(q) for q in quantiles]

    with path.open("r", encoding="utf-8", newline="") as f:
        rd = csv.DictReader(f)
        qcols = detect_quantile_columns(rd.fieldnames)
        qnames: dict[int, str] = {q: qcols[q] for q in qset if q in qcols}
        has_profile_col = bool(rd.fieldnames and any(isinstance(n, str) and n.lower() == "profile" for n in rd.fieldnames))
        has_scale_col = bool(rd.fieldnames and any(isinstance(n, str) and n == "band_scale" for n in rd.fieldnames))

        prof_norm = str(profile).strip().lower() if isinstance(profile, str) else ""

        for row in rd:
            if not isinstance(row, dict):
                continue

            # Optional profile filter
            if prof_norm and has_profile_col:
                try:
                    pv = str(row.get("profile") or "").strip().lower()
                    if pv != prof_norm:
                        continue
                except (AttributeError, TypeError, ValueError):
                    pass

            gen_ms = parse_int(row, "gen_ms") or 0
            tgt_ms = parse_int(row, "target_ms") or 0
            hmin = parse_int(row, "horizon_min") or 0
            if not gen_ms or not tgt_ms:
                continue
            if horizon_min is not None and hmin != int(horizon_min):
                continue
            if gen_ms_min is not None and gen_ms < int(gen_ms_min):
                continue
            if target_ms_max is not None and tgt_ms > int(target_ms_max):
                continue

            qvals: dict[int, Optional[float]] = {}
            for q in qset:
                name = qnames.get(q)
                qvals[q] = (parse_float(row, name) if name else None)

            band_scale = parse_float(row, "band_scale") if has_scale_col else None
            yield int(gen_ms), int(tgt_ms), int(hmin), qvals, band_scale
