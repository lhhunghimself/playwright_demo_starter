# Walkthrough — Running the Demo Live

The script for the ~20-minute Playwright demo in the second half of the Week 7
session. The arc mirrors what students did in Week 6 (manual e2e walk, caught
a bug) and shows them how to automate that loop with Playwright.

**Four acts. The bug is real and inherited from Week 6.**

Open this file in one window, your editor in another, your AI tool in a third,
a terminal in a fourth, and a browser pointed at your running demo app in a
fifth (or just toggle between them).

## Before you start (15 minutes before class)

1. Run `bash verify_setup.sh`. Must end with **ALL CHECKS PASSED**.
   The script (a) confirms chromium and Nominatim are reachable, (b) checks
   out commit 3 and asserts the test fails (catches the bug), (c) checks
   out main and asserts the test passes (fix applied), (d) puts you back
   on main. If anything breaks, fix it now.
2. Check out the demo start point: `git checkout demo-start`. This puts
   you at commit 2 — walkthrough exists, but the Playwright test files
   don't yet (they're added in commit 3, which is what Claude generates
   during Phase 2). The app.py still has the bug. This is the right state
   for the live demo. At the end, `git checkout main` returns to the full
   worked example.
3. Start the demo app in a separate terminal:
   ```
   docker compose up
   ```
   or, faster for the demo, the SQLite version:
   ```
   DATABASE_URL=sqlite:///dev.db SECRET_KEY=demo python app.py
   ```
   Open `http://localhost:5000/cafes` in a browser. Confirm the page loads.
4. Open these files in editor tabs you can switch between:
   - `walkthrough_search_for_cafes.md` (Act 1)
   - `prompts/phase_2_prompt.md` (Act 2)
   - `app.py` around line 370, the `_populate_cafes_from_nominatim` function
     (Act 4 — this is where the fix gets applied)
   - `fix_instructions.md` (Act 4 — the fix to apply, copy-pasteable)

---

## Act 1 — Manual walkthrough finds the bug (5 minutes)

**Goal:** Students see what their Week 6 walk looked like, applied to a
fresh user journey on the same app. The bug they caught last week is still
in the codebase, so it surfaces live.

### What to do

1. Switch to the editor showing `walkthrough_search_for_cafes.md`. Read the
   Steps section out loud (steps 1-6). Don't show the "What a regression
   looks like" section yet — that's the punchline at the end of this act.
2. Switch to the browser at `http://localhost:5000/cafes`.
3. Walk through the steps:
   - **Step 1**: visit `/cafes`. ✓
   - **Step 2**: see the heading "Cafes" and the search box. ✓
   - **Step 3**: type `Vancouver, BC` into the search box. Click Search.
   - **Step 4**: the page reloads with results. **One** result appears,
     with the name "Vancouver, Metro Vancouver Regional District, British
     Columbia, Canada" or similar.
   - **Step 5**: **bug surfaces.** The result is *the city of Vancouver*,
     not a cafe.
4. Stop. Ask the class: **"Why is the city showing up as a cafe?"**

   Take one or two answers. The right one is: Nominatim is a geocoder.
   Asking it "Vancouver, BC" gets you back the city, not cafes near the
   city. Our route handler treats every result as a cafe and inserts it.
   The query needs Nominatim's special-phrase syntax to ask for cafes.
5. Switch back to the editor with the walkthrough open. Scroll to the
   "What a regression in this slice would look like" section. Read the
   first paragraph out loud — this is the Week 6 truthy-fixtures bug,
   verbatim. The unit-test suite missed it (mocked Nominatim with cafe-
   shaped data). The Week 6 manual e2e walk caught it. **And the bug is
   still in the codebase as we speak.**

### What to emphasize

- The manual walk is what students did last week. They wrote a walkthrough
  document, walked it by hand, and caught a bug their unit tests had missed.
- This is the same kind of walk, applied to a journey we hadn't covered
  before. Same kind of bug surfaced — this time, in front of you.
