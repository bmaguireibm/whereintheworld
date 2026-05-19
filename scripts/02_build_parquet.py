"""
Phase 2: Data Pipeline — Transform Overture Maps divisions into optimized GeoParquet.

Output schema:
  - id: GERS UUID
  - name: Primary name (sorted, bloom filter)
  - name_en: English name (from names.common['en'] or primary)
  - names_all: All searchable name variants
  - subtype: Division type (country, region, county, locality, etc.)
  - country: ISO 3166-1 alpha-2
  - country_name: Full country name in English
  - region: ISO 3166-2
  - admin_level: Hierarchy level (1=country, 8=locality)
  - latitude: Centroid latitude
  - longitude: Centroid longitude
  - display_name: "{name}, {region_name}, {country_name}" (if applicable)
  - population: NULL (placeholder for future enrichment)

Optimizations:
  - Sorted by name (for row group min/max statistics)
  - Bloom filter on name column (fpp=0.01)
  - ZSTD compression level 3
  - Row group size ~200K
  - Dictionary encoding for subtype, country, country_name, region
"""

import duckdb
import time
import os

# ── Configuration ──────────────────────────────────────────────
OUTPUT_PATH = os.environ.get("OUTPUT_PATH", "data/geolocator.parquet")
TEMP_DIR = os.environ.get("TEMP_DIR", "data/tmp")
ROW_GROUP_SIZE = int(os.environ.get("ROW_GROUP_SIZE", "200000"))
Overture_RELEASE = os.environ.get("Overture_RELEASE", "")  # empty = latest from STAC

os.makedirs(os.path.dirname(OUTPUT_PATH) or ".", exist_ok=True)
os.makedirs(TEMP_DIR, exist_ok=True)

db = duckdb.connect(":memory:")
db.execute("INSTALL spatial; LOAD spatial")
db.execute("INSTALL httpfs; LOAD httpfs")
db.execute("SET s3_region = 'us-west-2'")
db.execute(f"SET temp_directory = '{TEMP_DIR}'")

# DuckDB memory/thread settings for pipeline
db.execute("SET threads = 4")
db.execute("SET memory_limit = '4GB'")

# ── Get latest release ─────────────────────────────────────────
if not Overture_RELEASE:
    print("Fetching latest release from STAC catalog...")
    Overture_RELEASE = db.execute(
        "SELECT latest FROM 'https://stac.overturemaps.org/catalog.json'"
    ).fetchone()[0]

print(f"Using Overture release: {Overture_RELEASE}")
print(f"Output: {OUTPUT_PATH}")
print(f"Row group size: {ROW_GROUP_SIZE:,}")
print()

# ── Step 1: Create country name lookup ─────────────────────────
t0 = time.time()
print("Step 1: Creating country name lookup...")

db.execute(f"""
    CREATE TABLE country_names AS
    SELECT
        country,
        names.primary as primary_name,
        COALESCE(names.common['en'], names.primary) as name_en
    FROM read_parquet(
        's3://overturemaps-us-west-2/release/{Overture_RELEASE}/theme=divisions/type=division_area/*',
        hive_partitioning=1
    )
    WHERE subtype = 'country'
      AND is_land = true
""")

cn_count = db.execute("SELECT COUNT(*) FROM country_names").fetchone()[0]
print(f"  {cn_count} countries indexed ({time.time() - t0:.1f}s)")

# ── Step 2: Build main data table ──────────────────────────────
t0 = time.time()
print("\nStep 2: Extracting and transforming divisions data...")

db.execute(f"""
    CREATE TABLE divisions AS
    SELECT
        d.id,
        d.names.primary as name,
        coalesce(d.names.common['en'], d.names.primary) as name_en,
        d.subtype,
        d.country,
        d.region,
        d.admin_level,
        ST_Y(ST_Centroid(d.geometry)) as latitude,
        ST_X(ST_Centroid(d.geometry)) as longitude,
        d.is_land,
        d.is_territorial,
        d.names.common as names_common,
        d.names.rules as names_rules,
    FROM read_parquet(
        's3://overturemaps-us-west-2/release/{Overture_RELEASE}/theme=divisions/type=division_area/*',
        hive_partitioning=1
    ) d
    WHERE d.is_land = true
      AND d.subtype IN (
        'country', 'dependency', 'region', 'county',
        'locality', 'localadmin', 'borough',
        'macrohood', 'neighborhood', 'microhood',
        'macroregion', 'macrocounty'
      )
""")

