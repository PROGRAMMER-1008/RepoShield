from analytics.client import EVENTS
from orders.service import place_order
from payments.service import PaymentService


def test_place_order_charges_and_tracks():
    svc = PaymentService()
    pid = place_order(svc, "acct", {"book": (10, 2)})
    assert svc.payments[pid]["cents"] == 2000
    assert EVENTS[-1]["event"] == "order_placed"
