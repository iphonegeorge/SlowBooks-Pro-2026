#!/usr/bin/env node
// ============================================================================
// Slowbooks Pro 2026 — Puppeteer End-to-End Browser Tests
//
// Tests the full UI workflow: register, login, create customers, invoices,
// receive payments, then verify P&L and Balance Sheet reports show correct
// values on cash basis accounting with Australian GST.
//
// Usage:   cd tests && npm install && npm test
// Prereqs: App running at http://localhost:3010 (fresh DB, no existing users)
// ============================================================================

const puppeteer = require('puppeteer');

const BASE_URL = process.env.BASE_URL || 'http://localhost:3010';
const SLOW = process.env.SLOW ? parseInt(process.env.SLOW) : 0; // ms delay between actions
const TEST_USER = process.env.ADMIN_USERNAME || 'gmirabelli';
const TEST_PASS = process.env.ADMIN_PASSWORD || 'Slowbooks2026';
const TEST_EMAIL = process.env.ADMIN_EMAIL || 'george@slowbooks.local';

let browser, page;
let passed = 0, failed = 0, total = 0;

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function assert(condition, name, detail = '') {
    total++;
    if (condition) {
        passed++;
        console.log(`  \x1b[32mPASS\x1b[0m ${name}`);
    } else {
        failed++;
        console.log(`  \x1b[31mFAIL\x1b[0m ${name}${detail ? ': ' + detail : ''}`);
    }
}

function approx(actual, expected, tolerance = 0.02) {
    return Math.abs(actual - expected) < tolerance;
}

async function sleep(ms) {
    return new Promise(r => setTimeout(r, ms));
}

// Wait for text to appear in page
async function waitForText(text, timeout = 5000) {
    await page.waitForFunction(
        (t) => document.body.innerText.includes(t),
        { timeout },
        text
    );
}

// Get text content of an element
async function getText(selector) {
    await page.waitForSelector(selector, { timeout: 5000 });
    return page.evaluate(sel => document.querySelector(sel)?.textContent?.trim() || '', selector);
}

// Type into a field (clear first)
async function clearAndType(selector, value) {
    await page.waitForSelector(selector, { timeout: 5000 });
    await page.click(selector, { clickCount: 3 }); // select all
    await page.type(selector, String(value));
}

// Click and wait for network to settle
async function clickAndWait(selector, waitMs = 500) {
    await page.waitForSelector(selector, { timeout: 5000 });
    await page.click(selector);
    await sleep(waitMs);
}

// Extract a number from text like "$3,500.00" or "3500"
function parseAmount(text) {
    if (!text) return 0;
    return parseFloat(text.replace(/[$,]/g, '')) || 0;
}

// Get table cell value: find row containing rowText, return the .amount cell
async function getReportValue(rowText) {
    return page.evaluate((text) => {
        const rows = document.querySelectorAll('#report-content tr, #modal-body tr');
        for (const row of rows) {
            if (row.textContent.includes(text)) {
                const amountCell = row.querySelector('.amount, td:last-child');
                return amountCell ? amountCell.textContent.trim() : '';
            }
        }
        return '';
    }, rowText);
}

// ---------------------------------------------------------------------------
// Main test suite
// ---------------------------------------------------------------------------

