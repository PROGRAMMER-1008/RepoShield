"""SQLite job store (stdlib only). One short-lived connection per operation => safe across worker threads."""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id TEXT PRIMARY KEY, created REAL NOT NULL, started REAL, finished REAL,
  status TEXT NOT NULL,                       -- queued | running | done | error | superseded
  source TEXT NOT NULL,                       -- local | github
  repo TEXT NOT NULL, repo_path TEXT, base TEXT, head TEXT, pr_number INTEGER,
  verdict TEXT, summary TEXT, run_id TEXT, run_dir TEXT, tests TEXT, error TEXT, meta TEXT
);
CREATE INDEX IF NOT EXISTS runs_status ON runs(status, created);
CREATE INDEX IF NOT EXISTS runs_repo_pr ON runs(repo, pr_number);
CREATE TABLE IF NOT EXISTS deliveries (id TEXT PRIMARY KEY, received REAL NOT NULL);
"""


class Store:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self):
        c = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        try:
            yield c
        finally:
            c.close()

    # ---- creation / transitions ----
    def create_run(self, *, source: str, repo: str, base: str | None, head: str | None, repo_path: str | None = None,
                   pr_number: int | None = None, meta: dict | None = None, supersede: bool = True) -> str:
        rid = uuid.uuid4().hex[:12]
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            if supersede and pr_number is not None:                  # a new push to a PR obsoletes its queued runs
                c.execute("UPDATE runs SET status='superseded', finished=? WHERE repo=? AND pr_number=? AND status='queued'",
                          (time.time(), repo, pr_number))
            c.execute("INSERT INTO runs(id,created,status,source,repo,repo_path,base,head,pr_number,meta) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (rid, time.time(), "queued", source, repo, repo_path, base, head, pr_number, json.dumps(meta or {})))
            c.execute("COMMIT")
        return rid

    def claim_next(self) -> dict | None:
        with self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT * FROM runs WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
            if row is None:
                c.execute("COMMIT")
                return None
            c.execute("UPDATE runs SET status='running', started=? WHERE id=?", (time.time(), row["id"]))
            c.execute("COMMIT")
            return dict(row)

    def finish(self, rid: str, *, verdict: str, summary: str, run_id: str, run_dir: str, tests: dict) -> None:
        with self._conn() as c:
            c.execute("UPDATE runs SET status='done', finished=?, verdict=?, summary=?, run_id=?, run_dir=?, tests=? WHERE id=?",
                      (time.time(), verdict, summary, run_id, run_dir, json.dumps(tests), rid))

    def fail(self, rid: str, error: str) -> None:
        with self._conn() as c:
            c.execute("UPDATE runs SET status='error', finished=?, error=? WHERE id=?", (time.time(), error[:2000], rid))

    def recover_interrupted(self) -> int:
        """After a crash/restart, jobs stuck in 'running' go back to the queue."""
        with self._conn() as c:
            return c.execute("UPDATE runs SET status='queued', started=NULL WHERE status='running'").rowcount

    # ---- deliveries (webhook idempotency) ----
    def seen_delivery(self, delivery_id: str) -> bool:
        with self._conn() as c:
            try:
                c.execute("INSERT INTO deliveries(id, received) VALUES(?,?)", (delivery_id, time.time()))
                return False
            except sqlite3.IntegrityError:
                return True

    # ---- queries ----
    def get(self, rid: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM runs WHERE id=?", (rid,)).fetchone()
            return dict(row) if row else None

    def list(self, limit: int = 100, verdict: str | None = None, repo: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM runs WHERE 1=1", []
        if verdict:
            q += " AND verdict=?"; args.append(verdict)
        if repo:
            q += " AND repo=?"; args.append(repo)
        with self._conn() as c:
            return [dict(r) for r in c.execute(q + " ORDER BY created DESC LIMIT ?", (*args, limit)).fetchall()]

    def stats(self) -> dict:
        with self._conn() as c:
            out = {"total": 0, "PASS": 0, "BLOCK": 0, "REVIEW_REQUIRED": 0, "queued": 0, "running": 0, "error": 0}
            for r in c.execute("SELECT status, verdict, COUNT(*) n FROM runs GROUP BY status, verdict"):
                out["total"] += r["n"]
                if r["status"] == "done" and r["verdict"] in out:
                    out[r["verdict"]] += r["n"]
                elif r["status"] in out:
                    out[r["status"]] += r["n"]
            return out
