from __future__ import annotations

from dataclasses import asdict
import json
import logging
import sys
from typing import Any, Protocol

from .events import OutputEvent

# Optional Rich support
try:
    import rich.console as _rich_console
except Exception:  # pragma: no cover
    _rich_console = None  # type: ignore[assignment]


class OutputSink(Protocol):
    def emit(self, event: OutputEvent) -> None:  # pragma: no cover
        ...


class StdoutSink:
    def __init__(self, stream: Any = sys.stdout) -> None:
        self._stream = stream

    def emit(self, event: OutputEvent) -> None:
        base = f"[{event.level.upper()}] {event.message}"
        if event.scope:
            base = f"({event.scope}) " + base
        if event.tags:
            base += f" tags={event.tags}"
        if event.data is not None:
            try:
                payload = json.dumps(event.data, ensure_ascii=False, default=str)
            except Exception:
                payload = str(event.data)
            base += f" data={payload}"
        try:
            self._stream.write(base + "\n")
        except Exception:
            print(base, file=self._stream)
        try:
            flush = getattr(self._stream, "flush", None)
            if callable(flush):
                flush()
        except Exception:
            pass


class LoggingSink:
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("g6")
        if not self._logger.handlers:
            logging.basicConfig(level=logging.INFO)

    def emit(self, event: OutputEvent) -> None:
        lvl_map = {
            "debug": logging.DEBUG,
            "info": logging.INFO,
            "success": logging.INFO,
            "warning": logging.WARNING,
            "warn": logging.WARNING,
            "error": logging.ERROR,
            "critical": logging.CRITICAL,
        }
        lvl = lvl_map.get(event.level.lower(), logging.INFO)
        msg = event.message
        extra = {
            "scope": event.scope,
            "tags": event.tags,
            "data": event.data,
            **(event.extra or {}),
        }
        try:
            self._logger.log(lvl, msg, extra=extra)
        except Exception:
            self._logger.log(lvl, msg)


class RichSink:
    def __init__(self, console: Any | None = None) -> None:
        if console is not None:
            self._console = console
        elif _rich_console is not None:
            try:
                self._console = _rich_console.Console()
            except Exception:  # pragma: no cover
                self._console = None
        else:
            self._console = None

    def emit(self, event: OutputEvent) -> None:
        if not self._console:
            return
        style = {
            "debug": "dim",
            "info": "",
            "success": "green",
            "warning": "yellow",
            "warn": "yellow",
            "error": "red",
            "critical": "bold red",
        }.get(event.level.lower(), "")
        payload = ""
        if event.data is not None:
            try:
                payload = json.dumps(event.data, ensure_ascii=False, default=str)
            except Exception:
                payload = str(event.data)
            payload = f"\n[data]\n{payload}"
        tags = f" tags={event.tags}" if event.tags else ""
        scope = f"({event.scope}) " if event.scope else ""
        self._console.print(f"{scope}[{style}]{event.level.upper()}[/] {event.message}{tags}{payload}")


class JsonlSink:
    def __init__(self, path: str) -> None:
        self._path = path

    def emit(self, event: OutputEvent) -> None:
        rec = asdict(event)
        try:
            line = json.dumps(rec, ensure_ascii=False, default=str)
        except Exception:
            rec["data"] = str(event.data)
            line = json.dumps(rec, ensure_ascii=False, default=str)
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


class MemorySink:
    def __init__(self) -> None:
        self.events: list[OutputEvent] = []

    def emit(self, event: OutputEvent) -> None:
        self.events.append(event)
