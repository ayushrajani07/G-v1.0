from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/stream", tags=["stream"])


@router.post("/ingest")
async def ingest_item(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"invalid_json: {e}")

    ingestor = getattr(request.app.state, "ingestor", None)
    if ingestor is None:
        raise HTTPException(status_code=503, detail="ingestor_unavailable")

    try:
        ingestor.enqueue(payload)  # type: ignore[attr-defined]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"enqueue_failed: {e}")

    return JSONResponse({"status": "queued"})


@router.get("/metrics/live_mae")
async def get_live_mae(request: Request) -> JSONResponse:
    try:
        from src.monitoring.feedback import FeedbackLoop
    except Exception:
        raise HTTPException(status_code=503, detail="feedback_unavailable")

    fb = getattr(request.app.state, "feedback", None)
    if fb is None or not isinstance(fb, FeedbackLoop):
        raise HTTPException(status_code=503, detail="feedback_unavailable")

    try:
        m = fb.get_metrics()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"feedback_error: {e}")

    return JSONResponse({
        "observations": m.get("observations", 0),
        "mae": m.get("mae", None)
    })
