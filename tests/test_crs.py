"""Tests for the CRS service."""

from __future__ import annotations

import pytest
from shapely.geometry import LineString, Point, Polygon

from app.services.crs import pick_projected_crs, project_geometry, utm_zone_for_latlon


@pytest.mark.parametrize(
    ("lat", "lon", "expected"),
    [
        (0.0, 0.0, 31),  # Greenwich, equator → zone 31N
        (40.0, -74.0, 18),  # NYC → zone 18N
        (-33.0, 151.0, 56),  # Sydney → zone 56S
        (60.0, 25.0, 35),  # Helsinki → zone 35N
    ],
)
def test_utm_zone_for_latlon(lat: float, lon: float, expected: int) -> None:
    assert utm_zone_for_latlon(lat, lon) == expected


def test_pick_projected_crs_uses_utm_zone() -> None:
    # A polygon near NYC.
    geom = Polygon([(-74.0, 40.7), (-74.0, 40.8), (-73.9, 40.8), (-73.9, 40.7)])
    crs = pick_projected_crs(geom)
    assert crs.to_epsg() == 32618


def test_pick_projected_crs_southern_hemisphere() -> None:
    geom = Point(151.0, -33.0)
    crs = pick_projected_crs(geom)
    assert crs.to_epsg() == 32756


def test_pick_projected_crs_empty_geometry_falls_back() -> None:
    geom = LineString()
    crs = pick_projected_crs(geom)
    assert crs.to_epsg() == 4326


def test_project_geometry_is_identity_for_point_in_utm() -> None:
    geom = Point(500000.0, 4649776.0)  # ~NYC in UTM 18N
    out = project_geometry(geom, "EPSG:32618", "EPSG:32618")
    assert out.x == pytest.approx(500000.0, abs=1e-3)
    assert out.y == pytest.approx(4649776.0, abs=1e-3)
