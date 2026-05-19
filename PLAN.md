# Where in the World - Architecture & Implementation Plan

A low-resource, cloud-optimized geolocator for city, town, administrative area, and country-level forward geocoding with auto-complete. Built on Overture Maps data, DuckDB, and GeoParquet.

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                   Data Pipeline                      │
│                                                     │
│  Overture Maps S3 ──▶ DuckDB (httpfs) ──▶           │
│  (divisions theme)    Filter + Transform    ──▶     │
│                        Sort + Bloom Filter   ──▶    │
│                        Export to GeoParquet          │
└─────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│              Optimized GeoParquet                    │
│                                                     │
│  • Sorted by name (min/max row group stats)         │
│  • Bloom filter on name column                     │
│  • ZSTD compression                                 │
│  • Dictionary encoding (country, subtype)           │
│  • Row group size: ~200K rows                       │
│  • Partitioned by subtype (optional)                │
└─────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────┐
│                 Query Server                         │
│                                                     │
│  FastAPI / DuckDB ──▶ reads GeoParquet directly     │
│  (local or S3 via httpfs)                           │
│                                                     │
│  Endpoints:                                          │
│  GET /v1/autocomplete?q=<prefix>&limit=10           │
│  GET /v1/search?q=<query>&limit=10                  │
│  GET /v1/reverse?lat=<lat>&lng=<lng>                │
└─────────────────────────────────────────────────────┘
```

## 2. Data Source: Overture Maps

### Divisions Theme

The primary source is the **divisions** theme (`division_area` type) which contains:

| Subtype       | Admin Level | Description           |
|---------------|-------------|-----------------------|
| `country`     | 1-2         | Sovereign states      |
| `dependency`  | 1-2         | Dependent territories |
| `macroregion` | 3           | Large regions         |
| `region`      | 4           | States / provinces    |
| `macrocounty` | 5           | Large counties        |
| `county`      | 6           | Counties / districts  |
| `localadmin`  | 7           | Municipalities        |
| `locality`    | 8           | Cities / towns        |
| `borough`     | 9           | Boroughs              |
| `macrohood`   | 10          | Large neighborhoods   |
| `neighborhood`| 11          | Neighborhoods         |
| `microhood`   | 12          | Small neighborhoods   |

### Key Fields (from `division_area`)

| Field            | Type                  | Description                          |
|------------------|-----------------------|--------------------------------------|
| `id`             | UUID                  | GERS ID                              |
| `names.primary`  | String                | Most common name                     |
| `names.common`   | Map<String,String>    | Language → name (e.g., en→Munich)    |
| `subtype`        | PlaceType (enum)      | Category in hierarchy                |
| `country`        | ISO 3166-1 alpha-2    | Country code (e.g., US, GB)          |
| `region`         | ISO 3166-2            | Subdivision (e.g., US-CA)            |
| `admin_level`    | Int                   | Hierarchy level (1=country, 8=town)  |
| `bbox`           | Struct {xmin,ymin...} | Bounding box                         |
| `geometry`       | Polygon/MultiPolygon  | Area geometry (heavy)                |
| `is_land`        | Boolean               | Land-clipped vs territorial          |
| `division_id`    | UUID                  | Reference to parent division         |

### S3 Access Pattern

```
s3://overturemaps-us-west-2/release/YYYY-MM-DD.0/theme=divisions/type=division_area/*
```

Read via DuckDB: `read_parquet(..., hive_partitioning=1)`

## 3. Optimized GeoParquet Schema

### Design Goals

1. **Self-contained** — all needed fields in a single file, no joins needed
2. **Sorted by name** — row group min/max statistics enable skipping ~90%+ of row groups on prefix queries
3. **Bloom filter on name** — secondary filter for row groups
4. **Minimal columns** — drop heavy geometry, keep only what's needed for auto-complete
5. **Low memory** — DuckDB can read parquet with zero-copy, no need to load into RAM

### Target Schema

| Column           | Type      | Description                               |
|------------------|-----------|-------------------------------------------|
| `id`             | String    | GERS UUID                                 |
| `name`           | String    | Primary name (`names.primary`)            |
| `subtype`        | String    | country/region/county/locality/etc.       |
| `country`        | String    | ISO 3166-1 alpha-2 (e.g., US)             |
| `country_name`   | String    | Full country name in English              |
| `region`         | String    | ISO 3166-2 (e.g., US-CA)                  |
| `region_name`    | String    | Full region name (state/province)         |
| `admin_level`    | Int32     | Hierarchy level                           |
| `latitude`       | Float64   | Centroid latitude                         |
| `longitude`      | Float64   | Centroid longitude                        |
| `population`     | Int64     | Population estimate (from join or NULL)   |
| `names_all`      | String[]  | All name variants for search              |
| `hierarchy`      | String    | Full path: "United States, California, .."|
| `display_name`   | String    | "London, England, United Kingdom"         |

### Parquet Encoding & Optimization

| Column         | Encoding            | Compression | Reason                            |
|----------------|---------------------|-------------|-----------------------------------|
| `id`           | Plain               | ZSTD        | UUID, unpredictable               |
| `name`         | Dictionary → Plain  | ZSTD        | **Bloom filter**, sorted          |
| `subtype`      | Dictionary          | ZSTD        | ~12 distinct values               |
| `country`      | Dictionary          | ZSTD        | ~250 distinct values              |
| `country_name` | Dictionary          | ZSTD        | ~250 distinct values              |
| `region`       | Dictionary          | ZSTD        | ~5000 distinct values             |
| `region_name`  | Dictionary          | ZSTD        | ~5000 distinct values             |
| `admin_level`  | Plain               | ZSTD        | Small integers                    |
| `latitude`     | Plain               | ZSTD        | Float, unpredictable              |
| `longitude`    | Plain               | ZSTD        | Float, unpredictable              |
| `population`   | Plain               | ZSTD        | Integer, variable                 |
| `names_all`    | Plain               | ZSTD        | Array of strings                  |
| `hierarchy`    | Plain               | ZSTD        | Pre-computed string               |
| `display_name` | Plain               | ZSTD        | Pre-computed string               |

### Sorting Strategy

Sort by `name ASC` — this is the critical optimization. With data sorted by name:
- Row group 0: names A → Aa*
- Row group 1: names Aa* → An*
- Row group N: names Z* → Zz*

A prefix query for "Lon" only needs to scan row groups where `min(name) <= 'Lon' AND max(name) >= 'Lon'`, which is typically 2-3 row groups out of hundreds.

### Bloom Filter

Parquet bloom filter on `name` column with `fpp=0.01` (1% false positive rate). The filter is per-row-group. When querying `name LIKE 'Lon%'`, DuckDB checks each row group's bloom filter — if the filter says "no values starting with Lon", the row group is skipped entirely.

### Row Group Sizing

Target: **200,000 rows per row group**. With ~500K-1M localities worldwide:
- ~3-5 row groups for localities
- ~10-20 row groups total (all subtypes)
- Each row group ~5-20 MB compressed
- Keeps statistics granular without excessive overhead

### Partitioning (Optional)

Hive-style: `subtype=<value>/part-*.parquet`

Pros: Queries filtered by subtype skip irrelevant partitions entirely.
Cons: Multiple files, slightly more complex.

Decision: **Start with single file** (simpler, adequate for scale). Add partitioning if needed.

## 4. Query Strategy

### Auto-complete Query Pattern

```sql
SELECT id, name, subtype, country, country_name,
       region, region_name, admin_level,
       latitude, longitude, population,
       display_name
