from __future__ import annotations

import json
import logging
import os
import threading
import time

from ..engine import VerifyOptions, verify
from ..report import markdown
from .config import ServerConfig
from .db import Store
from .github import DESCRIPTION, STATE, GitHubClient, git_sync

log = logging.getLogger("reposhield.server")


def _defang(text: str) -> str:
    """Repo-controlled strings end up in PR comments: neutralise @mentions so a path name cannot ping people."""
    return text.replace("@", "@\u200b")


class Worker:
    def __init__(self, cfg: ServerConfig, store: Store, github: GitHubClient):
        self.cfg, self.store, self.github = cfg, store, github
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    # ---- lifecycle ----
    def start(self) -> None:
        n = self.store.recover_interrupted()
        if n:
            log.warning("re-queued %d interrupted run(s)", n)
        for i in range(max(1, self.cfg.workers)):
            t = threading.Thread(target=self._loop, name=f"rs-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            job = self.store.claim_next()
            if job is None:
                time.sleep(0.5)
                continue
            self._process(job)

    def run_pending(self) -> int:
        """Process every queued job in the calling thread (used by tests and one-shot tools)."""
        n = 0
        while (job := self.store.claim_next()) is not None:
            self._process(job)
            n += 1
        return n

    def _lock(self, key: str) -> threading.Lock:
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    # ---- one job ----
    def _target_url(self, rid: str) -> str | None:
        return f"{self.cfg.public_url.rstrip('/')}/runs/{rid}" if self.cfg.public_url else None

    def _process(self, job: dict) -> None:
        rid, meta = job["id"], json.loads(job.get("meta") or "{}")
        is_gh = job["source"] == "github"
        try:
            if is_gh:
                with self._lock(job["repo"]):
                    path = git_sync(self.cfg.repos_dir, job["repo"], meta["clone_url"], job["pr_number"],
                                    meta["base_ref"], self.cfg.github_token)
                    result = verify(VerifyOptions(repo=path, base=f"refs/heads/{meta['base_ref']}", head=meta["head_sha"],
                                                  sandbox=self.cfg.sandbox, require_tests=True, untrusted_code=True,
                                                  allow_insecure_sandbox=self.cfg.insecure_dev_sandbox))
            else:
                with self._lock(job["repo_path"]):
                    result = verify(VerifyOptions(repo=job["repo_path"], base=job["base"] or None, head=job["head"] or "HEAD",
                                                  sandbox=self.cfg.sandbox, force=bool(meta.get("force"))))
            self.store.finish(rid, verdict=result["verdict"], summary=result["summary"], run_id=result["run_id"],
                              run_dir=result["run_dir"], tests=result["tests"])
            if is_gh:
                self._report(job, meta, result)
        except Exception as e:                                   # a failed run must be visible, never silently green
            log.exception("run %s failed", rid)
            self.store.fail(rid, f"{type(e).__name__}: {e}")
            if is_gh:
                self._safe(self.github.set_status, job["repo"], meta["head_sha"], "error", "RepoShield could not verify this change",
                           self._target_url(rid))

    def _report(self, job: dict, meta: dict, result: dict) -> None:
        v = result["verdict"]
        self._safe(self.github.set_status, job["repo"], meta["head_sha"], STATE[v], DESCRIPTION[v], self._target_url(job["id"]))
        self._safe(self.github.upsert_comment, job["repo"], job["pr_number"], _defang(markdown(result)))

    @staticmethod
    def _safe(fn, *args):
        try:
            return fn(*args)
        except Exception:                                        # reporting problems must not change the stored verdict
            log.exception("GitHub reporting failed")
            return None
