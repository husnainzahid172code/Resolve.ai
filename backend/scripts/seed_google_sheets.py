"""Create/refresh the three ResolveAI tabs in your Google Sheet with demo rows.

Usage (from backend/):  python -m scripts.seed_google_sheets
Requires GOOGLE_SHEETS_SPREADSHEET_ID and GOOGLE_SERVICE_ACCOUNT_FILE in .env, and the
sheet shared (Editor) with the service account's client_email.
Order dates are written relative to TODAY, so re-run this before a demo.
"""
from __future__ import annotations

import gspread

from app.core.config import get_settings
from app.services.data_source import DEMO_POLICIES, LOG_COLUMNS, ORDER_COLUMNS, POLICY_COLUMNS, demo_orders


def upsert_tab(book, title, header, rows):
    try:
        ws = book.worksheet(title)
        if title == "Resolution Logs":
            if not ws.row_values(1):
                ws.update([header], "A1")
            return ws
        ws.clear()
    except gspread.WorksheetNotFound:
        ws = book.add_worksheet(title=title, rows=200, cols=len(header) + 2)
    ws.update([header] + [[r.get(c, "") for c in header] for r in rows], "A1")
    return ws


def main():
    s = get_settings()
    if not (s.google_sheets_spreadsheet_id and s.google_service_account_file):
        raise SystemExit("Set GOOGLE_SHEETS_SPREADSHEET_ID and GOOGLE_SERVICE_ACCOUNT_FILE in backend/.env")
    book = gspread.service_account(filename=s.google_service_account_file).open_by_key(s.google_sheets_spreadsheet_id)
    upsert_tab(book, "Orders", ORDER_COLUMNS, demo_orders())
    upsert_tab(book, "Store Policies", POLICY_COLUMNS, DEMO_POLICIES)
    upsert_tab(book, "Resolution Logs", LOG_COLUMNS, [])
    print("Seeded Orders, Store Policies and Resolution Logs tabs.")


if __name__ == "__main__":
    main()
