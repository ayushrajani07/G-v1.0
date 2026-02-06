from __future__ import annotations

from src.web.dashboard.routes._index_norm import normalize_index


def test_normalize_index_uppercase_and_strip():
    assert normalize_index("  nifty ") == "NIFTY"


def test_normalize_index_placeholder_defaults():
    assert normalize_index("${index}") == "NIFTY"


def test_normalize_index_none_defaults():
    assert normalize_index(None) == "NIFTY"


def test_normalize_index_custom_default():
    assert normalize_index("${x}", default="SENSEX") == "SENSEX"