- **The next 15 minutes are about automating this walk so the bug can never
  reach production again.**

---

## Act 2 — Generate the Playwright test from the walkthrough (7 minutes)

**Goal:** Students see how the walkthrough they just wrote becomes a
Playwright test. The walkthrough is the source of truth; the LLM does the
implementation.

### What to do

1. Switch to your AI tool. Opus 4.7 selected.
2. Open `prompts/phase_2_prompt.md`. Copy everything below the first `---`
   marker. (Above the marker is meta-instruction for you, not the LLM.)
3. Paste into the AI tool. Send.
4. While it generates (~10-30 seconds), point at the prompt structure and
   narrate: walkthrough first, then the route handler, the templates, the
   model, the env note, then the explicit ask. **"This is the work — not
   the prompt 'write me a test', but this structured prompt."**
5. When the output arrives, save the two files to `tests/e2e/`:
   - `tests/e2e/conftest.py`
   - `tests/e2e/test_search_for_cafes.py`
6. Open both files in the editor. Walk through them.

### What to point out in the LLM's output

Three things, in order:

**1. `DATABASE_URL` is set before `from app import ...`.** Same lesson as
the other Playwright tests in the codebase. If the LLM forgets this line,
the test silently hits the production DB.

**2. Selectors use `get_by_label`, `get_by_role`.** The search input is
selected by its label ("Search by city or place") and the submit button by
its role. Readable, refactor-resilient.

**3. The assertions name the bug they catch.** Look at the assertion
message — it should reference the Week 6 bug specifically: "Expected
multiple cafe results, got 1. If exactly 1, suspect the Week 6 Nominatim
bug." That's not boilerplate; it's the test author saying out loud what
regression they're guarding against.

### Compare to the committed reference

If you want to show the "expected shape," show students commit 3 in `git
log` or open it on GitHub — the files added there are what Claude is
expected to produce. Cosmetic differences (variable names, comment style)
are fine; structural differences are worth pausing on. If Claude's output
is missing one of the three things above, ask it to add it rather than
redoing the whole prompt.

---

## Act 3 — Run the test against the buggy app (3 minutes)

**Goal:** The test catches the bug Act 1 found manually. The bug is real,
the test is real, the failure is the same one students saw with their own
eyes 10 minutes ago.

### What to do

1. Switch to the terminal in the demo directory.
2. Run:
   ```
   python -m pytest tests/e2e/test_search_for_cafes.py -v
   ```
3. Watch. Nominatim is being hit for real; expect 5-10 seconds of "thinking"
   before the failure surfaces. **Pause here.** Tell students: the test is
   waiting for Nominatim, just like a real user would wait. This is the
   `to_be_visible(timeout=15000)` line doing its job. The auto-wait is the
   feature.
4. When it fails, the assertion message reads:
   ```
   AssertionError: Expected multiple cafe results, got 1.
   If exactly 1, suspect the Week 6 Nominatim bug: search query goes to
   Nominatim as-is, returning the city of Vancouver instead of cafes.
   ```
5. Read it out loud. Point out: **the test failure tells you what the bug
   is.** Because the test author wrote the assertion message that way. This
   is what good test authoring looks like.

### What to emphasize

The Playwright test is the *automated* version of the Act 1 manual walk.
It catches the same bug. The difference: it'll keep catching the bug every
time the test runs, forever, without a human walking through it again.

---

## Act 4 — Apply the fix, run the test, watch it pass (5 minutes)

**Goal:** Students see the green-bar moment — the fix turns a failing test
into a passing one, validating the fix without ambiguity.

### What to do

1. Switch to the editor showing `fix_instructions.md`. Read the two-edit
   summary out loud:
   - Edit 1: prefix the query with "cafes near" so Nominatim's special-
     phrase handling returns cafes.
   - Edit 2: filter results to keep only `class == "amenity" AND type == "cafe"`.
