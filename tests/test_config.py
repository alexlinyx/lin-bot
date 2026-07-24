import pytest
from pydantic import ValidationError

from linbot.config import Settings, load_settings


def make(**kwargs):
    return Settings(_env_file=None, **kwargs)


def test_deepseek_requires_api_key():
    with pytest.raises(ValidationError, match="DEEPSEEK_API_KEY"):
        make(provider="deepseek", database_url="sqlite+aiosqlite://")


def test_hf_requires_endpoint_and_token():
    with pytest.raises(ValidationError, match="HF_ENDPOINT_URL"):
        make(provider="hf", database_url="sqlite+aiosqlite://")


def test_fallback_provider_requirements_also_checked():
    with pytest.raises(ValidationError, match="DEEPSEEK_API_KEY"):
        make(provider="fake", fallback_provider="deepseek", database_url="sqlite+aiosqlite://")


def test_anthropic_requires_api_key():
    with pytest.raises(ValidationError, match="ANTHROPIC_API_KEY"):
        make(provider="anthropic", database_url="sqlite+aiosqlite://")


def test_canary_percent_requires_canary_provider():
    with pytest.raises(ValidationError, match="CANARY_PROVIDER"):
        make(provider="fake", canary_percent=10, database_url="sqlite+aiosqlite://")


def test_railway_style_url_is_normalized():
    s = make(provider="fake", database_url="postgres://u:p@host:5432/db")
    assert s.database_url == "postgresql+psycopg://u:p@host:5432/db"


def test_load_settings_exits_loudly_when_unconfigured(monkeypatch, tmp_path, capsys):
    # A clean environment and an empty cwd (no .env): DATABASE_URL is missing.
    for key in list(__import__("os").environ):
        if key.upper() in {"DATABASE_URL", "PROVIDER", "DEEPSEEK_API_KEY"}:
            monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as excinfo:
        load_settings()
    assert excinfo.value.code == 1
    assert "cannot start" in capsys.readouterr().err
