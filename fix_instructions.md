# Fix — making the Nominatim integration return cafes, not cities

The bug: `_populate_cafes_from_nominatim` sends the raw search query to Nominatim, which is a geocoder, so `Vancouver, BC` resolves to the city of Vancouver. Then every result is inserted into the cafes table without checking that it's actually a cafe.

The fix has two parts. Both are in `app.py`, inside `_populate_cafes_from_nominatim`.

## Edit 1 — Prefix the query with "cafes near"

This triggers Nominatim's special-phrase handling, which returns actual amenities of the requested type near the location, rather than geocoding the location itself.

**Find:**

```python
        response = requests.get(
            NOMINATIM_URL,
            params={"q": query, "format": "json"},
            headers={"User-Agent": NOMINATIM_USER_AGENT},
            timeout=NOMINATIM_TIMEOUT_SECONDS,
        )
```

**Replace with:**

```python
        # Prefix with "cafes near" so Nominatim's special-phrase handling
        # returns cafes near the location, not the location itself.
        search_query = query if query.lower().startswith("cafes ") else f"cafes near {query}"
        response = requests.get(
            NOMINATIM_URL,
            params={"q": search_query, "format": "json"},
            headers={"User-Agent": NOMINATIM_USER_AGENT},
            timeout=NOMINATIM_TIMEOUT_SECONDS,
        )
```

## Edit 2 — Filter results to keep only cafes

Belt and suspenders: even with the "cafes near" prefix, Nominatim may return a few non-amenity results when no cafes match. This filter ensures only actual cafes make it into the database.

**Find** the for-loop that processes results:

```python
    matched: list[Cafe] = []
    for entry in payload:
        try:
            osm_id = str(entry["osm_id"])
            display_name = entry["display_name"]
            lat = float(entry["lat"])
            lon = float(entry["lon"])
        except (KeyError, TypeError, ValueError):
            # Skip malformed entries rather than failing the whole search.
            continue
```

**Insert** these three lines right after the `except` block, before the `existing = db.exec(...)` line:

```python
        # Safety belt: skip results that aren't actually cafes.
        if entry.get("class") != "amenity" or entry.get("type") != "cafe":
            continue
```

## Verification

Restart the Flask app, search `Vancouver, BC` again — you should now see multiple cafe results with names like "Blue Mountain Coffee", "Revolver Coffee", "Nemesis Coffee", etc., not a single "Vancouver, British Columbia, Canada" entry.

The Playwright test from Phase 2 should now pass.
