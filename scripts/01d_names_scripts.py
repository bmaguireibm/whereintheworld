"""Phase 1b continued: non-latin names and duplicates (using python filter)."""

import duckdb

db = duckdb.connect(":memory:")
db.execute("INSTALL spatial; LOAD spatial")
db.execute("INSTALL httpfs; LOAD httpfs")
db.execute("SET s3_region = 'us-west-2'")

latest = db.execute(
    "SELECT latest FROM 'https://stac.overturemaps.org/catalog.json'"
).fetchone()[0]
release_path = f"s3://overturemaps-us-west-2/release/{latest}/theme=divisions/type=division_area/*"

print("=== Country code validation ===")
codes = db.execute(f"""
    SELECT country, COUNT(*) as cnt
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE is_land = true AND subtype = 'locality'
    GROUP BY country
    ORDER BY cnt DESC
    LIMIT 5
""").fetchdf()
print(codes.to_string())

print("\n=== 'London' search example ===")
london = db.execute(f"""
    SELECT names.primary as name, subtype, country, region
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE is_land = true
      AND names.primary ILIKE 'London%'
    ORDER BY
        CASE subtype
            WHEN 'country' THEN 1
            WHEN 'region' THEN 2
            WHEN 'locality' THEN 3
            ELSE 5
        END
    LIMIT 15
""").fetchdf()
print(london.to_string())

print("\n=== 'San' search example ===")
san = db.execute(f"""
    SELECT names.primary as name, subtype, country
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE is_land = true
      AND names.primary ILIKE 'San %'
    LIMIT 10
""").fetchdf()
print(san.to_string())

print("\n=== 'Tokyo' characters test ===")
tokyo = db.execute(f"""
    SELECT names.primary as name, subtype, country, names.common
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE is_land = true AND country = 'JP'
      AND names.primary IS NOT NULL
    LIMIT 20
""").fetchdf()
has_cjk = 0
for _, row in tokyo.iterrows():
    if row['name'] and any(ord(c) > 127 for c in str(row['name'])):
        has_cjk += 1
        if has_cjk <= 5:
            common = row['common']
            en = common.get('en') if common else None
            print(f"  {row['name']} ({row['subtype']}) en={en}")

print(f"\n  Total JP rows with non-latin names in sample: {has_cjk}/20")

print("\n=== Non-latin name counting (sampling) ===")
sample_all = db.execute(f"""
    SELECT names.primary as name, country, names.common
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE is_land = true AND subtype = 'locality'
    LIMIT 10000
""").fetchdf()

non_latin_names = []
for _, row in sample_all.iterrows():
    name = str(row['name'])
    if any(ord(c) > 127 for c in name):
        non_latin_names.append((name, row['country']))
        if len(non_latin_names) <= 5:
            common = row['common']
            en = common.get('en') if common else None
            print(f"  {name} ({row['country']}) en={en}")

print(f"\n  Non-latin in 10000 sample: {len(non_latin_names)} ({100*len(non_latin_names)/10000:.1f}%)")

print("\n=== Top duplicated locality names (worldwide) ===")
dupes = db.execute(f"""
    SELECT names.primary as name, COUNT(*) as cnt,
           COUNT(DISTINCT country) as distinct_countries
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE subtype = 'locality' AND is_land = true
    GROUP BY name
    HAVING cnt > 1
    ORDER BY cnt DESC
    LIMIT 10
""").fetchdf()
print(dupes.to_string())

print("\n=== Region coverage ===")
region_cnt = db.execute(f"""
    SELECT
        subtype,
        COUNT(*) as total,
        SUM(CASE WHEN region IS NOT NULL THEN 1 ELSE 0 END) as with_region
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE is_land = true
    GROUP BY subtype
    ORDER BY total DESC
""").fetchdf()
print(region_cnt.to_string())

print("\n=== Country names as lookup table ===")
countries = db.execute(f"""
    SELECT country, names.primary as primary_name, names.common
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE subtype = 'country' AND is_land = true
    ORDER BY country
""").fetchdf()
for _, c in countries.iterrows():
    common = c['common']
    en = common.get('en') if common else c['primary_name']
    print(f"  {c['country']}: {en}")

print("\nDone.")
