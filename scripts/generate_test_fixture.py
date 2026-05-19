"""Generate a small test parquet fixture for CI testing."""

import os
import duckdb

OUTPUT = os.environ.get("TEST_PARQUET_PATH", "data/test_geolocator.parquet")
ROW_GROUP_SIZE = int(os.environ.get("ROW_GROUP_SIZE", "100"))
os.makedirs(os.path.dirname(OUTPUT) or ".", exist_ok=True)

db = duckdb.connect(":memory:")
db.execute("INSTALL spatial; LOAD spatial")

print(f"Generating test parquet: {OUTPUT}")

db.execute("""
    CREATE TABLE test_data AS
    SELECT *
    FROM (
        VALUES
            ('id_000001', 'London', 'london', 'London', ['London'], 'locality', 'GB', 'United Kingdom', 'GB-ENG', 8, 51.5074, -0.1278, 'London, United Kingdom'),
            ('id_000002', 'Londonderry', 'londonderry', 'Londonderry', ['Londonderry'], 'locality', 'GB', 'United Kingdom', 'GB-NIR', 8, 54.9927, -7.3251, 'Londonderry, United Kingdom'),
            ('id_000003', 'London Colney', 'london colney', 'London Colney', ['London Colney'], 'locality', 'GB', 'United Kingdom', 'GB-ENG', 8, 51.7210, -0.3016, 'London Colney, United Kingdom'),
            ('id_000004', 'London', 'london', 'London', ['London'], 'locality', 'US', 'United States', 'US-OH', 8, 39.8952, -83.4368, 'London, United States'),
            ('id_000005', 'London', 'london', 'London', ['London'], 'locality', 'US', 'United States', 'US-KY', 8, 37.1208, -84.0798, 'London, United States'),
            ('id_000006', 'London', 'london', 'London', ['London'], 'county', 'CA', 'Canada', 'CA-ON', 6, 42.9534, -81.2379, 'London, Canada'),
            ('id_000007', 'Paris', 'paris', 'Paris', ['Paris'], 'locality', 'FR', 'France', 'FR-IDF', 8, 48.8566, 2.3522, 'Paris, France'),
            ('id_000008', 'Paradise', 'paradise', 'Paradise', ['Paradise'], 'locality', 'US', 'United States', 'US-NV', 8, 36.0972, -115.1467, 'Paradise, United States'),
            ('id_000009', 'San Francisco', 'san francisco', 'San Francisco', ['San Francisco'], 'locality', 'US', 'United States', 'US-CA', 8, 37.7749, -122.4194, 'San Francisco, United States'),
            ('id_000010', 'San Diego', 'san diego', 'San Diego', ['San Diego'], 'locality', 'US', 'United States', 'US-CA', 8, 32.7157, -117.1611, 'San Diego, United States'),
            ('id_000011', 'San Jose', 'san jose', 'San Jose', ['San Jose'], 'locality', 'US', 'United States', 'US-CA', 8, 37.3382, -121.8863, 'San Jose, United States'),
            ('id_000012', 'Springfield', 'springfield', 'Springfield', ['Springfield'], 'locality', 'US', 'United States', 'US-IL', 8, 39.7817, -89.6501, 'Springfield, United States'),
            ('id_000013', 'Springfield', 'springfield', 'Springfield', ['Springfield'], 'locality', 'US', 'United States', 'US-MO', 8, 37.2089, -93.2923, 'Springfield, United States'),
            ('id_000014', 'New York', 'new york', 'New York', ['New York'], 'region', 'US', 'United States', 'US-NY', 3, 40.7128, -74.0060, 'New York, United States'),
            ('id_000015', 'New York', 'new york', 'New York', ['New York'], 'locality', 'US', 'United States', 'US-NY', 8, 40.7128, -74.0060, 'New York, United States'),
            ('id_000016', 'Newark', 'newark', 'Newark', ['Newark'], 'locality', 'US', 'United States', 'US-NJ', 8, 40.7357, -74.1724, 'Newark, United States'),
            ('id_000017', '東京都', '東京都', 'Tokyo', ['東京都', 'Tokyo'], 'region', 'JP', 'Japan', 'JP-13', 3, 35.6762, 139.6503, '東京都, Japan'),
            ('id_000018', '東京おかしランド', '東京おかしらんど', 'Tokyo Okashi Land', ['東京おかしランド', 'Tokyo Okashi Land'], 'microhood', 'JP', 'Japan', 'JP-13', 12, 35.6809, 139.7682, '東京おかしランド, Japan'),
            ('id_000019', '北京市', '北京市', 'Beijing', ['北京市', 'Beijing'], 'region', 'CN', 'China', 'CN-BJ', 3, 39.9042, 116.4074, '北京市, China'),
            ('id_000020', 'Москва', 'Москва', 'Москва', ['Москва'], 'region', 'RU', 'Russia', 'RU-MOW', 3, 55.7558, 37.6173, 'Москва, Russia'),
            ('id_000021', 'München', 'münchen', 'München', ['München'], 'locality', 'DE', 'Germany', 'DE-BY', 8, 48.1351, 11.5820, 'München, Germany'),
            ('id_000022', 'Münster', 'münster', 'Münster', ['Münster'], 'locality', 'DE', 'Germany', 'DE-NW', 8, 51.9607, 7.6261, 'Münster, Germany'),
            ('id_000023', 'Berlin', 'berlin', 'Berlin', ['Berlin'], 'region', 'DE', 'Germany', 'DE-BE', 3, 52.5200, 13.4050, 'Berlin, Germany'),
            ('id_000024', 'Berlin', 'berlin', 'Berlin', ['Berlin'], 'locality', 'DE', 'Germany', 'DE-BE', 8, 52.5200, 13.4050, 'Berlin, Germany'),
            ('id_000025', 'Bern', 'bern', 'Bern', ['Bern'], 'locality', 'CH', 'Switzerland', 'CH-BE', 8, 46.9480, 7.4474, 'Bern, Switzerland'),
            ('id_000026', 'Belgrade', 'belgrade', 'Belgrade', ['Belgrade'], 'locality', 'RS', 'Serbia', 'RS-00', 8, 44.7866, 20.4489, 'Belgrade, Serbia'),
            ('id_000027', 'Barcelona', 'barcelona', 'Barcelona', ['Barcelona'], 'locality', 'ES', 'Spain', 'ES-CT', 8, 41.3874, 2.1686, 'Barcelona, Spain'),
            ('id_000028', 'Washington', 'washington', 'Washington', ['Washington'], 'region', 'US', 'United States', 'US-DC', 3, 38.9072, -77.0369, 'Washington, United States'),
            ('id_000029', 'Washington', 'washington', 'Washington', ['Washington'], 'locality', 'US', 'United States', 'US-DC', 8, 38.9072, -77.0369, 'Washington, United States'),
            ('id_000030', 'Amsterdam', 'amsterdam', 'Amsterdam', ['Amsterdam'], 'locality', 'NL', 'Netherlands', 'NL-NH', 8, 52.3676, 4.9041, 'Amsterdam, Netherlands'),
            ('id_000031', 'Athens', 'athens', 'Athens', ['Athens'], 'locality', 'GR', 'Greece', 'GR-I', 8, 37.9838, 23.7275, 'Athens, Greece'),
            ('id_000032', 'Atlanta', 'atlanta', 'Atlanta', ['Atlanta'], 'locality', 'US', 'United States', 'US-GA', 8, 33.7490, -84.3880, 'Atlanta, United States'),
            ('id_000033', 'Zürich', 'zürich', 'Zürich', ['Zürich'], 'locality', 'CH', 'Switzerland', 'CH-ZH', 8, 47.3769, 8.5417, 'Zürich, Switzerland'),
            ('id_000034', 'Zaragoza', 'zaragoza', 'Zaragoza', ['Zaragoza'], 'locality', 'ES', 'Spain', 'ES-AR', 8, 41.6488, -0.8891, 'Zaragoza, Spain'),
            ('id_000035', 'Tokyo', 'tokyo', 'Tokyo', ['Tokyo'], 'locality', 'US', 'United States', 'US-TX', 8, 30.2672, -97.7431, 'Tokyo, United States'),
            ('id_000036', 'United Kingdom', 'united kingdom', 'United Kingdom', ['United Kingdom'], 'country', 'GB', 'United Kingdom', NULL, 1, 55.3781, -3.4360, 'United Kingdom'),
            ('id_000037', 'United States', 'united states', 'United States', ['United States'], 'country', 'US', 'United States', NULL, 1, 37.0902, -95.7129, 'United States'),
            ('id_000038', 'France', 'france', 'France', ['France'], 'country', 'FR', 'France', NULL, 1, 46.2276, 2.2137, 'France'),
            ('id_000039', 'Germany', 'germany', 'Germany', ['Germany'], 'country', 'DE', 'Germany', NULL, 1, 51.1657, 10.4515, 'Germany'),
            ('id_000040', 'Japan', 'japan', 'Japan', ['Japan'], 'country', 'JP', 'Japan', NULL, 1, 36.2048, 138.2529, 'Japan'),
            ('id_000041', 'China', 'china', 'China', ['China'], 'country', 'CN', 'China', NULL, 1, 35.8617, 104.1954, 'China'),
            ('id_000042', 'Russia', 'russia', 'Russia', ['Russia'], 'country', 'RU', 'Russia', NULL, 1, 61.5240, 105.3188, 'Russia'),
            ('id_000043', 'Spain', 'spain', 'Spain', ['Spain'], 'country', 'ES', 'Spain', NULL, 1, 40.4637, -3.7492, 'Spain'),
            ('id_000044', 'Switzerland', 'switzerland', 'Switzerland', ['Switzerland'], 'country', 'CH', 'Switzerland', NULL, 1, 46.8182, 8.2275, 'Switzerland'),
            ('id_000045', 'Netherlands', 'netherlands', 'Netherlands', ['Netherlands'], 'country', 'NL', 'Netherlands', NULL, 1, 52.1326, 5.2913, 'Netherlands'),
            ('id_000046', 'Greece', 'greece', 'Greece', ['Greece'], 'country', 'GR', 'Greece', NULL, 1, 39.0742, 21.8243, 'Greece'),
            ('id_000047', 'Serbia', 'serbia', 'Serbia', ['Serbia'], 'country', 'RS', 'Serbia', NULL, 1, 44.0165, 21.0059, 'Serbia'),
            ('id_000048', 'Canada', 'canada', 'Canada', ['Canada'], 'country', 'CA', 'Canada', NULL, 1, 56.1304, -106.3468, 'Canada'),
            ('id_000049', 'Zimbabwe', 'zimbabwe', 'Zimbabwe', ['Zimbabwe'], 'country', 'ZW', 'Zimbabwe', NULL, 1, -19.0154, 29.1549, 'Zimbabwe'),
            ('id_000050', 'Afghanistan', 'afghanistan', 'Afghanistan', ['Afghanistan'], 'country', 'AF', 'Afghanistan', NULL, 1, 33.9391, 67.7100, 'Afghanistan'),
    ) AS t(id, name, sort_name, name_en, names_all, subtype, country, country_name, region, admin_level, latitude, longitude, display_name)
    ORDER BY sort_name
""")

db.execute(f"""
    COPY (
        SELECT *, NULL::BIGINT AS population
        FROM test_data
    ) TO '{OUTPUT}'
    WITH (
        FORMAT PARQUET,
        COMPRESSION ZSTD,
        ROW_GROUP_SIZE {ROW_GROUP_SIZE},
        PER_THREAD_OUTPUT FALSE,
        OVERWRITE_OR_IGNORE TRUE
    )
""")

row_count = db.execute(f"SELECT COUNT(*) FROM read_parquet('{OUTPUT}')").fetchone()[0]
file_size = os.path.getsize(OUTPUT)
print(f"Generated: {row_count} rows, {file_size / 1024:.1f} KB")

db.execute(f"CREATE VIEW tgeo AS SELECT * FROM read_parquet('{OUTPUT}')")
cols = db.execute("DESCRIBE tgeo").fetchdf()["column_name"].tolist()
print(f"Schema: {len(cols)} columns: {cols}")
print("Test fixture ready.")
db.close()
