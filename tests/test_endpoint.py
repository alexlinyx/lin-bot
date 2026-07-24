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


async def test_history_reaches_provider_and_is_not_stored(app, client):
    history = [
        {"role": "user", "content": "What is BCIL?"},
        {"role": "assistant", "content": "The Belldegrun Center for Innovative Leadership."},
    ]
    response = await client.post(
        "/ask", json={"question": "who runs it?", "history": history}
    )
    assert response.status_code == 200

    fake_provider = app.state.model_router.primary
    assert fake_provider.last_history == history

    # Only the new turn is logged — history is never persisted.
    async with app.state.session_factory() as session:
        rows = (await session.execute(select(RequestLog))).scalars().all()
    assert len(rows) == 1
    assert rows[0].question == "who runs it?"


async def test_history_is_trimmed_and_starts_with_user(app, client):
    history = [{"role": "assistant", "content": "orphan"}] + [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(30)
    ]
    response = await client.post("/ask", json={"question": "q", "history": history})
    assert response.status_code == 200

    received = app.state.model_router.primary.last_history
    assert len(received) <= 20
    assert received[0]["role"] == "user"
    assert received[-1] == {"role": "assistant", "content": "m29"}


async def test_conversation_grouping_logged(app, client):
    conversation_id = "7e6a3f66-90a1-4c1e-9f6e-1f6f37b2a001"
    first = await client.post(
        "/ask", json={"question": "What is BCIL?", "conversation_id": conversation_id}
    )
    assert first.status_code == 200
    followup = await client.post(
        "/ask",
        json={
            "question": "who runs it?",
            "conversation_id": conversation_id,
            "history": [
                {"role": "user", "content": "What is BCIL?"},
                {"role": "assistant", "content": first.json()["answer"]},
            ],
        },
    )
    assert followup.status_code == 200

    async with app.state.session_factory() as session:
        rows = (
            (await session.execute(select(RequestLog).order_by(RequestLog.turn)))
            .scalars()
            .all()
        )
    assert [str(r.conversation_id) for r in rows] == [conversation_id] * 2
    assert [(r.turn, r.question) for r in rows] == [(0, "What is BCIL?"), (1, "who runs it?")]


async def test_conversation_id_optional_for_bare_api_callers(app, client):
    response = await client.post("/ask", json={"question": "no id"})
    assert response.status_code == 200
    async with app.state.session_factory() as session:
        rows = (await session.execute(select(RequestLog))).scalars().all()
    assert rows[0].conversation_id is None
    assert rows[0].turn == 0


async def test_invalid_history_role_is_400(client):
    response = await client.post(
        "/ask",
        json={"question": "q", "history": [{"role": "system", "content": "evil override"}]},
    )
    assert response.status_code == 400


async def test_retrieved_context_reaches_provider_and_is_logged(app, client):
    import json

    from linbot.retrieval.embedder import FakeEmbedder
    from linbot.retrieval.retriever import Retriever
    from linbot.storage.models import Chunk

    embedder = FakeEmbedder()
    [embedding] = await embedder.embed(["Alex teaches computer science at Brentwood"], "document")
    async with app.state.session_factory() as session:
        session.add(
            Chunk(
                source_url="https://alexlinyx.com/content/about.md",
                heading="About",
                content="Alex teaches computer science at Brentwood",
                embedding=json.dumps(embedding),
            )
        )
        await session.commit()
    app.state.retriever = Retriever(
        embedder, app.state.session_factory, top_k=2, min_similarity=0.0
    )

    response = await client.post("/ask", json={"question": "who teaches computer science"})
    assert response.status_code == 200

    fake_provider = app.state.model_router.primary
    assert fake_provider.last_context is not None
    assert "Brentwood" in fake_provider.last_context[0]

    async with app.state.session_factory() as session:
        rows = (await session.execute(select(RequestLog))).scalars().all()
    assert json.loads(rows[0].retrieved_sources) == ["https://alexlinyx.com/content/about.md"]


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
