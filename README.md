# Where in the World

A low-resource, cloud-optimized geolocator for city, town, administrative area, and country-level forward geocoding with auto-complete. Built on [Overture Maps](https://overturemaps.org) data, [DuckDB](https://duckdb.org), and [GeoParquet](https://geoparquet.org).

**Features:**
- Auto-complete forward geocoding for 1M+ places worldwide
- Specify town + country/region (`"Dublin, Ireland"`, `"Austin, Texas"`)
- Optional lat/lng hint for proximity-biased results
- Support for Latin, CJK, Cyrillic, and Arabic name queries
- Transliterated search (e.g. "tokyo" finds `東京都`)
- Reverse geocoding from coordinates
- Subtype and country filtering
- ~30-50ms query latency, < 100 MB memory footprint
- Runs locally or reads directly from S3

## Quick Start

### Docker

```bash
docker run -p 8080:8080 ghcr.io/anomalyco/whereintheworld:latest
```

The image includes a pre-built GeoParquet with ~1M place records (Overture Maps 2026-04-15.0 release).

### Build from source

```bash
# 1. Generate the optimized GeoParquet (requires internet, ~10 min)
python scripts/02_build_parquet.py

# 2. Start the server
PARQUET_PATH=data/geolocator_v2.parquet PORT=8080 python server.py

# 3. Test it
curl "http://localhost:8080/v1/autocomplete?q=London&limit=5"
```

### From S3

```bash
# Point directly at a GeoParquet on S3
PARQUET_PATH=s3://my-bucket/geolocator.parquet \
  AWS_REGION=us-east-1 \
  python server.py
```

Sets up DuckDB's httpfs extension to query the parquet in-place without downloading.

## API

### `GET /health`

```json
{"status": "ok", "row_count": 1072414, "parquet_path": "data/geolocator_v2.parquet"}
```

### `GET /v1/autocomplete`

Forward geocode with prefix matching and auto-complete. Supports comma-separated `Town, Country` or `Town, Region` queries (e.g. `"Dublin, Ireland"`, `"Austin, Texas"`) and optional lat/lng proximity hints.

| Parameter | Type   | Default | Description                           |
|-----------|--------|---------|---------------------------------------|
| `q`       | string | _(req)_ | Search prefix (1-100 chars). Use `Town, Country` or `Town, Region` to scope results. |
| `limit`   | int    | 10      | Max results (1-50)                    |
| `subtype` | string | —       | Filter: `country`, `region`, `locality`, `county` |
| `country` | string | —       | ISO 3166-1 alpha-2 code (e.g. `US`)   |
| `lat`     | float  | —       | Latitude hint for proximity sorting (pair with `lng`) |
| `lng`     | float  | —       | Longitude hint for proximity sorting (pair with `lat`) |

```bash
curl "http://localhost:8080/v1/autocomplete?q=San%20F&limit=5"
curl "http://localhost:8080/v1/autocomplete?q=東京&limit=5"
curl "http://localhost:8080/v1/autocomplete?q=tokyo&limit=5"
curl "http://localhost:8080/v1/autocomplete?q=springfield&country=US&limit=5"
curl "http://localhost:8080/v1/autocomplete?q=Dublin,%20Ireland&limit=5"
curl "http://localhost:8080/v1/autocomplete?q=Austin,%20Texas&limit=5"
curl "http://localhost:8080/v1/autocomplete?q=San&limit=10&lat=37.77&lng=-122.42"
```

```json
{
  "results": [
    {
      "id": "381b1767-...",
      "name": "東京都",
      "display_name": "東京都, Japan",
      "subtype": "region",
      "country": "JP",
      "country_name": "Japan",
      "region": "JP-13",
      "latitude": 35.0764,
      "longitude": 139.5612,
      "population": null
    }
  ],
  "query": "东京",
  "took_ms": 13.2
}
```

### `GET /v1/search`

Full-text search across all name variants (slower, more comprehensive).

```bash
curl "http://localhost:8080/v1/search?q=München&limit=5"
```

### `GET /v1/reverse`

Reverse geocode from coordinates.

| Parameter | Type  | Default | Description       |
|-----------|-------|---------|-------------------|
| `lat`     | float | _(req)_ | Latitude (-90..90) |
| `lng`     | float | _(req)_ | Longitude (-180..180) |
| `limit`   | int   | 3       | Max results (1-10) |

```bash
curl "http://localhost:8080/v1/reverse?lat=51.5074&lng=-0.1278&limit=3"
```

## Architecture

```
Overture Maps S3 ──▶ DuckDB pipeline ──▶ Optimized GeoParquet (70MB)
                                                  │
                                          FastAPI server (50MB RSS)
                                                  │
                                    ┌─────────────┼─────────────┐
                              /v1/autocomplete  /v1/search  /v1/reverse
```

The parquet is sorted by a lowercased `sort_name` column, enabling DuckDB to use row-group min/max statistics to skip ~90% of row groups on prefix queries. A two-step search strategy uses the fast `sort_name` path first, then falls back to `name_en` for transliterated queries. Comma-separated queries (`"Dublin, Ireland"`) are parsed into a place prefix and scope filter that matches against country names, country codes, region names (via subquery), and region codes. Optional `lat`/`lng` parameters re-sort results by Euclidean distance for location-biased results.

## Configuration

| Env Variable      | Default                        | Description                     |
|-------------------|--------------------------------|---------------------------------|
| `PARQUET_PATH`    | `data/geolocator_v2.parquet`   | Local path or `s3://` URI       |
| `PORT`            | `5100`                         | Server listen port              |
| `HOST`            | `0.0.0.0`                      | Server listen address           |
| `DEFAULT_LIMIT`   | `10`                           | Default result count            |
| `MAX_LIMIT`       | `50`                           | Maximum result count            |
| `FALLBACK_THRESHOLD` | `5`                         | Trigger transliteration fallback|
| `S3_REGION`       | `us-west-2`                    | AWS region for S3 parquet       |

## Development

```bash
# Install dependencies
uv venv .venv && source .venv/bin/activate
uv pip install -r requirements.txt

# Data discovery (explore Overture Maps schema)
python scripts/01_data_discovery.py
python scripts/01b_name_deep_dive.py

# Build the optimized parquet
python scripts/02_build_parquet.py

# Run benchmarks
python scripts/03c_benchmark_v2.py

# Generate test fixture (for CI)
python scripts/generate_test_fixture.py

# Run server locally
PORT=5100 python server.py

# Run integration tests
python tests/test_server.py
```

## Data

Sourced from the [Overture Maps Foundation](https://overturemaps.org) divisions theme (`division_area` type), release 2026-04-15.0. Contains ~1M administrative divisions worldwide:

| Subtype        | Count    |
|----------------|----------|
| locality       | 567,307  |
| neighborhood   | 312,482  |
| microhood      | 83,468   |
| macrohood      | 44,796   |
| county         | 38,840   |
| localadmin     | 21,342   |
| region         | 3,907    |
| country        | 219      |
| dependency     | 53       |

Data is licensed under [Community Data License Agreement – Permissive v2.0](https://cdla.dev/permissive-2-0/).

## License

MIT
