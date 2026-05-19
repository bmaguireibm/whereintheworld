"""
Phase 3: Query Speed Benchmarks — Test auto-complete performance on the optimized GeoParquet.

Tests:
  1. Cold vs warm query times
  2. Prefix matching at various lengths
  3. Different LIMIT values
  4. With/without subtype filtering
  5. Row group pruning effectiveness (EXPLAIN ANALYZE)
  6. Memory usage
"""

import duckdb
import time
import os
import sys

PARQUET_PATH = os.environ.get("PARQUET_PATH", "data/geolocator.parquet")

if not os.path.exists(PARQUET_PATH):
    print(f"ERROR: {PARQUET_PATH} not found. Run 02_build_parquet.py first.")
    sys.exit(1)

db = duckdb.connect(":memory:")
db.execute("INSTALL spatial; LOAD spatial")
db.execute(f"CREATE VIEW geo AS SELECT * FROM read_parquet('{PARQUET_PATH}')")

# Pre-warm
_ = db.execute("SELECT COUNT(*) FROM geo").fetchone()

def timed_query(label, sql, iterations=5):
    """Run query multiple times and report timing stats."""
    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        result = db.execute(sql).fetchdf()
        elapsed = (time.perf_counter() - t0) * 1000
        times.append(elapsed)
    times.sort()
    print(f"  {label:50s} min={min(times):8.1f}ms  "
          f"median={times[len(times)//2]:8.1f}ms  "
          f"rows={len(result)}")
    return times, result

print("=" * 80)
print("PHASE 3: QUERY SPEED BENCHMARKS")
print("=" * 80)

# ── Test 1: Query plan analysis ─────────────────────────────────
print("\n--- Test 1: EXPLAIN ANALYZE for prefix query ---")
plan = db.execute("""
    EXPLAIN ANALYZE
    SELECT name, display_name, subtype, country, latitude, longitude
    FROM geo
    WHERE name ILIKE 'Lon%'
    ORDER BY
        CASE subtype
            WHEN 'country' THEN 1
            WHEN 'region' THEN 2
            WHEN 'locality' THEN 3
            WHEN 'county' THEN 4
            ELSE 5
        END,
        length(name)
    LIMIT 10
""").fetchdf()

for _, row in plan.iterrows():
    print(f"  {row.iloc[0]}")

# ── Test 2: Prefix queries at various lengths ───────────────────
print("\n--- Test 2: Prefix query latency vs prefix length ---")
prefixes = [
    ("L",     "Single char"),
    ("Lo",    "Two chars"),
    ("Lon",   "Three chars"),
    ("Lond",  "Four chars"),
    ("Londo", "Five chars"),
    ("San F", "With space"),
    ("東",    "CJK single"),
    ("東京",   "CJK two chars"),
    ("Мос",   "Cyrillic"),
]

for prefix, desc in prefixes:
    sql = f"""
        SELECT name, display_name, subtype, country, latitude, longitude
        FROM geo
        WHERE name ILIKE '{prefix}%'
        ORDER BY
            CASE subtype
                WHEN 'country' THEN 1
                WHEN 'region' THEN 2
                WHEN 'locality' THEN 3
                ELSE 5
            END
        LIMIT 10
    """
    try:
        times, result = timed_query(desc, sql, iterations=3)
        if len(result) > 0:
            sample = ", ".join(result['display_name'].head(3).tolist())
            print(f"         Results: {sample}")
    except Exception as e:
        print(f"  ERROR: {e}")

# ── Test 3: Different limit sizes ───────────────────────────────
print("\n--- Test 3: Latency vs LIMIT size ---")
for limit in [1, 5, 10, 20, 50]:
    sql = f"""
        SELECT name, display_name, subtype, country
        FROM geo
        WHERE name ILIKE 'San%'
        ORDER BY
            CASE subtype
                WHEN 'country' THEN 1
                WHEN 'region' THEN 2
                WHEN 'locality' THEN 3
                ELSE 5
            END
        LIMIT {limit}
    """
    times, _ = timed_query(f"LIMIT {limit}", sql, iterations=3)

# ── Test 4: Subtype filtering ───────────────────────────────────
print("\n--- Test 4: Subtype-filtered queries ---")
for subtype in ['country', 'region', 'locality', 'county']:
    sql = f"""
        SELECT name, display_name, country, latitude, longitude
        FROM geo
        WHERE name ILIKE 'San%'
          AND subtype = '{subtype}'
        LIMIT 10
    """
    times, result = timed_query(f"subtype={subtype}", sql, iterations=3)
    if len(result) > 0:
        print(f"         {len(result)} results")

# ── Test 5: Country-filtered queries ────────────────────────────
print("\n--- Test 5: Country-filtered queries ---")
for country in ['US', 'GB', 'JP', 'FR']:
    sql = f"""
        SELECT name, display_name, subtype, latitude, longitude
        FROM geo
        WHERE name ILIKE 'San%'
          AND country = '{country}'
        LIMIT 10
    """
    times, result = timed_query(f"country={country}", sql, iterations=3)
    if len(result) > 0:
        print(f"         {len(result)} results (sample: {result['display_name'].iloc[0] if len(result) > 0 else 'none'})")

# ── Test 6: Full-text search on names_all ───────────────────────
print("\n--- Test 6: Search across all name variants ---")
sql = """
    SELECT name, display_name, subtype, country
    FROM (
        SELECT *, unnest(names_all) as search_name
        FROM geo
    )
    WHERE search_name ILIKE 'München%'
    LIMIT 10
"""
times, result = timed_query("München (via names_all)", sql, iterations=3)
for _, row in result.iterrows():
    print(f"    {row['display_name']} ({row['subtype']})")

sql = """
    SELECT name, display_name, subtype, country
    FROM (
        SELECT *, unnest(names_all) as search_name
        FROM geo
    )
    WHERE search_name ILIKE 'Londres%'
    LIMIT 10
"""
times, result = timed_query("Londres (via names_all)", sql, iterations=3)
for _, row in result.iterrows():
    print(f"    {row['display_name']} ({row['subtype']})")

# ── Test 7: Memory usage estimate ───────────────────────────────
print("\n--- Test 7: Memory usage ---")
try:
    import psutil
    process = psutil.Process()
    mem = process.memory_info()
    print(f"  RSS: {mem.rss / (1024*1024):.1f} MB")
    print(f"  VMS: {mem.vms / (1024*1024):.1f} MB")
except ImportError:
    print("  (psutil not installed, skipping)")

# ── Test 8: Row group pruning effectiveness ─────────────────────
print("\n--- Test 8: Row group pruning analysis ---")
# Check how many row groups each query scans
queries_to_analyze = [
    ("Lon short prefix", "WHERE name ILIKE 'Lon%'"),
    ("San common prefix", "WHERE name ILIKE 'San%'"),
    ("Zz rare prefix", "WHERE name ILIKE 'Zz%'"),
    ("Single 'A'", "WHERE name ILIKE 'A%'"),
    ("Empty prefix", "WHERE TRUE"),
]

for label, where in queries_to_analyze:
    sql = f"""
        SELECT name, display_name, subtype
        FROM geo
        {where}
        LIMIT 20
    """
    # Just get rough timing as proxy for row group pruning
    t0 = time.perf_counter()
    result = db.execute(sql).fetchdf()
    elapsed = (time.perf_counter() - t0) * 1000
    print(f"  {label:25s}: {elapsed:8.1f}ms, {len(result)} results")

db.close()
print("\nBenchmarks complete.")
