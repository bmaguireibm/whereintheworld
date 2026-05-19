"""Phase 1b continued: rule variants and country names."""

import duckdb

db = duckdb.connect(":memory:")
db.execute("INSTALL spatial; LOAD spatial")
db.execute("INSTALL httpfs; LOAD httpfs")
db.execute("SET s3_region = 'us-west-2'")

latest = db.execute(
    "SELECT latest FROM 'https://stac.overturemaps.org/catalog.json'"
).fetchone()[0]
release_path = f"s3://overturemaps-us-west-2/release/{latest}/theme=divisions/type=division_area/*"

print("=== NAME RULE VARIANT TYPES ===")
variants = db.execute(f"""
    SELECT r.variant, COUNT(*) as cnt
    FROM (
        SELECT unnest(names.rules) as r
        FROM read_parquet('{release_path}', hive_partitioning=1)
        WHERE is_land = true AND names.rules IS NOT NULL
    )
    GROUP BY r.variant
    ORDER BY cnt DESC
""").fetchdf()
print(variants.to_string())

for variant in variants['variant']:
    ex = db.execute(f"""
        SELECT names.primary as prim, unnest(names.rules) as r
        FROM read_parquet('{release_path}', hive_partitioning=1)
        WHERE is_land = true
          AND names.rules IS NOT NULL
        LIMIT 50
    """).fetchdf()
    matches = [(row['prim'], row['r']['value'], row['r'].get('language', ''))
               for _, row in ex.iterrows()
               if row['r'] is not None and row['r'].get('variant') == variant]
    if matches:
        print(f"\n  Variant: {variant}")
        for m in matches[:3]:
            print(f"    {m[0]} → {m[1]} (lang={m[2]})")

print("\n=== COUNTRY NAME LOOKUP ===")
countries = db.execute(f"""
    SELECT country, names.primary as primary_name, names.common
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE subtype = 'country' AND is_land = true
    ORDER BY country
""").fetchdf()

# Show a few and count
for _, c in countries.iterrows():
    common = c['common']
    en = common.get('en') if common else None
    if en is None:
        print(f"  NO_EN: {c['country']} primary='{c['primary_name']}' common={common}")
print(f"\nCountries needing EN fallback: {sum(1 for _,c in countries.iterrows() if c['common'] is None or c['common'].get('en') is None)}")
print(f"Total countries: {len(countries)}")

print("\n=== CHECKING FOR NON-LATIN NAMES ===")
scripts = db.execute(f"""
    SELECT
        CASE
            WHEN names.primary ~ '^[A-Za-z0-9 \\-\\.\\,\\(\\)\\'\\&]+$' THEN 'latin'
            ELSE 'non-latin'
        END as script,
        COUNT(*) as cnt
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE subtype = 'locality' AND is_land = true
    GROUP BY 1
""").fetchdf()
print(scripts.to_string())

print("\n=== NON-LATIN LOCALITY EXAMPLES ===")
non_latin = db.execute(f"""
    SELECT names.primary as name, country, names.common
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE subtype = 'locality' AND is_land = true
      AND names.primary !~ '^[A-Za-z0-9 \\-\\.\\,\\(\\)\\'\\&]+$'
    LIMIT 10
""").fetchdf()
for _, row in non_latin.iterrows():
    common = row['common']
    en = common.get('en') if common else None
    print(f"  {row['name']} ({row['country']}) en={en}")

print("\n=== DUPLICATE NAME HANDLING (worldwide) ===")
dupes = db.execute(f"""
    SELECT names.primary as name, COUNT(*) as cnt,
           LIST(DISTINCT country) as countries
    FROM read_parquet('{release_path}', hive_partitioning=1)
    WHERE subtype = 'locality' AND is_land = true
    GROUP BY name
    HAVING cnt > 1
    ORDER BY cnt DESC
    LIMIT 10
""").fetchdf()
for _, row in dupes.iterrows():
    print(f"  {row['name']}: {row['cnt']} times in {row['countries']}")

print("\nDone.")
