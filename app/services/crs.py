"""CRS handling: detect and choose projected coordinate systems."""

from __future__ import annotations

import warnings

import pyproj
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform

# Boundary latitude for northern vs southern UTM zones.
UTM_NORTH_MAX_LAT = 84.0
UTM_SOUTH_MIN_LAT = -80.0


def utm_zone_for_latlon(lat: float, lon: float) -> int:
    """Return the UTM zone (1..60) for a latitude/longitude in WGS84."""

    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"Longitude out of range: {lon}")
    return int((lon + 180.0) // 6) + 1


def pick_projected_crs(geom: BaseGeometry) -> pyproj.CRS:
    """Choose a projected CRS appropriate for measuring ``geom``.

    The geometry must be in WGS84 (lon/lat) for this heuristic to be valid.
    Empty geometries fall back to ``EPSG:4326`` so callers don't crash.
    """

    if geom.is_empty:
        return pyproj.CRS.from_user_input("EPSG:4326")

    centroid = geom.centroid
    lon, lat = centroid.x, centroid.y

    zone = utm_zone_for_latlon(lat, lon)
    epsg = 32600 + zone if lat >= 0 else 32700 + zone  # N or S hemisphere
    return pyproj.CRS.from_user_input(f"EPSG:{epsg}")


def make_transformer(src: str | pyproj.CRS | None, dst: str | pyproj.CRS) -> pyproj.Transformer:
    """Build a ``Transformer`` from ``src`` to ``dst``.

    Falls back to ``EPSG:4326`` if the source is missing, empty, or unparseable.
    """

    if src is None or (isinstance(src, str) and not src.strip()):
        src = "EPSG:4326"
    try:
        src_crs = pyproj.CRS.from_user_input(src) if not isinstance(src, pyproj.CRS) else src
    except Exception:
        src_crs = pyproj.CRS.from_user_input("EPSG:4326")
    dst_crs = pyproj.CRS.from_user_input(dst) if not isinstance(dst, pyproj.CRS) else dst
    return pyproj.Transformer.from_crs(src_crs, dst_crs, always_xy=True)


def project_geometry(
    geom: BaseGeometry, src_crs: str | pyproj.CRS, dst_crs: str | pyproj.CRS
) -> BaseGeometry:
    """Reproject ``geom`` from ``src_crs`` to ``dst_crs``."""

    transformer = make_transformer(src_crs, dst_crs)
    # ``shapely.ops.transform`` accepts the ``(x, y) -> (x', y')`` signature from pyproj.
    # The newer ``shapely.transform`` requires a different call shape that's currently
    # fragile with bound methods, so we use the well-known ``ops`` form here.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        return shapely_transform(transformer.transform, geom)
