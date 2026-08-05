"""Web app fixtures: FastAPI client, DB cleanup, fakeredis."""

from __future__ import annotations

import os

import pytest

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "").strip()


@pytest.fixture(scope="session")
def database_url():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set — skipping db-backed web tests")
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
def db_engine(database_url):
    from sqlalchemy import create_engine

    from smart_pdf2md.web import models  # noqa: F401
    from smart_pdf2md.web.db import Base, reset_engine

    engine = create_engine(database_url, pool_pre_ping=True)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    reset_engine()
    os.environ["DATABASE_URL"] = database_url
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()
    reset_engine()


@pytest.fixture
def redis_conn():
    import fakeredis

    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def app(db_engine, database_url, redis_conn, tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("WEB_DATA_DIR", str(tmp_path / "webdata"))
    monkeypatch.setenv("WEB_DEFAULT_CREDITS", "10")
    monkeypatch.setenv("WEB_SECRET_KEY", "test-secret")
    monkeypatch.setenv("PDF2MD_CACHE_DIR", str(tmp_path / "cache"))
    # Override local .env so public register stays available unless a test disables it.
    monkeypatch.setenv("WEB_ALLOW_REGISTER", "true")
    # Secure cookies refuse to stick on http://testserver.
    monkeypatch.setenv("COOKIE_SECURE", "false")

    from smart_pdf2md.web.db import Base, get_db, reset_engine
    from smart_pdf2md.web.settings import get_settings

    get_settings.cache_clear()
    reset_engine()

    # Isolate each test: wipe tables
    Base.metadata.drop_all(db_engine)
    Base.metadata.create_all(db_engine)

    from smart_pdf2md.web.app import create_app
    from smart_pdf2md.web.db import get_session_factory
    from smart_pdf2md.web.worker import set_redis_override

    set_redis_override(redis_conn)
    application = create_app()
    application.state.redis = redis_conn
    application.state.rq_is_async = False

    SessionLocal = get_session_factory()

    def _override_db():
        session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    application.dependency_overrides[get_db] = _override_db
    yield application
    application.dependency_overrides.clear()
    set_redis_override(None)
    get_settings.cache_clear()
    reset_engine()


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


@pytest.fixture
def authed_client(client):
    from helpers import csrf_headers, register

    resp = register(client, "user@example.com")
    assert resp.status_code in {303, 200}
    client.headers.update(csrf_headers(client))
    return client


@pytest.fixture
def admin_client(client):
    """Log in as an admin seeded directly in the DB (not via registration order)."""
    from helpers import csrf_headers
    from smart_pdf2md.web.credits import grant_signup_credits
    from smart_pdf2md.web.db import get_session_factory
    from smart_pdf2md.web.models import User
    from smart_pdf2md.web.security import hash_password
    from smart_pdf2md.web.settings import get_settings

    email = "admin@example.com"
    password = "password123"
    with get_session_factory()() as session:
        user = User(
            email=email,
            password_hash=hash_password(password),
            role="admin",
            credits=0,
        )
        session.add(user)
        session.flush()
        grant_signup_credits(session, user, get_settings().web_default_credits)
        session.commit()

    resp = client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )
    assert resp.status_code in {303, 200}
    client.headers.update(csrf_headers(client))
    return client
