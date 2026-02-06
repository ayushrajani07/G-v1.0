from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

JsonLike = None | str | int | float | bool | Sequence["JsonLike"] | Mapping[str, "JsonLike"]


@dataclass
class OutputEvent:
    timestamp: str
    level: str
    message: str
    scope: str | None = None
    tags: list[str] | Mapping[str, str] | None = None
    data: JsonLike | None = None
    # Allow attaching arbitrary extras without breaking sinks
    extra: Mapping[str, Any] | None = None

    @staticmethod
    def now_iso() -> str:
        return datetime.now(UTC).isoformat().replace("+00:00", "Z")
