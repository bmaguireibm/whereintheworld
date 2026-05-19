"""
Phase 3b: Deep query optimization — explore query plans, try range scans, add sort key.
"""

import duckdb
import time

PARQUET_PATH = "data/geolocator.parquet"

db = duckdb.connect(":memory:")
db.execute("INSTALL spatial; LOAD spatial")
db.execute(f"CREATE VIEW geo AS SELECT * FROM read_parquet('{PARQUET_PATH}')")

print("=== EXPLAIN ANALYZE ===")
print("\n--- ILIKE 'Lon%' ---")
plan = db.execute("""
    EXPLAIN ANALYZE
    SELECT name, display_name, subtype, country
    FROM geo
    WHERE name ILIKE 'Lon%'
    ORDER BY CASE subtype
        WHEN 'country' THEN 1 WHEN 'region' THEN 2
        WHEN 'locality' THEN 3 ELSE 5 END
    LIMIT 10
""").fetchall()
for row in plan:
    print(row[0])

print("\n--- Range scan: name >= 'Lon' AND name < 'Lop' ---")
t0 = time.perf_counter()
result = db.execute("""
    SELECT name, display_name, subtype, country
    FROM geo
    WHERE name >= 'Lon' AND name < 'Lop'
    ORDER BY CASE subtype
        WHEN 'country' THEN 1 WHEN 'region' THEN 2
        WHEN 'locality' THEN 3 ELSE 5 END
    LIMIT 10
""").fetchdf()
elapsed = (time.perf_counter() - t0) * 1000
print(f"Time: {elapsed:.1f}ms, rows: {len(result)}")
for _, row in result.iterrows():
    print(f"  {row['display_name']} ({row['subtype']})")

print("\n--- Range scan with explain ---")
plan2 = db.execute("""
    EXPLAIN ANALYZE
    SELECT name, display_name, subtype, country
    FROM geo
    WHERE name >= 'Lon' AND name < 'Lop'
    LIMIT 10
""").fetchall()
for row in plan2:
    print(row[0])

# Test: does COLLATE matter?
print("\n--- Check how sort was applied ---")
sample = db.execute("""
    SELECT name FROM geo LIMIT 10
""").fetchdf()
print("First 10 by current sort:")
for _, r in sample.iterrows():
    print(f"  {r['name']}")

sample2 = db.execute("""
    SELECT name FROM geo ORDER BY name LIMIT 10
""").fetchdf()
print("First 10 with ORDER BY name:")
for _, r in sample2.iterrows():
    print(f"  {r['name']}")

# Test ILIKE vs LIKE on the sorted data
print("\n--- LIKE vs ILIKE comparison ---")
for pattern in ['Lon%', 'lon%', 'LON%', 'San%', '東%']:
    t0 = time.perf_counter()
    r1 = db.execute(f"SELECT count(*) FROM geo WHERE name LIKE '{pattern}'").fetchone()[0]
    t1 = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    r2 = db.execute(f"SELECT count(*) FROM geo WHERE name ILIKE '{pattern}'").fetchone()[0]
    t2 = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    # Range equivalent
    if pattern.endswith('%'):
        prefix = pattern[:-1]
        t0 = time.perf_counter()
        r3 = db.execute(f"""
            SELECT count(*) FROM geo
            WHERE name >= '{prefix}' AND name < '{prefix + chr(0x10FFFF)}'
        """).fetchone()[0]
        t3 = (time.perf_counter() - t0) * 1000
        print(f"  {pattern:12s}  LIKE={t1:6.1f}ms({r1})  ILIKE={t2:6.1f}ms({r2})  RANGE={t3:6.1f}ms({r3})")
    else:
        print(f"  {pattern:12s}  LIKE={t1:6.1f}ms({r1})  ILIKE={t2:6.1f}ms({r2})")

# Check if parquet metadata scan helps
print("\n--- Parquet metadata info ---")
meta = db.execute(f"""
    SELECT
        file_name,
        num_row_groups,
        row_group_id,
        row_group_num_rows,
        compression,
        total_compressed_size,
        total_uncompressed_size
    FROM parquet_metadata('{PARQUET_PATH}')
    ORDER BY row_group_id
""").fetchdf()
print(meta.to_string())

# Check row group column statistics
print("\n--- Row group name column min/max ---")
stats = db.execute(f"""
    SELECT
        row_group_id,
        column_id,
        stats_min,
        stats_max,
        stats_null_count
    FROM parquet_schema('{PARQUET_PATH}')
    WHERE name = 'name'
    ORDER BY row_group_id
""").fetchdf()
print(stats.to_string())

# What if we sort by NOCASE?
print("\n--- Case-insensitive sort check ---")
sample3 = db.execute("""
    SELECT name FROM geo ORDER BY name COLLATE NOCASE LIMIT 20
""").fetchdf()
print("First 20 (COLLATE NOCASE):")
for _, r in sample3.iterrows():
    print(f"  {r['name']}")

db.close()
