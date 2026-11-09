"""Unit tests: deterministic policy engine (thresholds come from the policy sheet)."""
from datetime import date, timedelta

from app.schemas.domain import Order, Policy
from app.services import policy_engine as pe
from app.services.data_source import DEMO_POLICIES

TODAY = date(2026, 11, 9)
POL = [Policy(**p) for p in DEMO_POLICIES]


def order(**kw):
    base = dict(order_id="ORD1", customer_name="A", customer_email="a@x", product_name="Lamp", product_price=50.0,
                order_date=(TODAY - timedelta(days=5)).isoformat(), delivery_status="delivered",
                delivery_date=(TODAY - timedelta(days=2)).isoformat(), payment_method="card")
    base.update(kw)
    return Order(**base)


def test_policy_params_parsed():
    assert pe.merged_params(POL)["return_window_days"] == "7"
    assert pe.merged_params(POL)["late_credit_percent"] == "10"


def test_return_within_window_eligible():
    r = pe.return_eligibility(order(), POL, TODAY)
    assert r["eligible"] and r["days_since_delivery"] == 2


def test_return_outside_window_denied():
    r = pe.return_eligibility(order(delivery_date=(TODAY - timedelta(days=12)).isoformat()), POL, TODAY)
    assert not r["eligible"] and any("7 days" in x for x in r["reasons"])


def test_return_boundary_day_7_eligible_day_8_not():
    assert pe.return_eligibility(order(delivery_date=(TODAY - timedelta(days=7)).isoformat()), POL, TODAY)["eligible"]
    assert not pe.return_eligibility(order(delivery_date=(TODAY - timedelta(days=8)).isoformat()), POL, TODAY)["eligible"]


def test_opened_hygiene_not_returnable():
    r = pe.return_eligibility(order(product_name="Electric Toothbrush", product_condition="opened"), POL, TODAY)
    assert not r["eligible"] and r["is_hygiene_product"]


def test_changing_sheet_threshold_changes_decision():
    custom = [p.model_copy() for p in POL]
    custom[0] = custom[0].model_copy(update={"policy_conditions": "return_window_days=14"})
    r = pe.return_eligibility(order(delivery_date=(TODAY - timedelta(days=12)).isoformat()), custom, TODAY)
    assert r["eligible"]


def test_inactive_policy_ignored():
    custom = [p.model_copy(update={"active_status": "inactive"}) if p.policy_id == "P001" else p for p in POL]
    assert "P001" not in [p.policy_id for p in pe.policies_for_issue("return_request", custom)]


def test_damage_requires_photo():
    a = pe.assess_issue("damaged_item", order(), POL, {"photo_verified": False}, TODAY)
    assert "damage_photo" in a["missing_evidence"] and "refund" not in a["allowed_actions"]
    a2 = pe.assess_issue("damaged_item", order(), POL, {"photo_verified": True}, TODAY)
    assert {"refund", "replacement"} <= set(a2["allowed_actions"]) and a2["max_amounts"]["refund"] == 50.0


def test_duplicate_refund_blocks_money_actions():
    a = pe.assess_issue("damaged_item", order(previous_refund_status="refunded"), POL, {"photo_verified": True}, TODAY)
    assert a["duplicate_refund"] and "refund" not in a["allowed_actions"] and "deny" in a["allowed_actions"]


def test_late_delivery_store_credit_amount():
    o = order(order_date=(TODAY - timedelta(days=12)).isoformat(), delivery_date=(TODAY - timedelta(days=1)).isoformat(),
              product_price=74.50)
    a = pe.assess_issue("late_delivery", o, POL, {}, TODAY)
    assert a["recommended_action"] == "store_credit" and a["max_amounts"]["store_credit"] == 7.45


def test_on_time_delivery_no_action():
    a = pe.assess_issue("late_delivery", order(), POL, {}, TODAY)
    assert a["recommended_action"] == "no_action_needed"


def test_in_transit_overdue_and_lost():
    overdue = order(delivery_status="in_transit", delivery_date=None, order_date=(TODAY - timedelta(days=10)).isoformat())
    assert pe.assess_issue("not_delivered", overdue, POL, {}, TODAY)["recommended_action"] == "carrier_investigation"
    lost = order(delivery_status="in_transit", delivery_date=None, order_date=(TODAY - timedelta(days=20)).isoformat())
    assert "refund" in pe.assess_issue("not_delivered", lost, POL, {}, TODAY)["allowed_actions"]


def test_cancellation_depends_on_fulfillment():
    assert pe.assess_issue("cancellation", order(delivery_status="processing", delivery_date=None), POL)["recommended_action"] == "cancel_order"
    assert pe.assess_issue("cancellation", order(), POL)["recommended_action"] == "deny"


def test_wrong_item_needs_description():
    a = pe.assess_issue("wrong_item", order(), POL, {}, TODAY)
    assert "received_item_description" in a["missing_evidence"]
    a2 = pe.assess_issue("wrong_item", order(), POL, {"received_item_description": "a red mug"}, TODAY)
    assert a2["recommended_action"] == "replacement"
