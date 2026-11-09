def to_cents(amount) -> int:
    """Convert a decimal amount (str/float/int) to integer cents."""
    cents = round(float(amount) * 100)
    if cents < 0:
        raise ValueError("amount must not be negative")
    return int(cents)


def from_cents(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"
