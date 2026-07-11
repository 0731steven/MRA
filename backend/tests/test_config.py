import pytest

from src import config


def test_production_rejects_default_secret(monkeypatch):
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    monkeypatch.setattr(config, "SECRET_KEY", "dev-secret-change-me-please")
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql+asyncpg://user:pass@db/app")
    monkeypatch.setattr(config, "ALLOWED_ORIGINS", [])

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        config.validate_runtime_config()


def test_production_rejects_sqlite(monkeypatch):
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    monkeypatch.setattr(config, "SECRET_KEY", "a-secure-production-secret-with-32-chars")
    monkeypatch.setattr(config, "DATABASE_URL", "sqlite+aiosqlite:///./app.db")
    monkeypatch.setattr(config, "ALLOWED_ORIGINS", [])

    with pytest.raises(RuntimeError, match="PostgreSQL"):
        config.validate_runtime_config()


def test_valid_production_configuration(monkeypatch):
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    monkeypatch.setattr(config, "SECRET_KEY", "a-secure-production-secret-with-32-chars")
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql+asyncpg://user:pass@db/app")
    monkeypatch.setattr(config, "ALLOWED_ORIGINS", ["https://example.invalid"])

    config.validate_runtime_config()
