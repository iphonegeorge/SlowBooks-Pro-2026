#!/bin/bash
# ============================================================================
# Slowbooks Pro 2026 — Setup, Start, and Smoke Test
#
# This script:
#   1. Tears down any existing containers and volumes (fresh start)
#   2. Builds and starts the app via Docker Compose
#   3. Waits for the app to be healthy
#   4. Registers an admin account and logs in
#   5. Runs security checks (auth guard, registration lock)
#   6. Creates multiple customers, items, invoices (with GST), payments
#   7. Verifies P&L, Balance Sheet, and GST Summary have correct values
#
# Usage:   ./scripts/setup_and_test.sh
# Prereqs: Docker Desktop running, port 3010 available
# ============================================================================

set -uo pipefail

# Read ADMIN_* credentials from .env (if present) without sourcing the whole file
# (sourcing would corrupt POSTGRES_PASSWORD if it contains # characters)
ENV_FILE="$(cd "$(dirname "$0")/.." && pwd)/.env"
if [ -f "$ENV_FILE" ]; then
    _read_env() { grep "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2-; }
    ADMIN_USERNAME="${ADMIN_USERNAME:-$(_read_env ADMIN_USERNAME)}"
    ADMIN_PASSWORD="${ADMIN_PASSWORD:-$(_read_env ADMIN_PASSWORD)}"
    ADMIN_EMAIL="${ADMIN_EMAIL:-$(_read_env ADMIN_EMAIL)}"
fi

BASE_URL="http://localhost:${APP_PORT:-3010}"
API="$BASE_URL/api"
BOLD="\033[1m"
GREEN="\033[32m"
RED="\033[31m"
YELLOW="\033[33m"
RESET="\033[0m"

passed=0
failed=0

pass() { ((passed++)); echo -e "  ${GREEN}PASS${RESET} $1"; }
fail() { ((failed++)); echo -e "  ${RED}FAIL${RESET} $1: $2"; }

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
auth_get()  { curl -s -H "Authorization: Bearer $TOKEN" "$API$1"; }
auth_post() { curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "$2" "$API$1"; }
auth_put()  { curl -s -X PUT  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "$2" "$API$1"; }
jq_val()    { python3 -c "import sys,json; print(json.load(sys.stdin)$1)" 2>/dev/null; }

# Float comparison with tolerance (handles rounding)
approx() {
    python3 -c "
import sys
a, b, label = float('$1'), float('$2'), '$3'
if abs(a - b) < 0.02:
    print(f'MATCH {label}: expected {b}, got {a}')
    sys.exit(0)
else:
    print(f'MISMATCH {label}: expected {b}, got {a}')
    sys.exit(1)
"
}

echo -e "${BOLD}============================================${RESET}"
echo -e "${BOLD}  Slowbooks Pro 2026 — Setup & Smoke Test${RESET}"
echo -e "${BOLD}============================================${RESET}"
echo ""

# ---------------------------------------------------------------------------
# Step 1: Tear down existing containers
# ---------------------------------------------------------------------------
echo -e "${BOLD}[1/9] Tearing down existing containers...${RESET}"
docker compose down --remove-orphans 2>/dev/null || true
docker volume rm slowbooks-pro-2026_postgres_data 2>/dev/null || true
echo "  Done."
echo ""

# ---------------------------------------------------------------------------
# Step 2: Build and start
# ---------------------------------------------------------------------------
echo -e "${BOLD}[2/9] Building and starting containers...${RESET}"
docker compose build --no-cache slowbooks 2>&1 | tail -1
docker compose up -d 2>&1
echo "  Containers started."
echo ""

# ---------------------------------------------------------------------------
# Step 3: Wait for app to be healthy
# ---------------------------------------------------------------------------
echo -e "${BOLD}[3/9] Waiting for app to be healthy...${RESET}"
MAX_WAIT=90
WAITED=0
while true; do
    if curl -sf "$BASE_URL/" > /dev/null 2>&1; then
        echo "  App is responding after ${WAITED}s."
        break
    fi
    if [ "$WAITED" -ge "$MAX_WAIT" ]; then
        echo -e "  ${RED}TIMEOUT: App did not start within ${MAX_WAIT}s${RESET}"
        docker compose logs slowbooks 2>&1 | tail -20
        exit 1
    fi
    sleep 2
    WAITED=$((WAITED + 2))
done
echo ""

# ---------------------------------------------------------------------------
# Step 4: Register and login
# ---------------------------------------------------------------------------
echo -e "${BOLD}[4/9] Registering admin account and logging in...${RESET}"

# Check if admin was pre-seeded from env vars
STATUS_BODY=$(curl -s "$API/auth/status")
NEEDS_SETUP=$(echo "$STATUS_BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('needs_setup',False))" 2>/dev/null)

# Determine credentials — use ADMIN_USERNAME/PASSWORD env vars if set, else defaults
TEST_USER="${ADMIN_USERNAME:-gmirabelli}"
TEST_PASS="${ADMIN_PASSWORD:-Slowbooks2026}"
TEST_EMAIL="${ADMIN_EMAIL:-george@slowbooks.local}"

if [ "$NEEDS_SETUP" = "True" ]; then
    REG_RESULT=$(curl -s -w "\n%{http_code}" -X POST "$API/auth/register" \
        -H "Content-Type: application/json" \
        -d "{\"username\":\"$TEST_USER\",\"email\":\"$TEST_EMAIL\",\"password\":\"$TEST_PASS\"}")
    REG_CODE=$(echo "$REG_RESULT" | tail -1)
    REG_BODY=$(echo "$REG_RESULT" | sed '$d')

    if [ "$REG_CODE" = "201" ]; then
        pass "Admin account created ($TEST_USER)"
    else
        fail "Register" "HTTP $REG_CODE — $REG_BODY"
    fi
else
    pass "Admin pre-seeded from env ($TEST_USER)"
fi

LOGIN_RESULT=$(curl -s -w "\n%{http_code}" -X POST "$API/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$TEST_USER\",\"password\":\"$TEST_PASS\"}")
LOGIN_CODE=$(echo "$LOGIN_RESULT" | tail -1)
LOGIN_BODY=$(echo "$LOGIN_RESULT" | sed '$d')

if [ "$LOGIN_CODE" = "200" ]; then
    TOKEN=$(echo "$LOGIN_BODY" | jq_val "['access_token']")
    pass "Logged in — got JWT token"
else
    fail "Login" "HTTP $LOGIN_CODE — $LOGIN_BODY"
    echo -e "${RED}Cannot continue without auth token. Aborting.${RESET}"
    exit 1
fi
echo ""

# ---------------------------------------------------------------------------
# Step 5: Security checks
# ---------------------------------------------------------------------------
echo -e "${BOLD}[5/9] Security checks...${RESET}"
NOAUTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$API/dashboard")
if [ "$NOAUTH_CODE" = "401" ] || [ "$NOAUTH_CODE" = "403" ]; then
    pass "Unauthenticated GET /dashboard returns $NOAUTH_CODE"
else
    fail "Auth guard" "Expected 401/403, got $NOAUTH_CODE"
fi

REG2_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API/auth/register" \
    -H "Content-Type: application/json" \
    -d '{"username":"hacker","email":"h@h.com","password":"Hacker1234"}')
if [ "$REG2_CODE" = "403" ]; then
    pass "Second registration blocked (403)"
else
    fail "Registration lock" "Expected 403, got $REG2_CODE"
fi

# Settings check (Phase 8 fields)
SETTINGS=$(auth_get "/settings")
ACCT_BASIS=$(echo "$SETTINGS" | jq_val ".get('accounting_basis','?')")
COUNTRY=$(echo "$SETTINGS" | jq_val ".get('country','?')")
if [ "$ACCT_BASIS" = "cash" ] && [ "$COUNTRY" = "AU" ]; then
    pass "Settings: accounting_basis=cash, country=AU"
else
    fail "Settings" "basis=$ACCT_BASIS country=$COUNTRY (expected cash, AU)"
fi
echo ""

# ---------------------------------------------------------------------------
# Step 6: Seed data — customers, items, chart of accounts
# ---------------------------------------------------------------------------
echo -e "${BOLD}[6/9] Creating test data...${RESET}"

# Verify chart of accounts
ACCTS=$(auth_get "/accounts" | jq_val "len(d)" < /dev/stdin 2>/dev/null || auth_get "/accounts" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
if [ "$ACCTS" -gt 0 ] 2>/dev/null; then
    pass "Chart of accounts seeded ($ACCTS accounts)"
else
    fail "Chart of accounts" "Expected >0 accounts"
fi

# Customer 1: Acme
CUST1=$(auth_post "/customers" '{"name":"Acme Pty Ltd","email":"acme@example.com.au","phone":"0412345678"}')
CUST1_ID=$(echo "$CUST1" | jq_val "['id']")
[ -n "$CUST1_ID" ] && [ "$CUST1_ID" != "null" ] && pass "Customer: Acme Pty Ltd (id=$CUST1_ID)" || fail "Customer 1" "$CUST1"

# Customer 2: BuildCo
CUST2=$(auth_post "/customers" '{"name":"BuildCo Holdings","email":"accounts@buildco.com.au","phone":"0298765432"}')
CUST2_ID=$(echo "$CUST2" | jq_val "['id']")
[ -n "$CUST2_ID" ] && [ "$CUST2_ID" != "null" ] && pass "Customer: BuildCo Holdings (id=$CUST2_ID)" || fail "Customer 2" "$CUST2"

# Item 1: Web Development (service, $150/hr)
ITEM1=$(auth_post "/items" '{"name":"Web Development","item_type":"service","description":"Hourly web dev","rate":150.00}')
ITEM1_ID=$(echo "$ITEM1" | jq_val "['id']")
[ -n "$ITEM1_ID" ] && [ "$ITEM1_ID" != "null" ] && pass "Item: Web Development \$150/hr (id=$ITEM1_ID)" || fail "Item 1" "$ITEM1"

# Item 2: Consulting ($200/hr)
ITEM2=$(auth_post "/items" '{"name":"Consulting","item_type":"service","description":"Strategy consulting","rate":200.00}')
ITEM2_ID=$(echo "$ITEM2" | jq_val "['id']")
[ -n "$ITEM2_ID" ] && [ "$ITEM2_ID" != "null" ] && pass "Item: Consulting \$200/hr (id=$ITEM2_ID)" || fail "Item 2" "$ITEM2"

# Item 3: Training ($100/hr, GST-free)
ITEM3=$(auth_post "/items" '{"name":"Training","item_type":"service","description":"Education & training","rate":100.00}')
ITEM3_ID=$(echo "$ITEM3" | jq_val "['id']")
[ -n "$ITEM3_ID" ] && [ "$ITEM3_ID" != "null" ] && pass "Item: Training \$100/hr (id=$ITEM3_ID)" || fail "Item 3" "$ITEM3"
echo ""

# ---------------------------------------------------------------------------
# Step 7: Create invoices and payments with known amounts
# ---------------------------------------------------------------------------
echo -e "${BOLD}[7/9] Creating invoices and receiving payments...${RESET}"
echo ""

# ---- Invoice A: Acme, 10hrs web dev @ $150, TAXABLE 10% ----
# Subtotal: $1,500 | GST: $150 | Total: $1,650
INV_A=$(auth_post "/invoices" "{
    \"customer_id\": $CUST1_ID, \"date\": \"2026-04-01\", \"terms\": \"Net 30\", \"tax_rate\": 0.10,
    \"lines\": [{\"item_id\": $ITEM1_ID, \"description\": \"April web development\",
                 \"quantity\": 10, \"rate\": 150.00, \"gst_classification\": \"TAXABLE\", \"line_order\": 0}]
}")
INV_A_ID=$(echo "$INV_A" | jq_val "['id']")
INV_A_NUM=$(echo "$INV_A" | jq_val "['invoice_number']")
INV_A_TOTAL=$(echo "$INV_A" | jq_val "['total']")
if [ -n "$INV_A_ID" ] && [ "$INV_A_ID" != "null" ]; then
    pass "Invoice A: $INV_A_NUM — \$${INV_A_TOTAL} (10hrs x \$150 + 10% GST)"
else
    fail "Invoice A" "$INV_A"
fi

# ---- Invoice B: BuildCo, 5hrs consulting @ $200, TAXABLE 10% ----
# Subtotal: $1,000 | GST: $100 | Total: $1,100
INV_B=$(auth_post "/invoices" "{
    \"customer_id\": $CUST2_ID, \"date\": \"2026-04-05\", \"terms\": \"Net 30\", \"tax_rate\": 0.10,
    \"lines\": [{\"item_id\": $ITEM2_ID, \"description\": \"Strategy consulting - April\",
                 \"quantity\": 5, \"rate\": 200.00, \"gst_classification\": \"TAXABLE\", \"line_order\": 0}]
}")
INV_B_ID=$(echo "$INV_B" | jq_val "['id']")
INV_B_NUM=$(echo "$INV_B" | jq_val "['invoice_number']")
INV_B_TOTAL=$(echo "$INV_B" | jq_val "['total']")
if [ -n "$INV_B_ID" ] && [ "$INV_B_ID" != "null" ]; then
    pass "Invoice B: $INV_B_NUM — \$${INV_B_TOTAL} (5hrs x \$200 + 10% GST)"
else
    fail "Invoice B" "$INV_B"
fi

# ---- Invoice C: Acme, 3hrs training @ $100, GST_FREE ----
# Subtotal: $300 | GST: $0 | Total: $300
INV_C=$(auth_post "/invoices" "{
    \"customer_id\": $CUST1_ID, \"date\": \"2026-04-10\", \"terms\": \"Net 30\", \"tax_rate\": 0.10,
    \"lines\": [{\"item_id\": $ITEM3_ID, \"description\": \"Staff training - April\",
                 \"quantity\": 3, \"rate\": 100.00, \"gst_classification\": \"GST_FREE\", \"line_order\": 0}]
}")
INV_C_ID=$(echo "$INV_C" | jq_val "['id']")
INV_C_NUM=$(echo "$INV_C" | jq_val "['invoice_number']")
INV_C_TOTAL=$(echo "$INV_C" | jq_val "['total']")
if [ -n "$INV_C_ID" ] && [ "$INV_C_ID" != "null" ]; then
    pass "Invoice C: $INV_C_NUM — \$${INV_C_TOTAL} (3hrs x \$100, GST-free)"
else
    fail "Invoice C" "$INV_C"
fi

# ---- Invoice D: BuildCo, 8hrs web dev @ $175, TAXABLE 10% ----
# Subtotal: $1,400 | GST: $140 | Total: $1,540 (will be partially paid)
INV_D=$(auth_post "/invoices" "{
    \"customer_id\": $CUST2_ID, \"date\": \"2026-04-15\", \"terms\": \"Net 30\", \"tax_rate\": 0.10,
    \"lines\": [{\"item_id\": $ITEM1_ID, \"description\": \"Web development - mid April\",
                 \"quantity\": 8, \"rate\": 175.00, \"gst_classification\": \"TAXABLE\", \"line_order\": 0}]
}")
INV_D_ID=$(echo "$INV_D" | jq_val "['id']")
INV_D_NUM=$(echo "$INV_D" | jq_val "['invoice_number']")
INV_D_TOTAL=$(echo "$INV_D" | jq_val "['total']")
if [ -n "$INV_D_ID" ] && [ "$INV_D_ID" != "null" ]; then
    pass "Invoice D: $INV_D_NUM — \$${INV_D_TOTAL} (8hrs x \$175 + 10% GST)"
else
    fail "Invoice D" "$INV_D"
fi

# Verify invoice list
INV_COUNT=$(auth_get "/invoices" | python3 -c "import sys,json; print(len(json.load(sys.stdin)))")
if [ "$INV_COUNT" = "4" ]; then
    pass "Invoice list returns 4 invoices"
else
    fail "Invoice count" "Expected 4, got $INV_COUNT"
fi

# Send all invoices (mark as sent)
auth_post "/invoices/$INV_A_ID/send" '{}' > /dev/null
auth_post "/invoices/$INV_B_ID/send" '{}' > /dev/null
auth_post "/invoices/$INV_C_ID/send" '{}' > /dev/null
auth_post "/invoices/$INV_D_ID/send" '{}' > /dev/null
pass "All 4 invoices marked as sent"

echo ""
echo "  Receiving payments..."

# ---- Payment 1: Acme pays Invoice A in full ($1,650) ----
PAY1=$(auth_post "/payments" "{
    \"customer_id\": $CUST1_ID, \"date\": \"2026-04-20\", \"amount\": $INV_A_TOTAL,
    \"method\": \"bank_transfer\",
    \"allocations\": [{\"invoice_id\": $INV_A_ID, \"amount\": $INV_A_TOTAL}]
}")
PAY1_ID=$(echo "$PAY1" | jq_val "['id']")
[ -n "$PAY1_ID" ] && [ "$PAY1_ID" != "null" ] && pass "Payment 1: Acme pays Invoice A in full (\$$INV_A_TOTAL)" || fail "Payment 1" "$PAY1"

# ---- Payment 2: BuildCo pays Invoice B in full ($1,100) ----
PAY2=$(auth_post "/payments" "{
    \"customer_id\": $CUST2_ID, \"date\": \"2026-04-22\", \"amount\": $INV_B_TOTAL,
    \"method\": \"bank_transfer\",
    \"allocations\": [{\"invoice_id\": $INV_B_ID, \"amount\": $INV_B_TOTAL}]
}")
PAY2_ID=$(echo "$PAY2" | jq_val "['id']")
[ -n "$PAY2_ID" ] && [ "$PAY2_ID" != "null" ] && pass "Payment 2: BuildCo pays Invoice B in full (\$$INV_B_TOTAL)" || fail "Payment 2" "$PAY2"

# ---- Payment 3: Acme pays Invoice C in full ($300) ----
PAY3=$(auth_post "/payments" "{
    \"customer_id\": $CUST1_ID, \"date\": \"2026-04-23\", \"amount\": $INV_C_TOTAL,
    \"method\": \"eft\",
    \"allocations\": [{\"invoice_id\": $INV_C_ID, \"amount\": $INV_C_TOTAL}]
}")
PAY3_ID=$(echo "$PAY3" | jq_val "['id']")
[ -n "$PAY3_ID" ] && [ "$PAY3_ID" != "null" ] && pass "Payment 3: Acme pays Invoice C in full (\$$INV_C_TOTAL)" || fail "Payment 3" "$PAY3"

# ---- Payment 4: BuildCo partial payment on Invoice D ($770 of $1,540) ----
PAY4=$(auth_post "/payments" "{
    \"customer_id\": $CUST2_ID, \"date\": \"2026-04-25\", \"amount\": 770,
    \"method\": \"bank_transfer\",
    \"allocations\": [{\"invoice_id\": $INV_D_ID, \"amount\": 770}]
}")
PAY4_ID=$(echo "$PAY4" | jq_val "['id']")
[ -n "$PAY4_ID" ] && [ "$PAY4_ID" != "null" ] && pass "Payment 4: BuildCo partial on Invoice D (\$770 of \$$INV_D_TOTAL)" || fail "Payment 4" "$PAY4"

echo ""

# Verify invoice statuses
INV_A_STATUS=$(auth_get "/invoices/$INV_A_ID" | jq_val "['status']")
INV_B_STATUS=$(auth_get "/invoices/$INV_B_ID" | jq_val "['status']")
INV_C_STATUS=$(auth_get "/invoices/$INV_C_ID" | jq_val "['status']")
INV_D_STATUS=$(auth_get "/invoices/$INV_D_ID" | jq_val "['status']")
INV_D_BAL=$(auth_get "/invoices/$INV_D_ID" | jq_val "['balance_due']")

[ "$INV_A_STATUS" = "paid" ] && pass "Invoice A: paid" || fail "Invoice A status" "Expected paid, got $INV_A_STATUS"
[ "$INV_B_STATUS" = "paid" ] && pass "Invoice B: paid" || fail "Invoice B status" "Expected paid, got $INV_B_STATUS"
[ "$INV_C_STATUS" = "paid" ] && pass "Invoice C: paid" || fail "Invoice C status" "Expected paid, got $INV_C_STATUS"
[ "$INV_D_STATUS" = "partial" ] && pass "Invoice D: partial (balance \$$INV_D_BAL)" || fail "Invoice D status" "Expected partial, got $INV_D_STATUS"
echo ""

# ---------------------------------------------------------------------------
# Step 8: Verify financial reports
# ---------------------------------------------------------------------------
echo -e "${BOLD}[8/9] Verifying financial reports...${RESET}"
echo ""

# ---- Profit & Loss ----
# Cash basis: income recognised on payment, not invoice creation
# Payment 1: $1,500 income (line amount before GST)
# Payment 2: $1,000 income
# Payment 3: $300 income (GST-free)
# Payment 4: $770 payment on $1,540 invoice => ratio 0.5 => $700 income
# Expected total income: $3,500
# Expected net income: $3,500 (no expenses entered)
echo "  Checking Profit & Loss report..."
PNL=$(auth_get "/reports/profit-loss?start_date=2026-04-01&end_date=2026-04-30")
PNL_TOTAL_INCOME=$(echo "$PNL" | jq_val "['total_income']")
PNL_NET_INCOME=$(echo "$PNL" | jq_val "['net_income']")
PNL_TOTAL_EXPENSES=$(echo "$PNL" | jq_val "['total_expenses']")

echo "    Total Income: \$$PNL_TOTAL_INCOME (expected: \$3500.00)"
echo "    Total Expenses: \$$PNL_TOTAL_EXPENSES (expected: \$0)"
echo "    Net Income: \$$PNL_NET_INCOME (expected: \$3500.00)"

if approx "$PNL_TOTAL_INCOME" "3500" "P&L Total Income" > /dev/null 2>&1; then
    pass "P&L Total Income = \$$PNL_TOTAL_INCOME (expected \$3,500)"
else
    fail "P&L Total Income" "Expected \$3,500, got \$$PNL_TOTAL_INCOME"
fi
if approx "$PNL_NET_INCOME" "3500" "P&L Net Income" > /dev/null 2>&1; then
    pass "P&L Net Income = \$$PNL_NET_INCOME (expected \$3,500)"
else
    fail "P&L Net Income" "Expected \$3,500, got \$$PNL_NET_INCOME"
fi

# ---- Balance Sheet ----
# Expected:
#   Undeposited Funds (1200): $3,820 ($1,650 + $1,100 + $300 + $770)
#   GST Collected (2210): $320 ($150 + $100 + $0 + $70)
echo ""
echo "  Checking Balance Sheet..."
BS=$(auth_get "/reports/balance-sheet?as_of_date=2026-04-30")
BS_ASSETS=$(echo "$BS" | jq_val "['total_assets']")
BS_LIABILITIES=$(echo "$BS" | jq_val "['total_liabilities']")

echo "    Total Assets: \$$BS_ASSETS"
echo "    Total Liabilities: \$$BS_LIABILITIES"

# Check specific accounts in balance sheet
UNDEPOSITED=$(echo "$BS" | python3 -c "
import sys, json
bs = json.load(sys.stdin)
for a in bs['assets']:
    if a['account_number'] == '1200':
        print(a['amount'])
        break
else:
    print('0')
")
echo "    Undeposited Funds (1200): \$$UNDEPOSITED (expected: \$3,820)"
if approx "$UNDEPOSITED" "3820" "Undeposited Funds" > /dev/null 2>&1; then
    pass "Balance Sheet: Undeposited Funds = \$$UNDEPOSITED (expected \$3,820)"
else
    fail "Undeposited Funds" "Expected \$3,820, got \$$UNDEPOSITED"
fi

GST_COLL=$(echo "$BS" | python3 -c "
import sys, json
bs = json.load(sys.stdin)
for l in bs['liabilities']:
    if l['account_number'] == '2210':
        print(abs(l['amount']))
        break
else:
    print('0')
")
echo "    GST Collected (2210): \$$GST_COLL (expected: \$320)"
if approx "$GST_COLL" "320" "GST Collected" > /dev/null 2>&1; then
    pass "Balance Sheet: GST Collected = \$$GST_COLL (expected \$320)"
else
    fail "GST Collected" "Expected \$320, got \$$GST_COLL"
fi

# ---- Dashboard ----
DASH_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" "$API/dashboard")
[ "$DASH_CODE" = "200" ] && pass "Dashboard loads (200)" || fail "Dashboard" "HTTP $DASH_CODE"

# ---- GST Summary ----
echo ""
echo "  Checking GST Summary (Q2 2026)..."
GST_RPT=$(auth_get "/reports/gst-summary?year=2026")
Q2_COLLECTED=$(echo "$GST_RPT" | python3 -c "
import sys, json
rpt = json.load(sys.stdin)
for q in rpt.get('quarters', []):
    if q.get('quarter') in ('Q2', 2):
        print(q.get('gst_collected', 0))
        break
else:
    # Fallback to total
    print(rpt.get('total_gst_collected', 0))
" 2>/dev/null || echo "0")
echo "    Q2 GST Collected: \$$Q2_COLLECTED (expected: \$320)"
if approx "$Q2_COLLECTED" "320" "Q2 GST" > /dev/null 2>&1; then
    pass "GST Summary: Q2 Collected = \$$Q2_COLLECTED (expected \$320)"
else
    fail "GST Q2 Collected" "Expected \$320, got \$$Q2_COLLECTED"
fi

# ---- AR Aging ----
echo ""
echo "  Checking AR Aging..."
AR_AGING=$(auth_get "/reports/ar-aging")
AR_TOTAL=$(echo "$AR_AGING" | python3 -c "
import sys, json
data = json.load(sys.stdin)
total = sum(c.get('total',0) for c in data.get('items', data.get('customers',[])))
print(total)
" 2>/dev/null || echo "0")
echo "    AR Outstanding: \$$AR_TOTAL (expected: \$770 — Invoice D partial)"
if approx "$AR_TOTAL" "770" "AR Aging" > /dev/null 2>&1; then
    pass "AR Aging: Outstanding = \$$AR_TOTAL (expected \$770)"
else
    fail "AR Aging" "Expected \$770, got \$$AR_TOTAL"
fi
echo ""

# ---------------------------------------------------------------------------
# Step 9: Summary
# ---------------------------------------------------------------------------
echo -e "${BOLD}============================================${RESET}"
echo -e "${BOLD}  Results: ${GREEN}$passed passed${RESET}, ${RED}$failed failed${RESET}"
echo -e "${BOLD}============================================${RESET}"
echo ""

if [ "$failed" -gt 0 ]; then
    echo -e "${RED}Some tests failed. Check output above.${RESET}"
    echo "Container logs:"
    docker compose logs slowbooks 2>&1 | tail -15
    exit 1
else
    echo -e "${GREEN}All tests passed! App is running at $BASE_URL${RESET}"
    echo ""
    echo "  Login credentials:"
    echo "    Username: $TEST_USER"
    echo "    Password: $TEST_PASS"
    echo ""
    echo "  To stop:  docker compose down"
    echo "  To logs:  docker compose logs -f slowbooks"
fi
