from __future__ import annotations

import typing as t

# Minimal contract test for pipeline return shape with empty indices.

def test_pipeline_return_shape_empty_indices(monkeypatch):
    # Import here to avoid import-time side-effects if any
    from src.collectors.modules.pipeline import run_pipeline

    # Call with empty index_params so no provider interactions occur
    result = run_pipeline(
        index_params={},
        providers=None,   # not used when no indices
        csv_sink=None, metrics=None,
        build_snapshots=False,
        legacy_baseline=None,
    )

    assert isinstance(result, dict), "pipeline should return a dict"
    # Required top-level keys
    for key in (
        'status', 'indices_processed', 'have_raw', 'snapshots', 'snapshot_count', 'indices', 'partial_reason_totals'
    ):
        assert key in result, f"missing key: {key}"

    assert result['status'] == 'ok'
    assert result['indices_processed'] == 0
    assert isinstance(result['indices'], list)
    assert result['indices'] == []
    assert isinstance(result['partial_reason_totals'], dict)
