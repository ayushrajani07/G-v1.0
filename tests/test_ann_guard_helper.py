from scripts.ml.path_forecast_grid_eval import _apply_ann_mad_guard


def test_guard_triggers_and_falls_back():
    # Construct dummy qmaps
    qmap_ann = {0.5: [100, 101]}
    qmap_base = {0.5: [100, 100]}
    times_ann = [1, 2]
    times_base = [1, 2]
    ann_q50_mad = 0.6
    threshold = 0.5
    ann_speedup = 2.0
    latency_ms = 50
    baseline_latency_ms = 100

    new_qmap, new_times, new_speed, new_mad, trig, orig_mad, new_lat = _apply_ann_mad_guard(
        qmap_ann,
        times_ann,
        qmap_base,
        times_base,
        ann_q50_mad,
        threshold,
        ann_speedup,
        latency_ms,
        baseline_latency_ms,
    )

    assert trig == 1
    assert orig_mad == ann_q50_mad
    assert new_qmap == qmap_base
    assert new_times == times_base
    assert new_speed is None
    assert new_mad is None
    assert new_lat == baseline_latency_ms


def test_guard_noop_when_below_threshold():
    qmap_ann = {0.5: [100, 101]}
    qmap_base = {0.5: [100, 100]}
    times_ann = [1, 2]
    times_base = [1, 2]
    ann_q50_mad = 0.4
    threshold = 0.5
    ann_speedup = 2.0
    latency_ms = 50
    baseline_latency_ms = 100

    new_qmap, new_times, new_speed, new_mad, trig, orig_mad, new_lat = _apply_ann_mad_guard(
        qmap_ann, times_ann, qmap_base, times_base, ann_q50_mad, threshold, ann_speedup, latency_ms, baseline_latency_ms
    )

    assert trig == 0
    assert orig_mad is None
    assert new_qmap == qmap_ann
    assert new_times == times_ann
    assert new_speed == ann_speedup
    assert new_mad == ann_q50_mad
    assert new_lat == latency_ms
