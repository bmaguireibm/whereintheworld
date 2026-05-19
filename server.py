"""
Where in the World — Geocoding Server

Lightweight FastAPI server using DuckDB to query an optimized GeoParquet
for auto-complete forward geocoding.

Usage:
    python server.py
    # or
    PARQUET_PATH=s3://bucket/geolocator.parquet python server.py
"""

import os
import time
import math
import logging
from contextlib import asynccontextmanager
from typing import Optional

import duckdb
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Configuration ──────────────────────────────────────────────
PARQUET_PATH = os.environ.get("PARQUET_PATH", "data/geolocator_v2.parquet")
S3_REGION = os.environ.get("S3_REGION", "us-west-2")
DEFAULT_LIMIT = int(os.environ.get("DEFAULT_LIMIT", "10"))
MAX_LIMIT = int(os.environ.get("MAX_LIMIT", "50"))
FALLBACK_THRESHOLD = int(os.environ.get("FALLBACK_THRESHOLD", "5"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("whereintheworld")

db: duckdb.DuckDBPyConnection = None


def init_duckdb():
    global db
    logger.info("Initializing DuckDB...")
    db = duckdb.connect(":memory:")
    db.execute("INSTALL spatial")
    db.execute("LOAD spatial")

    is_s3 = PARQUET_PATH.startswith("s3://")
    if is_s3:
        logger.info("S3 path detected, loading httpfs extension")
        db.execute("INSTALL httpfs")
        db.execute("LOAD httpfs")
        db.execute(f"SET s3_region = '{S3_REGION}'")

    path = PARQUET_PATH
    if not is_s3:
        path = os.path.abspath(PARQUET_PATH)
        if not os.path.exists(path):
            raise FileNotFoundError(f"Parquet file not found: {path}")

    logger.info(f"Loading parquet from: {path}")
    db.execute(f"CREATE VIEW geo AS SELECT * FROM read_parquet('{path}')")

    t0 = time.perf_counter()
    row_count = db.execute("SELECT COUNT(*) FROM geo").fetchone()[0]
    elapsed = (time.perf_counter() - t0) * 1000
    logger.info(f"Pre-warmed. Row count: {row_count:,} ({elapsed:.0f}ms)")

    cols = db.execute("DESCRIBE geo").fetchdf()["column_name"].tolist()
    required = {"id", "name", "sort_name", "name_en", "subtype", "country",
                "country_name", "region", "latitude", "longitude", "display_name"}
    missing = required - set(cols)
    if missing:
        raise RuntimeError(f"Parquet missing required columns: {missing}")

    logger.info(f"DuckDB ready. {len(cols)} columns available.")


# ── Pydantic Models ────────────────────────────────────────────

class GeoResult(BaseModel):
    id: str
    name: str
    display_name: str
    subtype: str
    country: str
    country_name: str
    region: Optional[str] = None
    latitude: float
    longitude: float
    population: Optional[int] = None


class AutocompleteResponse(BaseModel):
    results: list[GeoResult]
    query: str
    took_ms: float


class HealthResponse(BaseModel):
    status: str
    row_count: int
    parquet_path: str


# ── Helpers ────────────────────────────────────────────────────

def _safe(val):
    """Convert NaN floats to None for Pydantic/JSON."""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    return val


def _row_to_result(r: dict) -> GeoResult:
    return GeoResult(
        id=r["id"],
        name=r["name"],
        display_name=r["display_name"],
        subtype=r["subtype"],
        country=r["country"],
        country_name=r["country_name"],
        region=_safe(r.get("region")),
        latitude=r["latitude"],
        longitude=r["longitude"],
    )


# ── Query Logic ─────────────────────────────────────────────────

SUBTYPE_PRIORITY = """
    CASE subtype
        WHEN 'country' THEN 1
        WHEN 'dependency' THEN 2
        WHEN 'region' THEN 3
        WHEN 'county' THEN 4
        WHEN 'locality' THEN 5
        WHEN 'localadmin' THEN 6
        ELSE 7
    END
"""


def search_fast(prefix: str, limit: int, subtype: Optional[str] = None,
                country: Optional[str] = None) -> list[dict]:
    subtype_clause = f"AND subtype = '{subtype}'" if subtype else ""
    country_clause = f"AND country = '{country}'" if country else ""
    sql = f"""
        SELECT id, name, display_name, subtype, country, country_name,
               region, latitude, longitude
        FROM geo
        WHERE sort_name LIKE '{prefix}%'
          {subtype_clause}
          {country_clause}
        ORDER BY {SUBTYPE_PRIORITY}
        LIMIT {limit}
    """
    return db.execute(sql).fetchdf().to_dict(orient="records")


def search_en_fallback(prefix: str, limit: int, exclude_ids: set,
                       subtype: Optional[str] = None,
                       country: Optional[str] = None) -> list[dict]:
    subtype_clause = f"AND subtype = '{subtype}'" if subtype else ""
    country_clause = f"AND country = '{country}'" if country else ""
    exclude_clause = ""
    if exclude_ids:
        ids = "', '".join(exclude_ids)
        exclude_clause = f"AND id NOT IN ('{ids}')"

    sql = f"""
        SELECT id, name, display_name, subtype, country, country_name,
               region, latitude, longitude
        FROM geo
        WHERE LOWER(name_en) LIKE '{prefix}%'
          {exclude_clause}
          {subtype_clause}
          {country_clause}
        ORDER BY {SUBTYPE_PRIORITY}
        LIMIT {limit}
    """
    return db.execute(sql).fetchdf().to_dict(orient="records")


def search(prefix: str, limit: int, subtype: Optional[str] = None,
           country: Optional[str] = None) -> tuple[list[dict], float]:
    t0 = time.perf_counter()
    primary = search_fast(prefix, limit, subtype, country)
    results = primary

    if len(results) < limit and len(results) < FALLBACK_THRESHOLD:
        exclude = {r["id"] for r in results}
        remaining = limit - len(results)
        fallback = search_en_fallback(prefix, remaining, exclude, subtype, country)
        results.extend(fallback)

    elapsed = (time.perf_counter() - t0) * 1000
    return results[:limit], elapsed


# ── App Lifespan ────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_duckdb()
    yield
    if db:
        db.close()
        logger.info("DuckDB connection closed.")


app = FastAPI(
    title="Where in the World",
    description="Low-resource, cloud-optimized geolocator",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Endpoints ───────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    row_count = db.execute("SELECT COUNT(*) FROM geo").fetchone()[0]
    return HealthResponse(status="ok", row_count=row_count, parquet_path=PARQUET_PATH)


@app.get("/v1/autocomplete", response_model=AutocompleteResponse)
async def autocomplete(
    q: str = Query(..., min_length=1, max_length=100),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    subtype: Optional[str] = Query(None),
    country: Optional[str] = Query(None, min_length=2, max_length=2),
):
    prefix = q.lower().replace("'", "''")
    results, took_ms = search(prefix, limit, subtype, country)
    return AutocompleteResponse(
        results=[_row_to_result(r) for r in results],
        query=q,
        took_ms=round(took_ms, 1),
    )


@app.get("/v1/search", response_model=AutocompleteResponse)
async def search_endpoint(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    subtype: Optional[str] = Query(None),
    country: Optional[str] = Query(None, min_length=2, max_length=2),
):
    """Full-text search across all name variants (slower, more comprehensive)."""
    prefix = q.lower().replace("'", "''")
    subtype_clause = f"AND subtype = '{subtype}'" if subtype else ""
    country_clause = f"AND country = '{country}'" if country else ""

    t0 = time.perf_counter()
    sql = f"""
        SELECT id, name, display_name, subtype, country, country_name,
               region, latitude, longitude
        FROM geo
        WHERE list_contains(names_all, '{q}')
           OR sort_name LIKE '%{prefix}%'
          {subtype_clause}
          {country_clause}
        ORDER BY {SUBTYPE_PRIORITY}
        LIMIT {limit}
    """
    results_df = db.execute(sql).fetchdf()
    took_ms = (time.perf_counter() - t0) * 1000

    return AutocompleteResponse(
        results=[_row_to_result(r) for _, r in results_df.iterrows()],
        query=q,
        took_ms=round(took_ms, 1),
    )


@app.get("/v1/reverse", response_model=AutocompleteResponse)
async def reverse(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    limit: int = Query(3, ge=1, le=10),
):
    t0 = time.perf_counter()
    sql = f"""
        SELECT id, name, display_name, subtype, country, country_name,
               region, latitude, longitude,
               ((latitude - {lat})*(latitude - {lat}) +
                (longitude - {lng})*(longitude - {lng})) as dist
        FROM geo
        WHERE subtype IN ('locality', 'region', 'county', 'country')
          AND latitude IS NOT NULL
        ORDER BY dist
        LIMIT {limit}
    """
    results_df = db.execute(sql).fetchdf()
    took_ms = (time.perf_counter() - t0) * 1000

    return AutocompleteResponse(
        results=[_row_to_result(r) for _, r in results_df.iterrows()],
        query=f"{lat},{lng}",
        took_ms=round(took_ms, 1),
    )


# ── Main ────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "5100"))
    logger.info(f"Starting server on {host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")
