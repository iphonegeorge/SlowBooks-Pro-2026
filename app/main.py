# ============================================================================
# Slowbooks Pro 2026 — Self-hosted accounting for small business
# ============================================================================

import os
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from app.auth import router as auth_router
from app.routes import (
    dashboard, accounts, customers, vendors, items,
    invoices, estimates, payments, banking, reports, settings, iif,
)
# Phase 1: Foundation
from app.routes import audit, search
# Phase 2: Accounts Payable
from app.routes import purchase_orders, bills, bill_payments, credit_memos
# Phase 3: Productivity
from app.routes import recurring, batch_payments
# Phase 4: Communication & Export
from app.routes import csv as csv_routes
from app.routes import uploads
# Phase 5: Advanced Integration
from app.routes import bank_import, tax, backups
# Phase 6: Ambitious
from app.routes import companies, employees, payroll
# Phase 7: Online Payments
from app.routes import stripe_payments, public
# Phase 8: QuickBooks Online
from app.routes import qbo
# Phase 9: Forum Bug Fixes & Missing Features
from app.routes import journal, deposits, cc_charges, checks
# Phase 10: Quick Wins + Medium Effort Features
from app.routes import bank_rules, budgets, attachments, email_templates

from app.database import SessionLocal
from app.services.audit import register_audit_hooks

# ---------------------------------------------------------------------------
# Rate limiter (shared instance)
# ---------------------------------------------------------------------------
from app.limiter import limiter

# ---------------------------------------------------------------------------
# Security headers middleware
# ---------------------------------------------------------------------------

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://js.stripe.com; "
            "style-src 'self' 'unsafe-inline'; "
            "frame-src https://js.stripe.com; "
            "img-src 'self' data:; "
            "connect-src 'self'"
        )
        return response

# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

app = FastAPI(title="Slowbooks Pro 2026", version="2.1.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS — configurable origins, no wildcard
allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:3003").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in allowed_origins],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    allow_headers=["Authorization", "Content-Type", "X-Company-Id"],
)

app.add_middleware(SecurityHeadersMiddleware)

# Auth routes (login, register — no JWT required)
app.include_router(auth_router)

# API routes (all require JWT via get_current_user dependency in each route)
app.include_router(dashboard.router)
app.include_router(accounts.router)
app.include_router(customers.router)
app.include_router(vendors.router)
app.include_router(items.router)
app.include_router(invoices.router)
app.include_router(estimates.router)
app.include_router(payments.router)
app.include_router(banking.router)
app.include_router(reports.router)
app.include_router(settings.router)
app.include_router(iif.router)

# Phase 1: Foundation
app.include_router(audit.router)
app.include_router(search.router)
# Phase 2: Accounts Payable
app.include_router(purchase_orders.router)
app.include_router(bills.router)
app.include_router(bill_payments.router)
app.include_router(credit_memos.router)
# Phase 3: Productivity
app.include_router(recurring.router)
app.include_router(batch_payments.router)
# Phase 4: Communication & Export
app.include_router(csv_routes.router)
app.include_router(uploads.router)
# Phase 5: Advanced Integration
app.include_router(bank_import.router)
app.include_router(tax.router)
app.include_router(backups.router)
# Phase 6: Ambitious
app.include_router(companies.router)
app.include_router(employees.router)
app.include_router(payroll.router)
# Phase 7: Online Payments
app.include_router(stripe_payments.router)
app.include_router(public.router)
# Phase 8: QuickBooks Online
app.include_router(qbo.router)
# Phase 9: Forum Bug Fixes & Missing Features
app.include_router(journal.router)
app.include_router(deposits.router)
app.include_router(cc_charges.router)
app.include_router(checks.router)
# Phase 10: Quick Wins + Medium Effort Features
app.include_router(bank_rules.router)
app.include_router(budgets.router)
app.include_router(attachments.router)
app.include_router(email_templates.router)

# Register audit log hooks
register_audit_hooks(SessionLocal)

# Static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Ensure uploads directory exists
uploads_dir = static_dir / "uploads"
uploads_dir.mkdir(exist_ok=True)

# SPA entry point
index_path = Path(__file__).parent.parent / "index.html"


@app.get("/")
async def serve_index():
    return FileResponse(str(index_path))
