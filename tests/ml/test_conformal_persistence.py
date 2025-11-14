from src.analytics.ml.conformal import ConformalBand

def test_conformal_preload_affects_radius_and_coverage():
    # Create band with small window for test
    band = ConformalBand(target_coverage=0.8, window=10)
    # Preload residuals simulating prior session
    preload = [0.5, 0.6, 0.4, 0.2, 0.9]
    band.extend_from_residuals(preload)
    # Without new updates, radius should reflect quantile of existing residuals
    rad = band.radius()
    assert rad > 0.0, "Expected non-zero radius from preloaded residuals"
    # Coverage estimate at that radius should be close to target (not exact due to small sample)
    cov_est = band.coverage_estimate(rad)
    assert 0.4 <= cov_est <= 1.0, f"Coverage estimate {cov_est} out of plausible range"


def test_conformal_update_appends_residual():
    band = ConformalBand(target_coverage=0.8, window=5)
    band.extend_from_residuals([0.1, 0.2])
    before_len = band._residuals.__len__()
    band.update(pred=10.0, actual=9.7)  # residual 0.3
    after_len = band._residuals.__len__()
    assert after_len == before_len + 1, "Residual not appended on update()"
    assert any(abs(r - 0.3) < 1e-6 for r in band._residuals), "Expected residual value missing"
