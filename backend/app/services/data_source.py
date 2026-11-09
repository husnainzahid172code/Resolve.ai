"""Business data access: Orders, Store Policies, Resolution Logs.

Two adapters share one interface:

* GoogleSheetsDataSource -- the real integration (service account via gspread).
* LocalDemoDataSource    -- a clearly labelled demo adapter used when Google
  credentials are not configured. Its order dates are computed relative to
  today so the demo scenarios (e.g. "delivered 12 days ago") stay reproducible.

Both raise DataSourceUnavailable on failure so the agent can never mistake an
outage for "no data" and invent an investigation result.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from abc import ABC, abstractmethod
from datetime import date, timedelta
from typing import Any

from app.core.config import get_settings
from app.schemas.domain import Order, Policy

ORDER_COLUMNS = [
    "order_id", "customer_name", "customer_email", "product_name", "product_price", "order_date",
    "delivery_status", "delivery_date", "payment_method", "return_status", "previous_refund_status",
    "tracking_number", "product_condition",
]
POLICY_COLUMNS = [
    "policy_id", "policy_category", "policy_description", "policy_conditions", "policy_action", "active_status",
]
LOG_COLUMNS = [
    "case_id", "timestamp", "order_id", "customer_message", "issue_categories", "retrieved_order_information",
    "retrieved_policy_evidence", "proposed_action", "decision_summary", "risk_flags", "validation_status",
    "approval_status", "admin_decision", "final_customer_response",
]


class DataSourceUnavailable(Exception):
    """Raised when the business data source cannot be reached."""


class DataSource(ABC):
    name: str = "abstract"
    label: str = "abstract"

    @abstractmethod
    def get_order(self, order_id: str) -> Order | None: ...

    @abstractmethod
    def list_policies(self) -> list[Policy]: ...

    @abstractmethod
    def append_resolution_log(self, row: dict[str, Any]) -> None: ...

    @abstractmethod
    def list_resolution_logs(self) -> list[dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# Demo data (shared by the local adapter and the Sheets seeding script)
# ---------------------------------------------------------------------------

def demo_orders(today: date | None = None) -> list[dict[str, Any]]:
    t = today or date.today()

    def d(days_ago: int | None) -> str:
        return "" if days_ago is None else (t - timedelta(days=days_ago)).isoformat()

    rows = [
        # id, name, email, product, price, ordered, status, delivered, pay, return, prev_refund, tracking, condition
        ("ORD1001", "Ayesha Khan", "ayesha.khan@example.com", "Wireless Noise-Cancelling Headphones", 89.99,
         d(6), "delivered", d(2), "card", "none", "none", "TRK55010001", "new"),
        ("ORD1002", "Bilal Ahmed", "bilal.ahmed@example.com", "Smart Fitness Watch", 129.00,
         d(16), "delivered", d(12), "card", "none", "none", "TRK55010002", "new"),
        ("ORD1003", "Sara Malik", "sara.malik@example.com", "Trail Running Shoes (Size 42, Blue)", 74.50,
         d(12), "delivered", d(1), "paypal", "none", "none", "TRK55010003", "new"),
        ("ORD1004", "Usman Tariq", "usman.tariq@example.com", "Bluetooth Speaker", 45.00,
         d(20), "delivered", d(15), "card", "none", "refunded", "TRK55010004", "new"),
        ("ORD1005", "Hina Raza", "hina.raza@example.com", "Electric Toothbrush", 39.99,
         d(5), "delivered", d(3), "card", "none", "none", "TRK55010005", "opened"),
        ("ORD1006", "Omar Farooq", "omar.farooq@example.com", "Ceramic Coffee Mug Set", 24.00,
         d(1), "processing", None, "card", "none", "none", "", "new"),
        ("ORD1007", "Zara Hussain", "zara.hussain@example.com", "Laptop Backpack", 55.00,
         d(10), "in_transit", None, "cod", "none", "none", "TRK55010007", "new"),
        ("ORD1008", "Ali Hassan", "ali.hassan@example.com", "Glass Desk Lamp", 32.00,
         d(4), "delivered", d(2), "card", "none", "none", "TRK55010008", "new"),
        ("ORD1009", "Fatima Noor", "fatima.noor@example.com", "Yoga Mat", 28.00,
         d(4), "delivered", d(1), "card", "none", "none", "TRK55010009", "sealed"),
    ]
    return [dict(zip(ORDER_COLUMNS, r)) for r in rows]


DEMO_POLICIES: list[dict[str, str]] = [
    {"policy_id": "P001", "policy_category": "returns",
     "policy_description": "Returns are accepted within 7 days of delivery.",
     "policy_conditions": "return_window_days=7; requires delivery_status=delivered",
     "policy_action": "return_and_refund", "active_status": "active"},
    {"policy_id": "P002", "policy_category": "returns",
     "policy_description": "Opened hygiene products are not eligible for return.",
     "policy_conditions": "hygiene_keywords=toothbrush|razor|earbuds|cosmetic|makeup|underwear; excluded_condition=opened",
     "policy_action": "deny", "active_status": "active"},
    {"policy_id": "P003", "policy_category": "damage",
     "policy_description": "Damaged products require photographic evidence before a refund or replacement is offered.",
     "policy_conditions": "requires_photo=true; report_window_days=14",
     "policy_action": "refund_or_replacement", "active_status": "active"},
    {"policy_id": "P004", "policy_category": "wrong_item",
     "policy_description": "Wrong-item complaints must be checked against the original order before a replacement is sent.",
     "policy_conditions": "requires_received_item_description=true",
     "policy_action": "replacement", "active_status": "active"},
    {"policy_id": "P005", "policy_category": "refund",
     "policy_description": "All refunds require administrator approval. The system never executes payments.",
     "policy_conditions": "requires_admin_approval=true",
     "policy_action": "admin_approval", "active_status": "active"},
    {"policy_id": "P006", "policy_category": "refund",
     "policy_description": "Duplicate refund requests must be investigated; an order that was already refunded cannot be refunded again.",
     "policy_conditions": "blocked_previous_refund_status=refunded|refund_pending",
     "policy_action": "investigate", "active_status": "active"},
    {"policy_id": "P007", "policy_category": "cancellation",
     "policy_description": "Orders can be cancelled only before they are shipped (fulfillment status processing).",
     "policy_conditions": "cancellable_statuses=processing|pending",
     "policy_action": "cancel_order", "active_status": "active"},
    {"policy_id": "P008", "policy_category": "delivery",
     "policy_description": "Late delivery complaints require checking delivery and tracking information. Deliveries over 7 days are late and qualify for a 10% store credit; parcels not delivered after 14 days are treated as lost.",
     "policy_conditions": "late_threshold_days=7; late_credit_percent=10; lost_after_days=14",
     "policy_action": "store_credit_or_carrier_investigation", "active_status": "active"},
]


class LocalDemoDataSource(DataSource):
    name = "local_demo"
    label = "Local demo data (NOT Google Sheets)"

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.simulate_outage = False
        s = get_settings()
        self._db_path = s.data_dir / "demo_resolution_logs.db"
        with sqlite3.connect(self._db_path) as c:
            c.execute("CREATE TABLE IF NOT EXISTS logs (id INTEGER PRIMARY KEY AUTOINCREMENT, row TEXT)")

    def _check(self) -> None:
        if self.simulate_outage:
            raise DataSourceUnavailable("Simulated data-source outage (demo toggle)")

    def get_order(self, order_id: str) -> Order | None:
        self._check()
        for row in demo_orders():
            if row["order_id"].upper() == order_id.upper():
                return Order(**{**row, "delivery_date": row["delivery_date"] or None})
        return None

    def list_policies(self) -> list[Policy]:
        self._check()
        return [Policy(**p) for p in DEMO_POLICIES]

    def append_resolution_log(self, row: dict[str, Any]) -> None:
        self._check()
        with self._lock, sqlite3.connect(self._db_path) as c:
            c.execute("INSERT INTO logs(row) VALUES (?)", (json.dumps(row),))

    def list_resolution_logs(self) -> list[dict[str, Any]]:
        with sqlite3.connect(self._db_path) as c:
            return [json.loads(r[0]) for r in c.execute("SELECT row FROM logs ORDER BY id")]


class GoogleSheetsDataSource(DataSource):
    """Google Sheets adapter. Requires a service-account JSON shared with the sheet.

    Tabs: "Orders", "Store Policies", "Resolution Logs" (headers = *_COLUMNS).
    """

    name = "google_sheets"
    label = "Google Sheets"

    def __init__(self, spreadsheet_id: str, credentials_file: str, client: Any | None = None) -> None:
        self.simulate_outage = False
        self._spreadsheet_id = spreadsheet_id
        self._credentials_file = credentials_file
        self._client = client
        self._sheet = None
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._lock = threading.Lock()

    def _book(self):
        if self.simulate_outage:
            raise DataSourceUnavailable("Simulated Google Sheets outage (demo toggle)")
        if self._sheet is None:
            try:
                if self._client is None:
                    import gspread  # imported lazily so the demo runs without it

                    self._client = gspread.service_account(filename=self._credentials_file)
                    self._client.set_timeout(get_settings().sheets_timeout_seconds)
                self._sheet = self._client.open_by_key(self._spreadsheet_id)
            except Exception as exc:  # network, auth, permission
                raise DataSourceUnavailable(f"Google Sheets unreachable: {type(exc).__name__}: {exc}") from exc
        return self._sheet

    def _records(self, tab: str) -> list[dict]:
        ttl = get_settings().sheets_cache_seconds
        hit = self._cache.get(tab)
        if hit and time.time() - hit[0] < ttl and not self.simulate_outage:
            return hit[1]
        last_exc: Exception | None = None
        for attempt in range(2):  # one retry
            try:
                rows = self._book().worksheet(tab).get_all_records()
                self._cache[tab] = (time.time(), rows)
                return rows
            except DataSourceUnavailable:
                raise
            except Exception as exc:
                last_exc = exc
                time.sleep(0.5 * (attempt + 1))
        raise DataSourceUnavailable(f"Failed reading '{tab}': {last_exc}")

    def get_order(self, order_id: str) -> Order | None:
        for row in self._records("Orders"):
            if str(row.get("order_id", "")).strip().upper() == order_id.upper():
                clean = {k: ("" if row.get(k) is None else row.get(k)) for k in ORDER_COLUMNS}
                clean["product_price"] = float(clean["product_price"] or 0)
                clean["delivery_date"] = str(clean["delivery_date"]) or None
                for k in ("tracking_number", "order_date"):
                    clean[k] = str(clean[k])
                return Order(**clean)
        return None

    def list_policies(self) -> list[Policy]:
        return [Policy(**{k: str(r.get(k, "")) for k in POLICY_COLUMNS}) for r in self._records("Store Policies")]

    def append_resolution_log(self, row: dict[str, Any]) -> None:
        try:
            ws = self._book().worksheet("Resolution Logs")
            ws.append_row([str(row.get(c, "")) for c in LOG_COLUMNS], value_input_option="RAW")
        except DataSourceUnavailable:
            raise
        except Exception as exc:
            raise DataSourceUnavailable(f"Failed writing resolution log: {exc}") from exc

    def list_resolution_logs(self) -> list[dict[str, Any]]:
        return self._records("Resolution Logs")


_instance: DataSource | None = None
_instance_lock = threading.Lock()


def get_data_source() -> DataSource:
    global _instance
    with _instance_lock:
        if _instance is None:
            s = get_settings()
            if s.resolved_data_source == "google_sheets":
                _instance = GoogleSheetsDataSource(s.google_sheets_spreadsheet_id, s.google_service_account_file)
            else:
                _instance = LocalDemoDataSource()
        return _instance


def set_data_source(ds: DataSource | None) -> None:
    """Used by tests and the comparison runner to inject an adapter."""
    global _instance
    with _instance_lock:
        _instance = ds
