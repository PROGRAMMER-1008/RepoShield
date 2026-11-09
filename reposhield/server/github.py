"""GitHub integration: webhook signature check, payload parsing, commit status + PR comment reporting.

Uses commit statuses and issue comments (work with a fine-grained token). Check Runs need a GitHub *App*
installation token - that is the next step, see docs/ROADMAP.md.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import subprocess
import urllib.error
import urllib.request

MARKER = "<!-- reposhield-report -->"
HANDLED_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}
STATE = {"PASS": "success", "BLOCK": "failure", "REVIEW_REQUIRED": "failure"}
DESCRIPTION = {"PASS": "All checks passed", "BLOCK": "Blocked by policy or failing tests", "REVIEW_REQUIRED": "Human review required"}
_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


def verify_signature(secret: str | None, body: bytes, header: str | None) -> bool:
    """Constant-time check of GitHub's `X-Hub-Signature-256`. A missing secret or header is always a rejection."""
    if not secret or not header or not header.startswith("sha256="):
        return False
    expect = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expect, header[7:])


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def parse_pull_request(payload: dict) -> dict | None:
    """Return the fields we need, or None if the event is not one we act on / is malformed."""
    if payload.get("action") not in HANDLED_ACTIONS:
        return None
    try:
        pr, repo = payload["pull_request"], payload["repository"]
        out = {"repo": repo["full_name"], "clone_url": repo["clone_url"], "pr_number": int(pr["number"]),
               "head_sha": pr["head"]["sha"], "base_ref": pr["base"]["ref"], "html_url": pr.get("html_url", "")}
    except (KeyError, TypeError, ValueError):
        return None
    if not _NAME.match(out["repo"]) or not re.fullmatch(r"[0-9a-f]{40}", out["head_sha"]) \
            or not re.fullmatch(r"[A-Za-z0-9_./-]+", out["base_ref"]) or ".." in out["base_ref"]:
        return None
    return out


def repo_allowed(allowed: list, full_name: str) -> bool:
    return "*" in allowed or full_name in allowed


def _redact(text: str, token: str | None) -> str:
    return text.replace(token, "***") if token else text


def git_sync(repos_dir: str, repo: str, clone_url: str, pr_number: int, base_ref: str, token: str | None = None) -> str:
    """Maintain a bare mirror of the repo and fetch the PR head (works for fork PRs via refs/pull/N/head)."""
    import os
    path = os.path.join(repos_dir, repo.replace("/", "__") + ".git")
    url = clone_url
    if token and url.startswith("https://"):
        url = url.replace("https://", f"https://x-access-token:{token}@", 1)
    os.makedirs(repos_dir, exist_ok=True)
    if not os.path.isdir(path):
        _git(["init", "--bare", "-q", path], token)
    _git(["-C", path, "fetch", "-q", "--no-tags", url,
          f"+refs/heads/{base_ref}:refs/heads/{base_ref}",
          f"+refs/pull/{pr_number}/head:refs/reposhield/pr-{pr_number}"], token)
    return path


def _git(args: list, token: str | None) -> None:
    p = subprocess.run(["git", *args], capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        raise RuntimeError("git failed: " + _redact(p.stderr.strip(), token)[:500])


class GitHubClient:
    """Minimal REST client. `transport(method, url, headers, body_bytes) -> (status, json)` is injectable for tests."""

    def __init__(self, token: str | None, transport=None, api: str = "https://api.github.com"):
        self.token, self.api, self.transport = token, api, transport or self._urllib

    @staticmethod
    def _urllib(method, url, headers, body):
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                raw = r.read()
                return r.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as e:
            return e.code, None

    def _call(self, method, path, payload=None):
        if not self.token:
            return None, None
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "reposhield", "Content-Type": "application/json"}
        return self.transport(method, f"{self.api}{path}", headers, json.dumps(payload).encode() if payload is not None else None)

    def set_status(self, repo: str, sha: str, state: str, description: str, target_url: str | None = None):
        body = {"state": state, "context": "reposhield", "description": description[:140]}
        if target_url:
            body["target_url"] = target_url
        return self._call("POST", f"/repos/{repo}/statuses/{sha}", body)

    def upsert_comment(self, repo: str, pr: int, markdown: str):
        body = {"body": f"{MARKER}\n{markdown}"}
        status, items = self._call("GET", f"/repos/{repo}/issues/{pr}/comments?per_page=100")
        for c in items or []:
            if MARKER in (c.get("body") or ""):
                return self._call("PATCH", f"/repos/{repo}/issues/comments/{c['id']}", body)
        return self._call("POST", f"/repos/{repo}/issues/{pr}/comments", body)
