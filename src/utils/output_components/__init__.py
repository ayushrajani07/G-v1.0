"""Extracted helpers from src.utils.output.

This package exists to break the huge src/utils/output.py into smaller, testable
units while keeping src.utils.output as the stable public facade.
"""

from .atomic import atomic_replace, atomic_write_json
from .events import JsonLike, OutputEvent
from .panels_sink import PanelFileSink
from .sinks import JsonlSink, LoggingSink, MemorySink, OutputSink, RichSink, StdoutSink

__all__ = [
    "JsonLike",
    "OutputEvent",
    "PanelFileSink",
    "OutputSink",
    "StdoutSink",
    "LoggingSink",
    "RichSink",
    "JsonlSink",
    "MemorySink",
    "atomic_replace",
    "atomic_write_json",
]
