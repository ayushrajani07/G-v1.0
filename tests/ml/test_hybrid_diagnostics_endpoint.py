from __future__ import annotations

import tempfile
from pathlib import Path
from typing import List

import math

# We will call the diagnostics function directly by importing the router module.
# This avoids needing the whole ASGI stack. The function returns a PlainTextResponse.

from src.web.dashboard.routes.ml import api_ml_diagnostics  # type: ignore
from fastapi import Query
import asyncio

# Helper to write synthetic prediction CSVs

def _write_primary_csv(fp: Path, rows: List[str]) -> None:
    fp.write_text("timestamp,prediction,model,index,horizon\n" + "\n".join(rows), encoding="utf-8")


def _write_hybrid_csv(fp: Path, rows: List[str]) -> None:
    fp.write_text("timestamp,prediction,baseline,residual,model,index,horizon\n" + "\n".join(rows), encoding="utf-8")


def _write_live_csv(fp: Path, rows: List[str]) -> None:
    # Minimal live csv containing ts,tp
    fp.write_text("ts,tp\n" + "\n".join(rows), encoding="utf-8")


async def _call(index="TEST", horizon="1", model="all"):
    return await api_ml_diagnostics(
        index=Query(index).default,
        horizon=Query(horizon).default,
        model=Query(model).default,
        expiry_tag=Query("this_week").default,
        offset=Query("0").default,
        bucket_ms=Query(60000).default,
        window_minutes=Query(120).default,
        include_bands=Query(False).default,
        coverage=Query(0.8).default,
    )


def test_hybrid_diagnostics_improvement(tmp_path: Path, monkeypatch):
    # Arrange: create synthetic directories mimicking project_root layout
    data_root = tmp_path / "data" / "ml" / "live_predictions"
    data_root.mkdir(parents=True, exist_ok=True)
    g6_data_root = tmp_path / "data" / "g6_data"
    g6_data_root.mkdir(parents=True, exist_ok=True)

    # Monkeypatch project_root to point at tmp_path
    from src.web.dashboard.core import paths as _paths  # type: ignore

    monkeypatch.setattr(_paths, "project_root", lambda: tmp_path)

    # Live TP stream: increasing underlying true tp values around ~100 with slight noise
    # Use epoch ms timestamps spaced 1 minute apart
    base_ts = 1_700_000_000_000  # arbitrary epoch ms
    live_rows = []
    tp_vals = []
    for i in range(30):
        ts = base_ts + i * 60_000
        tp = 100 + math.sin(i / 5) * 2  # mild oscillation
        tp_vals.append(tp)
        live_rows.append(f"{ts},{tp}")
    _write_live_csv(g6_data_root / "TEST_this_week_0.csv", live_rows)

    # Primary model predictions: slightly worse (add more noise)
    primary_rows = []
    for i, tp in enumerate(tp_vals):
        pred = tp + math.sin(i / 3) * 4  # larger deviation
        iso = "2025-11-10T10:{:02d}:00".format(i)
        primary_rows.append(f"{iso},{pred},sk_hgb_regressor,TEST,1")
    _write_primary_csv(data_root / "TEST.csv", primary_rows)

    # Hybrid predictions: baseline + residual
    # Baseline = tp + small bias; residual corrects most of it
    hybrid_rows = []
    for i, tp in enumerate(tp_vals):
        baseline = tp + 1.5  # structural slight overestimate
        residual = -1.2 + math.sin(i / 4) * 0.2  # learned correction
        hybrid_pred = baseline + residual
        iso = "2025-11-10T10:{:02d}:00".format(i)
        hybrid_rows.append(f"{iso},{hybrid_pred},{baseline},{residual},sk_hgb_residual,TEST,1")
    _write_hybrid_csv(data_root / "TEST_hybrid.csv", hybrid_rows)

    # Act
    resp = asyncio.run(_call(index="TEST", horizon="1", model="all"))
    # PlainTextResponse .body is a bytes-like (memoryview) in FastAPI; ensure str
    if hasattr(resp, "body"):
        body_bytes = bytes(resp.body)  # type: ignore[attr-defined]
        csv_text = body_bytes.decode("utf-8")
    else:  # pragma: no cover - fallback
        csv_text = str(resp)

    # Assert header contains hybrid extras
    header = csv_text.splitlines()[0].split(",")
    assert "baseline_rmse" in header
    assert "hybrid_rmse" in header
    assert "improvement_ratio" in header
    assert "last_baseline" in header
    assert "last_residual" in header

    # Find hybrid row
    lines = csv_text.splitlines()[1:]
    hybrid_line = next(l for l in lines if l.startswith("sk_hgb_residual,"))
    parts = hybrid_line.split(",")
    # Map header to values
    hmap = {h: parts[i] for i, h in enumerate(header)}

    baseline_rmse = float(hmap.get("baseline_rmse") or 0)
    hybrid_rmse = float(hmap.get("hybrid_rmse") or 0)
    improvement_ratio = float(hmap.get("improvement_ratio") or 0)

    # Hybrid should improve (ratio > 1)
    assert baseline_rmse > 0
    assert hybrid_rmse > 0
    assert improvement_ratio > 1.0, f"Expected improvement_ratio > 1, got {improvement_ratio}"