FROM read_parquet('geolocator.parquet')
WHERE name ILIKE 'lon%'
ORDER BY
    CASE subtype
        WHEN 'country' THEN 1
        WHEN 'dependency' THEN 2
        WHEN 'region' THEN 3
        WHEN 'locality' THEN 4
        WHEN 'county' THEN 5
        ELSE 6
    END,
    population DESC NULLS LAST,
    name
LIMIT 10
```

### Optimizations Used by DuckDB

1. **Row group pruning**: Min/max stats on sorted `name` column eliminate ~90%+ of row groups
2. **Bloom filter**: Confirms row group pruning decisions
3. **Late materialization**: Only reads `name` column first, then fetches other columns for surviving rows
4. **Column projection**: Only reads requested columns (not all 14)
5. **Limit pushdown**: Stops scanning once LIMIT is satisfied

### S3 Remote Access

When the geoparquet is on S3:
- DuckDB's httpfs extension fetches only the byte ranges needed (row group metadata → column chunks → data pages)
- Not the entire file
- Bloom filter pages fetched and checked before data pages
- Typically transfers < 5% of total file size per query

## 5. Expected Data Volumes

| Subtype      | Est. Count | Notes                          |
|--------------|------------|---------------------------------|
| `country`    | ~250       | Sovereign states + dependencies|
| `region`     | ~5,000     | States, provinces               |
| `county`     | ~100,000   | Counties, districts             |
| `locality`   | ~500,000   | Cities, towns, villages         |
| `localadmin` | ~200,000   | Municipalities                  |
| `others`     | ~300,000   | Boroughs, neighborhoods         |
| **Total**    | **~1.1M**  | Rows                            |

Estimated GeoParquet size: **~50-150 MB** (without geometry column, with ZSTD compression).

## 6. Server Implementation Plan

### Tech Choices

- **Language**: Python 3.12+
- **Framework**: FastAPI (lightweight, async, good for I/O-bound workloads)
- **Query Engine**: DuckDB (Python API, linked as library)
- **Package Manager**: uv (pip)

### Server Architecture

```
FastAPI (uvicorn, single worker)
  │
  ├── /v1/autocomplete?q=<prefix>&limit=<n>&subtype=<filter>
  ├── /v1/search?q=<query>&limit=<n>
  └── /v1/reverse?lat=<lat>&lng=<lng>&radius=<km>
  │
  └── DuckDB (in-process)
       │
       └── GeoParquet (local file or S3 via httpfs)
