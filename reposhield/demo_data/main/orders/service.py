from analytics.client import track
from payments.service import PaymentService


def place_order(payments: PaymentService, account: str, items: dict) -> str:
    total = sum(price * qty for price, qty in items.values())
    pid = payments.charge(account, total)
    track("order_placed", account=account, total=total)
    return pid
