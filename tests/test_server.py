"""
Integration tests for the Where in the World geocoding server.

Usage:
    source .venv/bin/activate && python tests/test_server.py
"""

import os
import sys
import json
import urllib.request
import urllib.parse

PORT = os.environ.get("V2_TEST_PORT", "5100")
BASE = f"http://0.0.0.0:{PORT}"

def api(path, params=None):
    url = f"{BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = b""
        try:
            body = e.read()
        except Exception:
            pass
        try:
            return e.code, json.loads(body) if body else {}
        except Exception:
            return e.code, {"error": str(e)}
    except Exception as e:
        return 500, {"error": str(e)}

passed = 0
failed = 0

def test(name, condition, detail=""):
    global passed, failed
    if condition:
        print(f"OK   {name}")
        passed += 1
    else:
        print(f"FAIL {name} {detail}")
        failed += 1

print("=" * 60)
print("Integration Tests: Where in the World Server")
print("=" * 60)

# ── Health ──
print("\n--- Health ---")
status, data = api("/health")
test("Health returns 200", status == 200, f"got {status}")
test("Health status ok", data.get("status") == "ok", f"got {data.get('status')}")
test("Health has row_count", isinstance(data.get("row_count"), int) and data["row_count"] > 0,
     f"got {data.get('row_count')}")

# ── Autocomplete ──
print("\n--- Autocomplete ---")

status, data = api("/v1/autocomplete", {"q": "london", "limit": "5"})
test("London returns 200", status == 200)
test("London has results", len(data.get("results", [])) > 0)
test("London query echoed", data.get("query") == "london")
test("London took_ms present", isinstance(data.get("took_ms"), (int, float)))

status, data = api("/v1/autocomplete", {"q": "lon", "limit": "1"})
test("Short prefix works", len(data.get("results", [])) > 0)

status, data = api("/v1/autocomplete", {"q": "san", "limit": "10"})
test("Common prefix <= limit", len(data.get("results", [])) <= 10,
     f"got {len(data.get('results', []))}")

# Country filter
status, data = api("/v1/autocomplete", {"q": "springfield", "country": "US", "limit": "5"})
all_us = all(r.get("country") == "US" for r in data.get("results", []))
test("Country filter US only", all_us)

# Subtype filter
status, data = api("/v1/autocomplete", {"q": "san", "subtype": "country", "limit": "5"})
all_country = all(r.get("subtype") == "country" for r in data.get("results", []))
test("Subtype filter country only", all_country,
     f"got subtypes: {[r.get('subtype') for r in data.get('results', [])]}")

# CJK
status, data = api("/v1/autocomplete", {"q": "東京", "limit": "5"})
test("CJK 東京 works", len(data.get("results", [])) > 0)

# Transliterated fallback
status, data = api("/v1/autocomplete", {"q": "tokyo", "limit": "5"})
test("Transliterated tokyo works", len(data.get("results", [])) > 0)

status, data = api("/v1/autocomplete", {"q": "beijing", "limit": "5"})
test("Transliterated beijing works", len(data.get("results", [])) > 0)

# Unicode
status, data = api("/v1/autocomplete", {"q": "münchen", "limit": "5"})
test("Unicode münchen returns results", len(data.get("results", [])) > 0)

status, data = api("/v1/autocomplete", {"q": "москва", "limit": "5"})
test("Cyrillic москва returns results", len(data.get("results", [])) > 0)

# Performance
status, data = api("/v1/autocomplete", {"q": "san", "limit": "10"})
took = data.get("took_ms", 999)
test(f"Response time OK ({took}ms < 500ms)", took < 500,
     f"took {took}ms")

# ── Reverse ──
print("\n--- Reverse ---")
status, data = api("/v1/reverse", {"lat": "51.5074", "lng": "-0.1278", "limit": "3"})
test("Reverse London returns results", len(data.get("results", [])) > 0)

status, data = api("/v1/reverse", {"lat": "35.6762", "lng": "139.6503", "limit": "3"})
test("Reverse Tokyo returns results", len(data.get("results", [])) > 0)

# ── Edge Cases ──
print("\n--- Edge Cases ---")
status, data = api("/v1/autocomplete", {"q": "zzzxxxyyy", "limit": "5"})
test("No-match returns empty", data.get("results") == [],
     f"got {data.get('results')}")

status, data = api("/v1/autocomplete", {"q": "a", "limit": "50"})
test("Single char <= limit", len(data.get("results", [])) <= 50,
     f"got {len(data.get('results', []))}")

status, data = api("/v1/autocomplete", {"q": "x" * 101, "limit": "5"})
test("Over-length query rejected", status == 422, f"got {status}")

# Response validation
print("\n--- Response Validation ---")
status, data = api("/v1/autocomplete", {"q": "london", "limit": "3"})
results = data.get("results", [])
if results:
    r = results[0]
    required = ["id", "name", "display_name", "subtype", "country",
                "country_name", "latitude", "longitude"]
    missing = [k for k in required if k not in r]
    test("Result has all required fields", not missing,
         f"missing: {missing}")
    test("Result lat/lng are floats", isinstance(r.get("latitude"), (int, float))
         and isinstance(r.get("longitude"), (int, float)))
    test("Region is string or null", r.get("region") is None or isinstance(r.get("region"), str))

# ── Summary ──
print(f"\n{'=' * 60}")
print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
if failed > 0:
    sys.exit(1)
