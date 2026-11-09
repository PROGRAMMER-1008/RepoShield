class Ledger:
    """In-memory ledger (stand-in for a real database)."""

    def __init__(self):
        self._entries = []

    def add_entry(self, account: str, cents: int, kind: str) -> None:
        self._entries.append((account, cents, kind))

    def balance(self, account: str) -> int:
        return sum(c for a, c, _ in self._entries if a == account)

    def entries(self, account: str):
        return [e for e in self._entries if e[0] == account]
