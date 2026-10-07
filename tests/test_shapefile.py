"""End-to-end tests for zipped Shapefile upload."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon, mapping

from app.services.readers.shapefile import ShapefileReader


def _make_shapefile_in_memory(tmp_dir: Path) -> Path:
    """Write a small shapefile to ``tmp_dir`` and return the .shp path."""

    poly = Polygon(
        [
            (0.0, 0.0),
            (0.01, 0.0),
            (0.01, 0.01),
            (0.0, 0.01),
            (0.0, 0.0),
        ]
    )
    gdf = gpd.GeoDataFrame(
        {"name": ["box"], "id": [1]},
        geometry=[poly],
        crs="EPSG:4326",
    )
    shp_path = tmp_dir / "test.shp"
    gdf.to_file(shp_path, driver="ESRI Shapefile")
    return shp_path


def _zip_directory(src_dir: Path) -> bytes:
    """Return the contents of ``src_dir`` as a zip archive's bytes."""

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.iterdir():
            zf.write(f, arcname=f.name)
    buf.seek(0)
    return buf.getvalue()


def test_upload_zipped_shapefile(tmp_path, client) -> None:
    work = tmp_path / "shp"
    work.mkdir()
    _make_shapefile_in_memory(work)

    zip_bytes = _zip_directory(work)

    response = client.post(
        "/api/files/",
        files={"file": ("shapes.zip", io.BytesIO(zip_bytes), "application/zip")},
    )
    assert response.status_code == 201, response.text
    info = response.json()
    assert info["kind"] == "shapefile"
    assert info["status"] == "COMPLETED"
    assert info["feature_count"] == 1

    file_id = info["id"]
    meas = client.get(f"/api/files/{file_id}/measurements")
    assert meas.status_code == 200
    body = meas.json()
    assert body["feature_count"] == 1
    feat = body["features"][0]
    assert feat["geometry_type"] == "Polygon"
    assert feat["area_m2"] is not None
    assert feat["length_m"] is not None
    assert feat["properties"]["name"] == "box"
    # external_id picks "name" first, then "id"
    assert feat["external_id"] in {"box", "1"}


def test_zip_without_shp_returns_422(tmp_path, client) -> None:
    work = tmp_path / "noshp"
    work.mkdir()
    (work / "readme.txt").write_text("no shapefile here")

    zip_bytes = _zip_directory(work)
    response = client.post(
        "/api/files/",
        files={"file": ("bad.zip", io.BytesIO(zip_bytes), "application/zip")},
    )
    assert response.status_code == 422
    assert "shp" in response.text.lower()


def test_reader_returns_features(tmp_path) -> None:
    work = tmp_path / "shp2"
    work.mkdir()
    _make_shapefile_in_memory(work)
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, mode="w") as zf:
        for f in work.iterdir():
            zf.write(f, arcname=f.name)

    reader = ShapefileReader()
    features = list(reader.features(str(zip_path)))
    assert len(features) == 1
    assert features[0].geometry_type == "Polygon"
    assert features[0].properties["name"] == "box"
    assert features[0].src_crs is not None


# Silence unused-import warnings for symbols kept for environment hints.
_ = (Point, LineString, mapping)
