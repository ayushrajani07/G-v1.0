"""Test that scripts.summary.app.run works correctly.

Since the legacy summary_view wrapper has been removed, we test the
unified app directly.
"""
from __future__ import annotations


def test_summary_app_run_directly(monkeypatch):
    """Test that the unified summary app can be called with standard args."""
    called = {}
    def fake_run(argv):  # noqa: D401
        called['args'] = list(argv) if argv else []
        return 0
    import scripts.summary.app as app_mod
    monkeypatch.setattr(app_mod, 'run', fake_run)
    # Test direct invocation of the unified app
    rc = app_mod.run(['--no-rich', '--cycles', '1'])
    assert rc == 0
    assert called.get('args') == ['--no-rich', '--cycles', '1']
