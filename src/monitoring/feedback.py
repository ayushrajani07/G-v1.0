from typing import Dict, Any


class FeedbackLoop:
    def __init__(self):
        self._stats: Dict[str, Any] = {
            "count": 0,
            "mae_sum": 0.0,
        }

    def observe(self, y_true: float, y_pred: float) -> None:
        err = abs(y_true - y_pred)
        self._stats["count"] += 1
        self._stats["mae_sum"] += err

    def get_metrics(self) -> Dict[str, Any]:
        c = self._stats["count"] or 1
        return {
            "observations": self._stats["count"],
            "mae": self._stats["mae_sum"] / c,
        }
