"""Per-feature measurement calculation."""

from __future__ import annotations

from typing import Any

from shapely.geometry.base import BaseGeometry

from app.services.crs import project_geometry

_POLYGON_TYPES = {"Polygon", "MultiPolygon"}
_LINE_TYPES = {"LineString", "MultiLineString", "LinearRing"}
_POINT_TYPES = {"Point", "MultiPoint"}


def _aggregate_from_subgeometries(geom: BaseGeometry) -> tuple[float | None, float | None]:
    """Sum area/length across parts of a GeometryCollection."""

    area_total = 0.0
    length_total = 0.0
    saw_anything = False

    for part in geom.geoms:
        sub_area, sub_length = compute_measurement(part)
        if sub_area is not None:
            area_total += sub_area
            saw_anything = True
        if sub_length is not None:
            length_total += sub_length
            saw_anything = True

    if not saw_anything:
        return None, None
    return (area_total or None), (length_total or None)


def compute_measurement(geom: BaseGeometry) -> tuple[float | None, float | None]:
    """Return ``(area_m2, length_m)`` for an already-projected geometry.

    The geometry must be in a metric (projected) CRS for these values to be
    meaningful. Returns ``(None, None)`` for unsupported or empty geometries.
    """

    if geom is None or geom.is_empty:
        return None, None

    gtype = geom.geom_type

    if gtype in _POLYGON_TYPES:
        return geom.area, geom.length
    if gtype in _LINE_TYPES:
        return None, geom.length
    if gtype in _POINT_TYPES:
        return None, None
    if gtype == "GeometryCollection":
        return _aggregate_from_subgeometries(geom)

    # Unknown / unsupported geometry kind — graceful no-op.
    return None, None


def measurement_for_feature(geometry: BaseGeometry, src_crs: str | None) -> dict[str, Any]:
    """Project ``geometry`` into a metric CRS, then compute area/length.

    Returns a dict with ``projected_crs`` (string) and the four measurement
    fields. Exactly one of (area_m2, length_m) vs (area_native, length_native)
    is populated:

    - normal path: ``area_m2``/``length_m`` are set; ``area_native``/``length_native`` are null.
    - NATIVE path (CRS missing/unidentifiable): ``area_native``/``length_native`` are
      set; ``area_m2``/``length_m`` are null. This is the only way to avoid lying
      about units when we don't know what they are.

    Source-CRS handling: the geometry may already be in a projected (metric) CRS,
    in which case centroid coordinates are easting/northing in metres, not
    lon/lat. We first reproject to WGS84 *only to pick a sensible target UTM
    zone*, then reproject the original geometry straight from its native CRS
    into that target.

    If the source CRS is missing AND the coordinates don't look like lon/lat,
    we treat the geometry as already-projected and emit the NATIVE path.
    """

    from app.services.crs import pick_projected_crs

    empty = {
        "projected_crs": None,
        "area_m2": None,
        "length_m": None,
        "area_native": None,
        "length_native": None,
    }
    if geometry is None or geometry.is_empty:
        return empty

    src = src_crs or "EPSG:4326"
    if not src_crs and _looks_projected(geometry):
        # Unknown CRS but the coordinates don't look like lon/lat. Treat as
        # already-projected; expose unitless measurements only.
        area, length = compute_measurement(geometry)
        return {
            "projected_crs": "NATIVE",
            "area_m2": None,
            "length_m": None,
            "area_native": area,
            "length_native": length,
        }

    wgs84_for_zone = project_geometry(geometry, src, "EPSG:4326")
    target = pick_projected_crs(wgs84_for_zone)
    projected = project_geometry(geometry, src, target)
    area, length = compute_measurement(projected)
    epsg = target.to_epsg()
    projected_str = f"EPSG:{epsg}" if epsg is not None else target.to_wkt()
    return {
        "projected_crs": projected_str,
        "area_m2": area,
        "length_m": length,
        "area_native": None,
        "length_native": None,
    }


def _looks_projected(geom: BaseGeometry) -> bool:
    """Heuristic: do the geometry's coordinates look like projected (metric)?

    Returns True when either the centroid's x or y is outside the valid
    lon/lat range (|x| > 360 or |y| > 90). Empty geometries return False.
    """

    if geom.is_empty:
        return False
    c = geom.centroid
    return abs(c.x) > 360.0 or abs(c.y) > 90.0