```

### Startup

1. Open DuckDB database (in-memory)
2. Install + load `spatial` and `httpfs` extensions
3. If S3: create a view over `s3://bucket/geolocator.parquet`
4. If local: create a view over local file
5. Pre-warm: run test query to populate parquet metadata cache

### Memory Profile

- DuckDB instance: ~10-20 MB (in-memory, no data loaded)
- FastAPI + uvicorn: ~30-50 MB
- Parquet metadata cached: ~1-5 MB
- **Total target: < 100 MB RSS**

### API Specification

#### `GET /v1/autocomplete`

Forward geocode with prefix matching.

| Parameter | Type   | Default | Description                        |
|-----------|--------|---------|------------------------------------|
| `q`       | String | (req)   | Search prefix (min 1 char)         |
| `limit`   | Int    | 10      | Max results (1-50)                 |
| `subtype` | String | (all)   | Filter: country,region,locality... |
| `country` | String | (all)   | Filter by ISO country code         |

Example: `GET /v1/autocomplete?q=Lon&limit=5`

Response:
```json
{
  "results": [
    {
      "id": "...",
      "name": "London",
      "subtype": "locality",
      "country": "GB",
      "country_name": "United Kingdom",
      "region": "GB-ENG",
      "region_name": "England",
      "latitude": 51.5074,
      "longitude": -0.1278,
      "population": 8982000,
      "display_name": "London, England, United Kingdom"
    }
  ],
  "query": "Lon",
  "took_ms": 12
}
```

#### `GET /v1/reverse`

Reverse geocode from coordinates.

| Parameter | Type   | Default | Description          |
|-----------|--------|---------|----------------------|
| `lat`     | Float  | (req)   | Latitude             |
| `lng`     | Float  | (req)   | Longitude            |
| `radius`  | Float  | 10.0    | Search radius (km)   |

(Phase 2 feature — basic bounding box filter for now)

### Health Check

`GET /health` → `{"status": "ok", "parquet_path": "...", "row_count": 1100000}`

## 7. Implementation Phases

### Phase 1: Data Discovery & Validation
- [ ] Query Overture Maps S3, explore divisions data
- [ ] Understand name structures (primary, common, rules)
- [ ] Sample data from major countries
- [ ] Identify edge cases (multi-name, disputed territories, etc.)
- [ ] Write tests validating row counts and data quality

### Phase 2: Data Pipeline
- [ ] Build DuckDB pipeline to extract + transform divisions data
- [ ] Implement sorting by name
- [ ] Compute centroids from polygon geometries
- [ ] Build display_name and hierarchy strings
- [ ] Export optimized GeoParquet with bloom filter
- [ ] Validate output with tests

### Phase 3: Query Optimization & Benchmarking
- [ ] Benchmark auto-complete query speeds (local parquet)
- [ ] Compare: vs unsorted, vs no bloom filter, vs different row group sizes
- [ ] Profile memory usage
- [ ] Document query plan and row group elimination
- [ ] Test with S3-hosted parquet

### Phase 4: Server Implementation
- [ ] FastAPI server with DuckDB backend
- [ ] Auto-complete endpoint
- [ ] Response caching headers
- [ ] Error handling and validation
- [ ] CORS support
- [ ] Dockerfile (multi-stage, minimal)

### Phase 5: Polish
- [ ] Rate limiting
- [ ] Request logging
- [ ] Metrics (response time percentiles)
- [ ] Integration tests
- [ ] Documentation

## 8. Technology Rationale

### Why DuckDB over...

- **PostGIS**: Too heavy, requires DB server, higher memory footprint. DuckDB is embeddable.
- **Elasticsearch**: Requires JVM, significant RAM, complex ops. Parquet + DuckDB is simpler.
- **SQLite**: Doesn't natively read Parquet, no bloom filter support, no S3.
- **Custom C++**: Over-engineered for this scale. DuckDB is fast enough (sub-100ms queries).

### Why GeoParquet over...

- **GeoJSON**: Much larger, no columnar optimizations, no statistics, no bloom filters.
- **PostGIS dump**: Requires database restore, not queryable in-place.
- **FlatGeobuf**: Good for streaming but less ecosystem support for cloud querying.
- **pmtiles**: Vector tile format, designed for rendering, not text search.

## 9. Risks & Mitigations

| Risk                              | Mitigation                                    |
|-----------------------------------|-----------------------------------------------|
| Overture data has gaps in coverage| Validate row counts per country; log coverage |
| Name duplicates cause bad results | Rank by subtype priority + population          |
| Bloom filter false positives      | fpp=0.01, sorted data is the primary filter   |
| S3 latency for remote queries     | Row group pruning minimizes data transferred  |
| Large geometry column bloats file | Drop geometry, store only centroid coordinates|
| Unicode/encoding issues in names  | Test with CJK, Arabic, Cyrillic names         |
| Parquet version compatibility     | Use DuckDB >= 1.1.0 for GeoParquet support    |
