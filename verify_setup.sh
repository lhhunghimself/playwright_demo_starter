#!/usr/bin/env bash
# verify_setup.sh — confirm the demo will work.
#
# This script verifies the bug→fix loop using the repo's commit history:
#
#   1. Check chromium and Nominatim are reachable.
#   2. Check out commit 3 (test added, bug still in app.py). Run pytest.
#      Expect FAIL — the test catches the bug.
#   3. Check out main (commit 4, fix applied). Run pytest. Expect PASS.
#   4. Restore the branch you were on.
#
# Requires network access to nominatim.openstreetmap.org. The Playwright
# test in this demo hits real Nominatim — no network, no demo.

set -eo pipefail

DEMO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DEMO_DIR"

# Find a python binary — Ubuntu 20.04+ and several other distros only ship
# `python3`, not `python`. Prefer python3 if available; fall back to python.
if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    echo "FAIL: neither python3 nor python in PATH" >&2
    exit 1
fi

# Remember which branch/commit we were on so we can restore at the end
ORIGINAL_REF=$(git rev-parse --abbrev-ref HEAD)
if [ "$ORIGINAL_REF" = "HEAD" ]; then
    ORIGINAL_REF=$(git rev-parse HEAD)
fi

cleanup() {
    git checkout -q "$ORIGINAL_REF" 2>/dev/null || true
}
trap cleanup EXIT

run_and_expect_pass() {
    local LABEL="$1"
    local OUTPUT
    if OUTPUT=$($PYTHON -m pytest tests/e2e/test_search_for_cafes.py -v 2>&1); then
        echo "    $LABEL: PASS"
    else
        echo "    $LABEL: did not pass — aborting"
        echo "$OUTPUT" | tail -25
        exit 1
    fi
}

run_and_expect_fail() {
    local LABEL="$1"
    local OUTPUT
    if OUTPUT=$($PYTHON -m pytest tests/e2e/test_search_for_cafes.py -v 2>&1); then
        echo "    $LABEL: test passed against buggy code — assertions are too loose"
        echo "$OUTPUT" | tail -10
        exit 1
    fi
    if echo "$OUTPUT" | grep -qE "^FAILED|1 failed"; then
        echo "    $LABEL: failed as expected (bug detected)"
    else
        echo "    $LABEL: test errored rather than failing"
        echo "    Common causes: (1) Nominatim is unreachable, (2) Chromium not installed."
        echo "$OUTPUT" | tail -20
        exit 1
    fi
}

echo "==> Checking playwright + chromium..."
$PYTHON -m playwright --version >/dev/null || {
    echo "FAIL: playwright not installed."
    echo "Run: pip install -r requirements.txt && $PYTHON -m playwright install chromium"
    exit 1
}
echo "    OK"

echo
echo "==> Checking nominatim.openstreetmap.org is reachable..."
if ! curl -sS -A "StudySpot-verify/1.0" -m 10 \
        "https://nominatim.openstreetmap.org/search?q=test&format=json&limit=1" >/dev/null; then
    echo "FAIL: can't reach nominatim.openstreetmap.org."
    echo "The demo's test hits real Nominatim — no network, no demo."
    exit 1
fi
echo "    OK"

echo
echo "==> [1/2] Checking out commit 3 (test added, bug still in place)..."
# Commit 3 = HEAD~1 from main (the fix is HEAD)
COMMIT3=$(git rev-list --reverse HEAD | sed -n '3p')
git checkout -q "$COMMIT3"
echo "    at $(git log -1 --oneline)"
run_and_expect_fail "    buggy (catches the bug)"

echo
echo "==> [2/2] Checking out main (commit 4, fix applied)..."
git checkout -q "$ORIGINAL_REF"
echo "    at $(git log -1 --oneline)"
run_and_expect_pass "    fixed"

echo
echo "==> ALL CHECKS PASSED. Demo is ready."
