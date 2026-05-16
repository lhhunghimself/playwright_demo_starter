# Week 7 — Playwright Demo (Worked Example)

A worked example of the Week 7 Playwright demo, with the work broken into
four reviewable commits.

This repo is a slice of `study_spot_demo` (Brew Crew, the Week 6 worked
example) with the Week 7 work added on top. The Nominatim bug from Week 6
is still in the codebase at commit 1; commits 2-4 show how a manual
walkthrough turns into an automated test that catches the bug, and how the
fix turns red into green.

## The commits

```
git log --oneline
```

| Commit | What it adds | Why |
|--------|--------------|-----|
| 1 — Initial | Brew Crew app, scaffolding, demo materials | The Week 6 codebase carried into Week 7. The `_populate_cafes_from_nominatim` function still has the bug Brew Crew documented in `e2e.md`. |
| 2 — Walkthrough | `walkthrough_search_for_cafes.md` | The plain-English user journey we want to test. No code yet. |
| 3 — Playwright test | `tests/e2e/conftest.py` and `tests/e2e/test_search_for_cafes.py` | The automated version of the walkthrough. **At this commit, the test fails** — it catches the Nominatim bug. |
| 4 — Fix | Two edits to `_populate_cafes_from_nominatim` in `app.py` | Adds the `cafes near` prefix and the amenity-type filter. **At this commit, the test passes.** |

## Walking through the commits

```bash
# Clone
git clone <repo-url> playwright_demo
cd playwright_demo

# Install
pip install -r requirements.txt
python -m playwright install chromium

# Step through the progression
git checkout HEAD~3      # commit 1: initial state, bug present, no test
git checkout HEAD~2      # commit 2: walkthrough added
git checkout HEAD~1      # commit 3: test added — pytest fails here, catches the bug
python -m pytest tests/e2e/test_search_for_cafes.py -v

git checkout main        # commit 4: fix applied — pytest passes
python -m pytest tests/e2e/test_search_for_cafes.py -v
```

## What's in this repo

| Path | What it is | Added in commit |
|------|------------|-----------------|
| `app.py`, `templates/`, `static/`, `CONTRACTS.md` | Brew Crew Flask app | 1 (modified in 4) |
| `walkthrough_search_for_cafes.md` | The Act 1 walkthrough students write before any code | 2 |
| `tests/e2e/conftest.py`, `tests/e2e/test_search_for_cafes.py` | The Playwright test generated from the walkthrough | 3 |
| `prompts/phase_2_prompt.md` | The LLM prompt used to generate the test from the walkthrough | 1 |
| `fix_instructions.md` | Human-readable description of the fix applied in commit 4 | 1 |
| `verify_setup.sh` | One-shot end-to-end check (chromium, Nominatim, the bug→fix loop via git) | 1 |
| `INSTRUCTOR_NOTES.md` | The lecturer's minute-by-minute script | 1 |

## One-time setup

```bash
pip install -r requirements.txt
python -m playwright install chromium
bash verify_setup.sh
```

The verify script confirms (a) chromium is installed, (b) Nominatim is
reachable, (c) the test fails at commit 3, (d) the test passes at commit 4.
If any of those breaks, fix it before doing the walkthrough.

### Network requirement

The Playwright test hits real Nominatim
(`nominatim.openstreetmap.org`). If that's unreachable from your
environment, the test won't run. This is by design — the whole pedagogical
point is that e2e tests against real services catch what mocked unit tests
can't. The verify script tells you immediately if Nominatim isn't reachable.

## Running through the demo

Open `INSTRUCTOR_NOTES.md` for the minute-by-minute version. The short
version for following along:

1. Read `walkthrough_search_for_cafes.md` (commit 2's contribution). Walk
   the same flow in a browser at `localhost:5000/cafes` — type `Vancouver,
   BC`, click Search. The bug surfaces: one "cafe" result, the city itself.
2. Paste `prompts/phase_2_prompt.md` into Claude (Opus 4.7). Save the two
   files Claude produces into `tests/e2e/`. (For comparison: commit 3 of
   this repo shows what Claude is expected to produce.)
3. Run `python -m pytest tests/e2e/test_search_for_cafes.py -v`. It fails
   after 5-10s with an assertion message naming the Week 6 bug.
4. Apply the two edits in `fix_instructions.md` to `_populate_cafes_from_nominatim`
   in `app.py`. (For comparison: commit 4 of this repo is exactly those
   two edits.) Re-run pytest. Passes.

Total time: about 20 minutes if you follow along during the lecture.

## After the demo

The walkthrough → test pattern in commits 2-3 is the team-project version
of the Week 7 assignment Part 3 deliverable. Each user journey you want to
verify gets a walkthrough document, then a Playwright test. The team's
`team_walkthrough.md` collects the journeys; the team's
`test_full_lifecycle.py` is the test suite that exercises them.

## Notes

- OAuth is **not** part of this demo. The course deck slides 36-37 cover
  the test-login backdoor pattern for OAuth-protected flows, and the
  assignment includes the backdoor code as a reference.
- The bug in commit 1 is real and inherited from Week 6. The Brew Crew
  team documented finding it during their manual e2e walk; the
  `study_spot_demo` repo's `e2e.md` has the full write-up.
