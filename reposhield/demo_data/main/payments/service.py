from common.money import to_cents
from payments.database import Ledger


class PaymentService:
    def __init__(self, ledger: Ledger | None = None):
        self.ledger = ledger or Ledger()
        self.payments = {}
        self._next = 1

    def charge(self, account: str, amount) -> str:
        cents = to_cents(amount)
        if cents <= 0:
            raise ValueError("charge must be positive")
        pid = f"pay_{self._next}"
        self._next += 1
        self.ledger.add_entry(account, -cents, "charge")
        self.payments[pid] = {"account": account, "cents": cents, "refunded": 0}
        return pid
