# Walkthrough — "Visitor searches for cafes in Vancouver, BC"

This is the user journey I want to walk end-to-end. First by hand, then automated with Playwright. The point of doing it by hand first is to find bugs the unit-test suite missed — exactly like the Week 6 walk did.

## Scenario

A visitor lands on the cafes page and uses the search box to look for cafes in Vancouver, BC. The page should return a list of *real cafes* — places with cafe-like names, not the city itself or roads. Each result is clickable.

## Step by step

1. Visitor navigates to `/cafes`.
2. The page shows a heading called **Cafes** and a search box labeled "Search by city or place".
3. Visitor types `Vancouver, BC` into the search box and clicks **Search**.
4. The page reloads with results. The results section shows multiple cafe cards.
5. Each cafe card's title is a *cafe name* — something like "Blue Mountain Coffee" or "Revolver Coffee", not "Vancouver, British Columbia, Canada" (which is the city itself, not a cafe).
6. Clicking any cafe's name navigates to its detail page.

## What this test does not cover

- Search queries that return zero results (empty location, typo)
- Tag filters (separate journey)
- Search rate-limiting / Nominatim errors (separate test, with stubbed errors)

## What a regression in this slice would look like

**The Week 6 truthy-fixtures bug.** Search for `Vancouver, BC` returns the city of Vancouver as a single "cafe" result — display name "Vancouver, British Columbia, Canada". Root cause: the search query goes to Nominatim as-is, but Nominatim is a *geocoder*, not a cafe search. Querying "Vancouver, BC" returns the city. To get cafes, the query must use Nominatim's special-phrase syntax: `cafes near Vancouver, BC`. The unit-test suite missed this because it mocked Nominatim with cafe-shaped responses — a textbook truthy fixture. The bug only surfaced when Brew Crew walked this flow against real Nominatim.

This is the bug we expect Playwright to catch automatically. Other regressions it would catch:

- Search button not rendered → form submit fails at step 3
- Results don't link to detail pages → step 6 fails
- Non-cafe results (roads, boundaries) leak through → step 5 fails

## Note

Real cafe names and counts will vary slightly across Nominatim queries — Vancouver doesn't have a fixed roster of cafes. The Playwright test asserts on *shape* (multiple results, no city-named results), not on specific cafe names. This is intentional: the test should verify the behavior of *our integration* with Nominatim, not Nominatim's specific dataset.