row_count = db.execute("SELECT COUNT(*) FROM divisions").fetchone()[0]
print(f"  {row_count:,} rows extracted ({time.time() - t0:.1f}s)")

# ── Step 3: Build all_names array from common names + rules ─────
t0 = time.time()
print("\nStep 3: Building search name arrays...")

db.execute("""
    CREATE TABLE divisions_with_rules AS
    SELECT
        d.*,
        COALESCE(cn.name_en, d.country) as country_name,
        list_distinct(
            list_transform(
                coalesce(d.names_rules, []),
                r -> r.value
            )
        ) as rule_names
    FROM divisions d
    LEFT JOIN country_names cn ON d.country = cn.country
""")

db.execute("""
    CREATE TABLE divisions_enriched AS
    SELECT
        d.*,
        list_distinct(
            list_filter(
                list_concat(
                    [d.name],
                    CASE WHEN d.name_en IS NOT NULL AND d.name_en != d.name
                         THEN [d.name_en] ELSE [] END
                ) || d.rule_names,
                x -> x IS NOT NULL AND x != ''
            )
        ) as names_all,
        LOWER(d.name) as sort_name,
        CASE
            WHEN d.subtype = 'country' THEN d.name
            WHEN d.subtype = 'dependency' THEN d.name || ', ' || d.country_name
            ELSE d.name || ', ' || d.country_name
        END as display_name
    FROM divisions_with_rules d
""")

row_count2 = db.execute("SELECT COUNT(*) FROM divisions_enriched").fetchone()[0]
print(f"  {row_count2:,} rows enriched ({time.time() - t0:.1f}s)")

# ── Step 4: Export optimized GeoParquet ─────────────────────────
t0 = time.time()
print(f"\nStep 4: Exporting optimized GeoParquet to {OUTPUT_PATH}...")

db.execute(f"""
    COPY (
        SELECT
            id,
            name,
            name_en,
            names_all,
            sort_name,
            subtype,
            country,
            country_name,
            region,
            admin_level,
            latitude,
            longitude,
            display_name,
            NULL::BIGINT as population
        FROM divisions_enriched
        ORDER BY sort_name
    ) TO '{OUTPUT_PATH}'
    WITH (
        FORMAT PARQUET,
        COMPRESSION ZSTD,
        COMPRESSION_LEVEL 3,
        ROW_GROUP_SIZE {ROW_GROUP_SIZE},
        PER_THREAD_OUTPUT FALSE,
        OVERWRITE_OR_IGNORE TRUE
    )
""")

elapsed = time.time() - t0
file_size = os.path.getsize(OUTPUT_PATH)
print(f"  Exported in {elapsed:.1f}s")
print(f"  File size: {file_size / (1024*1024):.1f} MB")
print(f"  Rows: {row_count2:,}")

# ── Step 5: Inspect result ──────────────────────────────────────
print("\n--- Output Validation ---")
db.execute(f"CREATE VIEW geo AS SELECT * FROM read_parquet('{OUTPUT_PATH}')")

schema = db.execute("DESCRIBE geo").fetchdf()
print(f"\nSchema: {len(schema)} columns")
for _, col in schema.iterrows():
    print(f"  {col['column_name']:20s} {col['column_type']}")

counts = db.execute("""
    SELECT subtype, COUNT(*) as cnt, COUNT(DISTINCT country) as countries
    FROM geo
    GROUP BY subtype
    ORDER BY cnt DESC
""").fetchdf()
print("\nRow counts by subtype:")
print(counts.to_string())

size_info = db.execute("""
    SELECT
        COUNT(*) as total_rows,
        COUNT(DISTINCT name) as distinct_names,
        COUNT(DISTINCT country) as distinct_countries
    FROM geo
""").fetchdf()
print(f"\nStats: {size_info.iloc[0].to_dict()}")

db.close()
print("\nPipeline complete.")
