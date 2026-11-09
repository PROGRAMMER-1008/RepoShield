import pytest
from payments.service import PaymentService


def test_charge_records_ledger_entry():
    svc = PaymentService()
    pid = svc.charge("acct", "10.00")
    assert pid == "pay_1"
    assert svc.ledger.balance("acct") == -1000


def test_zero_charge_rejected():
    with pytest.raises(ValueError):
        PaymentService().charge("acct", 0)
