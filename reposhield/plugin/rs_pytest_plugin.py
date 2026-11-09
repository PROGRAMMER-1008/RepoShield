"""Tiny pytest plugin injected into the sandbox run.

* writes per-test outcomes to $RS_RESULT_PATH as JSON (deterministic evidence, no log scraping)
* optionally tags coverage contexts with the pytest nodeid ($RS_COV_CONTEXT=1) for test->code maps
"""
import json
import os

import pytest

_tests = {}
_collect_errors = []


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):
    cov = None
    if os.environ.get("RS_COV_CONTEXT"):
        try:
            import coverage
            cov = coverage.Coverage.current()
        except Exception:
            cov = None
    if cov:
        cov.switch_context(item.nodeid)
    yield
    if cov:
        cov.switch_context("")


def pytest_runtest_logreport(report):
    rec = _tests.setdefault(report.nodeid, {"outcome": "incomplete", "duration": 0.0})
    rec["duration"] += getattr(report, "duration", 0.0)
    if report.failed:
        rec["outcome"] = "failed" if report.when == "call" else "error"
    elif report.skipped and rec["outcome"] not in ("failed", "error"):
        rec["outcome"] = "xfailed" if hasattr(report, "wasxfail") else "skipped"
    elif report.when == "call" and report.passed and rec["outcome"] == "incomplete":
        rec["outcome"] = "xpassed" if hasattr(report, "wasxfail") else "passed"


def pytest_collectreport(report):
    if report.failed:
        _collect_errors.append(str(report.nodeid))


def pytest_sessionfinish(session, exitstatus):
    path = os.environ.get("RS_RESULT_PATH")
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as fh:
        json.dump({"tests": _tests, "collect_errors": _collect_errors, "exitstatus": int(exitstatus)}, fh)
