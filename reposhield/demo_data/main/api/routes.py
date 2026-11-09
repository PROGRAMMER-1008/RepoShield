from auth.tokens import verify_token
from orders.service import place_order
from payments.refund import refund
from payments.service import PaymentService

SECRET = "dev-only-secret"
PAYMENTS = PaymentService()


def handle(request: dict) -> dict:
    user = verify_token(request.get("token", ""), SECRET)
    if user is None:
        return {"status": 401}
    if request["path"] == "/orders":
        pid = place_order(PAYMENTS, user, request["items"])
        return {"status": 201, "payment_id": pid}
    if request["path"] == "/refund":
        cents = refund(PAYMENTS, request["payment_id"], request["amount"])
        return {"status": 200, "refunded_cents": cents}
    return {"status": 404}
