"""Schemas for the measurements endpoint."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FeatureMeasurement(BaseModel):
    """Measurement information for a single feature."""

    feature_index: int
    external_id: str | None = None
    geometry_type: str
    geometry: dict | None = Field(
        default=None,
        description=(
            "The feature's geometry as a GeoJSON geometry object (the same CRS as `src_crs`)."
        ),
    )
    src_crs: str | None = None
    projected_crs: str | None = Field(
        default=None,
        description=(
            "The metric CRS used for `area_m2`/`length_m`, e.g. `EPSG:32618`. "
            "`null` for non-polygon/line features, or `null` for unsupported "
            "geometries. `NATIVE` means the geometry was already in a metric "
            "CRS but we couldn't identify it; see `area_native`/`length_native`."
        ),
    )
    area_m2: float | None = Field(
        default=None,
        description=(
            "Polygon area in square metres. `null` for non-polygon or empty "
            "geometries, or for features whose CRS couldn't be determined "
            "(in which case the unitless `area_native` is populated instead)."
        ),
    )
    length_m: float | None = Field(
        default=None,
        description=(
            "LineString length / polygon boundary length in metres. `null` "
            "for points/empty, or for features whose CRS couldn't be "
            "determined (in which case the unitless `length_native` is "
            "populated instead)."
        ),
    )
    area_native: float | None = Field(
        default=None,
        description=(
            "Polygon area in the source CRS's native units. Only populated "
            "when `projected_crs == 'NATIVE'` (i.e. the source CRS was missing "
            "or could not be parsed). Otherwise `null`."
        ),
    )
    length_native: float | None = Field(
        default=None,
        description=(
            "LineString length / polygon boundary length in the source CRS's "
            "native units. Only populated when `projected_crs == 'NATIVE'`."
        ),
    )
    properties: dict = Field(default_factory=dict)


class MeasurementsResponse(BaseModel):
    """All measurements for an uploaded file."""

    model_config = ConfigDict(from_attributes=True)

    file_id: str
    feature_count: int
    supported_count: int = Field(description="Features with at least one measurement.")
    features: list[FeatureMeasurement]
