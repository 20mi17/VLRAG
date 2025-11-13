import os

from config import get_settings


def test_settings_reads_env(monkeypatch):
    # clear cache so we read fresh env variables
    get_settings.cache_clear()

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test-anon-key")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role")
    monkeypatch.setenv("ENV", "test")

    settings = get_settings()

    assert settings.openai_api_key == "test-openai-key"
    assert settings.supabase_url == "https://example.supabase.co"
    assert settings.supabase_anon_key == "test-anon-key"
    assert settings.supabase_service_role_key == "test-service-role"
    assert settings.env == "test"
    assert settings.has_openai is True
    assert settings.has_supabase is True


def test_settings_defaults_when_env_missing(monkeypatch):
    # clear cache so we read fresh env variables
    get_settings.cache_clear()

    # ensure env vars are not set
    for var in [
        "OPENAI_API_KEY",
        "SUPABASE_URL",
        "SUPABASE_ANON_KEY",
        "SUPABASE_SERVICE_ROLE_KEY",
        "ENV",
    ]:
        if var in os.environ:
            monkeypatch.delenv(var, raising=False)

    settings = get_settings()

    assert settings.openai_api_key is None
    assert settings.supabase_url is None
    assert settings.supabase_anon_key is None
    assert settings.supabase_service_role_key is None
    assert settings.env == "local"  # default
    assert settings.has_openai is False
    assert settings.has_supabase is False
