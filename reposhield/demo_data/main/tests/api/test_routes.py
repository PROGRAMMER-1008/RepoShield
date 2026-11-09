from api.routes import SECRET, handle
from auth.tokens import issue_token


def test_unauthenticated():
    assert handle({"path": "/orders", "token": ""})["status"] == 401


def test_order_then_refund():
    token = issue_token("ana", SECRET)
    res = handle({"path": "/orders", "token": token, "items": {"pen": (2, 3)}})
    assert res["status"] == 201
    out = handle({"path": "/refund", "token": token, "payment_id": res["payment_id"], "amount": "1.00"})
    assert out == {"status": 200, "refunded_cents": 100}
