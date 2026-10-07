"""End-to-end tests for KML upload + measurements."""

from __future__ import annotations

import io

KML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>park</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              {coords}
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>road</name>
      <LineString>
        <coordinates>
          {line}
        </coordinates>
      </LineString>
    </Placemark>
    <Placemark>
      <name>marker</name>
      <Point>
        <coordinates>0.005,0.005,0</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>
"""


def _square_ring(lat: float, lon: float, size: float) -> str:
    """Return a closed ring (lon,lat) around ``(lat,lon)`` of half-width ``size``."""

    coords = [
        (lon - size, lat - size),
        (lon + size, lat - size),
        (lon + size, lat + size),
        (lon - size, lat + size),
        (lon - size, lat - size),
    ]
    return "\n".join(f"{x},{y},0" for x, y in coords)


def _line() -> str:
    return "\n".join(f"{x},0,0" for x in (0.0, 0.001, 0.002, 0.003))


def test_upload_kml_and_fetch_measurements(client) -> None:
    kml_body = KML_TEMPLATE.format(coords=_square_ring(0.0, 0.0, 0.005), line=_line())

    response = client.post(
        "/api/files/",
        files={
            "file": (
                "sample.kml",
                io.BytesIO(kml_body.encode()),
                "application/vnd.google-earth.kml+xml",
            )
        },
    )
    assert response.status_code == 201, response.text
    info = response.json()
    assert info["status"] == "COMPLETED"
    assert info["kind"] == "kml"
    assert info["feature_count"] == 3

    file_id = info["id"]

    meas = client.get(f"/api/files/{file_id}/measurements")
    assert meas.status_code == 200, meas.text
    body = meas.json()
    assert body["feature_count"] == 3
    assert body["supported_count"] == 2  # polygon + line; point is skipped

    by_type = {f["geometry_type"]: f for f in body["features"]}
    assert "Polygon" in by_type
    assert "LineString" in by_type
    assert "Point" in by_type

    polygon = by_type["Polygon"]
    assert polygon["area_m2"] is not None
    assert polygon["length_m"] is not None
    assert polygon["area_m2"] > 0

    line = by_type["LineString"]
    assert line["area_m2"] is None
    assert line["length_m"] is not None
    assert line["length_m"] > 0

    point = by_type["Point"]
    assert point["area_m2"] is None
    assert point["length_m"] is None


def test_unknown_file_type_returns_422(client) -> None:
    response = client.post(
        "/api/files/",
        files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert response.status_code == 422
    assert "Unsupported file type" in response.text


def test_get_unknown_file_returns_404(client) -> None:
    response = client.get("/api/files/zzzzz")
    assert response.status_code == 404


def test_healthz(client) -> None:
    response = client.get("/api/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
