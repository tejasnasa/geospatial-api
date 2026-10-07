"""FastAPI application entrypoint."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.api.files import router as files_router
from app.core.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="Geospatial File Measurement API",
        version=__version__,
        description=(
            "Upload a geospatial file (Shapefile as a .zip or .kml) and "
            "retrieve per-feature measurements (area, length)."
        ),
        lifespan=lifespan,
    )

    @app.get("/api/healthz", tags=["meta"])
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    app.include_router(files_router)
    return app


app = create_app()
