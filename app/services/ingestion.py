"""Top-level ingestion pipeline: detect format, read, persist."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.models.file import FeatureRecord, FileRecord
from app.services.readers.kml import KmlError, KmlReader
from app.services.readers.shapefile import ShapefileError, ShapefileReader


class IngestionError(Exception):
    """Raised when an uploaded file can't be processed."""


def _detect_kind(filename: str) -> str:
    """Return ``"shapefile"`` or ``"kml"`` based on the filename."""

    lower = filename.lower()
    if lower.endswith(".zip"):
        return "shapefile"
    if lower.endswith(".kml"):
        return "kml"
    raise IngestionError(
        f"Unsupported file type for '{filename}'. Expected .zip (shapefile) or .kml."
    )


def _reader_for(kind: str, path: Path):
    if kind == "shapefile":
        return ShapefileReader()
    if kind == "kml":
        return KmlReader()
    raise IngestionError(f"No reader for kind '{kind}'.")


def ingest_file(db: Session, file_record: FileRecord, source_path: str) -> FileRecord:
    """Parse ``source_path`` and populate ``file_record`` + child features."""

    file_record.status = "PROCESSING"
    db.flush()

    kind = file_record.kind
    reader = _reader_for(kind, Path(source_path))

    try:
        raw_features = list(reader.features(source_path))
    except (ShapefileError, KmlError) as exc:
        file_record.status = "FAILED"
        file_record.error = str(exc)
        db.flush()
        raise IngestionError(str(exc)) from exc

    crs_counts: dict[str, int] = {}
    for idx, raw in enumerate(raw_features):
        if raw.src_crs:
            crs_counts[raw.src_crs] = crs_counts.get(raw.src_crs, 0) + 1
        db.add(
            FeatureRecord(
                file_id=file_record.id,
                feature_index=idx,
                external_id=raw.external_id,
                geometry_type=raw.geometry_type,
                geometry_json=raw.geometry_json,
                properties_json=_dump_json(raw.properties),
                src_crs=raw.src_crs,
            )
        )
    # File-level CRS: the most common non-null value across all features.
    crs_str: str | None = max(crs_counts.items(), key=lambda kv: kv[1])[0] if crs_counts else None

    file_record.feature_count = len(raw_features)
    file_record.crs = crs_str
    file_record.status = "COMPLETED"
    db.flush()
    return file_record


def _dump_json(value: dict) -> str:
    import json

    def default(o):  # noqa: ANN001
        # Last-ditch serialization for numpy/pandas scalar types.
        if hasattr(o, "item"):
            return o.item()
        return str(o)

    return json.dumps(value, default=default, ensure_ascii=False)


def start_ingestion(db: Session, file_id: str, filename: str, storage_path: str) -> FileRecord:
    """Create the FileRecord row, then run the ingestion pipeline."""

    kind = _detect_kind(filename)
    record = FileRecord(
        id=file_id,
        filename=filename,
        kind=kind,
        storage_path=storage_path,
        status="PROCESSING",
    )
    db.add(record)
    db.flush()
    try:
        ingest_file(db, record, storage_path)
    except IngestionError:
        db.flush()
        raise
    db.refresh(record)
    return record