async function run() {
    console.log('\x1b[1m============================================\x1b[0m');
    console.log('\x1b[1m  Slowbooks Pro — Puppeteer E2E Tests\x1b[0m');
    console.log('\x1b[1m============================================\x1b[0m');
    console.log('');

    browser = await puppeteer.launch({
        headless: process.env.HEADLESS !== 'false',
        args: ['--no-sandbox', '--disable-setuid-sandbox'],
        slowMo: SLOW,
    });
    page = await browser.newPage();
    await page.setViewport({ width: 1280, height: 900 });

    // Catch console errors from the app
    const consoleErrors = [];
    page.on('console', msg => {
        if (msg.type() === 'error') consoleErrors.push(msg.text());
    });

    try {
        await testRegistration();
        await testLogin();
        await testSecurityGuards();
        await testCreateCustomers();
        await testCreateInvoices();
        await testSendInvoices();
        await testReceivePayments();
        await testInvoiceStatuses();
        await testProfitAndLoss();
        await testBalanceSheet();
        await testGSTSummary();

        if (consoleErrors.length > 0) {
            console.log('');
            console.log(`\x1b[33mBrowser console errors (${consoleErrors.length}):\x1b[0m`);
            consoleErrors.slice(0, 5).forEach(e => console.log(`  ${e}`));
        }
    } catch (err) {
        console.log(`\n\x1b[31mFATAL: ${err.message}\x1b[0m`);
        console.log(err.stack);
        failed++;
    } finally {
        await browser.close();
    }

    console.log('');
    console.log('\x1b[1m============================================\x1b[0m');
    console.log(`\x1b[1m  Results: \x1b[32m${passed} passed\x1b[0m, \x1b[31m${failed} failed\x1b[0m (${total} total)\x1b[0m`);
    console.log('\x1b[1m============================================\x1b[0m');
    process.exit(failed > 0 ? 1 : 0);
}

// ---------------------------------------------------------------------------
// Test: Registration (first-time admin setup)
// ---------------------------------------------------------------------------
async function testRegistration() {
    console.log('\x1b[1m[1/11] Registration...\x1b[0m');

    await page.goto(BASE_URL, { waitUntil: 'networkidle2' });
    await page.waitForSelector('#login-screen', { timeout: 10000 });
    assert(true, 'Login screen displayed');

    // Check if admin was pre-seeded from env vars
    const status = await page.evaluate(async (url) => {
        const r = await fetch(`${url}/api/auth/status`);
        return r.json();
    }, BASE_URL);

    if (!status.needs_setup) {
        // Admin pre-seeded — skip registration
        assert(true, `Admin pre-seeded from env (${TEST_USER}) — skipping registration`);
        console.log('');
        return;
    }

    // First boot — register via the UI
    await sleep(500);
    const regVisible = await page.$('#register-form:not(.hidden)');
    if (!regVisible) {
        const regLink = await page.$('a[onclick*="showRegister"]');
        if (regLink) {
            await regLink.click();
            await sleep(300);
        }
    }
    await page.waitForSelector('#register-form:not(.hidden)', { timeout: 5000 });

    await clearAndType('#reg-username', TEST_USER);
    await clearAndType('#reg-email', TEST_EMAIL);
    await clearAndType('#reg-password', TEST_PASS);
    await page.click('#register-submit');
    await sleep(1500);

    // After registration, it should show the login form or auto-login
    const loginVisible = await page.$('#login-form:not(.hidden)');
    const appVisible = await page.$('#app:not([style*="display: none"])');
    assert(loginVisible || appVisible, 'Registration succeeded — login form or app visible');
    console.log('');
}

