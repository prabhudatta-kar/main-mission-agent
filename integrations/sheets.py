"""
Legacy shim — kept so any stray imports of `integrations.sheets` still work.
Primary database is now Firebase (integrations/firebase_db.py).
Google Sheets is used only for coach view sync (integrations/sheets_sync.py).
"""
from integrations.firebase_db import sheets, FirebaseClient  # noqa: F401
from integrations.sheets_sync import SheetsClient, _normalize_phone  # noqa: F401
