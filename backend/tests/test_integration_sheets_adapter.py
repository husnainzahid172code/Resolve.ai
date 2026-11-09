"""Google Sheets adapter tested against an in-memory fake of the gspread API.

This verifies row mapping, log appends and failure handling. It does NOT prove
connectivity to a live Google Sheet (no credentials in the test environment);
that remains an untested integration documented in the testing report.
"""
import pytest

from app.services.data_source import (
    DEMO_POLICIES, LOG_COLUMNS, DataSourceUnavailable, GoogleSheetsDataSource, demo_orders,
)


class FakeWorksheet:
    def __init__(self, rows):
        self.rows = rows
        self.appended = []

    def get_all_records(self):
        return self.rows

    def append_row(self, values, value_input_option=None):
        self.appended.append(values)


class FakeBook:
    def __init__(self):
        orders = [dict(r, delivery_date=r["delivery_date"] or "") for r in demo_orders()]
        self.tabs = {"Orders": FakeWorksheet(orders), "Store Policies": FakeWorksheet(DEMO_POLICIES),
                     "Resolution Logs": FakeWorksheet([])}

    def worksheet(self, name):
        return self.tabs[name]


class FakeClient:
    def __init__(self, fail=False):
        self.fail = fail
        self.book = FakeBook()

    def open_by_key(self, key):
        if self.fail:
            raise ConnectionError("network down")
        return self.book


def test_sheets_order_mapping():
    ds = GoogleSheetsDataSource("sheet-id", "creds.json", client=FakeClient())
    o = ds.get_order("ord1003")
    assert o.order_id == "ORD1003" and o.product_price == 74.5
    assert ds.get_order("ORD9999") is None
    assert {p.policy_id for p in ds.list_policies()} >= {"P001", "P008"}


def test_sheets_log_append_columns():
    client = FakeClient()
    ds = GoogleSheetsDataSource("sheet-id", "creds.json", client=client)
    ds.append_resolution_log({"case_id": "RAI-1", "approval_status": "approved"})
    row = client.book.tabs["Resolution Logs"].appended[0]
    assert len(row) == len(LOG_COLUMNS) and row[0] == "RAI-1"


def test_sheets_unreachable_raises_unavailable():
    ds = GoogleSheetsDataSource("sheet-id", "creds.json", client=FakeClient(fail=True))
    with pytest.raises(DataSourceUnavailable):
        ds.get_order("ORD1001")
