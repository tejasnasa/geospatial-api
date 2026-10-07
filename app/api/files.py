"""HTTP endpoints for file upload, info, and measurements."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.db import get_db
from app.core.ids import generate_file_id
from app.models.file import FileRecord
from app.schemas.file import FileInfoResponse
from app.schemas.measurement import FeatureMeasurement, MeasurementsResponse
from app.services.ingestion import IngestionError, start_ingestion
from app.services.measurements import measurement_for_feature

router = APIRouter(prefix="/api/files", tags=["files"])


def _save_upload(file_id: str, upload: UploadFile) -> tuple[str, str]:
    """Persist the upload to disk. Returns ``(storage_path, original_filename)``.

    Enforces ``settings.max_upload_bytes`` while streaming so a runaway client
    can't fill the disk. Raises ``HTTPException(413)`` if the limit is hit.
    """

    settings = get_settings()
    original = upload.filename or "upload"
    safe_name = original.replace("/", "_").replace("\\", "_")
    target = settings.upload_dir / f"{file_id}_{safe_name}"
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with target.open("wb") as fh:
            while chunk := upload.file.read(1024 * 1024):
                written += len(chunk)
                if written > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            f"Upload exceeds maximum allowed size of "
                            f"{settings.max_upload_bytes} bytes."
                        ),
                    )
                fh.write(chunk)
    finally:
        upload.file.close()
    return str(target), original


@router.post(
    "/",
    response_model=FileInfoResponse,
    status_code=status.HTTP_201_CREATED,
)
def upload_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> FileInfoResponse:
    """Upload a geospatial file (.zip for Shapefile, .kml)."""

    if file.filename is None:
        raise HTTPException(status_code=400, detail="Missing filename in upload.")

    file_id = generate_file_id()
    storage_path, original_filename = _save_upload(file_id, file)

    try:
        record = start_ingestion(db, file_id, original_filename, storage_path)
    except IngestionError as exc:
        # Clean up the stored upload to avoid leaving orphans on failure.
        try:
            Path(storage_path).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    db.commit()
    db.refresh(record)
    return FileInfoResponse.model_validate(record)


@router.get("/", response_model=list[FileInfoResponse])
def list_files(db: Session = Depends(get_db)) -> list[FileInfoResponse]:
    """List all uploaded files."""

    records = db.query(FileRecord).order_by(FileRecord.created_at.desc()).all()
    return [FileInfoResponse.model_validate(r) for r in records]


@router.get("/{file_id}", response_model=FileInfoResponse)
@router.get("/{file_id}/", response_model=FileInfoResponse, include_in_schema=False)
def get_file(file_id: str, db: Session = Depends(get_db)) -> FileInfoResponse:
    """Return info about a single uploaded file."""

    record = db.get(FileRecord, file_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"File '{file_id}' not found.")
    return FileInfoResponse.model_validate(record)


@router.get("/{file_id}/measurements", response_model=MeasurementsResponse)
@router.get(
    "/{file_id}/measurements/", response_model=MeasurementsResponse, include_in_schema=False
)
def get_measurements(file_id: str, db: Session = Depends(get_db)) -> MeasurementsResponse:
    """Compute and return measurements for every feature in a file."""

    record = (
        db.query(FileRecord)
        .options(selectinload(FileRecord.features))
        .filter(FileRecord.id == file_id)
        .one_or_none()
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"File '{file_id}' not found.")
    if record.status == "FAILED":
        raise HTTPException(
            status_code=409,
            detail=f"File '{file_id}' is in FAILED state: {record.error}",
        )
    if record.status != "COMPLETED":
        raise HTTPException(
            status_code=409,
            detail=f"File '{file_id}' has not finished processing (status={record.status}).",
        )

    out: list[FeatureMeasurement] = []
    supported = 0
    for feat in record.features:
        try:
            geometry = _geometry_from_json(feat.geometry_json)
        except Exception:  # noqa: BLE001
            out.append(
                FeatureMeasurement(
                    feature_index=feat.feature_index,
                    external_id=feat.external_id,
                    geometry_type=feat.geometry_type,
                    geometry=None,
                    src_crs=feat.src_crs,
                    projected_crs=None,
                    area_m2=None,
                    length_m=None,
                    area_native=None,
                    length_native=None,
                    properties=_props_from_json(feat.properties_json),
                )
            )
            continue

        # Per-feature guard: a mislabeled or corrupt .prj can leave src_crs
        # non-empty while the actual coordinates are out of the valid lon/lat
        # range. That would crash the projection step. Treat it as a bad
        # feature and keep the response otherwise intact.
        try:
            meas = measurement_for_feature(geometry, feat.src_crs)
        except Exception:  # noqa: BLE001
            out.append(
                FeatureMeasurement(
                    feature_index=feat.feature_index,
                    external_id=feat.external_id,
                    geometry_type=feat.geometry_type,
                    geometry=_raw_geometry_dict(feat.geometry_json),
                    src_crs=feat.src_crs,
                    projected_crs=None,
                    area_m2=None,
                    length_m=None,
                    area_native=None,
                    length_native=None,
                    properties=_props_from_json(feat.properties_json),
                )
            )
            continue
        if any(
            meas[k] is not None for k in ("area_m2", "length_m", "area_native", "length_native")
        ):
            supported += 1
        out.append(
            FeatureMeasurement(
                feature_index=feat.feature_index,
                external_id=feat.external_id,
                geometry_type=feat.geometry_type,
                geometry=_raw_geometry_dict(feat.geometry_json),
                src_crs=feat.src_crs,
                projected_crs=meas["projected_crs"],
                area_m2=meas["area_m2"],
                length_m=meas["length_m"],
                area_native=meas["area_native"],
                length_native=meas["length_native"],
                properties=_props_from_json(feat.properties_json),
            )
        )

    return MeasurementsResponse(
        file_id=file_id,
        feature_count=record.feature_count,
        supported_count=supported,
        features=out,
    )


def _geometry_from_json(blob: str):
    from shapely.geometry import shape

    return shape(json.loads(blob))


def _props_from_json(blob: str) -> dict:
    try:
        return json.loads(blob) if blob else {}
    except Exception:  # noqa: BLE001
        return {}


def _raw_geometry_dict(blob: str) -> dict | None:
    """Return the stored geometry as a plain dict, or None if it can't be parsed."""

    try:
        return json.loads(blob) if blob else None
    except Exception:  # noqa: BLE001
        return None
