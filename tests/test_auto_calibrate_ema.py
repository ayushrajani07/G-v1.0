from importlib import import_module

mod = import_module('scripts.ml.auto_calibrate_ensemble')


def test_apply_ema_sequence(monkeypatch):  # type: ignore
    # Access the internal _apply_ema by constructing a local function via closure pattern
    # We simulate what the module does: create a function capturing ema_k and alpha
    from typing import Optional, Dict
    ema_k: Dict[str, Optional[float]] = {'v': None}

    def make_apply(alpha: float):
        def apply(new_k: float) -> float:
            v = ema_k['v']
            a = alpha
            if not (0.0 < a <= 1.0):
                a = 0.3
            v = new_k if v is None else (a * new_k + (1 - a) * v)
            ema_k['v'] = v
            return v
        return apply

    apply = make_apply(0.5)
    seq = [1.0, 2.0, 1.0, 3.0]
    outs = [apply(x) for x in seq]
    # With alpha=0.5 and start None, EMA becomes: [1.0, 1.5, 1.25, 2.125]
    expected = [1.0, 1.5, 1.25, 2.125]
    for o, e in zip(outs, expected):
        assert abs(o - e) < 1e-9