2. Switch to `app.py`, navigate to `_populate_cafes_from_nominatim` (around
   line 370). Apply both edits in front of students. Save.
3. Back to the terminal. Re-run:
   ```
   python -m pytest tests/e2e/test_search_for_cafes.py -v
   ```
4. This takes ~3 seconds. **PASSED**.
5. Switch to the browser. Re-do the manual walk from Act 1: type
   `Vancouver, BC`, click Search. Now you see multiple cafe results
   (Revolver Coffee, Nemesis Coffee, etc.). The bug is gone.

### What to emphasize

- The test is the contract between the bug and the fix. The bug existed
  because the integration with Nominatim was wrong. The test asserts what
  "right" means. The fix makes the test pass. **In the team's repo from
  here on, this test stays — any future regression that reintroduces the
  bug fails the test before merge.**
- This is what teams mean by "tests as documentation." The test specifies
  what behavior we require from the search flow. The implementation
  satisfies that specification.

---

## If you have time at the end (~2 minutes)

Talk about what the *next* Playwright test for this app would be. The
walkthrough already names two candidates:

- Search queries that return zero results (empty location, typo).
- Search with combined tag filters.

Each candidate is a separate user journey. Each gets its own walkthrough
document, fed to Claude, becomes its own test. The team builds the suite
one walkthrough at a time.

You can also mention that the same pattern — manual walk to find bugs,
Playwright to automate the catching — applies to the team's OWN project
features. Their Week 7 assignment Part 3 deliverable is exactly this:
a `team_walkthrough.md` with four scenarios, plus the Playwright test
file that implements them.

---

## Time budget

| Act | Time | What you're doing |
|-----|------|-------------------|
| 1   | 5 min | Manual walk in the browser, bug surfaces, name the cause |
| 2   | 7 min | LLM generates conftest + test, three things to notice |
| 3   | 3 min | Run buggy app — test fails, assertion message tells the story |
| 4   | 5 min | Apply fix in app.py, re-run — pass; verify in browser too |
| Total | 20 min | Second half of the Week 7 session |

## Takeaways for students

1. **The manual walk is the test design.** Whatever you do by hand at
   first, write it down as steps with expected outcomes — that's your
   walkthrough. The same walkthrough becomes the Playwright test later.
2. **LLMs produce serviceable Playwright tests given a clear walkthrough
   and the relevant app snippets.** Vague prompts produce nonsense. The
   prompt structure in `phase_2_prompt.md` is the leverage.
3. **A test's assertion message is documentation.** Write the message as
   though future-you (or your teammate) is reading it at 2am on a CI
   failure. "Got 1, expected 2+, suspect the Nominatim bug" is useful;
   "AssertionError" alone is not.
4. **End-to-end tests against real services catch what unit tests can't.**
   Mocks can lie. Real services tell the truth. Week 6 taught this with
   the manual walk; Week 7 makes it automatic.

## Troubleshooting (during the demo, in case)

**Nominatim is rate-limiting or down.** The test will time out at the
`expect(...).to_be_visible(timeout=15000)` line. If this happens, you have
two options: (a) wait 60 seconds and retry, or (b) explain that the test
relies on a real external service, and external services have failure
modes — which is itself a Week 7 lesson worth surfacing.

**LLM produces wildly different code.** Read it on screen. If structurally
similar, save and continue. If broken, ask the LLM to fix the specific
issue (e.g., "the test imports app before setting DATABASE_URL") rather
than redoing the whole prompt.

**Edit to app.py looks wrong.** If you've made changes you can't unmake,
`git checkout HEAD -- app.py` restores the file to its current commit's
state. From commit 2 (demo start), that restores the buggy app; from
commit 4 (main), that restores the fixed app.

**The test passes against the buggy app.** Either the LLM's assertions
were too loose (didn't check for the city result specifically), or
Nominatim is returning unusual data for "Vancouver, BC" today. Try a
different city (Seattle, Toronto) and update the test accordingly.
