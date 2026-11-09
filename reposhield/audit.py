"""Tamper-evident audit log: each event hashes its content plus the previous event's hash."""
from __future__ import annotations

import json
import os
import time

from .util import canonical_json, sha256_hex

GENESIS = "0" * 64


class AuditLog:
    def __init__(self, path: str, run_id: str = ""):
        self.path, self.run_id = path, run_id
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.seq, self.prev = 0, GENESIS
        if os.path.exists(path):
            events = read_events(path)
            if events:
                self.seq, self.prev = events[-1]["seq"] + 1, events[-1]["hash"]

    def append(self, etype: str, actor: str = "reposhield", data: dict | None = None) -> dict:
        ev = {"seq": self.seq, "ts": round(time.time(), 3), "run_id": self.run_id, "type": etype,
              "actor": actor, "data": data or {}, "prev": self.prev}
        ev["hash"] = sha256_hex(canonical_json(ev))
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(ev, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self.seq, self.prev = self.seq + 1, ev["hash"]
        return ev

    @property
    def head_hash(self) -> str:
        return self.prev


def read_events(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def verify_chain(path: str) -> tuple[bool, str]:
    prev = GENESIS
    try:
        events = read_events(path)
    except (OSError, ValueError) as e:
        return False, f"unreadable log: {e}"
    for i, ev in enumerate(events):
        claimed = ev.get("hash")
        body = {k: v for k, v in ev.items() if k != "hash"}
        if ev.get("seq") != i:
            return False, f"event {i}: sequence gap/reorder (seq={ev.get('seq')})"
        if ev.get("prev") != prev:
            return False, f"event {i}: previous-hash link broken"
        if sha256_hex(canonical_json(body)) != claimed:
            return False, f"event {i}: content does not match its hash (modified)"
        prev = claimed
    return True, f"{len(events)} events, chain intact, head={prev[:16]}"
