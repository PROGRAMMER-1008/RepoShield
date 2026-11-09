from payments.database import Ledger


def test_balance():
    ledger = Ledger()
    ledger.add_entry("a", -500, "charge")
    ledger.add_entry("a", 200, "refund")
    assert ledger.balance("a") == -300
    assert len(ledger.entries("a")) == 2
