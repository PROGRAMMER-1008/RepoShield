"""Separate, lease-fenced verification worker. No repository execution in RS2 03."""
from __future__ import annotations

import argparse
import os
import signal
import threading
import uuid

from ..engine import VerifyOptions, verify, _implementation_digest
from ..gitutil import resolve
from .durable import DurableStore, LeaseLost


class ProcessWorker:
    def __init__(self, store, worker_id=None, lease_seconds=30):
        self.store = store
        self.worker_id = worker_id or "worker_" + uuid.uuid4().hex
        self.lease_seconds = lease_seconds
        self.stop = threading.Event()

    def handle(self, claim):
        ctx = self.store.context(claim)
        inputs, outputs, path = ctx["inputs"], ctx["outputs"], ctx["repository_path"]
        stage = claim["stage"]
        if inputs["implementation_digest"] != _implementation_digest():
            raise RuntimeError("Coordinator implementation changed; submit a new logical run")
        if stage == "snapshot":
            for name in ("base_sha", "head_sha"):
                if resolve(path, inputs[name]) != inputs[name]:
                    raise RuntimeError("Snapshot revision mismatch")
            return {"base_sha": inputs["base_sha"], "head_sha": inputs["head_sha"],
                    "kind": "immutable-git-objects", "execution": "disabled"}
        if stage == "analyze":
            # Real diff/graph/policy/test planning. Deliberately cannot dispatch pytest.
            return verify(VerifyOptions(repo=path, base=outputs["snapshot"]["base_sha"],
                head=outputs["snapshot"]["head_sha"], sandbox="subprocess", run_tests=False,
                require_tests=True, untrusted_code=True))
        if stage == "tests":
            result = outputs["analyze"]
            return {"status": "NOT_NEEDED" if result["plan"]["mode"] == "NONE" else "NOT_RUN",
                    "reason": "restricted executor is unavailable until RS2 06", "executed": 0}
        if stage == "aggregate":
            result = outputs["analyze"]
            if result["plan"]["mode"] != "NONE" and result["verdict"] == "PASS":
                raise RuntimeError("Missing test evidence cannot yield PASS")
            return {**result, "coordinator_attempt_id": claim["attempt_id"],
                    "execution_availability": outputs["tests"]}
        if stage == "publish":
            # complete() atomically stores the real aggregate and durable publication intent.
            # Delivery to GitHub is RS2 09; enqueueing is not claimed as publication.
            return {"delivery": "pending", "kind": "verification.completed"}
        raise ValueError("Unknown stage")

    def run_once(self):
        self.store.recover_expired()
        claim = self.store.claim(self.worker_id, self.lease_seconds)
        if claim is None:
            return False
        done, lost = threading.Event(), threading.Event()

        def renew():
            while not done.wait(max(0.2, self.lease_seconds / 3)):
                try:
                    self.store.heartbeat(claim, self.lease_seconds)
                except Exception:
                    lost.set()
                    return

        pulse = threading.Thread(target=renew, daemon=True)
        pulse.start()
        try:
            output = self.handle(claim)
            if not lost.is_set():
                self.store.complete(claim, output)
        except LeaseLost:
            pass  # a newer lease owns finalization; never publish stale output
        except Exception as exc:
            if not lost.is_set():
                try:
                    self.store.fail(claim, type(exc).__name__)
                except LeaseLost:
                    pass
        finally:
            done.set()
            pulse.join(timeout=5)
        return True

    def run(self, once=False):
        while not self.stop.is_set():
            worked = self.run_once()
            if once:
                return
            if not worked:
                self.stop.wait(0.5)


def main(argv=None):
    parser = argparse.ArgumentParser(description="RepoShield PostgreSQL verification worker (static stages only)")
    parser.add_argument("--once", action="store_true", help="claim at most one ready task")
    args = parser.parse_args(argv)
    url = os.environ.get("REPOSHIELD_DATABASE_URL", "")
    store = DurableStore(url)
    store.check_schema()
    worker = ProcessWorker(store)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: worker.stop.set())
    try:
        worker.run(args.once)
    finally:
        store.engine.dispose()


if __name__ == "__main__":
    main()
