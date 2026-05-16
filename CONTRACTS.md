# StudySpot — CONTRACTS.md

**Team:** Brew Crew
**Week:** 6
**Coordinator:** Maya
**Last updated:** Tuesday, Week 6 (post-LLM session)

This document is the team's agreement for what gets built in Week 6. Every endpoint, every schema column, every error response is specified here. Each role's job is to make their assigned tests pass; tests live in `tests/` and were committed alongside this document.

If you think the contract is wrong, raise it in the team channel before changing your code. **Update CONTRACTS.md and the affected tests in the same PR** — the contract is the team's agreement, not a sacred text, but unilateral changes break integration.

---

## 1. Schema

### Table: `users` (already in skeleton — unchanged)

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PRIMARY KEY | autoincrement |
| username | VARCHAR(80) UNIQUE NOT NULL | indexed |
| password_hash | VARCHAR(255) NOT NULL | werkzeug pbkdf2 |
| created_at | TIMESTAMP WITH TIME ZONE NOT NULL | default now |

### Table: `cafes` (new)

Caches results from the OpenStreetMap Nominatim API. Never invalidated in Week 6 — known limitation, addressed in Week 7+.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PRIMARY KEY | autoincrement, our internal ID |
| osm_id | VARCHAR(50) UNIQUE NOT NULL | OpenStreetMap's ID, lets us reconcile across searches |
| name | VARCHAR(200) NOT NULL | from Nominatim |
| address | VARCHAR(500) | from Nominatim |
| lat | DOUBLE PRECISION NOT NULL | from Nominatim |
| lon | DOUBLE PRECISION NOT NULL | from Nominatim |
| created_at | TIMESTAMP WITH TIME ZONE NOT NULL | when we first saw this cafe |

### Table: `ratings` (new)

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PRIMARY KEY | autoincrement |
| user_id | INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE | indexed |
| cafe_id | INTEGER NOT NULL REFERENCES cafes(id) ON DELETE CASCADE | indexed |
| stars | INTEGER NOT NULL CHECK (stars BETWEEN 1 AND 5) | |
| review | VARCHAR(1000) | nullable |
| tags | JSON NOT NULL DEFAULT '[]' | array of valid tag strings |
| created_at | TIMESTAMP WITH TIME ZONE NOT NULL | default now |

**UNIQUE constraint:** `(user_id, cafe_id)` — a user can have at most one rating per cafe. Editing replaces the existing rating in place.

---

## 2. Tag enum

Six valid tags, fixed for Week 6:

```
wifi, outlets, quiet, late_hours, seating, outdoor
```

Stored as JSON array in `ratings.tags`. Validated in app code: any value not in this enum is rejected at the route layer (HTTP 400). Multi-select: a rating can carry zero, one, or multiple tags.

To add a tag in a future week: update this list, the validation in the route, and the tag-display logic in the templates. No schema migration needed.

---

## 3. Endpoint contracts

All endpoints below are in addition to the existing skeleton routes (`/`, `/site/`, `/login`, `/register`, `/logout`, `/about`). Skeleton routes are unchanged.

### `GET /cafes`

**Purpose:** Browse and filter cafes.

**Auth:** None required (anonymous access allowed).

**Query parameters:**
- `q` (optional, string): location search string passed to Nominatim
- `tags` (optional, comma-separated): filter to cafes that have *all* listed tags from at least one rating

**Behavior:**
- If `q` is present: server calls `/api/cafes/search?q=<q>` (internal), populates `cafes` table with new entries, returns the merged list
- If `tags` is present: server filters the results to cafes where each tag in the list appears in at least one rating for that cafe (AND semantics)
- If neither present: returns most-recently-added 50 cafes from the database

**Response:** HTML page rendering the cafe list. Each cafe shows name, address, average stars, count of ratings, and the union of tags from all its ratings.

**Errors:**
- Nominatim failure (rate limit, timeout, malformed): show flash banner with the message from the API error envelope (see `/api/cafes/search` below). Cafe list shows whatever was already in the database before the failed search.

