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
