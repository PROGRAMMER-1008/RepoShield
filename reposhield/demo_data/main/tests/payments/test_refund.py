import pytest
from payments.refund import refund
from payments.service import PaymentService


def test_partial_refund():
    svc = PaymentService()
    pid = svc.charge("acct", "10.00")
    assert refund(svc, pid, "4.00") == 400
    assert svc.ledger.balance("acct") == -600


def test_refund_cannot_exceed_original():
    svc = PaymentService()
    pid = svc.charge("acct", "10.00")
    with pytest.raises(ValueError):
        refund(svc, pid, "10.01")
