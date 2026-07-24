import pytest
from httpx import ASGITransport, AsyncClient

from linbot.config import Settings
from linbot.main import create_app
from linbot.storage.models import Base


def make_settings(tmp_path, **overrides) -> Settings:
    """Test settings: fake provider, throwaway SQLite DB, no .env interference."""
    values = {
        "provider": "fake",
        "database_url": f"sqlite+aiosqlite:///{tmp_path}/test.db",
        "rate_limit": 1000,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture
async def app(tmp_path):
    application = create_app(make_settings(tmp_path))
    # Tests create the schema directly; production uses alembic.
    async with application.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield application
    await application.state.engine.dispose()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
