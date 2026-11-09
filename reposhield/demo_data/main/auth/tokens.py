import base64
import hashlib
import hmac
import time


def issue_token(user: str, secret: str, ttl: int = 3600, now: float | None = None) -> str:
    exp = int((now if now is not None else time.time()) + ttl)
    body = base64.urlsafe_b64encode(f"{user}:{exp}".encode()).decode()
    sig = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str, secret: str, now: float | None = None) -> str | None:
    """Return the user for a valid, unexpired token, else None."""
    try:
        body, sig = token.rsplit(".", 1)
    except ValueError:
        return None
    expect = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expect, sig):
        return None
    user, exp = base64.urlsafe_b64decode(body.encode()).decode().rsplit(":", 1)
    if (now if now is not None else time.time()) > int(exp):
        return None
    return user
