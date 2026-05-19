"""Phase 1b: Deeper name structure exploration (fixed)."""

import duckdb

db = duckdb.connect(":memory:")

db.execute("INSTALL spatial")
db.execute("LOAD spatial")
db.execute("INSTALL httpfs")
db.execute("LOAD httpfs")
db.execute("SET s3_region = 'us-west-2'")

latest = db.execute(
    "SELECT latest FROM 'https://stac.overturemaps.org/catalog.json'"
).fetchone()[0]
print(f"Latest release: {latest}")

release_path = f"s3://overturemaps-us-west-2/release/{latest}/theme=divisions/type=division_area/*"

print("\n=== NAME STRUCTURE DEEP DIVE ===")

print("\n--- How many have names.common? ---")
non_null_counts = db.execute(f"""
    SELECT
        subtype,
        COUNT(*) as total,
        SUM(CASE WHEN names.common IS NOT NULL THEN 1 ELSE 0 END) as has_common,
        SUM(CASE WHEN names.rules IS NOT NULL THEN 1 ELSE 0 END) as has_rules,
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE is_land = true
    GROUP BY subtype
    ORDER BY total DESC
""").fetchdf()
print(non_null_counts.to_string())

print("\n--- Sample names with common MAP ---")
result = db.execute(f"""
    SELECT names.primary as primary_name, names.common, subtype, country
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE names.common IS NOT NULL
      AND is_land = true
    LIMIT 10
""").fetchdf()
for _, row in result.iterrows():
    print(f"\n  Primary: {row['primary_name']}")
    print(f"  Common:  {row['common']}")
    print(f"  Country: {row['country']}")

print("\n--- Sample names with RULES ---")
result2 = db.execute(f"""
    SELECT names.primary as primary_name, names.rules, subtype, country
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE names.rules IS NOT NULL
      AND is_land = true
    LIMIT 10
""").fetchdf()

for _, row in result2.iterrows():
    print(f"\n  Primary: {row['primary_name']}")
    print(f"  Country: {row['country']}")
    rules = row['rules']
    if rules is not None:
        print(f"  Rules:   {str(rules)[:500]}")

print("\n--- Distinct rule variants ---")
variants = db.execute(f"""
    SELECT rule.variant, COUNT(*) as cnt
    FROM read_parquet('{release_path}', hive_partitioning=1),
         UNNEST(names.rules) AS rule
    WHERE is_land = true
    GROUP BY rule.variant
    ORDER BY cnt DESC
""").fetchdf()
print(variants.to_string())

print("\n--- Rule examples per variant ---")
for variant in variants['variant']:
    ex = db.execute(f"""
        SELECT names.primary as prim, rule.variant, rule.language, rule.value
        FROM read_parquet('{release_path}', hive_partitioning=1),
             UNNEST(names.rules) AS rule
        WHERE rule.variant = '{variant}'
        LIMIT 3
    """).fetchdf()
    print(f"\n  Variant: {variant}")
    for _, r in ex.iterrows():
        print(f"    {r['prim']} → lang={r['language']}, val={r['value']}")

print("\n=== COUNTRY NAME RESOLUTION ===")
countries = db.execute(f"""
    SELECT country, names.primary as primary_name, names.common
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE subtype = 'country' AND is_land = true
    ORDER BY country
""").fetchdf()

print(f"\nTotal countries (land): {len(countries)}")
for _, c in countries.iterrows():
    common = c['common']
    en_name = common.get('en') if common else None
    print(f"  {c['country']:4s} primary={c['primary_name']:30s} en={en_name}")

print("\n=== LOCALITY vs LAND SPLIT ===")
split = db.execute(f"""
    SELECT is_land, is_territorial, COUNT(*) as cnt
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE subtype = 'locality'
    GROUP BY is_land, is_territorial
""").fetchdf()
print(split.to_string())

print("\n=== DUPLICATE LOCALITIES (same name, same country) ===")
dupes = db.execute(f"""
    SELECT names.primary as name, country, COUNT(*) as cnt
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE subtype = 'locality' AND is_land = true
    GROUP BY name, country
    HAVING cnt > 1
    ORDER BY cnt DESC
    LIMIT 20
""").fetchdf()
print(dupes.to_string())

print("\n=== CENTROIDS WORK ===")
centroids = db.execute(f"""
    SELECT
        names.primary as name,
        subtype,
        country,
        ROUND(ST_Y(ST_Centroid(geometry)), 4) as lat,
        ROUND(ST_X(ST_Centroid(geometry)), 4) as lng
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE subtype = 'locality' AND is_land = true
      AND names.primary ILIKE 'Lon%'
    LIMIT 5
""").fetchdf()
print(centroids.to_string())

db.close()
print("\nDone.")
