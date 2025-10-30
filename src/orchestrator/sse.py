from __future__ import annotations

import json
import time
from typing import Any, Callable

# Optional imports
try:
    from src.events.latency_client import observe_event_latency
except ImportError:
    observe_event_latency = None  # type: ignore

try:
    from src.metrics import get_metrics
except ImportError:
    get_metrics = None  # type: ignore


def serve_events_sse(
    handler: Any,
    get_event_bus: Callable[[], Any] | None,
    env_int: Callable[[str, int], int],
    env_float: Callable[[str, float], float],
    is_truthy_env: Callable[[str], bool],
    logger: Any,
) -> None:
    """Serve Server-Sent Events stream for /events endpoint.

    Mirrors existing behavior in catalog_http, factored out for reuse.
    """
    if get_event_bus is None:
        handler.send_response(503)
        handler.send_header('Content-Type', 'application/json')
        handler.end_headers()
        handler.wfile.write(b'{"error":"event_bus_unavailable"}')
        return
    try:
        from urllib.parse import parse_qs, urlparse

        bus: Any = get_event_bus()
        parsed = urlparse(handler.path)
        qs = parse_qs(parsed.query or '')
        force_full = False
        try:
            vals = qs.get('force_full') or qs.get('forcefull') or []
            if vals:
                raw = vals[0]
                if raw is None or str(raw).strip() == '' or str(raw).lower() in ('1','true','yes','on'):
                    force_full = True
        except Exception:
            force_full = False
        type_filters: list[str] = []
        for key in ('type', 'types'):
            for item in qs.get(key, []):
                for part in item.split(','):
                    part = part.strip()
                    if part:
                        type_filters.append(part)
        type_filters = list(dict.fromkeys(type_filters))  # dedupe preserve order
        last_event_id = 0
        hdr_id = (handler.headers.get('Last-Event-ID') if handler.headers else None) or None
        if hdr_id:
            try:
                last_event_id = int(hdr_id)
            except Exception:
                last_event_id = 0
        if 'last_id' in qs:
            try:
                last_event_id = int(qs['last_id'][0])
            except Exception:
                pass
        backlog_limit = None
        if 'backlog' in qs:
            try:
                backlog_limit = max(0, int(qs['backlog'][0]))
            except Exception:
                backlog_limit = None
        retry_ms = env_int('G6_EVENTS_SSE_RETRY_MS', 5000)
        poll_interval = env_float('G6_EVENTS_SSE_POLL', 0.5)
        heartbeat_interval = env_float('G6_EVENTS_SSE_HEARTBEAT', 5.0)
        last_heartbeat = time.time()
        conn_start_ts = time.time()
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.send_header('Cache-Control', 'no-cache')
        handler.send_header('Connection', 'keep-alive')
        handler.end_headers()
        handler.wfile.write(f"retry: {retry_ms}\n".encode())
        handler.wfile.flush()
        try:
            if hasattr(bus, '_consumer_started'):
                fn = getattr(bus, '_consumer_started', None)
                if callable(fn):
                    fn()
        except Exception:
            pass

        def _send(event) -> None:
            nonlocal last_event_id, last_heartbeat
            payload = event.as_sse_payload()
            if observe_event_latency is not None:
                try:
                    observe_event_latency(payload)
                except Exception:
                    pass
            evt_type = payload.get('type')
            if type_filters and evt_type not in type_filters:
                return
            try:
                if is_truthy_env('G6_SSE_FLUSH_LATENCY_CAPTURE'):
                    try:
                        pub_ts = None
                        if isinstance(payload, dict):
                            inner = payload.get('payload')
                            if isinstance(inner, dict):
                                pub_ts = inner.get('publish_unixtime')
                        if isinstance(pub_ts, (int,float)):
                            now_ts = time.time()
                            flush_latency = max(0.0, now_ts - pub_ts)
                            if get_metrics is not None:
                                m = get_metrics()
                                if m and hasattr(m, 'sse_flush_seconds'):
                                    try:
                                        hist = m.sse_flush_seconds
                                        observe = getattr(hist, 'observe', None)
                                        if callable(observe):
                                            observe(flush_latency)
                                    except Exception:
                                        pass
                    except Exception:
                        pass
                if is_truthy_env('G6_SSE_TRACE') and isinstance(payload, dict):
                    try:
                        inner = payload.get('payload')
                        if isinstance(inner, dict):
                            tr = inner.get('_trace')
                            if isinstance(tr, dict) and 'flush_ts' not in tr:
                                tr['flush_ts'] = time.time()
                                if get_metrics is not None:
                                    try:
                                        m = get_metrics()
                                        if m and hasattr(m, 'sse_trace_stages_total'):
                                            ctr = m.sse_trace_stages_total
                                            inc = getattr(ctr, 'inc', None)
                                            if callable(inc):
                                                inc()
                                    except Exception:
                                        pass
                    except Exception:
                        pass
                handler.wfile.write(f"id: {event.event_id}\n".encode())
                if evt_type:
                    handler.wfile.write(f"event: {evt_type}\n".encode())
                data = json.dumps(payload, separators=(',', ':'))
                handler.wfile.write(f"data: {data}\n\n".encode())
                handler.wfile.flush()
                last_event_id = event.event_id
                last_heartbeat = time.time()
            except Exception:
                raise

        # Initial backlog replay
        try:
            if force_full:
                try:
                    latest_full = getattr(bus, 'latest_full_snapshot', None)
                    if callable(latest_full):
                        snap = latest_full()
                        if isinstance(snap, dict):
                            class _Synthetic:
                                def __init__(self, eid: int, payload: dict, gen: int):
                                    self.event_id = eid
                                    self._payload = payload
                                    self.event_type = 'panel_full'
                                    self._gen = gen
                                def as_sse_payload(self):
                                    p = dict(self._payload)
                                    if '_generation' not in p:
                                        p['_generation'] = getattr(bus, '_generation', 0)
                                    return {
                                        'id': self.event_id,
                                        'sequence': self.event_id,
                                        'type': 'panel_full',
                                        'timestamp_ist': p.get('timestamp_ist') or '',
                                        'payload': p,
                                        'generation': p.get('_generation'),
                                        'publish_unixtime': time.time(),
                                    }
                            synthetic = _Synthetic(last_event_id, snap, getattr(bus, '_generation', 0))
                            _send(synthetic)
                except Exception:
                    logger.debug("catalog_http: force_full injection failed", exc_info=True)
            bus_any = bus  # type: ignore[assignment]
            for ev in bus_any.get_since(last_event_id, limit=backlog_limit):
                _send(ev)
        except Exception:
            return

        try:
            while True:
                try:
                    pending = bus.get_since(last_event_id)
                    if pending:
                        for ev in pending:
                            _send(ev)
                    else:
                        now = time.time()
                        if now - last_heartbeat >= heartbeat_interval:
                            try:
                                handler.wfile.write(b': keep-alive\n\n')
                                handler.wfile.flush()
                            except Exception:
                                break
                            last_heartbeat = now
                        time.sleep(poll_interval)
                except Exception:
                    break
        finally:
            try:
                _geb2 = get_event_bus
                if _geb2 is not None:
                    bus2 = _geb2()
                    duration = max(0.0, time.time() - conn_start_ts)
                    if hasattr(bus2, '_observe_connection_duration'):
                        try:
                            fn = getattr(bus2, '_observe_connection_duration', None)
                            if callable(fn):
                                fn(duration)
                        except Exception:
                            pass
                    if hasattr(bus2, '_consumer_stopped'):
                        fn2 = getattr(bus2, '_consumer_stopped', None)
                        if callable(fn2):
                            fn2()
            except Exception:
                pass
    except Exception:
        logger.exception("catalog_http: failure serving SSE events")


