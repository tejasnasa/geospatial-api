"""ORM models for uploaded files and their features."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


class FileRecord(Base):
    """A geospatial file that has been ingested."""

    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)  # shapefile | kml
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    crs: Mapped[str | None] = mapped_column(String(256), nullable=True)
    feature_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PROCESSING")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    features: Mapped[list[FeatureRecord]] = relationship(
        back_populates="file",
        cascade="all, delete-orphan",
        order_by="FeatureRecord.feature_index",
    )


class FeatureRecord(Base):
    """A single feature extracted from an ingested file."""

    __tablename__ = "features"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("files.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feature_index: Mapped[int] = mapped_column(Integer, nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    geometry_type: Mapped[str] = mapped_column(String(64), nullable=False)
    geometry_json: Mapped[str] = mapped_column(Text, nullable=False)
    properties_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    src_crs: Mapped[str | None] = mapped_column(String(256), nullable=True)

    file: Mapped[FileRecord] = relationship(back_populates="features")
