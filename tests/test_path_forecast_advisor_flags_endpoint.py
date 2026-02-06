import pytest
from fastapi.responses import JSONResponse
import json

from src.web.dashboard.routes.path_forecast._advisor_flags_handler import handle_path_advisor_flags


@pytest.mark.asyncio
async def test_path_advisor_flags_basic():
    async def fake_advisor(**kwargs):
        # Minimal payload shape expected by _advisor_flags_handler
        return JSONResponse(
            {
                "summary": {
                    "fallback": False,
                    "band_scale": 5.2,
                    "gap_abs": 0.07,
                    "samples": 42,
                }
            }
        )

    resp = await handle_path_advisor_flags(
        index="NIFTY",
        horizon=60,
        window_minutes=180,
        expiry_tag="this_week",
        offset="0",
        bucket_ms=60_000,
        date_str=None,
        gap_warn=0.05,
        gap_crit=0.10,
        min_samples_warn=30,
        min_samples_crit=10,
        compute_advisor=fake_advisor,
    )

    assert isinstance(resp, JSONResponse)
    data = json.loads(resp.body.decode("utf-8"))
    assert data["fallback"] == 0
    assert data["sat_hi"] == 1
    assert data["sat_lo"] == 0
    assert data["gap_abs"] == 0.07
    assert data["samples"] == 42
    assert data["band_scale"] == 5.2


@pytest.mark.asyncio
async def test_path_advisor_flags_missing_summary():
    async def fake_advisor(**kwargs):
        # No summary -> should return zeros/None consistently
        return JSONResponse({"ok": True})

    resp = await handle_path_advisor_flags(
        index="NIFTY",
        horizon=60,
        window_minutes=180,
        expiry_tag="this_week",
        offset="0",
        bucket_ms=60_000,
        date_str=None,
        gap_warn=0.05,
        gap_crit=0.10,
        min_samples_warn=30,
        min_samples_crit=10,
        compute_advisor=fake_advisor,
    )

    assert isinstance(resp, JSONResponse)
    data = json.loads(resp.body.decode("utf-8"))
    assert data["fallback"] == 0
    assert data["sat_hi"] == 0
    assert data["sat_lo"] == 0
    assert data["gap_abs"] is None
    assert data["samples"] == 0
    assert data["band_scale"] is None
