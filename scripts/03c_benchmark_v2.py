"""
Phase 3c: Benchmark v2 parquet with sort_name (lowercase, sorted for LIKE).
"""

import duckdb
import time

PARQUET_PATH = "data/geolocator_v2.parquet"

db = duckdb.connect(":memory:")
db.execute("INSTALL spatial; LOAD spatial")
db.execute(f"CREATE VIEW geo AS SELECT * FROM read_parquet('{PARQUET_PATH}')")

# Pre-warm
_ = db.execute("SELECT COUNT(*) FROM geo").fetchone()

def timed_query(label, sql, iterations=5):
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        result = db.execute(sql).fetchdf()
        elapsed = (time.perf_counter() - t0) * 1000
        times.append(elapsed)
    times.sort()
    p50 = times[len(times)//2]
    print(f"  {label:45s} p50={p50:7.1f}ms  min={min(times):7.1f}ms  rows={len(result)}")
    return times, result

print("=" * 80)
print("BENCHMARK: sort_name (lowercased, byte-sorted) vs ILIKE")
print("=" * 80)

print("\n--- LIKE on sort_name (the new optimized path) ---")
for prefix in ['L', 'Lo', 'Lon', 'Lond', 'Londo', 'san', 'london', 'new y', 'tokyo', 'мос', '東京']:
    sql = f"""
        SELECT name, display_name, subtype, country
        FROM geo
        WHERE sort_name LIKE '{prefix}%'
        ORDER BY CASE subtype
            WHEN 'country' THEN 1 WHEN 'region' THEN 2
            WHEN 'locality' THEN 3 ELSE 5 END
        LIMIT 10
    """
    times, result = timed_query(f"sort_name LIKE '{prefix}%'", sql, iterations=3)
    if len(result) > 0:
        print(f"           → {result['display_name'].iloc[0]}, ...")

print("\n--- Old ILIKE on name for comparison ---")
for prefix in ['Lon%', 'London%', 'San%']:
    sql = f"""
        SELECT name, display_name, subtype, country
        FROM geo
        WHERE name ILIKE '{prefix}'
        ORDER BY CASE subtype
            WHEN 'country' THEN 1 WHEN 'region' THEN 2
            WHEN 'locality' THEN 3 ELSE 5 END
        LIMIT 10
    """
    times, result = timed_query(f"name ILIKE '{prefix}'", sql, iterations=3)

print("\n--- Explaining sort_name LIKE query ---")
explain = db.execute("""
    EXPLAIN ANALYZE
    SELECT name, display_name, subtype, country
    FROM geo
    WHERE sort_name LIKE 'lon%'
    ORDER BY CASE subtype
        WHEN 'country' THEN 1 WHEN 'region' THEN 2
        WHEN 'locality' THEN 3 ELSE 5 END
    LIMIT 10
""").fetchall()
for row in explain:
    print(f"  {row[0]}")

print("\n--- Query: 'Springfield' exact match speed ---")
t0 = time.perf_counter()
r = db.execute("""
    SELECT name, display_name, region, country FROM geo
    WHERE sort_name = 'springfield' AND subtype = 'locality'
""").fetchdf()
t = (time.perf_counter() - t0) * 1000
print(f"  {t:.1f}ms, found {len(r)} Springfield(s)")
for _, row in r.head(5).iterrows():
    print(f"    {row['display_name']} [{row['region']}]")

print("\n--- Query: 'Dublin, Ireland' (town + country filter) ---")
t0 = time.perf_counter()
r = db.execute("""
    SELECT name, display_name, subtype, country, country_name
    FROM geo
    WHERE sort_name LIKE 'dublin%'
      AND LOWER(country_name) LIKE '%ireland%'
    ORDER BY CASE subtype
        WHEN 'country' THEN 1 WHEN 'dependency' THEN 2
        WHEN 'region' THEN 3 WHEN 'county' THEN 4
        WHEN 'locality' THEN 5 ELSE 6 END
    LIMIT 10
""").fetchdf()
t = (time.perf_counter() - t0) * 1000
print(f"  {t:.1f}ms, found {len(r)} result(s)")
for _, row in r.iterrows():
    print(f"    {row['display_name']} [{row['subtype']}]")

print("\n--- Query: 'San Francisco, United States' (town + country filter) ---")
for prefix, country_match in [('san fra', 'united states'), ('san f', 'us'), ('san francisco', 'united')]:
    t0 = time.perf_counter()
    r = db.execute(f"""
        SELECT name, display_name, subtype, country, country_name
        FROM geo
        WHERE sort_name LIKE '{prefix}%'
          AND (LOWER(country_name) LIKE '%{country_match}%' OR LOWER(country) = '{country_match}')
        ORDER BY CASE subtype
            WHEN 'country' THEN 1 WHEN 'dependency' THEN 2
            WHEN 'region' THEN 3 WHEN 'county' THEN 4
            WHEN 'locality' THEN 5 ELSE 6 END
        LIMIT 10
    """).fetchdf()
    t = (time.perf_counter() - t0) * 1000
    print(f"  'San Francisco, {country_match}': {t:.1f}ms, {len(r)} result(s) → {r['display_name'].iloc[0] if len(r) else 'N/A'}")

print("\n--- Query: 'Austin, Texas' (town + region filter via subquery) ---")
t0 = time.perf_counter()
r = db.execute("""
    SELECT name, display_name, subtype, country, country_name, region
    FROM geo
    WHERE sort_name LIKE 'austin%'
      AND subtype = 'locality'
      AND region IN (
        SELECT DISTINCT region FROM geo
        WHERE sort_name LIKE 'texas%' AND subtype = 'region'
      )
    ORDER BY CASE subtype
        WHEN 'country' THEN 1 WHEN 'dependency' THEN 2
        WHEN 'region' THEN 3 WHEN 'county' THEN 4
        WHEN 'locality' THEN 5 ELSE 6 END
    LIMIT 10
""").fetchdf()
t = (time.perf_counter() - t0) * 1000
print(f"  {t:.1f}ms, found {len(r)} result(s)")
for _, row in r.iterrows():
    print(f"    {row['display_name']} region={row['region']}")

print("\n--- Region-level matching (combined country + region filter) ---")
for place, scope in [('austin', 'texas'), ('springfield', 'illinois'),
                     ('san diego', 'ca'), ('portland', 'oregon')]:
    t0 = time.perf_counter()
    r = db.execute(f"""
        SELECT name, display_name, subtype, country, country_name, region
        FROM geo
        WHERE sort_name LIKE '{place}%'
          AND subtype = 'locality'
          AND (
            LOWER(country_name) LIKE '%{scope}%'
            OR LOWER(country) = '{scope}'
            OR region IN (
              SELECT DISTINCT region FROM geo
              WHERE sort_name LIKE '{scope}%' AND subtype = 'region'
            )
            OR LOWER(region) LIKE '%{scope}%'
          )
        ORDER BY CASE subtype
            WHEN 'country' THEN 1 WHEN 'dependency' THEN 2
            WHEN 'region' THEN 3 WHEN 'county' THEN 4
            WHEN 'locality' THEN 5 ELSE 6 END
        LIMIT 5
    """).fetchdf()
    t = (time.perf_counter() - t0) * 1000
    label = f"'{place.title()}, {scope.title()}'"
    print(f"  {label:40s} {t:.1f}ms, {len(r)} result(s)", end="")
    if len(r) > 0:
        print(f" → {r['display_name'].iloc[0]} [{r['region'].iloc[0]}]")
    else:
        print()

print("\n--- Proximity-sorted queries (lat/lng hint) ---")
hints = [
    ("London", 51.5074, -0.1278),
    ("San", 37.7749, -122.4194),
    ("San", 51.5074, -0.1278),
    ("Springfield", 39.7817, -89.6501),
]
for prefix, lat, lng in hints:
    sql = f"""
        SELECT name, display_name, subtype, country, latitude, longitude,
               ((latitude - {lat})*(latitude - {lat}) +
                (longitude - {lng})*(longitude - {lng})) as dist
        FROM geo
        WHERE sort_name LIKE '{prefix.lower()}%' AND subtype = 'locality'
        ORDER BY dist
        LIMIT 5
    """
    times, result = timed_query(f"'{prefix}' near ({lat:.1f},{lng:.1f})", sql, iterations=3)
    if len(result) > 0:
        for _, row in result.head(3).iterrows():
            print(f"           → {row['display_name']} dist={row['dist']:.4f}")

print("\n--- Proximity + country filter (combined) ---")
sql = f"""
    SELECT name, display_name, subtype, country, latitude, longitude,
           ((latitude - 53.3498)*(latitude - 53.3498) +
            (longitude - -6.2603)*(longitude - -6.2603)) as dist
    FROM geo
    WHERE sort_name LIKE 'dublin%'
      AND LOWER(country_name) LIKE '%ireland%'
    ORDER BY dist
    LIMIT 5
"""
times, result = timed_query("'Dublin' near Dublin, IE", sql, iterations=3)
if len(result) > 0:
    for _, row in result.head(3).iterrows():
        print(f"           → {row['display_name']} dist={row['dist']:.4f}")

print("\n--- Empty query (no filter) minimal overhead ---")
t0 = time.perf_counter()
r = db.execute("SELECT name FROM geo LIMIT 1").fetchdf()
t = (time.perf_counter() - t0) * 1000
print(f"  Minimal query: {t:.1f}ms")

print("\n--- Count-only query ---")
t0 = time.perf_counter()
cnt = db.execute("SELECT count(*) FROM geo WHERE sort_name LIKE 'san%'").fetchone()[0]
t = (time.perf_counter() - t0) * 1000
print(f"  COUNT WHERE sort_name LIKE 'san%': {t:.1f}ms, count={cnt}")

# Verify sort_name ordering
print("\n--- Verifying sort_name ordering (first 15 rows) ---")
sample = db.execute("SELECT sort_name, name FROM geo LIMIT 15").fetchdf()
for _, row in sample.iterrows():
    print(f"  sort={row['sort_name']:30s} → {row['name']}")

# Check stats
print("\n--- Row group stats for sort_name column ---")
stats = db.execute(f"""
    SELECT
        row_group_id,
        row_group_num_rows,
        column_id,
        stats_min,
        stats_max
    FROM parquet_metadata('{PARQUET_PATH}')
    WHERE path_in_schema = 'sort_name'
    ORDER BY row_group_id
""").fetchdf()
print(stats.to_string())

db.close()
print("\nDone.")
