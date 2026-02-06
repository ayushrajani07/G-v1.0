from contextlib import suppress
import json
import logging

import pytest

from src.utils.logging_utils import setup_logging


def _detach_root_handlers() -> tuple[logging.Logger, list[logging.Handler], int]:
    root = logging.getLogger()
    existing = list(root.handlers)
    level = root.level
    for h in existing:
        with suppress(Exception):
            root.removeHandler(h)
    return root, existing, level


def _restore_root_handlers(root: logging.Logger, previous: list[logging.Handler], level: int) -> None:
    for h in list(root.handlers):
        with suppress(Exception):
            root.removeHandler(h)
        with suppress(Exception):
            h.close()

    root.setLevel(level)
    for h in previous:
        with suppress(Exception):
            root.addHandler(h)


def test_setup_logging_minimal_console_format(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Ensure env flags do not flip to verbose/full formatting.
    monkeypatch.delenv("G6_VERBOSE_CONSOLE", raising=False)
    monkeypatch.delenv("G6_DISABLE_MINIMAL_CONSOLE", raising=False)
    monkeypatch.delenv("G6_JSON_LOGS", raising=False)

    root, previous, level = _detach_root_handlers()
    try:
        setup_logging(level="INFO")
        logging.getLogger("test_logging_utils").info("hello")
        out = capsys.readouterr().out
        assert out.strip() == "hello"
    finally:
        _restore_root_handlers(root, previous, level)


def test_setup_logging_json_console(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("G6_JSON_LOGS", "1")
    monkeypatch.delenv("G6_VERBOSE_CONSOLE", raising=False)

    root, previous, level = _detach_root_handlers()
    try:
        setup_logging(level="INFO")
        logging.getLogger("test_logging_utils").info("hello")
        line = capsys.readouterr().out.strip()
        payload = json.loads(line)
        assert payload["msg"] == "hello"
        assert payload["level"] == "INFO"
        assert payload["logger"] == "test_logging_utils"
    finally:
        _restore_root_handlers(root, previous, level)
