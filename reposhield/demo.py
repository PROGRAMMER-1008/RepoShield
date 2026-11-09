"""Builds a demo git repository: a healthy `main` plus branches that mimic typical AI-agent pull requests."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys

DATA = os.path.join(os.path.dirname(__file__), "demo_data", "main")
ENV = {"GIT_AUTHOR_NAME": "dev", "GIT_AUTHOR_EMAIL": "dev@example.com",
       "GIT_COMMITTER_NAME": "dev", "GIT_COMMITTER_EMAIL": "dev@example.com"}


def _git(path, *args):
    subprocess.run(["git", "-C", path, *args], check=True, capture_output=True, env={**os.environ, **ENV})


def _read(root, rel):
    with open(os.path.join(root, rel), encoding="utf-8") as fh:
        return fh.read()


def _write(root, rel, text):
    full = os.path.join(root, rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write(text)


def _sub(root, rel, old, new):
    text = _read(root, rel)
    assert old in text, f"{rel}: pattern not found: {old!r}"
    _write(root, rel, text.replace(old, new, 1))


def safe_refactor(r):
    _sub(r, "payments/refund.py", "    payment = service.payments[payment_id]\n",
         "    if payment_id not in service.payments:\n        raise KeyError(f\"unknown payment {payment_id}\")\n    payment = service.payments[payment_id]\n")


def analytics_leak(r):
    _sub(r, "payments/refund.py", "from common.money import to_cents\n", "from analytics.client import track\nfrom common.money import to_cents\n")
    _sub(r, "payments/refund.py", "    return cents\n", "    track(\"refund\", payment=payment_id, cents=cents)\n    return cents\n")


def transitive_leak(r):
    _sub(r, "common/money.py", "def to_cents", "from analytics.client import track\n\n\ndef to_cents")
    _sub(r, "common/money.py", "    return int(cents)\n", "    track(\"to_cents\", cents=cents)\n    return int(cents)\n")


def secret_and_workflow(r):
    _sub(r, "payments/service.py", "class PaymentService:", "AWS_KEY = \"AKIAIOSFODNN7EXAMPLE\"\n\n\nclass PaymentService:")
    _write(r, ".github/workflows/deploy.yml", "name: deploy\non: push\njobs:\n  d:\n    runs-on: ubuntu-latest\n    steps:\n      - run: ./deploy.sh\n")


def weakened_tests(r):
    # the 'agent' makes refunds unlimited, then silences the test that would have caught it
    _sub(r, "payments/refund.py", "    if cents > remaining:\n        raise ValueError(\"cannot refund more than the original charge\")\n", "")
    _sub(r, "tests/payments/test_refund.py", "def test_refund_cannot_exceed_original",
         "@pytest.mark.skip(reason=\"flaky\")\ndef test_refund_cannot_exceed_original")


def real_bug(r):
    _sub(r, "auth/tokens.py", "    if (now if now is not None else time.time()) > int(exp):\n        return None\n", "")


def policy_tamper(r):
    text = _read(r, ".reposhield.yml")
    start = text.index("  - id: payment-isolation")
    end = text.index("  - id: authentication-tests")
    _write(r, ".reposhield.yml", text[:start] + text[end:])
    analytics_leak(r)


def docs_only(r):
    _write(r, "README.md", _read(r, "README.md") + "\n## Usage\n\nRun `pytest`.\n")


def new_dependency(r):
    _write(r, "requirements.txt", _read(r, "requirements.txt") + "requests==2.32.3\n")


def prod_config(r):
    _write(r, "config/production/settings.yaml", "debug: false\nreplicas: 12\n")


SCENARIOS = {
    "pr/safe-refactor": (safe_refactor, "adds an input guard to payments/refund.py"),
    "pr/analytics-leak": (analytics_leak, "makes the payments package import analytics directly"),
    "pr/transitive-leak": (transitive_leak, "edits a shared helper (common/money) so it imports analytics - payments itself never changed"),
    "pr/secret-and-workflow": (secret_and_workflow, "hard-codes an AWS key and adds a new CI deploy workflow"),
    "pr/weakened-tests": (weakened_tests, "removes a safety check, then skips the one test that would catch it"),
    "pr/real-bug": (real_bug, "deletes the token-expiry check in authentication"),
    "pr/policy-tamper": (policy_tamper, "deletes the isolation rule from the policy file, then breaks that rule"),
    "pr/docs-only": (docs_only, "updates the README only"),
    "pr/new-dependency": (new_dependency, "adds a new third-party dependency"),
    "pr/prod-config": (prod_config, "touches production configuration"),
}


EXPECTED = {
    "pr/safe-refactor": "PASS", "pr/analytics-leak": "BLOCK", "pr/transitive-leak": "BLOCK",
    "pr/secret-and-workflow": "BLOCK", "pr/weakened-tests": "REVIEW_REQUIRED", "pr/real-bug": "BLOCK",
    "pr/policy-tamper": "BLOCK", "pr/docs-only": "PASS", "pr/new-dependency": "REVIEW_REQUIRED",
    "pr/prod-config": "REVIEW_REQUIRED",
}


def rmtree_force(path: str) -> None:
    """shutil.rmtree that also removes read-only files (git marks its objects read-only; Windows refuses to delete them)."""
    def _fix(func, p, _exc):
        os.chmod(p, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
        func(p)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_fix)
    else:
        shutil.rmtree(path, onerror=_fix)


def _looks_like_demo(path: str) -> bool:
    return (os.path.exists(os.path.join(path, ".git", "RS_DEMO"))
            or os.path.exists(os.path.join(path, "payments", "refund.py")) and os.path.exists(os.path.join(path, ".reposhield.yml")))


def build_demo(dest: str, force: bool = False) -> dict:
    dest = os.path.abspath(dest)
    if os.path.exists(dest) and os.listdir(dest):
        if not (force or _looks_like_demo(dest)):
            raise RuntimeError(f"{dest} exists and does not look like a RepoShield demo; "
                               "choose another folder or pass --force to replace it")
        if os.path.abspath(os.getcwd()).startswith(dest):
            raise RuntimeError(f"your terminal is inside {dest}; cd out of it first, then re-run")
        rmtree_force(dest)
    shutil.copytree(DATA, dest, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
    _git(dest, "init", "-q", "-b", "main")
    with open(os.path.join(dest, ".git", "RS_DEMO"), "w") as fh:
        fh.write("reposhield demo repository\n")
    _git(dest, "add", "-A")
    _git(dest, "commit", "-q", "-m", "initial commit")
    for branch, (fn, _) in SCENARIOS.items():
        _git(dest, "checkout", "-q", "-b", branch, "main")
        fn(dest)
        _git(dest, "add", "-A")
        _git(dest, "commit", "-q", "-m", f"agent: {branch}")
        _git(dest, "checkout", "-q", "main")
    return {"path": dest, "branches": {b: d for b, (_, d) in SCENARIOS.items()}}
