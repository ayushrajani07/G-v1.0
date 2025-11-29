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
