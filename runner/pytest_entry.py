"""Load the trusted observer before adding candidate/dependency import paths."""
import json
from pathlib import Path
import sys
import pytest


class Evidence:
    def __init__(self):
        self.files = {}

    def pytest_runtest_logreport(self, report):
        path = report.nodeid.split("::", 1)[0]
        counts = self.files.setdefault(path, {"passed": 0, "failed": 0})
        if report.failed:
            counts["failed"] += 1
        elif report.when == "call" and report.passed and not hasattr(report, "wasxfail"):
            counts["passed"] += 1

    def pytest_sessionfinish(self, session, exitstatus):
        Path("/work/observations.json").write_text(json.dumps(self.files))


sys.path[:0] = ["/work/deps", "/work/source"]
raise SystemExit(pytest.main(sys.argv[1:], plugins=[Evidence()]))
