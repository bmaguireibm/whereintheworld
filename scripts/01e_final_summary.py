"""Phase 1b: Final summary of data discovery findings."""

import duckdb

db = duckdb.connect(":memory:")
db.execute("INSTALL spatial; LOAD spatial")
db.execute("INSTALL httpfs; LOAD httpfs")
db.execute("SET s3_region = 'us-west-2'")

latest = db.execute(
    "SELECT latest FROM 'https://stac.overturemaps.org/catalog.json'"
).fetchone()[0]
release_path = f"s3://overturemaps-us-west-2/release/{latest}/theme=divisions/type=division_area/*"

print("=== REGION COVERAGE BY SUBTYPE ===")
region_cnt = db.execute(f"""
    SELECT
        subtype,
        COUNT(*) as total,
        SUM(CASE WHEN region IS NOT NULL THEN 1 ELSE 0 END) as with_region,
        ROUND(100.0 * SUM(CASE WHEN region IS NOT NULL THEN 1 ELSE 0 END) / COUNT(*), 1) as pct
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE is_land = true
    GROUP BY subtype
    ORDER BY total DESC
""").fetchdf()
print(region_cnt.to_string())

print("\n=== NAME STATISTICS ===")
stats = db.execute(f"""
    SELECT
        subtype,
        COUNT(*) as total,
        AVG(LENGTH(names.primary)) as avg_name_len,
        MAX(LENGTH(names.primary)) as max_name_len,
        SUM(CASE WHEN names.common IS NOT NULL THEN 1 ELSE 0 END) as with_common,
        SUM(CASE WHEN names.rules IS NOT NULL THEN 1 ELSE 0 END) as with_rules
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE is_land = true
    GROUP BY subtype
    ORDER BY total DESC
""").fetchdf()
print(stats.to_string())

print("\n=== LONGEST LOCALITY NAMES ===")
longest = db.execute(f"""
    SELECT names.primary as name, LENGTH(names.primary) as len, country
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE subtype = 'locality' AND is_land = true
    ORDER BY LENGTH(names.primary) DESC
    LIMIT 5
""").fetchdf()
for _, row in longest.iterrows():
    print(f"  [{row['len']} chars] {row['name']} ({row['country']})")

print("\n=== HIERARCHY EXAMPLE (region→county→locality for US-CA) ===")
h = db.execute(f"""
    SELECT names.primary as name, subtype, admin_level
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE is_land = true AND country = 'US' AND region = 'US-CA'
      AND subtype IN ('region', 'county', 'locality')
    LIMIT 15
""").fetchdf()
print(h.to_string())

print("\n=== 'Springfield' duplicate check ===")
spring = db.execute(f"""
    SELECT names.primary as name, region, country, COUNT(*) OVER(PARTITION BY country) as cnt
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE is_land = true
      AND names.primary = 'Springfield' AND subtype = 'locality'
""").fetchdf()
print(f"Springfields found: {len(spring)}")
print(spring.head(10).to_string())

print("\n=== Country names final check ===")
countries = db.execute(f"""
    SELECT country, names.primary as name
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE subtype = 'country' AND is_land = true
    ORDER BY country
""").fetchdf()
no_en = 0
for _, c in countries.iterrows():
    if c['country'] in ('XB', 'XP', 'XR'):
        print(f"  {c['country']}: {c['name']} (no EN standard)")
        no_en += 1
print(f"  Total: {len(countries)} countries, {no_en} without EN name")

db.close()
print("\nData discovery summary complete.")
