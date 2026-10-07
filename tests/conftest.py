"""Test fixtures: an isolated FastAPI app with a temp SQLite DB."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import db as db_module
from app.core.config import get_settings
from app.main import create_app

# Silence Starlette's httpx→httpx2 deprecation noise from the imported TestClient.
pytestmark = pytest.mark.filterwarnings(
    "ignore:Using `httpx` with `starlette.testclient` is deprecated:DeprecationWarning"
)


@pytest.fixture()
def temp_settings(monkeypatch, tmp_path) -> Iterator[None]:
    """Redirect uploads and DB to a temp directory for the test."""

    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    db_file = tmp_path / "test.db"
    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    # Reset cached settings so the env vars above are picked up.
    db_module._settings = None  # type: ignore[attr-defined]
    from app.core import config as config_module

    config_module._settings = None  # type: ignore[attr-defined]
    yield


@pytest.fixture()
def client(temp_settings) -> Iterator[TestClient]:
    """A TestClient bound to a fresh app with the temp DB."""

    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db_session(temp_settings) -> Iterator:
    """A SQLAlchemy session bound to the temp DB."""

    from app.core.db import Base  # local import after env override

    # Re-create engine for the test DB.
    settings = get_settings()
    engine = create_engine(
        settings.database_url, connect_args={"check_same_thread": False}, future=True
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    # Swap the module-level engine too so app handlers use the temp DB.
    db_module.engine = engine
    db_module.SessionLocal = SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
