from common.money import to_cents
from payments.service import PaymentService


def refund(service: PaymentService, payment_id: str, amount) -> int:
    """Refund part or all of a payment. Returns the refunded cents."""
    payment = service.payments[payment_id]
    cents = to_cents(amount)
    remaining = payment["cents"] - payment["refunded"]
    if cents > remaining:
        raise ValueError("cannot refund more than the original charge")
    payment["refunded"] += cents
    service.ledger.add_entry(payment["account"], cents, "refund")
    return cents
