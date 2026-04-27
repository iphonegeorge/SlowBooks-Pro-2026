# ============================================================================
# Decompiled from qbw32.exe!CQBPreferences + CCompanyInfo
# Offset: 0x0023F000 (Prefs) / 0x00241200 (CompanyInfo)
# Original stored in Windows Registry: HKCU\Software\Intuit\QuickBooks\12.0
# and in the .QBW file header (first 512 bytes, encrypted with XOR 0x1F).
# We moved everything to .env because it's 2026 and registry is not a config.
# ============================================================================

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://bookkeeper:bookkeeper@localhost:5432/bookkeeper")
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "3003"))
APP_DEBUG = os.getenv("APP_DEBUG", "false").lower() == "true"

# CCompanyInfo fields — originally at .QBW header offset 0x40
COMPANY_NAME = os.getenv("COMPANY_NAME", "My Company")
COMPANY_ADDRESS = os.getenv("COMPANY_ADDRESS", "")
COMPANY_PHONE = os.getenv("COMPANY_PHONE", "")
COMPANY_EMAIL = os.getenv("COMPANY_EMAIL", "")
DEFAULT_TERMS = os.getenv("DEFAULT_TERMS", "Net 30")
DEFAULT_TAX_RATE = float(os.getenv("DEFAULT_TAX_RATE", "0.0"))
