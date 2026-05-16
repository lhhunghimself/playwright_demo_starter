# Phase 2 prompt — paste this into your AI tool (use Opus 4.7 as the model)

Below is the prompt to paste into Claude. Everything below the first `---` line.

The walkthrough goes first; then the relevant app code; then the explicit ask. Keep the framing about the Nominatim bug — the LLM doesn't need to know about the bug to write the test, but it does need to know that we're testing *real cafe* results vs *city* results, so the assertion logic is right.

---

I want you to generate a Playwright test from this walkthrough. Here's the walkthrough, the relevant app code, and what I need.

## The user journey

A visitor lands on /cafes and uses the search box to find cafes in Vancouver, BC. They expect to see *real cafes* — places with cafe-like names, not the city itself or roads. Each result should be clickable.

Steps:

1. Visitor navigates to `/cafes`.
2. The page shows a heading "Cafes" and a search box labeled "Search by city or place".
3. Visitor types `Vancouver, BC` into the search box and clicks "Search".
4. The page reloads with results. Multiple cafe cards appear.
5. Each cafe card's title is a real cafe name — not the city itself ("Vancouver, British Columbia, Canada"), not a road, not a boundary.
6. Clicking any cafe's name navigates to that cafe's detail page.

## Why the city-vs-cafe distinction matters

Nominatim is a geocoder. Sending `Vancouver, BC` to it returns the city of Vancouver as one result. To get cafes, you need to either query with `cafes near Vancouver, BC` (Nominatim's special-phrase syntax) or filter results by amenity type. The Week 6 e2e walk caught a bug where neither was done, and the search returned the city as a single "cafe". This test should catch that class of bug.

## The search form (from `templates/cafes_list.html`)

```html
<form action="/cafes" method="GET">
    <label for="cafes-q">Search by city or place</label>
    <input type="text" id="cafes-q" name="q" placeholder="e.g. Seattle, WA">
    <button type="submit">Search</button>
</form>
```

## The result rendering (from `templates/cafes_list.html`)

```html
{% for cafe in cafes %}
<div class="card h-100">
    <div class="card-body">
        <h5 class="card-title mb-1">
            <a href="{{ url_for('cafe_detail', cafe_id=cafe.id) }}"
               class="text-decoration-none">
                {{ cafe.name }}
            </a>
        </h5>
        ...
    </div>
</div>
{% endfor %}
```

## The route handler (from `app.py`)

```python
@app.route("/cafes")
def cafes_list():
    db = get_db_session()
    query = (request.args.get("q") or "").strip()
    if query:
        _populate_cafes_from_nominatim(query, db)
    cafes = db.exec(select(Cafe).order_by(Cafe.created_at.desc()).limit(50)).all()
    return render_template("cafes_list.html", cafes=cafes, query=query, ...)
```

The `_populate_cafes_from_nominatim` function calls real Nominatim and inserts results into the cafes table. The test should hit real Nominatim — no mocking.

## The Cafe model

```python
class Cafe(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    osm_id: str
    name: str       # display_name from Nominatim
    address: str
    lat: float
    lon: float
```

## The app's environment

- `DATABASE_URL` controls which database the app uses. Set it to `sqlite:///{tempfile.gettempdir()}/test_e2e.db` **before** importing from `app` — the engine is created at import time.
- The Flask app exports `app`, `engine`, `Cafe` from `app.py`.

## What I need from you

Two files:

1. **`tests/e2e/conftest.py`** — pytest fixtures:
   - Sets `DATABASE_URL` to sqlite *before* importing from `app`
   - Starts the Flask app on a real port using `werkzeug.serving.make_server` in a background thread (session-scoped)
   - Provides a `live_server` fixture exposing the base URL
   - Resets the cafes table before each test (autouse) so search results don't accumulate across tests

2. **`tests/e2e/test_search_for_cafes.py`** — one test function `test_search_returns_cafes_not_city` that:
   - Maps line-by-line to the walkthrough's six steps (comments showing which step each assertion is)
   - Uses `get_by_label` and `get_by_role` for selectors where possible (CSS as last resort)
   - Uses `expect(...).to_be_visible(timeout=15000)` because Nominatim can be slow (1-3 seconds typical)
   - Asserts that at least 2 cafe-card results appear (the buggy code returns 1: the city)
   - Asserts that no result has "British Columbia" in its name (the buggy code returns "Vancouver, British Columbia, Canada")
   - Includes a docstring explaining what regression this test catches

Output the two files, each in a complete code block with the filename in a comment at the top.
