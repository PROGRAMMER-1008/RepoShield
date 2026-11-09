"""Built-in deterministic checks (no LLM involved)."""
from __future__ import annotations

import re

from .gitutil import Change
from .graph import Graph
from .models import Finding
from .policy import POLICY_FILE
from .util import match_any

SECRET_PATTERNS = [
    ("aws-access-key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private-key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("github-token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("slack-token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("generic-secret", re.compile(r"(?i)(?:api[_-]?key|secret|passwd|password|token)\s*[:=]\s*['\"][^'\"\s]{12,}['\"]")),
]
DEP_FILES = ("requirements*.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile", "poetry.lock", "package.json")


def _redact(s: str) -> str:
    return s[:4] + "…" + f"[{len(s)} chars]"


def secret_scan(added: dict) -> Finding:
    ev = []
    for path, lines in added.items():
        for ln, text in lines:
            for name, rx in SECRET_PATTERNS:
                m = rx.search(text)
                if m:
                    ev.append({"file": path, "line": ln, "kind": name, "match": _redact(m.group(0))})
    if ev:
        return Finding("check", "secret-scan", "secrets", "FAIL", "critical",
                       f"possible secret introduced: {ev[0]['kind']} at {ev[0]['file']}:{ev[0]['line']}", ev)
    return Finding("check", "secret-scan", "secrets", "PASS", "critical", "no secrets in added lines")


def dependency_check(changes: list[Change], added: dict) -> Finding:
    hits = [c.path for c in changes if match_any(DEP_FILES, c.path)]
    if not hits:
        return Finding("check", "dependency-change", "dependencies", "NOT_APPLICABLE", "medium", "no dependency manifests changed")
    pkgs = []
    for p in hits:
        if p.endswith(".txt"):
            for ln, t in added.get(p, []):
                t = t.strip()
                if t and not t.startswith(("#", "-")):
                    pkgs.append({"file": p, "line": ln, "requirement": t})
    msg = "dependency manifest changed" + (f"; new/updated requirements: {', '.join(x['requirement'] for x in pkgs[:5])}" if pkgs else "")
    return Finding("check", "dependency-change", "dependencies", "REVIEW_REQUIRED", "medium", msg,
                   pkgs or [{"file": p} for p in hits])


def policy_tamper(changes: list[Change], policy_source: str) -> Finding | None:
    if any(c.path == POLICY_FILE for c in changes):
        return Finding("check", "policy-file-changed", "policy_tamper", "REVIEW_REQUIRED", "high",
                       f"{POLICY_FILE} was modified by this change; verification used the trusted policy from {policy_source}",
                       [{"file": POLICY_FILE}])
    return None


def syntax_check(head: Graph, changes: list[Change]) -> Finding:
    bad, skipped = [], []
    for c in changes:
        pf = head.files.get(c.path)
        if c.status == "D" or pf is None or pf.ok:
            continue
        (skipped if pf.error.startswith("skipped") else bad).append({"file": c.path, "error": pf.error})
    if bad:
        return Finding("check", "python-syntax", "analysis", "FAIL", "high", f"{len(bad)} changed file(s) do not parse", bad)
    if skipped:
        return Finding("check", "python-syntax", "analysis", "UNKNOWN", "high",
                       f"{len(skipped)} changed file(s) too large to analyse; dependency rules could not be verified for them", skipped)
    return Finding("check", "python-syntax", "analysis", "PASS", "high", "all changed Python files parse")


def test_integrity(head: Graph, base: Graph | None, changes: list[Change], mode: str) -> Finding | None:
    """AI agents frequently 'fix' failing tests by deleting or weakening them. Detect that."""
    if mode == "off" or base is None:
        return None
    ev = []
    for c in changes:
        b = base.files.get(c.path)
        if b is None or not b.is_test:
            continue
        if c.status == "D":
            ev.append({"file": c.path, "issue": f"test file deleted ({len(b.tests)} tests)"})
            continue
        h = head.files.get(c.path)
        if h is None:
            continue
        bt = {t.name: t for t in b.tests}
        ht = {t.name: t for t in h.tests}
        for name in sorted(set(bt) - set(ht)):
            ev.append({"file": c.path, "test": name, "issue": "test removed"})
        for name in sorted(set(bt) & set(ht)):
            if ht[name].asserts < bt[name].asserts:
                ev.append({"file": c.path, "test": name, "line": ht[name].line,
                           "issue": f"assertions reduced {bt[name].asserts} -> {ht[name].asserts}"})
            if ht[name].skipped and not bt[name].skipped:
                ev.append({"file": c.path, "test": name, "line": ht[name].line, "issue": "test newly skipped/xfail"})
    if not ev:
        return Finding("check", "test-integrity", "test_integrity", "PASS", "medium", "no tests removed, weakened or skipped")
    f = Finding("check", "test-integrity", "test_integrity", "FAIL", "medium",
                f"tests were weakened or removed ({len(ev)} issue(s)): {ev[0]['file']} - {ev[0]['issue']}", ev,
                on_fail="block" if mode == "block" else "review")
    return f
