"""Settings are env-overridable; verify the wiring rather than assume it."""

from app.config import Settings


def test_defaults():
    s = Settings()
    assert s.base_url == "https://hiringcafe.com"
    assert s.cache_ttl == 300.0
    assert s.max_concurrency == 4
    assert s.max_search_state_bytes == 20_000
    assert s.impersonate == "chrome"


def test_env_overrides_are_applied(monkeypatch):
    monkeypatch.setenv("HC_CACHE_TTL", "42")
    monkeypatch.setenv("HC_MAX_CONCURRENCY", "7")
    monkeypatch.setenv("HC_IMPERSONATE", "firefox")
    monkeypatch.setenv("HC_LOG_LEVEL", "debug")
    monkeypatch.setenv("HC_MAX_SEARCH_STATE_BYTES", "1234")

    s = Settings.from_env()

    assert s.cache_ttl == 42.0
    assert s.max_concurrency == 7
    assert s.impersonate == "firefox"
    assert s.log_level == "debug"
    assert s.max_search_state_bytes == 1234


def test_invalid_env_numbers_fall_back_to_defaults(monkeypatch):
    monkeypatch.setenv("HC_TIMEOUT", "not-a-number")
    monkeypatch.setenv("HC_CACHE_TTL", "")

    s = Settings.from_env()

    assert s.timeout == 30.0
    assert s.cache_ttl == 300.0


def test_concurrency_is_clamped_to_at_least_one(monkeypatch):
    monkeypatch.setenv("HC_MAX_CONCURRENCY", "0")
    assert Settings.from_env().max_concurrency == 1
