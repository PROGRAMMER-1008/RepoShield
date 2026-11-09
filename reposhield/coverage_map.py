"""Baseline test->code map from runtime coverage (one coverage context per pytest nodeid)."""
from __future__ import annotations

import json
import os
import shutil
import sys

PLUGIN_SRC = os.path.join(os.path.dirname(__file__), "plugin", "rs_pytest_plugin.py")


def install_plugin(workspace: str) -> None:
    d = os.path.join(workspace, ".reposhield", "plugins")
    os.makedirs(d, exist_ok=True)
    shutil.copy(PLUGIN_SRC, os.path.join(d, "rs_pytest_plugin.py"))
    os.makedirs(os.path.join(workspace, ".reposhield", "out"), exist_ok=True)


def collect(workspace: str, sandbox, limits, test_command=None) -> dict | None:
    """Run the suite under coverage inside the sandbox; return {source_file: [test_file, ...]} or None."""
    install_plugin(workspace)
    data_file = ".reposhield/out/.coverage"
    argv = [sandbox.python, "-m", "coverage", "run", f"--data-file={data_file}", "--source=.",
            "--omit=.reposhield/*", "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "rs_pytest_plugin"]
    res = sandbox.run(argv, workspace, env={"RS_COV_CONTEXT": "1", "RS_RESULT_PATH": ".reposhield/out/baseline.json"},
                      limits=limits)
    full = os.path.join(workspace, data_file)
    if os.path.islink(full) or not os.path.isfile(full) or \
            not os.path.realpath(full).startswith(os.path.realpath(workspace) + os.sep):
        return None
    try:
        from coverage import CoverageData
    except ImportError:
        return None
    data = CoverageData(basename=full)
    data.read()
    mapping: dict[str, set] = {}
    root = os.path.realpath(workspace)
    for f in data.measured_files():
        rel = os.path.relpath(os.path.realpath(f), root).replace(os.sep, "/")
        if rel.startswith(".."):
            continue
        for _ln, ctxs in data.contexts_by_lineno(f).items():
            for c in ctxs:
                if c and "::" in c:
                    mapping.setdefault(rel, set()).add(c.split("::", 1)[0])
    return {k: sorted(v) for k, v in mapping.items()}


def save(path: str, mapping: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(mapping, fh, sort_keys=True)


def load(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None
