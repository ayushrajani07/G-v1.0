from fastapi import APIRouter, Response

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics() -> Response:
    try:
        from ..prom_metrics import get_registry
        reg = get_registry()
        if reg is None:
            return Response(status_code=503, content=b"metrics_disabled", media_type="text/plain; charset=utf-8")
        from prometheus_client import generate_latest
        payload = generate_latest(reg)
        return Response(content=payload, media_type="text/plain; charset=utf-8")
    except Exception:
        return Response(status_code=503, content=b"metrics_error", media_type="text/plain; charset=utf-8")
