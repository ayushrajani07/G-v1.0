import os

import pytest

from src.config.env_unknown import find_unknown_g6_env_vars, load_known_g6_env_from_docs, validate_unknown_env_vars


def test_find_unknown_g6_env_vars_respects_allowlist(monkeypatch):
    # Ensure a deterministic env sandbox
    monkeypatch.delenv("G6_FOO_UNKNOWN", raising=False)
    monkeypatch.delenv("G6_UNKNOWN_ENV_ALLOW", raising=False)

    known_exact, known_prefixes = load_known_g6_env_from_docs()

    monkeypatch.setenv("G6_FOO_UNKNOWN", "1")
    # Without allow: should be unknown (unless docs explicitly includes it)
    unknown = find_unknown_g6_env_vars(os.environ, known_exact=known_exact, known_prefixes=known_prefixes)
    assert "G6_FOO_UNKNOWN" in unknown

    # With allow: should not be unknown
    unknown2 = find_unknown_g6_env_vars(
        os.environ,
        known_exact=known_exact,
        known_prefixes=known_prefixes,
        allow_exact={"G6_FOO_UNKNOWN"},
    )
    assert "G6_FOO_UNKNOWN" not in unknown2


def test_validate_unknown_env_vars_strict_raises(monkeypatch):
    monkeypatch.setenv("G6_FAIL_ON_UNKNOWN_ENV_VARS", "1")
    fake_env = {"G6_FOO_UNKNOWN": "1"}
    with pytest.raises(RuntimeError):
        validate_unknown_env_vars(fake_env)


def test_validate_unknown_env_vars_strict_allows_prefix(monkeypatch):
    # Prefix-style allow ("G6_FOO*")
    monkeypatch.setenv("G6_FAIL_ON_UNKNOWN_ENV_VARS", "1")
    monkeypatch.setenv("G6_UNKNOWN_ENV_ALLOW", "G6_FOO*")
    fake_env = {"G6_FOO_UNKNOWN": "1"}

    # Should not raise due to allow prefix
    validate_unknown_env_vars(fake_env)


def test_validate_unknown_env_vars_strict_allows_known_from_code(monkeypatch):
    # docs/env_dict.md currently lags behind a number of real env vars.
    # Strict mode should still allow vars that are referenced in src/**/*.py.
    monkeypatch.setenv("G6_FAIL_ON_UNKNOWN_ENV_VARS", "1")
    fake_env = {"G6_BANNER_DEBUG": "1"}

    # Should not raise: G6_BANNER_DEBUG is referenced in src/collectors/**
    validate_unknown_env_vars(fake_env)
