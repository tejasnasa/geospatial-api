# Geospatial File Measurement API

A small FastAPI backend that ingests geospatial files (Shapefile as a `.zip`,
or `.kml`), extracts their features, and returns per-feature measurements
(area in m² for polygons, length in m for line strings).

## Setup

```bash
# 1. Create a virtual environment
python -m venv .venv
. .venv/bin/activate   # PowerShell: .venv\Scripts\Activate.ps1

# 2. Install dependencies (project + dev/test)
pip install -e ".[dev]"

# 3. Run the API
uvicorn app.main:app --reload
```

On first request, the SQLite database (`geospatial.db`) is created automatically
and uploaded files are stored under `uploads/`.

## API

| Method | Path                            | Description                           |
| ------ | ------------------------------- | ------------------------------------- |
| GET    | `/api/healthz`                  | Liveness probe                        |
| GET    | `/api/files/`                   | List uploaded files                   |
| POST   | `/api/files/`                   | Upload a `.zip` (Shapefile) or `.kml` |
| GET    | `/api/files/{id}`               | File metadata + status                |
| GET    | `/api/files/{id}/`              | (trailing-slash alias of the above)   |
| GET    | `/api/files/{id}/measurements`  | Per-feature measurements              |
| GET    | `/api/files/{id}/measurements/` | (trailing-slash alias)                |
| GET    | `/docs`                         | Auto-generated OpenAPI / Swagger UI   |

Both slash and non-slash forms are registered for the per-file endpoints so
clients that follow the spec's trailing-slash URLs don't get a 307 redirect.

### Upload

```bash
curl -F file=@sample.kml http://localhost:8000/api/files/
```

Response (201 Created):

```json
{
  "id": "ABC123XYZ0",
  "filename": "sample.kml",
  "kind": "kml",
  "feature_count": 12,
  "crs": "EPSG:4326",
  "status": "COMPLETED",
  "error": null,
  "created_at": "2026-10-07T12:34:56+00:00"
}
```

For a Shapefile, upload the bundle as a `.zip`. Any `.shp` inside the zip is
auto-detected; its sidecar files (`.shx`, `.dbf`, `.prj`) must be present in the
same directory inside the zip.

### Measurements

```bash
curl http://localhost:8000/api/files/ABC123XYZ0/measurements
```

`supported_count` is the number of features that produced at least one
measurement — either metric (`area_m2` / `length_m`) or unitless
(`area_native` / `length_native`). Features with no measurement at all
(empty geometry, unsupported geometry type, or a corrupt/mislabeled source
CRS that we couldn't safely project) are not counted.

```json
{
  "file_id": "ABC123XYZ0",
  "feature_count": 12,
  "supported_count": 9,
  "features": [
    {
      "feature_index": 0,
      "external_id": "park",
      "geometry_type": "Polygon",
      "geometry": {
        "type": "Polygon",
        "coordinates": [
          [
            [-74.0, 40.7],
            [-74.0, 40.8],
            [-73.9, 40.8],
            [-73.9, 40.7],
            [-74.0, 40.7]
          ]
        ]
      },
      "src_crs": "EPSG:4326",
      "projected_crs": "EPSG:32618",
      "area_m2": 12345.6,
      "length_m": 444.0,
      "area_native": null,
      "length_native": null,
      "properties": { "name": "park" }
    },
    {
      "feature_index": 1,
      "external_id": "road",
      "geometry_type": "LineString",
      "geometry": {
        "type": "LineString",
        "coordinates": [
          [-74.0, 40.7],
          [-74.0, 40.8]
        ]
      },
      "src_crs": "EPSG:4326",
      "projected_crs": "EPSG:32618",
      "area_m2": null,
      "length_m": 250.7,
      "area_native": null,
      "length_native": null,
      "properties": { "name": "road" }
    },
    {
      "feature_index": 2,
      "external_id": "marker",
      "geometry_type": "Point",
      "geometry": { "type": "Point", "coordinates": [-74.0, 40.7] },
      "src_crs": "EPSG:4326",
      "projected_crs": "EPSG:32618",
      "area_m2": null,
      "length_m": null,
      "area_native": null,
      "length_native": null,
      "properties": { "name": "marker" }
    }
  ]
}
```

When the source CRS can't be identified (e.g. a `.prj`-less shapefile with
metric coordinates), measurements are reported under the unitless
`area_native` / `length_native` fields and `area_m2` / `length_m` are `null`
so the API never claims a unit it can't prove. `projected_crs` is the string
`"NATIVE"` in that case:

```json
{
  "feature_index": 0,
  "geometry_type": "Polygon",
  "src_crs": null,
  "projected_crs": "NATIVE",
  "area_m2": null,
  "length_m": null,
  "area_native": 1000000.0,
  "length_native": 4000.0
}
```

When the source CRS _is_ declared but the coordinates are out of range for
it — the classic case of a corrupt or mislabeled `.prj` (e.g. claims
`EPSG:4326` but the data is in projected metres) — we can't safely pick a
UTM zone from a centroid that isn't in degrees. Rather than fabricate a
number, we return that single feature with all four measurement fields
`null`, an empty `projected_crs`, and the original geometry still surfaced.
The rest of the response is unaffected.

## Architecture

