"""Tests for the measurement service."""

from __future__ import annotations

import pytest
from shapely.geometry import LineString, MultiLineString, MultiPoint, MultiPolygon, Point, Polygon

from app.services.measurements import compute_measurement, measurement_for_feature


def test_square_polygon_area_and_perimeter() -> None:
    square = Polygon([(0, 0), (10, 0), (10, 10), (10, 10), (0, 10)])
    area, length = compute_measurement(square)
    assert area == pytest.approx(100.0)
    assert length == pytest.approx(40.0)


def test_linestring_only_length() -> None:
    line = LineString([(0, 0), (3, 0), (3, 4)])
    area, length = compute_measurement(line)
    assert area is None
    assert length == pytest.approx(7.0)


def test_point_has_no_measurement() -> None:
    area, length = compute_measurement(Point(1, 2))
    assert area is None
    assert length is None


def test_multipolygon_areas_sum() -> None:
    mp = MultiPolygon(
        [
            Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]),
            Polygon([(10, 10), (12, 10), (12, 12), (10, 12)]),
        ]
    )
    area, length = compute_measurement(mp)
    assert area == pytest.approx(4.0 + 4.0)
    assert length == pytest.approx(8.0 + 8.0)


def test_multilinestring_length_sums() -> None:
    mls = MultiLineString([[(0, 0), (5, 0)], [(0, 0), (0, 3)]])
    area, length = compute_measurement(mls)
    assert area is None
    assert length == pytest.approx(8.0)


def test_multipoint_no_measurement() -> None:
    mp = MultiPoint([(0, 0), (1, 1)])
    area, length = compute_measurement(mp)
    assert area is None
    assert length is None


def test_empty_geometry_returns_none() -> None:
    area, length = compute_measurement(Polygon())
    assert area is None
    assert length is None


def test_measurement_for_feature_picks_projected_crs() -> None:
    # ~1km square near Greenwich
    geom = Polygon([(0.0, 51.5), (0.01, 51.5), (0.01, 51.51), (0.0, 51.51)])
    result = measurement_for_feature(geom, src_crs="EPSG:4326")
    assert result["area_m2"] is not None
    assert result["length_m"] is not None
    # 0.01 degrees of longitude at lat 51.5 ≈ 694 m; latitude ≈ 1113 m.
    # So this square is roughly 694 m × 1113 m ≈ 772,000 m².
    assert 600_000 < result["area_m2"] < 950_000
    assert result["projected_crs"] is not None


def test_measurement_for_feature_point_is_none() -> None:
    geom = Point(0.0, 51.5)
    result = measurement_for_feature(geom, src_crs="EPSG:4326")
    assert result["area_m2"] is None
    assert result["length_m"] is None
