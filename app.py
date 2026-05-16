"""
Course 506 Week 5 Skeleton — Flask + Postgres + SQLModel + Bootstrap

Single-file Flask app demonstrating the architecture of a web application:
- Server (Flask) handles HTTP requests
- Database (Postgres via SQLModel) stores user state across requests
- Sessions (Flask sessions) keep users logged in across requests
- Templates render HTML to send back to the browser

The home page serves the static site you sync from your S3 bucket into
S3_content/. Login, register, logout, and about are Flask-rendered routes.

This file is meant to be readable top-to-bottom. No Blueprints, no app factory,
no advanced Flask patterns. Just enough to teach the architecture.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from flask import (
    Flask, render_template, request, redirect, url_for, flash, g,
    send_from_directory, abort, jsonify,
)
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_required,
    login_user,
    logout_user,
)
import requests
from sqlalchemy import Column, JSON, UniqueConstraint
from sqlmodel import SQLModel, Field, Session, create_engine, select
from werkzeug.security import generate_password_hash, check_password_hash

# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------

app = Flask(__name__)

# Secret key signs the session cookie so users can't tamper with it.
# In production this comes from an environment variable and is a long random string.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-not-for-production")

# Database URL. Postgres runs in a separate container; the URL points there.
# For local testing without Docker, override with sqlite:
#   DATABASE_URL=sqlite:///dev.db python app.py
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://app:app@db:5432/app")

# SQLModel uses SQLAlchemy underneath. The engine is the connection pool.
engine = create_engine(DATABASE_URL, echo=False)

# Path to the synced S3 content. Students populate this with `aws s3 sync`.
S3_CONTENT_DIR = Path(__file__).parent / "S3_content"


# ---------------------------------------------------------------------------
# Database model
# ---------------------------------------------------------------------------

class User(SQLModel, UserMixin, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True, max_length=80)
    password_hash: str = Field(max_length=255)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Cafe(SQLModel, table=True):
    """Cached cafe data sourced from the OpenStreetMap Nominatim API.

    `osm_id` is the natural key — we reconcile across searches by it so the
    same physical cafe doesn't get inserted twice. `id` is our internal
    surrogate primary key that ratings reference.
    """

    __tablename__ = "cafes"

    id: int | None = Field(default=None, primary_key=True)
    osm_id: str = Field(unique=True, index=True, max_length=50)
    name: str = Field(max_length=200)
    address: str | None = Field(default=None, max_length=500)
    lat: float
    lon: float
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class Rating(SQLModel, table=True):
    """A user's rating of a cafe. One row per (user, cafe) pair — editing
    replaces fields in place rather than inserting a new row, enforced by
    the UNIQUE constraint below.
    """

    __tablename__ = "ratings"
    __table_args__ = (
        UniqueConstraint("user_id", "cafe_id", name="uq_ratings_user_cafe"),
    )

    id: int | None = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", index=True)
    cafe_id: int = Field(foreign_key="cafes.id", index=True)
    stars: int
    review: str | None = Field(default=None, max_length=1000)
    # SQLModel doesn't have a built-in JSON Field shortcut, so drop down to
    # the SQLAlchemy Column. `default=list` here is the SA column-level
    # server/python default — ratings without tags get [] not NULL.
    tags: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False, default=list),
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Tag enum + validation helper (CONTRACTS.md section 2)
#
# Six fixed tags for Week 6. Stored as a JSON array on each rating; validated
# at the route layer before insert/update. Adding a tag in a future week
# means: update VALID_TAGS, update the form template, no migration needed.
# ---------------------------------------------------------------------------

VALID_TAGS: set[str] = {
    "wifi",
    "outlets",
    "quiet",
    "late_hours",
    "seating",
    "outdoor",
}


def parse_and_validate_tags(raw) -> list[str]:
    """Normalize and validate a tags input from the rating form.

    Accepts either a list of strings (e.g. multi-select form fields) or a
    single comma-separated string (e.g. one input field). Returns a list of
    lower-snake-case tag strings, each guaranteed to be a member of
    VALID_TAGS. Empty/None input returns []. Raises ValueError on the first
    invalid value so the route handler can return HTTP 400.
    """
    if raw is None:
        return []

    if isinstance(raw, str):
        candidates = [t.strip() for t in raw.split(",")]
    else:
        # Assume an iterable of strings (list, tuple, MultiDict.getlist, ...)
        candidates = [str(t).strip() for t in raw]

    cleaned: list[str] = []
    for tag in candidates:
        if not tag:
            continue
        normalized = tag.lower()
        if normalized not in VALID_TAGS:
            raise ValueError(f"Invalid tag: {tag!r}")
        cleaned.append(normalized)
    return cleaned


# ---------------------------------------------------------------------------
# Session helper
#
# SQLModel doesn't have a Flask extension. We open a fresh DB session for each
# request and close it when the request finishes. Flask's `g` object holds
# request-scoped state.
# ---------------------------------------------------------------------------

def get_db_session():
    if "db_session" not in g:
        g.db_session = Session(engine)
    return g.db_session


@app.teardown_appcontext
def close_db_session(exception=None):
    db_session = g.pop("db_session", None)
    if db_session is not None:
        db_session.close()


# ---------------------------------------------------------------------------
# Flask-Login setup
#
# Auth refactor (commit 2): replaced the raw `session["user_id"]` pattern and
# the `inject_user` context processor with Flask-Login. `LoginManager(app)`
# attaches itself to `app.login_manager` and registers a context processor
# that exposes `current_user` to every Jinja template — so we no longer
# inject a `user` variable ourselves.
#
# Note: Flask-Login 0.6.x does NOT auto-register in `app.extensions`, unlike
# most Flask extensions. We add it explicitly so anything that introspects
# `app.extensions["login_manager"]` (the standard Flask convention, and what
# our test contract checks) finds it.
# ---------------------------------------------------------------------------

login_manager = LoginManager(app)
login_manager.login_view = "login"
app.extensions["login_manager"] = login_manager


@login_manager.user_loader
def load_user(user_id: str) -> User | None:
    """Map a stringified user id from the session cookie back to a User row.

    Flask-Login stores the id as a string; cast to int before looking up.
    Returns None if the id is malformed or the user no longer exists, which
    Flask-Login interprets as anonymous.
    """
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return None
    db = get_db_session()
    return db.get(User, uid)


# ---------------------------------------------------------------------------
# Routes — your S3 static site
#
# Your S3 site lives at /site/. Populate the S3_content/ folder by running:
#   aws s3 sync s3://<your-bucket>/ S3_content/
# from the repo root. Then click "My Site" in the navbar.
#
# The home page is Flask-rendered and acts as the entry point: it has the
# navbar (Login/Register/About/My Site) and a brief landing message.
# ---------------------------------------------------------------------------

@app.route("/")
def home():
    return render_template("home.html")


@app.route("/site/")
def site_home():
    index_path = S3_CONTENT_DIR / "index.html"
    if not index_path.exists():
        # Friendly placeholder when the student hasn't synced yet.
        return render_template("placeholder.html"), 200
    return send_from_directory(S3_CONTENT_DIR, "index.html")


@app.route("/site/<path:filename>")
def serve_s3_content(filename):
    file_path = S3_CONTENT_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        abort(404)
    return send_from_directory(S3_CONTENT_DIR, filename)


# ---------------------------------------------------------------------------
# Routes — authentication (Flask-rendered, not static)
# ---------------------------------------------------------------------------

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html")

    # POST: create a new user.
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    if not username or not password:
        flash("Username and password are required.")
        return redirect(url_for("register"))

    db = get_db_session()
    existing = db.exec(select(User).where(User.username == username)).first()
    if existing is not None:
        flash("That username is already taken.")
        return redirect(url_for("register"))

    user = User(
        username=username,
        password_hash=generate_password_hash(password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Log them in immediately after registration.
    login_user(user)
    return redirect(url_for("home"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        return render_template("login.html")

    # POST: validate credentials.
    username = request.form.get("username", "").strip()
    password = request.form.get("password", "")

    db = get_db_session()
    user = db.exec(select(User).where(User.username == username)).first()

    if user is None or not check_password_hash(user.password_hash, password):
        flash("Invalid username or password.")
        return redirect(url_for("login"))

    # Flask-Login serializes the user id into the signed session cookie under
    # the key `_user_id`. On subsequent requests the user_loader callback
    # turns that id back into a User row and exposes it as `current_user`.
    login_user(user)
    return redirect(url_for("home"))


@app.route("/logout", methods=["POST"])
def logout():
    logout_user()
    return redirect(url_for("home"))


@app.route("/about")
def about():
    # Each team replaces this content with their own About page (see
    # the assignment instructions in README.md).
    return render_template("about.html")


# ---------------------------------------------------------------------------
# Routes — cafe browse + Nominatim proxy (CONTRACTS.md section 3)
#
# Nominatim is a public OSM geocoder. Their usage policy requires a
# descriptive User-Agent and rate-limits to ~1 req/sec. We wrap every call
# with a small error envelope so route handlers (and the JSON API) can map
# upstream failures to a single, contract-defined shape:
#
#   { "results": [...], "error": null }                 # success
#   { "results": [],   "error": "timeout"|"rate_limited"|"upstream_invalid",
#     "message": "..." }                                # 503
#
# Catch order matters: requests.exceptions.Timeout is a subclass of
# RequestException, so it must be caught FIRST or it gets swallowed by the
# broader handler and we'd report "upstream_invalid" instead of "timeout".
# ---------------------------------------------------------------------------

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "StudySpot-Course506/1.0"
NOMINATIM_TIMEOUT_SECONDS = 5
NOMINATIM_ERROR_MESSAGE = "Search temporarily unavailable. Try again in a few seconds."


class _NominatimError(Exception):
    """Internal exception carrying the contract's error code.

    `code` is one of: "rate_limited", "timeout", "upstream_invalid".
    `message` is the human-readable string from the error envelope.
    """

    def __init__(self, code: str, message: str = NOMINATIM_ERROR_MESSAGE):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _populate_cafes_from_nominatim(query: str, db: Session) -> list[Cafe]:
    """Hit Nominatim with `query` and upsert any new cafes by osm_id.

    Returns the list of Cafe rows (newly inserted + already existing) that
    matched the query. Raises `_NominatimError` on any failure mode the
    contract recognizes; callers decide whether to flash + degrade (the
    HTML route) or return a 503 envelope (the JSON API).
    """
    try:
        response = requests.get(
            NOMINATIM_URL,
            params={"q": query, "format": "json"},
            headers={"User-Agent": NOMINATIM_USER_AGENT},
            timeout=NOMINATIM_TIMEOUT_SECONDS,
        )
    except requests.exceptions.Timeout:
        # Must come before the broader RequestException catch — Timeout is
        # a subclass and would otherwise be reported as upstream_invalid.
        raise _NominatimError("timeout")
    except requests.exceptions.RequestException:
        raise _NominatimError("upstream_invalid")

    if response.status_code == 429:
        raise _NominatimError("rate_limited")
    if response.status_code >= 400:
        raise _NominatimError("upstream_invalid")

    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        raise _NominatimError("upstream_invalid")

    if not isinstance(payload, list):
        raise _NominatimError("upstream_invalid")

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

        existing = db.exec(select(Cafe).where(Cafe.osm_id == osm_id)).first()
        if existing is not None:
            matched.append(existing)
            continue

        cafe = Cafe(
            osm_id=osm_id,
            name=display_name,
            address=display_name,
            lat=lat,
            lon=lon,
        )
        db.add(cafe)
        db.commit()
        db.refresh(cafe)
        matched.append(cafe)

    return matched


@app.route("/cafes")
def cafes_list():
    """Browse and filter cafes (CONTRACTS.md section 3).

    Query params:
        q (optional): location string forwarded to Nominatim. New results
            are inserted into the cafes table before we render.
        tags (optional, comma-separated): keep only cafes whose union of
            tags-across-ratings is a SUPERSET of the requested tags.

    With no params we render the 50 most recently added cafes.
    """
    db = get_db_session()

    query = (request.args.get("q") or "").strip()
    if query:
        try:
            _populate_cafes_from_nominatim(query, db)
        except _NominatimError as exc:
            flash(exc.message)

    raw_tags = request.args.get("tags")
    requested_tags: list[str] = []
    if raw_tags:
        try:
            requested_tags = parse_and_validate_tags(raw_tags)
        except ValueError as exc:
            # Bad tag from the URL — surface it but don't 500.
            flash(str(exc))
            requested_tags = []

    # If a query was supplied we want the union of cached + freshly inserted
    # cafes. Either way, "most recent first, capped at 50" is the contract
    # baseline; tag filtering trims further in Python.
    cafes = db.exec(
        select(Cafe).order_by(Cafe.created_at.desc()).limit(50)
    ).all()

    # Pull ratings once and group in Python. JSON-array containment queries
    # are awkward to write portably across Postgres and SQLite (which the
    # test fixture uses), and Week 6's data scale is tiny.
    ratings_by_cafe: dict[int, list[Rating]] = {}
    if cafes:
        cafe_ids = [c.id for c in cafes]
        all_ratings = db.exec(
            select(Rating).where(Rating.cafe_id.in_(cafe_ids))
        ).all()
        for r in all_ratings:
            ratings_by_cafe.setdefault(r.cafe_id, []).append(r)

    def _cafe_tag_union(cafe_id: int) -> set[str]:
        union: set[str] = set()
        for r in ratings_by_cafe.get(cafe_id, []):
            union.update(r.tags or [])
        return union

    if requested_tags:
        wanted = set(requested_tags)
        cafes = [c for c in cafes if wanted.issubset(_cafe_tag_union(c.id))]

    # Build a lightweight view-model so the template doesn't need to call
    # back into the DB. Average + count + tag union are cheap to compute.
    cafe_views = []
    for c in cafes:
        ratings = ratings_by_cafe.get(c.id, [])
        avg_stars = (sum(r.stars for r in ratings) / len(ratings)) if ratings else None
        cafe_views.append({
            "id": c.id,
            "name": c.name,
            "address": c.address,
            "lat": c.lat,
            "lon": c.lon,
            "avg_stars": avg_stars,
            "rating_count": len(ratings),
            "tags": sorted(_cafe_tag_union(c.id)),
        })

    return render_template(
        "cafes_list.html",
        cafes=cafe_views,
        query=query,
        active_tags=requested_tags,
    )


@app.route("/api/cafes/search")
def api_cafes_search():
    """JSON proxy to Nominatim (CONTRACTS.md section 3).

    Always returns the contract envelope shape. On success: HTTP 200 with
    `error: null` and a populated `results` array. On any of the three
    recognized failure modes: HTTP 503 with `error` set to the failure code
    and a generic `message`.
    """
    query = (request.args.get("q") or "").strip()
    if not query:
        # Contract treats q as required; return the upstream_invalid shape
        # rather than inventing a new error code.
        return jsonify({
            "results": [],
            "error": "upstream_invalid",
            "message": NOMINATIM_ERROR_MESSAGE,
        }), 503

    db = get_db_session()
    try:
        cafes = _populate_cafes_from_nominatim(query, db)
    except _NominatimError as exc:
        return jsonify({
            "results": [],
            "error": exc.code,
            "message": exc.message,
        }), 503

    results = [
        {
            "id": c.id,
            "name": c.name,
            "address": c.address,
            "lat": c.lat,
            "lon": c.lon,
        }
        for c in cafes
    ]
    return jsonify({"results": results, "error": None}), 200


# ---------------------------------------------------------------------------
# Routes — cafe detail (CONTRACTS.md section 3, GET /cafes/<int:cafe_id>)
#
# Anonymous-accessible. 404 on missing cafe; otherwise render cafe_detail.html
# with a precomputed view model so the template stays dumb. The view model
# includes the cafe row, the 20 most recent ratings, a user_id->username map
# (built from a single User.id.in_(...) query — explicitly NOT a per-rating
# db.get(User, ...) which would be N+1), the sorted union of tags across
# those ratings, the average stars rounded to 1dp (or None when there are no
# ratings yet), and the current user's existing rating for this cafe (or
# None if anonymous / no rating yet).
# ---------------------------------------------------------------------------

CAFE_DETAIL_RATINGS_LIMIT = 20


@app.route("/cafes/<int:cafe_id>")
def cafe_detail(cafe_id: int):
    db = get_db_session()

    cafe = db.get(Cafe, cafe_id)
    if cafe is None:
        abort(404)

    ratings = db.exec(
        select(Rating)
        .where(Rating.cafe_id == cafe_id)
        .order_by(Rating.created_at.desc())
        .limit(CAFE_DETAIL_RATINGS_LIMIT)
    ).all()

    # Single batched query for usernames — avoids N+1 on db.get(User, ...).
    user_ids = {r.user_id for r in ratings}
    usernames: dict[int, str] = {}
    if user_ids:
        users = db.exec(select(User).where(User.id.in_(user_ids))).all()
        usernames = {u.id: u.username for u in users}

    # `r.tags or []` guards against legacy rows with NULL tags even though
    # the column is NOT NULL DEFAULT '[]'; cheap insurance.
    tag_union = sorted(set().union(*[r.tags or [] for r in ratings])) if ratings else []

    avg_stars = (
        round(sum(r.stars for r in ratings) / len(ratings), 1) if ratings else None
    )

    current_user_rating = None
    if current_user.is_authenticated:
        current_user_rating = db.exec(
            select(Rating).where(
                Rating.cafe_id == cafe_id,
                Rating.user_id == current_user.id,
            )
        ).first()

    return render_template(
        "cafe_detail.html",
        cafe=cafe,
        ratings=ratings,
        usernames=usernames,
        tag_union=tag_union,
        avg_stars=avg_stars,
        current_user_rating=current_user_rating,
    )


# ---------------------------------------------------------------------------
# Routes — rating create / edit / delete (CONTRACTS.md sections 3 + 4)
#
# Four endpoints, all @login_required. Together they implement the contract's
# ownership-404 rule: a user can only see/edit/delete their OWN rating, and
# any other case (cafe missing, no rating for this user) returns 404 — never
# 403 — so a non-owner cannot probe for the existence of someone else's
# rating by URL guessing.
#
# Validation strategy (shared by /rate and POST /edit-rating):
#   - stars: int in [1, 5]; on bad value, flash + redirect to cafe detail
#   - tags : delegated to parse_and_validate_tags (Jamal's helper); accepts
#            either a list (multi-select) or a comma-separated string and
#            raises ValueError naming the offending tag, which we surface via
#            flash. The redirect-with-flash is the contract's "HTTP 400 with
#            flash" — Flask doesn't return a 400 body, it bounces the user
#            back to the form with the error message in session flashes.
# ---------------------------------------------------------------------------


def _parse_rating_form() -> tuple[int, str | None, list[str]] | None:
    """Pull stars/review/tags out of request.form and validate.

    Returns (stars, review, tags) on success, or None on any validation
    failure (in which case a flash message has already been queued and the
    caller should redirect back to the cafe detail page).
    """
    raw_stars = request.form.get("stars", "").strip()
    try:
        stars = int(raw_stars)
    except (TypeError, ValueError):
        flash("Stars must be an integer between 1 and 5.")
        return None
    if not 1 <= stars <= 5:
        flash("Stars must be an integer between 1 and 5.")
        return None

    review = request.form.get("review", "").strip() or None
    if review is not None and len(review) > 1000:
        flash("Review is too long (max 1000 characters).")
        return None

    # `getlist` covers multi-select forms (each <input name="tags"> becomes
    # one list element). Tests also post a single comma-separated string,
    # which getlist returns as a one-element list ["wifi,quiet"]. We join
    # everything back with a comma and hand it to the helper as a single
    # string — the helper splits on commas, so both shapes converge to the
    # same normalized list with no per-route branching.
    raw_tags = request.form.getlist("tags")
    try:
        tags = parse_and_validate_tags(",".join(raw_tags))
    except ValueError as exc:
        flash(f"Invalid tag: {exc}")
        return None

    return stars, review, tags


def _get_user_rating(db: Session, cafe_id: int, user_id: int) -> Rating | None:
    """Look up the (cafe_id, user_id) rating row, or None if it doesn't exist.

    This is the ownership-404 join: edit/delete routes use the result being
    None as the trigger for `abort(404)`, regardless of whether the cafe
    exists or another user has a rating on the same cafe. The contract
    forbids leaking that distinction.
    """
    return db.exec(
        select(Rating).where(
            Rating.cafe_id == cafe_id,
            Rating.user_id == user_id,
        )
    ).first()


@app.route("/cafes/<int:cafe_id>/rate", methods=["POST"])
@login_required
def rate_cafe(cafe_id: int):
    """Create a new rating for the current user on this cafe."""
    db = get_db_session()

    cafe = db.get(Cafe, cafe_id)
    if cafe is None:
        abort(404)

    # If the user already has a rating, send them to the edit form rather
    # than silently overwriting (and rather than tripping the UNIQUE
    # constraint with an opaque IntegrityError).
    existing = _get_user_rating(db, cafe_id, current_user.id)
    if existing is not None:
        return redirect(url_for("edit_rating", cafe_id=cafe_id))

    parsed = _parse_rating_form()
    if parsed is None:
        return redirect(url_for("cafe_detail", cafe_id=cafe_id))
    stars, review, tags = parsed

    rating = Rating(
        user_id=current_user.id,
        cafe_id=cafe_id,
        stars=stars,
        review=review,
        tags=tags,
    )
    db.add(rating)
    db.commit()

    flash("Rating submitted.")
    return redirect(url_for("cafe_detail", cafe_id=cafe_id))


@app.route("/cafes/<int:cafe_id>/edit-rating", methods=["GET", "POST"])
@login_required
def edit_rating(cafe_id: int):
    """Show or save edits to the current user's rating on this cafe.

    Both verbs share the same 404 guard: cafe missing OR user has no rating
    for this cafe -> 404. Per the contract, those cases must be
    indistinguishable to the caller (ownership probing protection).
    """
    db = get_db_session()

    cafe = db.get(Cafe, cafe_id)
    if cafe is None:
        abort(404)

    rating = _get_user_rating(db, cafe_id, current_user.id)
    if rating is None:
        abort(404)

    if request.method == "GET":
        return render_template(
            "edit_rating_form.html",
            cafe=cafe,
            rating=rating,
        )

    parsed = _parse_rating_form()
    if parsed is None:
        return redirect(url_for("cafe_detail", cafe_id=cafe_id))
    stars, review, tags = parsed

    # Update in place — `created_at` is intentionally untouched so the
    # rating's age in the most-recent-first feed reflects when it was first
    # written, not when it was last edited.
    rating.stars = stars
    rating.review = review
    rating.tags = tags
    db.add(rating)
    db.commit()

    flash("Rating updated.")
    return redirect(url_for("cafe_detail", cafe_id=cafe_id))


@app.route("/cafes/<int:cafe_id>/delete-rating", methods=["POST"])
@login_required
def delete_rating(cafe_id: int):
    """Delete the current user's rating on this cafe."""
    db = get_db_session()

    cafe = db.get(Cafe, cafe_id)
    if cafe is None:
        abort(404)

    rating = _get_user_rating(db, cafe_id, current_user.id)
    if rating is None:
        abort(404)

    db.delete(rating)
    db.commit()

    flash("Rating deleted.")
    return redirect(url_for("cafe_detail", cafe_id=cafe_id))


# ---------------------------------------------------------------------------
# First-run schema creation
# ---------------------------------------------------------------------------

# In production you'd use a migration tool (Alembic) instead.
# For Week 5, this is enough — it creates tables if they don't exist.
SQLModel.metadata.create_all(engine)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
