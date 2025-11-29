import asyncio
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/stream/sse", tags=["sse"])


def _format_sse_event(event: str, data: dict) -> bytes:
    payload = json.dumps(data, separators=(",", ":"))
    return f"event: {event}\ndata: {payload}\n\n".encode("utf-8")


@router.get("/live_mae")
async def sse_live_mae(request: Request, interval_ms: int = 1000) -> StreamingResponse:
    fb = getattr(request.app.state, "feedback", None)
    if fb is None:
        raise HTTPException(status_code=503, detail="feedback_unavailable")

    async def _gen() -> AsyncGenerator[bytes, None]:
        # Send an initial hello event
        yield _format_sse_event("hello", {"status": "ok"})
        try:
            while True:
                # Client disconnect check
                if await request.is_disconnected():
                    break
                try:
                    m = fb.get_metrics()
                    yield _format_sse_event("live_mae", {
                        "observations": m.get("observations", 0),
                        "mae": m.get("mae", None)
                    })
                except Exception:
                    # emit a best-effort error event and continue
                    yield _format_sse_event("error", {"message": "metrics_unavailable"})
                await asyncio.sleep(max(0.001, float(interval_ms) / 1000.0))
        finally:
            # graceful stream end
            yield _format_sse_event("bye", {"reason": "client_disconnect"})

    return StreamingResponse(_gen(), media_type="text/event-stream")


@router.get("/live")
async def sse_live(
    request: Request,
    interval_ms: int = 1000,
    index: str = "NIFTY",
    window: int = 30,
) -> StreamingResponse:
    """Consolidated SSE stream: emits live_mae and drift placeholders.

    Future: add real drift signals when implemented; for now emits stub fields.
    """
    fb = getattr(request.app.state, "feedback", None)
    if fb is None:
        raise HTTPException(status_code=503, detail="feedback_unavailable")

    async def _gen() -> AsyncGenerator[bytes, None]:
        yield _format_sse_event("hello", {"status": "ok"})
        try:
            while True:
                if await request.is_disconnected():
                    break
                # Live MAE
                try:
                    m = fb.get_metrics()
                    yield _format_sse_event("live_mae", {
                        "observations": m.get("observations", 0),
                        "mae": m.get("mae", None)
                    })
                except Exception:
                    yield _format_sse_event("error", {"message": "metrics_unavailable"})

                # Drift metrics from DriftMonitor (history/accuracy)
                try:
                    from . import drift as drift_routes
                    mon = getattr(drift_routes, "_monitor", None)
                    drift_payload = {"status": "unknown"}
                    if mon is not None:
                        # Use long-term accuracy as a proxy for drift score
                        acc = mon.get_long_term_accuracy(index=index, window=window)
                        drift_payload.update({
                            "status": "ok",
                            "mae": acc.get("mae", None),
                            "mape": acc.get("mape", None),
                            "window": window,
                            "index": index,
                        })
                        # Optionally include recent history sample
                        hist = mon.load_history(index=index, limit=1)
                        if hist:
                            drift_payload["last"] = hist[0]
                    yield _format_sse_event("drift", drift_payload)
                except Exception:
                    yield _format_sse_event("error", {"message": "drift_unavailable"})

                await asyncio.sleep(max(0.001, float(interval_ms) / 1000.0))
        finally:
            yield _format_sse_event("bye", {"reason": "client_disconnect"})

    return StreamingResponse(_gen(), media_type="text/event-stream")