```
app/
├── main.py                # FastAPI app + startup hook
├── api/
│   └── files.py           # HTTP endpoints
├── core/
│   ├── config.py          # settings (paths, limits)
│   ├── db.py              # SQLAlchemy engine + sessions
│   └── ids.py             # short random IDs
├── models/file.py         # ORM (FileRecord, FeatureRecord)
├── schemas/                # Pydantic v2 request/response models
└── services/
    ├── ingestion.py        # orchestrates read → persist
    ├── crs.py             # UTM zone math + transformer
    ├── measurements.py    # area/length on projected geometry
    └── readers/
        ├── base.py        # Reader protocol + RawFeature
        ├── shapefile.py   # zipped .shp/.shx/.dbf
        └── kml.py         # .kml via pyogrio/GDAL's KML driver
```

### File-processing flow

1. Client `POST`s `multipart/form-data` with a `file` part.
2. The endpoint saves the bytes under `uploads/{id}_{filename}` and creates a
   `FileRecord` row with `status = PROCESSING`.
3. `services/ingestion.ingest_file` detects the kind from the filename
   (`.zip` → Shapefile, `.kml` → KML) and dispatches to the matching reader.
4. The reader yields `RawFeature`s; each one becomes a `FeatureRecord` row with
   geometry serialized as GeoJSON.
5. On success the `FileRecord` is set to `COMPLETED`; on any reader error it's
   set to `FAILED` with a message (the endpoint returns 422).

### Measurement flow

1. `GET /api/files/{id}/measurements` loads every `FeatureRecord`.
2. For each feature we first reproject to WGS84 _only to pick a UTM zone from
   a sensible centroid_. We then reproject the _original_ geometry straight
   from its native CRS into the chosen UTM zone. This two-step approach is
   what makes the API work correctly for files whose native CRS is already
   projected — a common case for survey data.
3. We compute `area` and `length` on the reprojected geometry:
   - Polygon/MultiPolygon → area + boundary length
   - LineString/MultiLineString → length
   - Point/MultiPoint → null
   - GeometryCollection → sum from sub-geometries
   - Anything else → null (graceful fallback)

### CRS handling

The spec requires projected-CRS measurements and lets us choose the strategy.
We pick the UTM zone containing each geometry's centroid:

- Northern hemisphere → `EPSG:326xx`
- Southern hemisphere → `EPSG:327xx`

This avoids the classic "1° × 1° is not 1 m × 1 m" mistake and gives metric
units of measure everywhere on Earth (between 80°S and 84°N).

## Design Decisions

- **FastAPI** — typed contracts, auto OpenAPI, simple multipart upload.
- **SQLite + local filesystem** — single-command local dev, no external
  services, but persistent across restarts.
- **Sync ingestion** — keeps the minimum-spec shape (`POST` returns the
  processed file). The `status` field is wired so an async task queue could
  replace the synchronous path without breaking the contract.
- **GeoPandas + pyogrio** — geopandas 1.x reads via pyogrio (Fiona's
  successor). The same code path handles both Shapefile and KML; KML is
  enabled by pyogrio/GDAL's built-in KML driver.
- **pyproj + always_xy** — explicit CRS objects, no silent `lat,lon`/`lon,lat`
  flips.
- **Deterministic feature index** — 0-based integer index within a file.
  Optional `external_id` is taken from common attributes (`id`, `name`, `fid`).
- **Geometry stored as GeoJSON in the DB** — keeps the column portable and
  easy to inspect; measurements are computed on read so the CRS strategy can
  evolve without re-ingesting.
- **Two-step projection for measurements** — to pick a sensible UTM zone we
  first reproject each feature to WGS84 (cheap when already projected), then
  reproject the _original_ geometry straight into the chosen UTM zone. This
  is what makes the API work for files whose native CRS is already projected
  (a common case in survey data), and avoids treating easting metres as
  longitudes.
- **Upload size + zip-bomb guards** — `max_upload_bytes` (default 200 MB) is
  enforced while streaming to disk; shapefile zip extraction is capped at
  1 GB total / 500 MB per member and rejects path-traversal entries.

## Alternatives Considered

- **Django + DRF** — fine, just more boilerplate for the same surface.
- **Postgres + S3** — more "production", but heavy for a self-contained app.
- **Auto UTM vs equal-area (e.g. EPSG:6933)** — UTM is locally more accurate;
  equal-area is simpler. Picked UTM.
- **Background jobs (Celery/RQ)** — skipped for the assignment, but the
  `status` field is already in the response.
- **Asyncpg / async SQLAlchemy** — adds complexity; FastAPI handles sync DB
  calls fine for this scale.

## Testing

```bash
pytest
```

Unit tests cover the CRS service, the measurement service, and end-to-end
upload + measurement retrieval for both KML and Shapefile inputs.

## Learning

Things I hadn't done in this combination before:

- **Auto-picking UTM zones** from a centroid. The UTM zone formula is one of
  those things that looks intimidating but is five lines of Python.
- **pyogrio/GDAL's KML driver** — modern pyogrio reads KML without extra
  plugins, but it warns about mixed geometry types in a single layer (typical
  KML).
- **Shapefile as a bundle** — `.shp` is meaningless without `.shx` and
  `.dbf`. That's why the upload must be a zip.
- **Pydantic v2 + SQLAlchemy 2.x** together. `model_validate` from a
  `DeclarativeBase` instance works cleanly when the column types match.

## Future Scope

- **Background ingestion** for large files (Celery / ARQ) with status polling.
- **Auth + multi-user** isolation per tenant.
- **Streaming uploads** + partial progress.
- **Per-CRS override** — let the caller force a projected CRS instead of
  relying on auto-pick.
- **Geometry simplification** before measurement for huge features.
- **PostGIS backend** for files too large to fit in SQLite.
- **Geometry validation** (e.g. self-intersection detection) on upload.
