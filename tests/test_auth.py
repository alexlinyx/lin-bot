"""The password gate: nothing is served without a valid server-signed session.

These tests drive the real middleware + login routes over ASGI — the same code
paths a browser or a curl user would hit. The bypass-resistance claims are
tested directly: no cookie, a forged cookie, and an expired cookie all fail.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from linbot.main import create_app
from linbot.server.auth import SESSION_COOKIE, make_session_token, verify_session_token
from linbot.storage.models import Base
from tests.conftest import make_settings

PASSWORD = "correct-horse"


@pytest.fixture
async def gated_app(tmp_path):
    application = create_app(make_settings(tmp_path, access_password=PASSWORD))
    async with application.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield application
    await application.state.engine.dispose()


@pytest.fixture
async def gated_client(gated_app):
    transport = ASGITransport(app=gated_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def login(client: AsyncClient, password: str = PASSWORD):
    return await client.post("/login", data={"password": password})


# --- locked out ---------------------------------------------------------------


async def test_chat_page_redirects_to_login_without_session(gated_client):
    resp = await gated_client.get("/")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


async def test_ask_returns_401_without_session(gated_client):
    resp = await gated_client.post("/ask", json={"question": "hi"})
    assert resp.status_code == 401
    assert resp.json() == {"error": "authentication required"}


async def test_healthz_stays_open(gated_client):
    resp = await gated_client.get("/healthz")
    assert resp.status_code == 200


async def test_login_page_is_served_and_contains_no_password(gated_client):
    resp = await gated_client.get("/login")
    assert resp.status_code == 200
    assert "password" in resp.text.lower()  # the form field
    assert PASSWORD not in resp.text  # never the secret itself


async def test_wrong_password_rejected_without_cookie(gated_client):
    resp = await login(gated_client, "wrong")
    assert resp.status_code == 401
    assert SESSION_COOKIE not in resp.cookies


async def test_forged_cookie_rejected(gated_client):
    gated_client.cookies.set(SESSION_COOKIE, "9999999999.deadbeef")
    resp = await gated_client.get("/")
    assert resp.status_code == 303  # still bounced to login


async def test_expired_token_rejected():
    token = make_session_token(PASSWORD, ttl_seconds=-1)
    assert not verify_session_token(PASSWORD, token)


async def test_token_signed_with_other_secret_rejected():
    token = make_session_token("other-secret", ttl_seconds=60)
    assert not verify_session_token(PASSWORD, token)


# --- logged in ----------------------------------------------------------------


async def test_correct_password_grants_session_and_access(gated_client):
    resp = await login(gated_client)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert SESSION_COOKIE in resp.cookies

    page = await gated_client.get("/")  # cookie jar carries the session
    assert page.status_code == 200
    assert "LinBot" in page.text

    answer = await gated_client.post("/ask", json={"question": "hi"})
    assert answer.status_code == 200
    assert answer.json()["answer"]


async def test_login_attempts_are_rate_limited(gated_client):
    for _ in range(10):
        await login(gated_client, "wrong")
    resp = await login(gated_client, PASSWORD)  # even the right password now waits
    assert resp.status_code == 429


# --- gate off -----------------------------------------------------------------


async def test_no_gate_when_password_unset(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "LinBot" in resp.text
