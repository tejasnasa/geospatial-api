"""Regression tests for projected-CRS shapefiles and missing .prj files.

A shapefile whose native CRS is already projected (e.g. EPSG:32618) used to
crash the measurements endpoint with a 500: ``pick_projected_crs`` would read
the centroid's easting as a longitude and raise ``ValueError: Longitude out of
range``. The fix is to first reproject to WGS84 only to pick a UTM zone, then
reproject the original geometry into that zone.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import Polygon


def _make_shapefile(tmp_dir: Path, crs: str | None, name: str) -> Path:
    """Write a small shapefile in ``tmp_dir`` and return the .shp path."""

    poly = Polygon(
        [
            (500000.0, 4649776.0),  # ~NYC in UTM 18N
            (501000.0, 4649776.0),
            (501000.0, 4650776.0),
            (500000.0, 4650776.0),
            (500000.0, 4649776.0),
        ]
    )
    gdf = gpd.GeoDataFrame({"name": [name], "id": [1]}, geometry=[poly], crs=crs)
    shp_path = tmp_dir / "test.shp"
    gdf.to_file(shp_path, driver="ESRI Shapefile")
    return shp_path


def _zip_dir(src_dir: Path) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.iterdir():
            zf.write(f, arcname=f.name)
    buf.seek(0)
    return buf.getvalue()


def test_measurements_for_projected_shapefile(tmp_path, client) -> None:
    """Shapefile already in EPSG:32618 must not 500 on /measurements."""

    work = tmp_path / "proj"
    work.mkdir()
    _make_shapefile(work, crs="EPSG:32618", name="box")

    resp = client.post(
        "/api/files/",
        files={"file": ("p.zip", io.BytesIO(_zip_dir(work)), "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    info = resp.json()
    assert info["status"] == "COMPLETED"
    assert info["crs"] is not None
    assert "32618" in info["crs"]

    fid = info["id"]
    m = client.get(f"/api/files/{fid}/measurements")
    assert m.status_code == 200, m.text
    body = m.json()
    feat = body["features"][0]
    # 1000m x 1000m box → ~1_000_000 m² and ~4000 m perimeter
    assert feat["area_m2"] == 1_000_000.0
    assert feat["length_m"] == 4000.0
    # projected_crs should be the local UTM zone, not 32618 itself.
    assert feat["projected_crs"] is not None
    assert feat["projected_crs"].startswith("EPSG:")


def test_measurements_for_prjless_shapefile(tmp_path, client) -> None:
    """A .prj-less shapefile (raw metric coords) must not 500 and must not
    lie about units.

    The geometry clearly isn't in lon/lat (centroid ~500k easting), so we
    return ``projected_crs = "NATIVE"`` and put the unitless values in
    ``area_native``/``length_native``. The ``area_m2``/``length_m`` fields
    must be null because we can't claim they're square metres.
    """

    work = tmp_path / "noprj"
    work.mkdir()
    _make_shapefile(work, crs=None, name="box")

    resp = client.post(
        "/api/files/",
        files={"file": ("n.zip", io.BytesIO(_zip_dir(work)), "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    fid = resp.json()["id"]
    m = client.get(f"/api/files/{fid}/measurements")
    assert m.status_code == 200, m.text
    feat = m.json()["features"][0]
    # 1000m x 1000m box in unknown units → ~1e6 native² and 4000 native.
    assert feat["projected_crs"] == "NATIVE"
    assert feat["area_m2"] is None
    assert feat["length_m"] is None
    assert feat["area_native"] == 1_000_000.0
    assert feat["length_native"] == 4000.0
    # ``supported_count`` is "features with at least one measurement" per
    # the schema, so a NATIVE path feature with a non-null ``area_native``
    # must count. This regressed when area_m2/length_m were kept as the
    # only counted fields.
    assert m.json()["supported_count"] == 1


def test_trailing_slash_aliases(client) -> None:
    """Both /api/files/{id} and /api/files/{id}/ must return 200 (no 307)."""

    kml = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>x</name><Point><coordinates>0,0,0</coordinates></Point>
</Placemark></Document></kml>"""
    r = client.post(
        "/api/files/",
        files={"file": ("a.kml", io.BytesIO(kml), "application/vnd.google-earth.kml+xml")},
    )
    assert r.status_code == 201
    fid = r.json()["id"]

    no_slash = client.get(f"/api/files/{fid}")
    with_slash = client.get(f"/api/files/{fid}/")
    assert no_slash.status_code == 200
    assert with_slash.status_code == 200
    assert no_slash.json() == with_slash.json()

    meas_no = client.get(f"/api/files/{fid}/measurements")
    meas_with = client.get(f"/api/files/{fid}/measurements/")
    assert meas_no.status_code == 200
    assert meas_with.status_code == 200


