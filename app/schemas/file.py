"""Pydantic schemas for the public API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FileInfoResponse(BaseModel):
    """Summary information about an uploaded file."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    filename: str
    kind: str = Field(description="`shapefile` or `kml`.")
    feature_count: int
    crs: str | None = None
    status: str = Field(description="PROCESSING | COMPLETED | FAILED")
    error: str | None = None
    created_at: datetime


class FileListResponse(BaseModel):
    files: list[FileInfoResponse]