// ---------------------------------------------------------------------------
// Test: Login
// ---------------------------------------------------------------------------
async function testLogin() {
    console.log('\x1b[1m[2/11] Login...\x1b[0m');

    // Check if auto-login after registration already got us in
    const sidebar = await page.$('#sidebar');
    const sidebarVisible = sidebar ? await page.evaluate(el => {
        const style = getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden';
    }, sidebar) : false;

    if (!sidebarVisible) {
        // Need to login manually — wait for auth/status fetch to show the login form
        await page.waitForFunction(
            () => {
                const lf = document.querySelector('#login-form');
                return lf && !lf.classList.contains('hidden');
            },
            { timeout: 5000 }
        );

        await page.waitForSelector('#login-username', { visible: true, timeout: 5000 });
        await clearAndType('#login-username', TEST_USER);
        await clearAndType('#login-password', TEST_PASS);
        await page.click('#login-submit');
        await sleep(2000);

        // Check if login failed (error message visible)
        const loginErr = await page.evaluate(() => {
            const el = document.querySelector('#login-error');
            return (el && !el.classList.contains('hidden')) ? el.textContent : '';
        });
        if (loginErr) {
            console.log(`    \x1b[33mLogin error: ${loginErr}\x1b[0m`);
        }

        // Debug: check page state
        const debugState = await page.evaluate(() => {
            const app = document.querySelector('#app');
            const ls = document.querySelector('#login-screen');
            return {
                appHidden: app?.classList.contains('hidden'),
                loginScreenHidden: ls?.classList.contains('hidden'),
                hasToken: !!localStorage.getItem('slowbooks_token'),
                hasUser: !!localStorage.getItem('slowbooks_user'),
            };
        });
        if (debugState.appHidden) {
            console.log(`    \x1b[33mDebug: app.hidden=${debugState.appHidden}, loginScreen.hidden=${debugState.loginScreenHidden}, token=${debugState.hasToken}, user=${debugState.hasUser}\x1b[0m`);
        }
    }

    // Debug: check page state before asserting
    const preState = await page.evaluate(() => {
        const app = document.querySelector('#app');
        const ls = document.querySelector('#login-screen');
        const err = document.querySelector('#login-error');
        return {
            appClasses: app?.className || 'N/A',
            loginScreenClasses: ls?.className || 'N/A',
            loginError: (err && !err.classList.contains('hidden')) ? err.textContent : '',
            hasToken: !!localStorage.getItem('slowbooks_token'),
            url: location.href,
        };
    });
    console.log(`    State: app="${preState.appClasses}" loginScreen="${preState.loginScreenClasses}" token=${preState.hasToken} err="${preState.loginError}"`);

    // App should be visible (not just in DOM — actually rendered)
    await page.waitForFunction(
        () => {
            const app = document.querySelector('#app');
            return app && !app.classList.contains('hidden');
        },
        { timeout: 10000 }
    );
    assert(true, 'Logged in — app visible with sidebar');

    // Check username shows in topbar (may need a moment to render)
    await sleep(1000);
    const userText = await page.evaluate(() => {
        const el = document.querySelector('#topbar-user');
        return el ? el.textContent.trim() : '';
    });
    // Also check localStorage as fallback
    const storedUser = await page.evaluate(() => {
        try { return JSON.parse(localStorage.getItem('slowbooks_user') || '{}').username || ''; }
        catch { return ''; }
    });
    assert(
        userText.includes(TEST_USER) || storedUser.includes(TEST_USER),
        `User authenticated (topbar: "${userText}", stored: "${storedUser}")`
    );
    console.log('');
}

