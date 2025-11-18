from __future__ import annotations

from pathlib import Path
import sys
import unittest

# Ensure project root (containing src/) is on path if not already
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))


class TestSafeFileIOFailure:
    def test_safe_write_text_failure(self, monkeypatch, tmp_path):
        from src.error_handling import safe_write_text, get_error_handler, ErrorCategory

        handler = get_error_handler()
        start_len = len(handler.errors)

        # Monkeypatch Path.write_text to simulate filesystem failure
        def boom(self, content, encoding=None):  # pragma: no cover - forced failure path
            raise IOError("disk full simulated")

        monkeypatch.setattr(Path, "write_text", boom)

        target = tmp_path / "nested" / "fail.txt"
        ok = safe_write_text(target, "hello")
        assert ok is False, "safe_write_text should return False on failure"
        assert len(handler.errors) == start_len + 1, "ErrorHandler should record one new error"
        last = handler.errors[-1]
        assert last.category == ErrorCategory.FILE_IO
        assert 'fail.txt' in (last.context.get('path') or ''), "Context path should include filename"

    def test_safe_append_line_failure(self, monkeypatch, tmp_path):
        from src.error_handling import safe_append_line, get_error_handler, ErrorCategory

        handler = get_error_handler()
        start_len = len(handler.errors)

        # Create a dummy file first to ensure parent exists
        base = tmp_path / "append" / "file.txt"
        base.parent.mkdir(parents=True, exist_ok=True)
        base.write_text("initial\n", encoding="utf-8")

        # Monkeypatch Path.open to raise during append
        original_open = Path.open

        def bad_open(self, mode='r', *args, **kwargs):  # pragma: no cover - forced failure path
            if 'a' in mode:
                raise OSError("read-only filesystem simulated")
            return original_open(self, mode, *args, **kwargs)

        monkeypatch.setattr(Path, "open", bad_open)

        ok = safe_append_line(base, "new line")
        assert ok is False, "safe_append_line should return False on failure"
        assert len(handler.errors) == start_len + 1, "ErrorHandler should record one new error"
        last = handler.errors[-1]
        assert last.category == ErrorCategory.FILE_IO
        assert 'file.txt' in (last.context.get('path') or ''), "Context path should include filename"


class SafeFileIOFailureTests(unittest.TestCase):
    def test_safe_write_text_failure(self):
        import src.error_handling as eh
        ErrorCategory = eh.ErrorCategory
        handler = eh.get_error_handler()
        start_len = len(handler.errors)
        target = Path("_tmp_fail_write.txt")
        original = Path.write_text
        def failing(self, content, encoding=None):
            raise IOError("disk full simulated")
        Path.write_text = failing
        try:
            ok = eh.safe_write_text(target, "hello")
        finally:
            Path.write_text = original
        self.assertFalse(ok)
        self.assertEqual(len(handler.errors), start_len + 1)
        last = handler.errors[-1]
        self.assertEqual(last.category, ErrorCategory.FILE_IO)
        self.assertIn("_tmp_fail_write.txt", (last.context.get('path') or ''))

    def test_safe_append_line_failure(self):
        import src.error_handling as eh
        ErrorCategory = eh.ErrorCategory
        handler = eh.get_error_handler()
        start_len = len(handler.errors)
        base = Path("_tmp_fail_append.txt")
        base.write_text("initial\n", encoding="utf-8")
        original_open = Path.open
        def failing_open(self, mode='r', *args, **kwargs):
            if 'a' in mode:
                raise OSError("read-only filesystem simulated")
            return original_open(self, mode, *args, **kwargs)
        Path.open = failing_open
        try:
            ok = eh.safe_append_line(base, "new line")
        finally:
            Path.open = original_open
        self.assertFalse(ok)
        self.assertEqual(len(handler.errors), start_len + 1)
        last = handler.errors[-1]
        self.assertEqual(last.category, ErrorCategory.FILE_IO)
        self.assertIn("_tmp_fail_append.txt", (last.context.get('path') or ''))