---

### `GET /cafes/<int:cafe_id>`

**Purpose:** View a single cafe with all its ratings.

**Auth:** None required.

**Response:** HTML page with:
- Cafe metadata: name, address, lat/lon, when first seen
- Aggregated tags: union of tags across all ratings for this cafe
- All ratings, sorted **most recent first**, **capped at 20** (no pagination in Week 6)
- For each rating: username, stars, review text, tags, created_at, plus an "Edit" and "Delete" button if the rating belongs to the requesting user
- A "Rate this cafe" form if user is logged in and has not already rated this cafe; otherwise nothing (or "You rated this cafe — edit your rating" link)

**Errors:**
- Cafe not found: HTTP 404, render the standard 404 page

---

### `POST /cafes/<int:cafe_id>/rate`

**Purpose:** Submit a new rating.

**Auth:** Required (`@login_required`).

**Form fields:**
- `stars` (required, integer 1–5)
- `review` (optional, string ≤1000 chars)
- `tags` (optional, comma-separated, only values from the tag enum)

**Behavior:**
- Validate inputs; reject HTTP 400 with flash on invalid stars or invalid tag value
- If the user already has a rating for this cafe: redirect them to the edit form (don't silently overwrite)
- Otherwise: insert into `ratings`, redirect to `GET /cafes/<id>` with a success flash

**Errors:**
- Cafe not found: HTTP 404
- Invalid input: HTTP 400, redirect back to cafe page with flash error

---

### `GET /cafes/<int:cafe_id>/edit-rating`

**Purpose:** Show edit form for the current user's rating on this cafe.

**Auth:** Required (`@login_required`).

**Response:** HTML form pre-populated with the user's current rating, OR HTTP 404 if the user has no rating for this cafe (404 prevents probing for existence).

**Errors:**
- Cafe not found, OR cafe exists but user has no rating: HTTP 404 (indistinguishable to caller)

---

### `POST /cafes/<int:cafe_id>/edit-rating`

**Purpose:** Save edits to the current user's rating.

**Auth:** Required.

**Form fields:** same as `POST .../rate` (stars, review, tags).

**Behavior:**
- Find the user's rating for this cafe; if none exists, HTTP 404
- Update fields in place; do not change `created_at`
- Redirect to `GET /cafes/<id>` with success flash

**Errors:**
- 404 on missing rating (as above)
- 400 on invalid input

---

### `POST /cafes/<int:cafe_id>/delete-rating`

**Purpose:** Delete the current user's rating.

**Auth:** Required.

**Behavior:**
- Find the user's rating; if none, HTTP 404
- Delete the row
- Redirect to `GET /cafes/<id>` with success flash

**Errors:**
- 404 on missing rating

---

### `GET /api/cafes/search`

**Purpose:** Internal endpoint — server-side proxy to Nominatim. Called by `GET /cafes` when `q` is present.

**Auth:** None required (publicly accessible — accept this for Week 6, see "Known limitations").

**Query parameters:**
- `q` (required, string): location search

**Behavior:**
- Server makes one Nominatim request with the query, 5-second timeout, User-Agent header per their usage policy
- For each result that's a cafe (Nominatim category check), insert into `cafes` table if not already present (lookup by `osm_id`)
- Return JSON envelope (see below)

**Response on success:**
```json
{
  "results": [
    {"id": 42, "name": "Blue Mountain Coffee", "address": "123 Main St, Vancouver", "lat": 49.28, "lon": -123.12},
    ...
  ],
  "error": null
}
```

**Response on Nominatim failure:** HTTP 503 with envelope:
```json
{
  "results": [],
  "error": "rate_limited" | "timeout" | "upstream_invalid",
  "message": "Search temporarily unavailable. Try again in a few seconds."
}
```

---

## 4. Authorization rules

- **Public read:** `GET /cafes`, `GET /cafes/<id>`, `GET /api/cafes/search`
- **Login required:** all `POST` endpoints, `GET /cafes/<id>/edit-rating`
- **Ownership-restricted:** edit and delete a rating only if it's the current user's. **Return 404 (not 403)** when a non-owner attempts access — the rating's existence must not be confirmed to a non-owner.

Implementation: db-and-security role refactors auth to Flask-Login (`@login_required`, `current_user`). Server-side role implements ownership check inside the route handlers (look up rating by `(cafe_id, user_id=current_user.id)`; if missing, 404).

---

## 5. Role boundaries

What each role owns this week. Files outside your lane should not be modified by you without raising it in the team channel.

### Server-side (Devon)

**Owns:**
- All new routes in `app.py`: `/cafes`, `/cafes/<id>`, `/cafes/<id>/rate`, edit-rating routes, delete-rating, `/api/cafes/search`
- The `requests`-based call to Nominatim
- `tests/test_cafe_routes.py` — make it pass

**Does not touch:**
- Templates (Priya owns)
- Schema migrations or User model (Jamal owns)
- Existing skeleton routes (`/`, `/login`, `/register`, `/logout`, `/about`, `/site/`)

### Client-side (Priya)

**Owns:**
- Templates: `templates/cafes_list.html`, `templates/cafe_detail.html`, `templates/rate_form.html`, `templates/edit_rating_form.html`
- Updates to `templates/base.html` if the navbar needs new entries (e.g., link to `/cafes`)
- `tests/test_templates.py` — make it pass

**Does not touch:**
- `app.py` route logic (Devon)
- Schema or auth code (Jamal)
- The skeleton's existing templates other than navbar

### DB-and-security (Jamal)

**Owns:**
- New SQLModel models: `Cafe`, `Rating` in `app.py` (or a new `models.py` if the team agrees)
- Refactor of auth from raw `session["user_id"]` to Flask-Login (`login_user`, `logout_user`, `current_user`, `@login_required`, `LoginManager` setup, user-loader callback)
- Validation that the ownership 404 logic works (test only, server-side implements)
- `tests/test_schema_and_auth.py` — make it pass

**Does not touch:**
- Cafe/rating route logic (Devon)
- Templates (Priya)

### Coordinator (Maya)

**Owns:**
- This document
- The four role-specific test files (committed Tuesday, frozen unless team agrees to change)
- `tests/test_integration.py` — full register/search/rate/edit/delete flow, makes it pass once all three other roles' work is done
- The coord-LLM session transcript (`coord_session.md` in repo root)
- Saturday demo: orchestrate the team's end-to-end demo

**Does not touch:**
- Anyone else's owned files (raise in channel if it looks broken)

---

## 6. Known limitations (deliberate, will revisit)

- **Cafe data is never refreshed from Nominatim once cached.** Real cafes change. Acceptable for Week 6; will add `last_refreshed_at` and a refresh policy in Week 7+.
- **No pagination on the cafe detail page.** 20 most recent ratings only. Acceptable while no cafe has more than 20 ratings.
- **`/api/cafes/search` is publicly accessible.** No auth, no rate limit on our side — relies on Nominatim's own throttling. Acceptable; if abused, add Flask-Limiter in Week 8+.
- **No CSRF tokens on forms.** Flask doesn't add them by default; Flask-WTF would. Adding in Week 7 when we harden auth.
- **No tag-add UI for users.** Tag set is fixed in code. Adding a tag requires a code change. Acceptable — fixed enum is the design choice, not a limitation.

---

## 7. Saturday demo script

For the Week 6 Saturday demo, the team will walk the TA through:

1. Register a new account (Flask-Login flow)
2. Search for cafes near "Vancouver, BC" — Nominatim populates results
3. Click a cafe → view its detail page
4. Submit a rating with stars, review, and tags
5. Edit the rating
6. Try to edit *another user's* rating directly via URL → see 404
7. Delete the rating
8. Filter the cafe list by tags

If all 8 steps work, the team's group integration mark is full. If any fails, partial credit per step.

Tests must also be all-green: `docker compose exec app pytest -v` shows 23 passing.
