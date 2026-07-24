from sqlalchemy import select

from linbot.model.providers.fake import FakeProvider
from linbot.storage.models import RequestLog


async def test_chat_page_served_at_root(client):
    response = await client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "LinBot" in response.text


async def test_healthz(client):
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_ask_returns_answer_and_logs_attribution(app, client):
    response = await client.post("/ask", json={"question": "What is a hash map?"})
    assert response.status_code == 200
    assert "What is a hash map?" in response.json()["answer"]

    async with app.state.session_factory() as session:
        rows = (await session.execute(select(RequestLog))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.question == "What is a hash map?"
    assert row.model_id == "fake-echo"
    assert row.provider == "fake"
    assert row.fallback_used is False
    assert row.system_prompt_version is not None


async def test_missing_question_is_400(client):
    response = await client.post("/ask", json={})
    assert response.status_code == 400
    assert response.json() == {"error": "question is required and must be a non-empty string"}


async def test_empty_question_is_400(client):
    response = await client.post("/ask", json={"question": "   "})
    assert response.status_code == 400
    assert "non-empty" in response.json()["error"]


async def test_oversized_question_is_400(app, client):
    too_long = "x" * (app.state.settings.max_question_chars + 1)
    response = await client.post("/ask", json={"question": too_long})
    assert response.status_code == 400
    assert "too long" in response.json()["error"]


async def test_provider_failure_is_clean_502_and_logged(app, client):
    app.state.model_router.primary = FakeProvider(fail=True)
    response = await client.post("/ask", json={"question": "Will this fail?"})
    assert response.status_code == 502
    assert response.json() == {"error": "the model service is unavailable"}

    async with app.state.session_factory() as session:
        rows = (await session.execute(select(RequestLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].error is not None
    assert rows[0].answer is None


async def test_rate_limit_is_429(tmp_path):
    from httpx import ASGITransport, AsyncClient

    from linbot.main import create_app
    from linbot.storage.models import Base
    from tests.conftest import make_settings

    app = create_app(make_settings(tmp_path, rate_limit=2))
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(2):
            assert (await client.post("/ask", json={"question": "hi"})).status_code == 200
        response = await client.post("/ask", json={"question": "hi"})
    assert response.status_code == 429
    assert response.json() == {"error": "rate limit exceeded, try again shortly"}
    await app.state.engine.dispose()
