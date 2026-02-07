from src.collectors.pipeline.phase_result import PhaseRun, PipelineSummary


def test_pipeline_summary_from_runs_counts() -> None:
    runs = [
        PhaseRun(phase="resolve", final_outcome="ok", attempts=1, duration_ms=1.0),
        PhaseRun(phase="fetch", final_outcome="recoverable", attempts=3, duration_ms=10.5),
        PhaseRun(phase="enrich", final_outcome="ok", attempts=1, duration_ms=2.0),
        PhaseRun(phase="persist", final_outcome="fatal", attempts=1, duration_ms=0.5),
    ]

    summary = PipelineSummary.from_runs(runs, retry_enabled=True)
    d = summary.to_dict()

    assert d["phases_total"] == 4
    assert d["phases_ok"] == 2
    assert d["phases_error"] == 2
    assert d["phases_with_retries"] == 1
    assert d["retry_enabled"] is True
    assert d["aborted_early"] is False
    assert d["fatal"] is True
    assert d["recoverable_exhausted"] is False

    assert d["error_outcomes"]["recoverable"] == 1
    assert d["error_outcomes"]["fatal"] == 1