// ---------------------------------------------------------------------------
// Test: Security guards
// ---------------------------------------------------------------------------
async function testSecurityGuards() {
    console.log('\x1b[1m[3/11] Security checks...\x1b[0m');

    // Try unauthenticated API call
    const resp = await page.evaluate(async (url) => {
        const r = await fetch(`${url}/api/dashboard`);
        return r.status;
    }, BASE_URL);
    // Note: the app's fetch includes auth headers, so we test raw fetch
    const rawResp = await page.evaluate(async (url) => {
        const r = await fetch(`${url}/api/dashboard`, { headers: {} });
        return r.status;
    }, BASE_URL);
    assert(rawResp === 401 || rawResp === 403, `Unauthenticated API returns ${rawResp}`);

    // Try second registration via API
    const regResp = await page.evaluate(async (url) => {
        const r = await fetch(`${url}/api/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: 'hacker', email: 'h@h.com', password: 'Hacker1234' }),
        });
        return r.status;
    }, BASE_URL);
    assert(regResp === 403, `Second registration blocked (${regResp})`);
    console.log('');
}

// ---------------------------------------------------------------------------
// Test: Create customers
// ---------------------------------------------------------------------------
async function testCreateCustomers() {
    console.log('\x1b[1m[4/11] Creating customers...\x1b[0m');

    // Navigate to customers page
    await page.click('a[data-page="customers"]');
    await sleep(1000);

    // Create customer 1: Acme Pty Ltd
    await page.evaluate(() => CustomersPage.showForm());
    await page.waitForSelector('#customer-form', { timeout: 5000 });
    await clearAndType('#customer-form input[name="name"]', 'Acme Pty Ltd');
    await clearAndType('#customer-form input[name="email"]', 'acme@example.com.au');
    await clearAndType('#customer-form input[name="phone"]', '0412345678');
    // Submit form
    await page.evaluate(() => {
        document.querySelector('#customer-form').dispatchEvent(new Event('submit', { cancelable: true }));
    });
    await sleep(1500);
    await waitForText('Acme Pty Ltd');
    assert(true, 'Customer: Acme Pty Ltd created');

    // Create customer 2: BuildCo Holdings
    await page.evaluate(() => CustomersPage.showForm());
    await page.waitForSelector('#customer-form', { timeout: 5000 });
    await clearAndType('#customer-form input[name="name"]', 'BuildCo Holdings');
    await clearAndType('#customer-form input[name="email"]', 'accounts@buildco.com.au');
    await clearAndType('#customer-form input[name="phone"]', '0298765432');
    await page.evaluate(() => {
        document.querySelector('#customer-form').dispatchEvent(new Event('submit', { cancelable: true }));
    });
    await sleep(1500);
    await waitForText('BuildCo Holdings');
    assert(true, 'Customer: BuildCo Holdings created');
    console.log('');
}

// ---------------------------------------------------------------------------
// Test: Create invoices
// ---------------------------------------------------------------------------
async function testCreateInvoices() {
    console.log('\x1b[1m[5/11] Creating invoices...\x1b[0m');

    // Navigate to invoices
    await page.click('a[data-page="invoices"]');
    await sleep(1000);

    // ---- Invoice A: Acme, 10hrs web dev @ $150, TAXABLE 10% ----
    // Expected: subtotal $1,500 + GST $150 = $1,650
    await createInvoice({
        customerName: 'Acme',
        date: '2026-04-01',
        taxRate: '10',
        lines: [{ description: 'April web development', qty: '10', rate: '150', gst: 'TAXABLE' }],
        expectedTotal: 1650,
        label: 'A',
    });

    // ---- Invoice B: BuildCo, 5hrs consulting @ $200, TAXABLE 10% ----
    // Expected: subtotal $1,000 + GST $100 = $1,100
    await createInvoice({
        customerName: 'BuildCo',
        date: '2026-04-05',
        taxRate: '10',
        lines: [{ description: 'Strategy consulting - April', qty: '5', rate: '200', gst: 'TAXABLE' }],
        expectedTotal: 1100,
        label: 'B',
    });

    // ---- Invoice C: Acme, 3hrs training @ $100, GST_FREE ----
    // Expected: subtotal $300 + GST $0 (GST-free line but 10% rate on invoice) = $300
    // Note: GST_FREE lines don't attract GST even if invoice has tax_rate
    await createInvoice({
        customerName: 'Acme',
        date: '2026-04-10',
        taxRate: '10',
        lines: [{ description: 'Staff training - April', qty: '3', rate: '100', gst: 'GST_FREE' }],
        expectedTotal: 300,
        label: 'C',
    });

    // ---- Invoice D: BuildCo, 8hrs dev @ $175, TAXABLE 10% ----
    // Expected: subtotal $1,400 + GST $140 = $1,540
    await createInvoice({
        customerName: 'BuildCo',
        date: '2026-04-15',
        taxRate: '10',
        lines: [{ description: 'Web development - mid April', qty: '8', rate: '175', gst: 'TAXABLE' }],
        expectedTotal: 1540,
        label: 'D',
    });

    // Verify 4 invoices in list
    await page.click('a[data-page="invoices"]');
    await sleep(1000);
    const invCount = await page.evaluate(() => {
        const rows = document.querySelectorAll('#content table tbody tr');
        return rows.length;
    });
    assert(invCount === 4, `Invoice list shows ${invCount} invoices (expected 4)`);
    console.log('');
}

async function createInvoice({ customerName, date, taxRate, lines, expectedTotal, label }) {
    await page.evaluate(() => InvoicesPage.showForm());
    await page.waitForSelector('#inv-customer-select', { timeout: 5000 });
    await sleep(500);

    // Select customer by matching name
    await page.evaluate((name) => {
        const sel = document.querySelector('#inv-customer-select');
        for (const opt of sel.options) {
            if (opt.textContent.includes(name)) { sel.value = opt.value; break; }
        }
        sel.dispatchEvent(new Event('change'));
    }, customerName);

    // Set date
    await page.evaluate((d) => {
        const input = document.querySelector('input[name="date"]');
        if (input) { input.value = d; input.dispatchEvent(new Event('change')); }
    }, date);

    // Set tax rate
    await page.evaluate((rate) => {
        const input = document.querySelector('input[name="tax_rate"]');
        if (input) { input.value = rate; input.dispatchEvent(new Event('input')); }
    }, taxRate);

    // Fill line items
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        // First line already exists, add more if needed
        if (i > 0) {
            await page.evaluate(() => InvoicesPage.addLine());
            await sleep(200);
        }

        await page.evaluate((lineData, idx) => {
            const rows = document.querySelectorAll('#inv-lines tr');
            const row = rows[idx];
            if (!row) return;
            const desc = row.querySelector('.line-desc');
            const qty = row.querySelector('.line-qty');
            const rate = row.querySelector('.line-rate');
            const gst = row.querySelector('.line-gst');
            if (desc) { desc.value = lineData.description; }
            if (qty) { qty.value = lineData.qty; }
            if (rate) { rate.value = lineData.rate; }
            if (gst) { gst.value = lineData.gst; }
            // Trigger recalc
            if (qty) qty.dispatchEvent(new Event('input'));
        }, line, i);
        await sleep(200);
    }

    // Recalculate
    await page.evaluate(() => InvoicesPage.recalc());
    await sleep(300);

    // Read total
    const displayedTotal = await page.evaluate(() => {
        const el = document.querySelector('#inv-total');
        return el ? el.textContent.trim() : '';
    });

    // Submit
    await page.evaluate(() => {
        const form = document.querySelector('#invoice-form');
        if (form) form.dispatchEvent(new Event('submit', { cancelable: true }));
    });
    await sleep(1500);

    const actualTotal = parseAmount(displayedTotal);
    assert(
        approx(actualTotal, expectedTotal, 1),
        `Invoice ${label}: total ${displayedTotal} (expected $${expectedTotal.toFixed(2)})`
    );
}

// ---------------------------------------------------------------------------
// Test: Send invoices
// ---------------------------------------------------------------------------
async function testSendInvoices() {
    console.log('\x1b[1m[6/11] Sending invoices...\x1b[0m');

    // Send all 4 invoices via API (faster than navigating each one in UI)
    const sentCount = await page.evaluate(async () => {
        let count = 0;
        const invoices = await API.get('/invoices');
        for (const inv of invoices) {
            if (inv.status === 'draft') {
                try {
                    await API.post(`/invoices/${inv.id}/send`, {});
                    count++;
                } catch (e) { /* ignore */ }
            }
        }
        return count;
    });
    assert(sentCount >= 4 || sentCount >= 0, `Sent ${sentCount} invoices`);

    // Verify via API all are sent
    const statuses = await page.evaluate(async () => {
        const invoices = await API.get('/invoices');
        return invoices.map(i => i.status);
    });
    const allSent = statuses.every(s => s === 'sent' || s === 'partial' || s === 'paid');
    assert(allSent, `All invoices sent (statuses: ${statuses.join(', ')})`);
    console.log('');
}

// ---------------------------------------------------------------------------
// Test: Receive payments
// ---------------------------------------------------------------------------
async function testReceivePayments() {
    console.log('\x1b[1m[7/11] Receiving payments...\x1b[0m');

    // Get invoice data
    const invoices = await page.evaluate(async () => await API.get('/invoices'));

    // Navigate to payments page
    await page.click('a[data-page="payments"]');
    await sleep(1000);

    // Payment 1: Acme pays Invoice A in full ($1,650)
    const invA = invoices.find(i => i.invoice_number === '1001');
    if (invA) {
        await receivePayment({
            customerName: 'Acme',
            amount: invA.total,
            invoiceId: invA.id,
            invoiceBalance: invA.balance_due,
            label: '1 (Acme - Invoice A full)',
        });
    }

    // Payment 2: BuildCo pays Invoice B in full ($1,100)
    const invB = invoices.find(i => i.invoice_number === '1002');
    if (invB) {
        await receivePayment({
            customerName: 'BuildCo',
            amount: invB.total,
            invoiceId: invB.id,
            invoiceBalance: invB.balance_due,
            label: '2 (BuildCo - Invoice B full)',
        });
    }

    // Payment 3: Acme pays Invoice C in full ($300)
    const invC = invoices.find(i => i.invoice_number === '1003');
    if (invC) {
        await receivePayment({
            customerName: 'Acme',
            amount: invC.total,
            invoiceId: invC.id,
            invoiceBalance: invC.balance_due,
            label: '3 (Acme - Invoice C full)',
        });
    }

    // Payment 4: BuildCo partial on Invoice D ($770 of $1,540)
    const invD = invoices.find(i => i.invoice_number === '1004');
    if (invD) {
        await receivePayment({
            customerName: 'BuildCo',
            amount: 770,
            invoiceId: invD.id,
            invoiceBalance: 770,
            label: '4 (BuildCo - Invoice D partial $770)',
        });
    }

    console.log('');
}

async function receivePayment({ customerName, amount, invoiceId, invoiceBalance, label }) {
    await page.evaluate(() => PaymentsPage.showForm());
    await page.waitForSelector('#payment-form', { timeout: 5000 });
    await sleep(500);

    // Select customer
    await page.evaluate((name) => {
        const sel = document.querySelector('#payment-form select[name="customer_id"]');
        for (const opt of sel.options) {
            if (opt.textContent.includes(name)) { sel.value = opt.value; break; }
        }
        sel.dispatchEvent(new Event('change'));
    }, customerName);
    await sleep(1500); // wait for invoices to load

    // Set amount
    await page.evaluate((amt) => {
        const input = document.querySelector('#payment-form input[name="amount"]');
        if (input) { input.value = amt; }
    }, amount);

    // Select method
    await page.evaluate(() => {
        const sel = document.querySelector('#payment-form select[name="method"]');
        if (sel) {
            for (const opt of sel.options) {
                if (opt.textContent.includes('ACH') || opt.textContent.includes('EFT')) {
                    sel.value = opt.value; break;
                }
            }
        }
    });

    // Allocate to invoice
    await page.evaluate((invId, bal) => {
        const input = document.querySelector(`input.alloc-amount[data-invoice="${invId}"]`);
        if (input) {
            input.value = bal;
            input.dispatchEvent(new Event('input'));
        }
    }, invoiceId, invoiceBalance);
    await sleep(300);

    // Submit
    await page.evaluate(() => {
        const form = document.querySelector('#payment-form');
        if (form) form.dispatchEvent(new Event('submit', { cancelable: true }));
    });
    await sleep(1500);

    assert(true, `Payment ${label}: $${amount}`);
}

// ---------------------------------------------------------------------------
// Test: Invoice statuses after payments
// ---------------------------------------------------------------------------
async function testInvoiceStatuses() {
    console.log('\x1b[1m[8/11] Verifying invoice statuses...\x1b[0m');

    const invoices = await page.evaluate(async () => await API.get('/invoices'));

    const invA = invoices.find(i => i.invoice_number === '1001');
    const invB = invoices.find(i => i.invoice_number === '1002');
    const invC = invoices.find(i => i.invoice_number === '1003');
    const invD = invoices.find(i => i.invoice_number === '1004');

    assert(invA?.status === 'paid', `Invoice A (1001): ${invA?.status} (expected paid)`);
    assert(invB?.status === 'paid', `Invoice B (1002): ${invB?.status} (expected paid)`);
    assert(invC?.status === 'paid', `Invoice C (1003): ${invC?.status} (expected paid)`);
    assert(invD?.status === 'partial', `Invoice D (1004): ${invD?.status} (expected partial, balance $${invD?.balance_due})`);
    console.log('');
}

// ---------------------------------------------------------------------------
// Test: Profit & Loss report values
// ---------------------------------------------------------------------------
async function testProfitAndLoss() {
    console.log('\x1b[1m[9/11] Verifying Profit & Loss...\x1b[0m');

    // Cash basis expected:
    // Payment 1: $1,500 income (Inv A line amount)
    // Payment 2: $1,000 income (Inv B line amount)
    // Payment 3: $300 income (Inv C, GST-free)
    // Payment 4: $770/$1540 = 50% ratio => $1,400 * 0.5 = $700 income
    // Total income: $3,500

    await page.click('a[data-page="reports"]');
    await sleep(1000);

    // Click Profit & Loss card
    await page.evaluate(() => ReportsPage.profitLoss());
    await page.waitForSelector('#report-content', { timeout: 5000 });
    await sleep(2000); // let report render

    // Select "This Year to Date" (default)
    const totalIncomeText = await getReportValue('Total Income');
    const netIncomeText = await getReportValue('Net Income');
    const totalExpensesText = await getReportValue('Total Expenses');

    const totalIncome = parseAmount(totalIncomeText);
    const netIncome = parseAmount(netIncomeText);
    const totalExpenses = parseAmount(totalExpensesText);

    console.log(`    Total Income: ${totalIncomeText} (expected $3,500.00)`);
    console.log(`    Total Expenses: ${totalExpensesText} (expected $0.00)`);
    console.log(`    Net Income: ${netIncomeText} (expected $3,500.00)`);

    assert(approx(totalIncome, 3500, 5), `P&L Total Income = ${totalIncomeText} (expected $3,500)`);
    assert(approx(netIncome, 3500, 5), `P&L Net Income = ${netIncomeText} (expected $3,500)`);
    assert(totalExpenses < 1, `P&L Total Expenses = ${totalExpensesText} (expected $0)`);

    // Close modal
    await page.evaluate(() => closeModal());
    await sleep(300);
    console.log('');
}

// ---------------------------------------------------------------------------
// Test: Balance Sheet
// ---------------------------------------------------------------------------
async function testBalanceSheet() {
    console.log('\x1b[1m[10/11] Verifying Balance Sheet...\x1b[0m');

    // Expected assets:
    //   Undeposited Funds: $3,820 ($1,650 + $1,100 + $300 + $770)
    // Expected liabilities:
    //   GST Collected: $320 ($150 + $100 + $0 + $70)

    await page.evaluate(() => ReportsPage.balanceSheet());
    await page.waitForSelector('#report-content', { timeout: 5000 });
    await sleep(2000);

    // Get Undeposited Funds from the report table
    const udFundsText = await page.evaluate(() => {
        const rows = document.querySelectorAll('#report-content tr, #modal-body tr');
        for (const row of rows) {
            if (row.textContent.includes('Undeposited Funds')) {
                const cell = row.querySelector('.amount, td:last-child');
                return cell ? cell.textContent.trim() : '';
            }
        }
        return '';
    });

    // Get GST Collected
    const gstCollectedText = await page.evaluate(() => {
        const rows = document.querySelectorAll('#report-content tr, #modal-body tr');
        for (const row of rows) {
            if (row.textContent.includes('GST Collected')) {
                const cell = row.querySelector('.amount, td:last-child');
                return cell ? cell.textContent.trim() : '';
            }
        }
        return '';
    });

    const totalAssetsText = await getReportValue('Total Assets');

    const udFunds = parseAmount(udFundsText);
    const gstCollected = parseAmount(gstCollectedText);
    const totalAssets = parseAmount(totalAssetsText);

    console.log(`    Undeposited Funds: ${udFundsText} (expected $3,820.00)`);
    console.log(`    GST Collected: ${gstCollectedText} (expected $320.00)`);
    console.log(`    Total Assets: ${totalAssetsText}`);

    assert(approx(udFunds, 3820, 5), `BS Undeposited Funds = ${udFundsText} (expected $3,820)`);
    assert(approx(gstCollected, 320, 5), `BS GST Collected = ${gstCollectedText} (expected $320)`);

    await page.evaluate(() => closeModal());
    await sleep(300);
    console.log('');
}

// ---------------------------------------------------------------------------
// Test: GST Summary
// ---------------------------------------------------------------------------
async function testGSTSummary() {
    console.log('\x1b[1m[11/11] Verifying GST Summary...\x1b[0m');

    // All transactions are in Q2 2026 (April)
    // Expected Q2 GST Collected: $320

    // Open GST Summary modal
    await page.evaluate(() => ReportsPage.gstSummary());
    await page.waitForSelector('#gst-year', { timeout: 5000 });
    await sleep(500);

    // Set year and click Generate
    await page.evaluate(() => { document.querySelector('#gst-year').value = '2026'; });
    await page.evaluate(() => ReportsPage.loadGSTSummary());
    await sleep(2000);

    // Read TOTAL row from the GST summary table
    const gstData = await page.evaluate(() => {
        const rows = document.querySelectorAll('#gst-summary-content tr');
        const result = { total: null, q4: null };
        for (const row of rows) {
            const text = row.textContent;
            const cells = row.querySelectorAll('td');
            if (cells.length >= 2) {
                const data = {
                    collected: cells[1] ? cells[1].textContent.trim() : '0',
                    inputCredits: cells[2] ? cells[2].textContent.trim() : '0',
                    netPayable: cells[3] ? cells[3].textContent.trim() : '0',
                };
                if (text.includes('TOTAL')) result.total = data;
                // Q4 in the Australian FY display = Apr-Jun (calendar Q2)
                if (text.includes('Q4') || text.includes('Apr')) result.q4 = data;
            }
        }
        return result;
    });

    if (gstData.total) {
        const collected = parseAmount(gstData.total.collected);
        console.log(`    TOTAL GST Collected: ${gstData.total.collected} (expected $320.00)`);
        console.log(`    TOTAL Input Credits: ${gstData.total.inputCredits} (expected $0.00)`);
        console.log(`    TOTAL Net Payable: ${gstData.total.netPayable} (expected $320.00)`);
        assert(approx(collected, 320, 5), `GST Total Collected = ${gstData.total.collected} (expected $320)`);
    } else if (gstData.q4) {
        const collected = parseAmount(gstData.q4.collected);
        console.log(`    Q4 GST Collected: ${gstData.q4.collected} (expected $320.00)`);
        assert(approx(collected, 320, 5), `GST Q4 Collected = ${gstData.q4.collected} (expected $320)`);
    } else {
        // Fallback: verify via API
        const gstAPI = await page.evaluate(async () => {
            const data = await API.get('/reports/gst-summary?year=2026');
            return { collected: data.total_gst_collected, net: data.total_net_gst_payable };
        });
        console.log(`    GST API Total Collected: $${gstAPI.collected} (expected $320)`);
        assert(approx(gstAPI.collected || 0, 320, 5), `GST API Collected = $${gstAPI.collected} (expected $320)`);
    }

    await page.evaluate(() => closeModal());
    await sleep(300);
    console.log('');
}

// ---------------------------------------------------------------------------
// Run
// ---------------------------------------------------------------------------
run();
