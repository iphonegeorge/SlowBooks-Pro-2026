#!/bin/bash
# ============================================================================
# Slowbooks Pro 2026 — Full Test Suite
#
# Runs both test suites in sequence:
#   1. API smoke tests (curl-based) — tears down, builds, starts fresh
#   2. Puppeteer E2E tests — uses the running app from step 1
#
# Usage:   ./scripts/run_all_tests.sh
# Prereqs: Docker Desktop running, Node.js installed, port 3010 available
# ============================================================================

set -uo pipefail

BOLD="\033[1m"
GREEN="\033[32m"
RED="\033[31m"
RESET="\033[0m"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${BOLD}============================================${RESET}"
echo -e "${BOLD}  Slowbooks Pro ��� Full Test Suite${RESET}"
echo -e "${BOLD}============================================${RESET}"
echo ""

# ---------------------------------------------------------------------------
# Part 1: API smoke tests (includes docker setup)
# ---------------------------------------------------------------------------
echo -e "${BOLD}>>> Part 1: API Smoke Tests${RESET}"
echo ""
bash "$SCRIPT_DIR/setup_and_test.sh"
API_EXIT=$?

if [ "$API_EXIT" -ne 0 ]; then
    echo -e "${RED}API tests failed. Skipping Puppeteer tests.${RESET}"
    exit 1
fi

echo ""

# ---------------------------------------------------------------------------
# Part 2: Puppeteer E2E tests (app is already running from Part 1)
#
# We need a FRESH database for the Puppeteer tests since they register
# their own user. Tear down and restart without rebuilding.
# ---------------------------------------------------------------------------
echo -e "${BOLD}>>> Part 2: Puppeteer E2E Tests${RESET}"
echo ""

# Reset database for clean Puppeteer run
echo "  Resetting database for Puppeteer tests..."
docker compose down --remove-orphans 2>/dev/null
docker volume rm slowbooks-pro-2026_postgres_data 2>/dev/null || true
docker compose up -d 2>&1
echo "  Waiting for app..."

MAX_WAIT=90
WAITED=0
while true; do
    if curl -sf "http://localhost:3010/" > /dev/null 2>&1; then
        echo "  App ready after ${WAITED}s."
        break
    fi
    if [ "$WAITED" -ge "$MAX_WAIT" ]; then
        echo -e "  ${RED}TIMEOUT: App did not start within ${MAX_WAIT}s${RESET}"
        exit 1
    fi
    sleep 2
    WAITED=$((WAITED + 2))
done
echo ""

# Install Puppeteer deps if needed
if [ ! -d "$PROJECT_DIR/tests/node_modules" ]; then
    echo "  Installing Puppeteer..."
    (cd "$PROJECT_DIR/tests" && npm install --silent 2>&1)
    echo ""
fi

# Run Puppeteer tests
(cd "$PROJECT_DIR/tests" && node e2e.test.js)
PUPPET_EXIT=$?

echo ""
echo -e "${BOLD}============================================${RESET}"
if [ "$API_EXIT" -eq 0 ] && [ "$PUPPET_EXIT" -eq 0 ]; then
    echo -e "${GREEN}  All test suites passed!${RESET}"
else
    echo -e "${RED}  Some tests failed.${RESET}"
    [ "$API_EXIT" -ne 0 ] && echo -e "    ${RED}API tests: FAILED${RESET}"
    [ "$PUPPET_EXIT" -ne 0 ] && echo -e "    ${RED}Puppeteer tests: FAILED${RESET}"
fi
echo -e "${BOLD}============================================${RESET}"

exit $((API_EXIT + PUPPET_EXIT))