def serve_adaptive_theme_sse(
    handler: Any,
    get_cache: Callable[[], tuple[Any, float]],
    set_cache: Callable[[Any, float], None],
    theme_ttl_seconds: Callable[[], float],
    build_adaptive_payload: Callable[[], Any],
    force_window_env: Callable[[Any], Any],
    env_float: Callable[[str, float], float],
    env_int: Callable[[str, int], int],
    is_truthy_env: Callable[[str], bool],
    logger: Any,
) -> None:
    try:
        handler.send_response(200)
        handler.send_header('Content-Type', 'text/event-stream')
        handler.send_header('Cache-Control', 'no-cache')
        handler.send_header('Connection', 'keep-alive')
        handler.end_headers()
        interval = env_float('G6_ADAPTIVE_THEME_STREAM_INTERVAL', 3.0)
        max_events = env_int('G6_ADAPTIVE_THEME_STREAM_MAX_EVENTS', 200)
        diff_only = is_truthy_env('G6_ADAPTIVE_THEME_SSE_DIFF')
        last_payload = None
        for _i in range(max_events):
            ttl = theme_ttl_seconds()
            now = time.time()
            cache_payload, cache_ts = get_cache()
            if ttl > 0 and (now - cache_ts) < ttl and cache_payload is not None:
                full_payload = cache_payload
            else:
                full_payload = build_adaptive_payload()
                if ttl > 0:
                    set_cache(full_payload, now)
            send_obj = force_window_env(full_payload)
            if not diff_only and last_payload is not None and full_payload == last_payload:
                try:
                    time.sleep(interval)
                    continue
                except Exception:
                    break
            if (
                diff_only
                and last_payload is not None
                and isinstance(full_payload, dict)
                and isinstance(last_payload, dict)
            ):
                diff: dict[str, Any] = {'diff': True}
                try:
                    if full_payload.get('active_counts') != last_payload.get('active_counts'):
                        diff['active_counts'] = full_payload.get('active_counts')
                    cur_pt = full_payload.get('per_type') or {}
                    prev_pt = last_payload.get('per_type') or {}
                    changed_pt = {}
                    for k, v in cur_pt.items():
                        pv = prev_pt.get(k)
                        if (
                            not isinstance(pv, dict)
                            or pv.get('active') != v.get('active')
                            or pv.get('resolved_count') != v.get('resolved_count')
                            or pv.get('last_change_cycle') != v.get('last_change_cycle')
                        ):
                            changed_pt[k] = v
                    if changed_pt:
                        diff['per_type'] = changed_pt
                    cur_trend = (full_payload.get('trend') or {})
                    prev_trend = (last_payload.get('trend') or {})
                    send_trend = {}
                    for fld in ('critical_ratio','warn_ratio'):
                        if cur_trend.get(fld) != prev_trend.get(fld):
                            send_trend[fld] = cur_trend.get(fld)
                    try:
                        cur_snaps = cur_trend.get('snapshots') or []
                        prev_snaps = prev_trend.get('snapshots') or []
                        if cur_snaps and prev_snaps:
                            cur_last = cur_snaps[-1]
                            prev_last = prev_snaps[-1]
                            if cur_last.get('counts') != prev_last.get('counts'):
                                send_trend['latest'] = cur_last.get('counts')
                    except Exception:
                        pass
                    if send_trend:
                        diff['trend'] = send_trend
                    if len(diff) > 1:
                        send_obj = diff
                except Exception:
                    send_obj = full_payload
            data = json.dumps(send_obj)
            try:
                handler.wfile.write(f"data: {data}\n\n".encode())
                handler.wfile.flush()
            except Exception:
                break
            last_payload = full_payload
            time.sleep(interval)
    except Exception:
        logger.exception("catalog_http: SSE adaptive theme failure")


__all__ = [
    'serve_events_sse',
    'serve_adaptive_theme_sse',
]
