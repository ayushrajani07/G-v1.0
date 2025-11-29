from typing import Dict, Any, Callable


class AlertEngine:
    def __init__(self, sink: Callable[[str, Dict[str, Any]], None]):
        self._sink = sink

    def maybe_alert(self, name: str, metrics: Dict[str, Any], thresholds: Dict[str, float]) -> None:
        for k, thr in thresholds.items():
            v = metrics.get(k)
            if v is None:
                continue
            if k.endswith("_mae"):
                # example rule: higher is worse
                if v >= thr:
                    self._sink(name, {"metric": k, "value": v, "threshold": thr})
