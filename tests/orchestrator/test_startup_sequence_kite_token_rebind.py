import os


def test_kite_auth_validation_rebinds_provider_and_provider_config(monkeypatch):
    # Import inside test so monkeypatching happens on the module instance used.
    from src.orchestrator import startup_sequence as ss
    from src.provider.config import get_provider_config

    # Seed env with an "old" token and warm the ProviderConfig singleton.
    monkeypatch.setenv("KITE_API_KEY", "dummy_api_key")
    monkeypatch.setenv("KITE_API_SECRET", "dummy_api_secret")
    monkeypatch.setenv("KITE_ACCESS_TOKEN", "OLD_TOKEN")
    _ = get_provider_config(refresh=True)

    class FakeProvider:
        def __init__(self):
            self.called = False
            self.kwargs = None

        def update_credentials(self, **kwargs):
            self.called = True
            self.kwargs = kwargs

    class FakeProviders:
        def __init__(self):
            self.primary_provider = FakeProvider()

    class FakeTM:
        @staticmethod
        def load_env_vars() -> bool:
            return True

        @staticmethod
        def _kite_validate_token(api_key: str, access_token: str) -> bool:
            # Force a refresh path.
            return False

        @staticmethod
        def acquire_or_refresh_token(*, auto_open_browser: bool, interactive: bool, validate_after: bool) -> bool:
            # Mimic token-manager behavior: update env token in-process.
            os.environ["KITE_ACCESS_TOKEN"] = "NEW_TOKEN"
            return True

    # Patch token manager in the startup sequence module.
    monkeypatch.setattr(ss, "tm", FakeTM)

    class Ctx:
        providers = FakeProviders()

    ss.kite_auth_validation(Ctx())

    # ProviderConfig singleton should reflect refreshed token.
    snap = get_provider_config()
    assert snap.access_token == "NEW_TOKEN"

    # Existing provider should have been rebound with refreshed token.
    prov = Ctx.providers.primary_provider
    assert prov.called is True
    assert prov.kwargs["access_token"] == "NEW_TOKEN"
    assert prov.kwargs.get("rebuild") is True
