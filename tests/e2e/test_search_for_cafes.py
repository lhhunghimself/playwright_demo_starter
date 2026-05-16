"""
tests/e2e/test_search_for_cafes.py

Generated from walkthrough_search_for_cafes.md.

This test catches the Week 6 truthy-fixtures bug: searching for "Vancouver, BC"
returns the city of Vancouver (one "cafe" result with name "Vancouver, British
Columbia, Canada") instead of actual cafes. The bug was found manually during
the Brew Crew e2e walk; this test catches it automatically.

The test hits real Nominatim (no mocks). That's the point: only end-to-end
tests against real services can catch truthy-fixture bugs, by definition.
"""

import re
from playwright.sync_api import Page, expect


def test_search_returns_cafes_not_city(page: Page, live_server):
    # Step 1: visitor arrives at /cafes
    page.goto(f"{live_server.url}/cafes")

    # Step 2: page shows heading and search box
    expect(page.get_by_role("heading", name="Cafes")).to_be_visible()
    expect(page.get_by_label("Search by city or place")).to_be_visible()

    # Step 3: visitor types "Vancouver, BC" and clicks Search
    page.get_by_label("Search by city or place").fill("Vancouver, BC")
    page.get_by_role("button", name="Search").click()

    # Step 4: results render — wait up to 15s (Nominatim can be slow)
    cafe_card_links = page.locator(".card .card-title a")
    expect(cafe_card_links.first).to_be_visible(timeout=15_000)

    # Step 5a: at least 2 results.
    # The buggy code returns 1 result (Nominatim's geocoding of "Vancouver, BC"
    # is the city itself — a single entry). The fix produces several cafes via
    # Nominatim's special-phrase syntax ("cafes near ...") plus a class/type
    # filter.
    count = cafe_card_links.count()
    assert count >= 2, (
        f"Expected multiple cafe results, got {count}. "
        f"If exactly 1, suspect the Week 6 Nominatim bug: search query goes "
        f"to Nominatim as-is, returning the city of Vancouver instead of cafes."
    )

    # Step 5b: no result looks like the city itself.
    # Nominatim's display_name for the city follows the pattern
    # "Vancouver, British Columbia, Canada". Real cafe display_names start
    # with the cafe name, then street/neighborhood, then city.
    names = [cafe_card_links.nth(i).inner_text().strip() for i in range(count)]
    city_results = [n for n in names if re.search(r"^Vancouver,\s*British Columbia", n)]
    assert not city_results, (
        f"At least one result looks like the city of Vancouver, not a cafe:\n"
        f"  {city_results}\n"
        f"This is the Week 6 truthy-fixtures bug. The unit-test suite missed "
        f"it because the test fixture mocked Nominatim with cafe-shaped data. "
        f"Only an e2e walk against real Nominatim — or this test, which is the "
        f"automated version of that walk — catches it."
    )

    # Step 6: clicking a result navigates to a cafe detail page
    cafe_card_links.first.click()
    expect(page).to_have_url(re.compile(r"/cafes/\d+$"))
