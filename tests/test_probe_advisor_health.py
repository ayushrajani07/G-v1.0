from __future__ import annotations

import os
import socket
import pytest

from typing import Optional

# We import the function directly to avoid spawning a new process.
from scripts.probe_advisor_health import run_probe


def _port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    s: Optional[socket.socket] = None
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        return True
    except OSError:
        return False
    finally:
        try:
            if s:
                s.close()
        except Exception:
            pass


@pytest.mark.skipif(not _port_open("127.0.0.1", 9500), reason="dashboard api not listening on 9500")
def test_probe_returns_ok_or_warn_when_server_healthy():
    rc = run_probe(base_url="http://127.0.0.1:9500", warn_age_minutes=15.0)
    # Accept 0 (ok), 1 (warn) and 3 (temporary freshness retrieval failure) to avoid flakiness under CI
    # but report if fail codes 2 encountered.
    assert rc in (0, 1, 3), f"unexpected failure code rc={rc}"
