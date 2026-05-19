"""Phase 1: Data Discovery — Explore Overture Maps divisions data from S3."""

import duckdb

db = duckdb.connect(":memory:")

print("Loading extensions...")
db.execute("INSTALL spatial")
db.execute("LOAD spatial")
db.execute("INSTALL httpfs")
db.execute("LOAD httpfs")
db.execute("SET s3_region = 'us-west-2'")

print("\n--- Getting latest release from STAC catalog ---")
latest = db.execute(
    "SELECT latest FROM 'https://stac.overturemaps.org/catalog.json'"
).fetchone()[0]
print(f"Latest release: {latest}")

release_path = f"s3://overturemaps-us-west-2/release/{latest}/theme=divisions/type=division_area/*"
print(f"\nS3 path: {release_path}")

print("\n--- Schema inspection ---")
schema = db.execute(f"DESCRIBE SELECT * FROM read_parquet('{release_path}', hive_partitioning=1) LIMIT 0")
print(schema.fetchdf().to_string())

print("\n--- Row count by subtype ---")
counts = db.execute(f"""
    SELECT
        subtype,
        COUNT(*) as count,
        COUNT(DISTINCT country) as distinct_countries
    FROM read_parquet('{release_path}', hive_partitioning=1)
    GROUP BY subtype
    ORDER BY count DESC
""").fetchdf()
print(counts.to_string())

print("\n--- Country distribution (top 20) ---")
countries = db.execute(f"""
    SELECT country, COUNT(*) as count
    FROM read_parquet('{release_path}', hive_partitioning=1)
    GROUP BY country
    ORDER BY count DESC
    LIMIT 20
""").fetchdf()
print(countries.to_string())

print("\n--- Sample rows (10 random localities) ---")
sample = db.execute(f"""
    SELECT
        id,
        names.primary as name,
        subtype,
        country,
        region,
        admin_level,
        bbox
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE subtype = 'locality'
    USING SAMPLE 10
""").fetchdf()
print(sample.to_string())

print("\n--- Name structure examples ---")
names = db.execute(f"""
    SELECT
        names.primary as primary_name,
        names.common as common_names,
        names.rules as name_rules,
        subtype,
        country
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE subtype = 'locality'
      AND names.common IS NOT NULL
    USING SAMPLE 5
""").fetchdf()
for _, row in names.iterrows():
    print(f"\n  Primary: {row['primary_name']}")
    print(f"  Common:  {row['common_names']}")
    print(f"  Subtype: {row['subtype']}, Country: {row['country']}")

print("\n--- Cities with multiple common names (non-English) ---")
multi = db.execute(f"""
    SELECT
        names.primary as primary_name,
        names.common,
        subtype,
        country
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE subtype = 'locality'
      AND names.common IS NOT NULL
    USING SAMPLE 3
""").fetchdf()
for _, row in multi.iterrows():
    print(f"\n  Primary: {row['primary_name']}")
    print(f"  Common:  {row['common']}")
    print(f"  Country: {row['country']}")

print("\n--- Checking for NULL names ---")
nulls = db.execute(f"""
    SELECT COUNT(*) as null_names, COUNT(*) as total
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE names.primary IS NULL
""").fetchdf()
print(f"NULL names: {nulls['null_names'][0]} / {nulls['total'][0]}")

print("\n--- Country-level entries sample ---")
country_sample = db.execute(f"""
    SELECT
        names.primary as name,
        country,
        admin_level,
        is_land,
        is_territorial
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE subtype = 'country'
    LIMIT 5
""").fetchdf()
print(country_sample.to_string())

print("\n--- Locality examples with region context ---")
localities = db.execute(f"""
    SELECT
        names.primary as name,
        subtype,
        country,
        region
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE subtype IN ('locality', 'region')
      AND country = 'GB'
    LIMIT 10
""").fetchdf()
print(localities.to_string())

print("\n--- Estimated total row count ---")
total = db.execute(f"""
    SELECT COUNT(*) FROM read_parquet('{release_path}', hive_partitioning=1)
""").fetchone()[0]
print(f"Total rows: {total:,}")

db.close()
print("\nData discovery complete.")
