"""Reader for KML files."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import geopandas as gpd

from app.services.readers.base import RawFeature
from app.services.readers.shapefile import pd_is_na


class KmlError(Exception):
    """Raised when a KML file can't be loaded."""


def _external_id_from(row: dict) -> str | None:
    for key in ("id", "ID", "Id", "Name", "name"):
        if key in row and row[key] is not None:
            return str(row[key])
    return None


class KmlReader:
    """Reads a KML file."""

    def features(self, path: str) -> Iterator[RawFeature]:
        path = Path(path)
        if not path.is_file():
            raise KmlError(f"KML file not found: {path}")
        try:
            gdf = gpd.read_file(path, driver="KML")
        except Exception as exc:  # noqa: BLE001
            raise KmlError(f"Failed to read KML: {exc}") from exc

        crs_str: str | None = None
        if gdf.crs is not None:
            try:
                crs_str = gdf.crs.to_string()
            except Exception:  # noqa: BLE001
                crs_str = str(gdf.crs)

        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom is None:
                continue
            try:
                geom_json = json.loads(gpd.GeoSeries([geom]).to_json())
                geometry_only = geom_json["features"][0]["geometry"]
            except Exception:  # noqa: BLE001
                # Fallback: serialise via shapely + json
                geometry_only = json.loads(geom.to_json())
            properties = {
                k: (None if pd_is_na(v) else v) for k, v in row.items() if k != "geometry"
            }
            yield RawFeature(
                geometry_json=json.dumps(geometry_only),
                properties=properties,
                geometry_type=geom.geom_type,
                src_crs=crs_str,
                external_id=_external_id_from(properties),
            )
