"""Reader for zipped Shapefile bundles."""

from __future__ import annotations

import json
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path

import geopandas as gpd

from app.services.readers.base import RawFeature


class ShapefileError(Exception):
    """Raised when a shapefile bundle can't be loaded."""


_REQUIRED_EXTENSIONS = (".shp", ".shx", ".dbf")
# Defends against zip-bombs: refuse to extract more than this many bytes in total.
_MAX_EXTRACT_BYTES = 1 * 1024 * 1024 * 1024  # 1 GB
# Per-file size cap inside the zip.
_MAX_MEMBER_BYTES = 500 * 1024 * 1024  # 500 MB


def _external_id_from(row: dict) -> str | None:
    """Pick a stable external id from common attribute names, if any."""

    for key in ("id", "ID", "Id", "fid", "FID", "name", "Name", "NAME"):
        if key in row and row[key] is not None:
            value = row[key]
            return str(value)
    return None


def _safe_extract(zf: zipfile.ZipFile, target_dir: Path) -> None:
    """Extract ``zf`` into ``target_dir`` while enforcing size + path-safety limits."""

    resolved_target = target_dir.resolve()
    total = 0
    for member in zf.infolist():
        # Reject path traversal: every member must resolve inside target_dir.
        member_path = (target_dir / member.filename).resolve()
        if not member_path.is_relative_to(resolved_target):
            raise ShapefileError(f"Refusing zip entry with unsafe path: {member.filename}")
        if member.file_size > _MAX_MEMBER_BYTES:
            raise ShapefileError(
                f"Zip entry '{member.filename}' exceeds per-file limit "
                f"({member.file_size} > {_MAX_MEMBER_BYTES} bytes)."
            )
        total += member.file_size
        if total > _MAX_EXTRACT_BYTES:
            raise ShapefileError(
                f"Zip archive exceeds total extraction limit of {_MAX_EXTRACT_BYTES} bytes."
            )
    zf.extractall(target_dir)


class ShapefileReader:
    """Reads a zipped shapefile bundle."""

    def features(self, path: str) -> Iterator[RawFeature]:
        path = Path(path)
        if not path.is_file():
            raise ShapefileError(f"Shapefile archive not found: {path}")

        # Extract everything to a temp dir; GeoPandas (via pyogrio) needs
        # all sibling files (`.shp`, `.shx`, `.dbf`, optional `.prj`)
        # co-located.
        with tempfile.TemporaryDirectory(prefix="shp_") as tmp_dir:
            tmp_path = Path(tmp_dir)
            with zipfile.ZipFile(path) as zf:
                _safe_extract(zf, tmp_path)

            shp_files = list(tmp_path.rglob("*.shp"))
            if not shp_files:
                raise ShapefileError("Zip does not contain any .shp file.")

            shp = shp_files[0]
            missing = [ext for ext in _REQUIRED_EXTENSIONS if not shp.with_suffix(ext).exists()]
            if missing:
                raise ShapefileError(
                    f"Shapefile bundle is missing required sidecar files: {missing}"
                )

            gdf = gpd.read_file(shp)
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
                geom_json = json.loads(gpd.GeoSeries([geom]).to_json())
                # GeoSeries.to_json wraps a single feature in a FeatureCollection.
                feature_dict = geom_json["features"][0]
                geometry_only = feature_dict["geometry"]
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


def pd_is_na(value: object) -> bool:
    """Compatibility shim — returns True if ``value`` is pandas NaT/NaN/NA."""

    try:
        import pandas as pd

        if value is pd.NaT:
            return True
        # pandas.NA exists on pandas >= 1.0
        try:
            if value is pd.NA:
                return True
        except AttributeError:
            pass
        try:
            return bool(pd.isna(value))
        except (TypeError, ValueError):
            return False
    except ImportError:
        return False