def test_oversize_upload_rejected(tmp_path, client, monkeypatch) -> None:
    """An upload that exceeds max_upload_bytes is rejected with 413."""

    # Force a tiny cap via env so we can hit it cheaply.
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "100")
    # Re-read settings.
    from app.core import config as config_module
    from app.core import db as db_module

    config_module._settings = None  # type: ignore[attr-defined]
    db_module._settings = None  # type: ignore[attr-defined]
    from fastapi.testclient import TestClient  # noqa: F401
    from fastapi.testclient import TestClient as _TC

    from app.main import create_app  # noqa: F401  -- ensure fresh app

    # New client bound to fresh settings.
    from app.main import create_app as _create

    app = _create()
    with _TC(app) as c:
        big = b"x" * 500
        r = c.post(
            "/api/files/",
            files={"file": ("big.kml", io.BytesIO(big), "application/vnd.google-earth.kml+xml")},
        )
        assert r.status_code == 413
        assert "exceeds" in r.text.lower()


def test_mislabeled_crs_does_not_500_one_feature(tmp_path, client) -> None:
    """A shapefile that declares EPSG:4326 but contains out-of-range
    coordinates must not take down the whole measurements response.

    Models a corrupt/mislabeled .prj: the file says 4326, the data is in
    projected metres. Reprojecting the centroid to WGS84 to pick a UTM
    zone would feed easting ~500k into the longitude range check and
    raise ValueError. The endpoint must isolate that to a single bad
    feature row and still return the rest.
    """

    work = tmp_path / "mislabeled"
    work.mkdir()
    _make_shapefile(work, crs="EPSG:4326", name="box")  # lie: data is UTM 18N

    resp = client.post(
        "/api/files/",
        files={"file": ("m.zip", io.BytesIO(_zip_dir(work)), "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    fid = resp.json()["id"]
    m = client.get(f"/api/files/{fid}/measurements")
    assert m.status_code == 200, m.text
    body = m.json()
    assert body["feature_count"] == 1
    feat = body["features"][0]
    # The bad feature is reported with nulls; the rest of the response is intact.
    assert feat["projected_crs"] is None
    assert feat["area_m2"] is None
    assert feat["length_m"] is None
    assert feat["area_native"] is None
    assert feat["length_native"] is None
    # Geometry is still surfaced.
    assert feat["geometry"] is not None
    assert feat["geometry"]["type"] == "Polygon"
    # A feature with no measurement at all does not count.
    assert body["supported_count"] == 0


def test_zip_path_traversal_rejected(tmp_path) -> None:
    """A zip member whose path escapes the target directory is rejected.

    Specifically the prefix-string check at shapefile.py:44 would let
    ``../target_evil/x.shp`` slip through if the target happened to be
    ``target`` (a sibling with a longer name). The fix uses
    :py:meth:`pathlib.Path.is_relative_to`, which is exact.
    """

    from app.services.readers.shapefile import ShapefileError, _safe_extract

    work = tmp_path / "extraction"
    work.mkdir()
    sibling = tmp_path / "extraction_evil"
    sibling.mkdir()

    # Build a zip with a member that points outside the extraction dir.
    zpath = tmp_path / "evil.zip"
    with zipfile.ZipFile(zpath, mode="w") as zf:
        zf.writestr("../extraction_evil/pwned.shp", b"data")

    with (
        zipfile.ZipFile(zpath) as zf,
        pytest.raises(ShapefileError) as excinfo,
    ):
        _safe_extract(zf, work)
    assert "unsafe path" in str(excinfo.value).lower() or "refusing" in str(excinfo.value).lower()


def test_zip_member_size_cap_is_enforced(tmp_path) -> None:
    """A zip member whose uncompressed size exceeds the cap is rejected.

    We shrink the cap to something tiny via monkeypatch, then build a normal
    zip whose only member exceeds that cap. This exercises the same code path
    that rejects a 500 MB member, without writing half a gig to disk.
    """

    from app.services.readers import shapefile as shp_mod

    original_cap = shp_mod._MAX_MEMBER_BYTES
    shp_mod._MAX_MEMBER_BYTES = 1024  # 1 KB
    try:
        work = tmp_path / "bomb"
        work.mkdir()
        (work / "huge.shp").write_bytes(b"\x00" * 4096)  # 4 KB > 1 KB cap
        zpath = tmp_path / "huge.zip"
        with zipfile.ZipFile(zpath, mode="w") as zf:
            zf.write(work / "huge.shp", arcname="huge.shp")

        out = tmp_path / "out"
        out.mkdir()
        with (
            zipfile.ZipFile(zpath) as zf,
            pytest.raises(shp_mod.ShapefileError) as excinfo,
        ):
            shp_mod._safe_extract(zf, out)
        assert "limit" in str(excinfo.value).lower() or "exceeds" in str(excinfo.value).lower()
    finally:
        shp_mod._MAX_MEMBER_BYTES = original_cap


def test_measurements_endpoint_includes_geometry(client) -> None:
    """The spec lists Geometry among the per-feature fields; surface it."""

    kml = b"""<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2"><Document>
<Placemark><name>p</name><Polygon><outerBoundaryIs><LinearRing><coordinates>
0,0,0 0,0.01,0 0.01,0.01,0 0.01,0,0 0,0,0
</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>
</Document></kml>"""
    r = client.post(
        "/api/files/",
        files={"file": ("g.kml", io.BytesIO(kml), "application/vnd.google-earth.kml+xml")},
    )
    fid = r.json()["id"]
    m = client.get(f"/api/files/{fid}/measurements")
    feat = m.json()["features"][0]
    assert feat["geometry"] is not None
    assert feat["geometry"]["type"] == "Polygon"
    assert "coordinates" in feat["geometry"]
