"""RS2 regressions: real pytest observations, untrusted caches and attempt isolation."""
import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from reposhield import coverage_map
from reposhield.contracts import ActionRequest, VerificationReceipt
from reposhield.engine import (VerifyOptions, _finalize_required, _test_findings,
                               load_test_report, verify)
from reposhield.models import Finding
from reposhield.policy import RequiredTest
from reposhield.sandbox import Limits, SandboxResult, SubprocessSandbox
from reposhield.selector import TestPlan as Plan, SelectedTest
from reposhield.verdict import aggregate


def required_result(report, ran=True, on_fail=None):
    findings = [Finding("policy", "mandatory", "required_test", "PENDING", "low", on_fail=on_fail)]
    _finalize_required(findings, [RequiredTest("mandatory", "low", on_fail, [], ["test_a.py"])], report, ran)
    return findings


@pytest.mark.parametrize("body,expected", [
    ("def test_a():\n    assert True\n", "PASS"),
    ("import pytest\n@pytest.mark.skip\ndef test_a(): pass\n", "REVIEW_REQUIRED"),
    ("import pytest\n@pytest.mark.xfail\ndef test_a(): assert False\n", "REVIEW_REQUIRED"),
    ("import pytest\n@pytest.mark.xfail\ndef test_a(): pass\n", "REVIEW_REQUIRED"),
    ("import pytest\n@pytest.mark.xfail(strict=True)\ndef test_a(): pass\n", "BLOCK"),
    ("# Empty file\n", "REVIEW_REQUIRED"),
    ("import pytest\npytest.skip('module skip', allow_module_level=True)\n", "REVIEW_REQUIRED"),
    ("def test_a(): assert True\nimport pytest\n@pytest.mark.skip\ndef test_b(): pass\n", "PASS"),
    ("import pytest\n@pytest.fixture\ndef broken(): raise RuntimeError('setup')\ndef test_a(broken): pass\n", "BLOCK"),
    ("import pytest\n@pytest.fixture\ndef broken():\n    yield\n    raise RuntimeError('teardown')\ndef test_a(broken): pass\n", "BLOCK"),
])
def test_real_pytest_required_evidence(tmp_path, body, expected):
    (tmp_path / "test_a.py").write_text(body)
    coverage_map.install_plugin(str(tmp_path))
    result = SubprocessSandbox().run(
        [sys.executable, "-m", "pytest", "--rootdir=.", "test_a.py", "-q", "-p", "no:cacheprovider", "-p", "rs_pytest_plugin"],
        str(tmp_path), env={"RS_RESULT_PATH": ".reposhield/out/results.json"}, limits=Limits())
    report = load_test_report(str(tmp_path / ".reposhield/out/results.json"), str(tmp_path))
    assert report is not None
    findings = required_result(report)
    plan = Plan("FULL", "safe", [SelectedTest("test_a.py", "HIGH")], 1, [], [], True)
    run_findings, _ = _test_findings(result, report, plan, Limits())
    assert aggregate(findings + run_findings)[0] == expected


@pytest.mark.parametrize("report,ran", [(None, True), (None, False), ({"tests": {}}, True),
    ({"tests": {"test_a.py::test_a": {"outcome": "skipped"}}}, True)])
def test_missing_mandatory_evidence_cannot_be_downgraded_to_info(report, ran):
    assert aggregate(required_result(report, ran, "info"))[0] != "PASS"


def test_pending_evidence_never_passes():
    assert aggregate([Finding("policy", "r", "required_test", "PENDING")])[0] == "REVIEW_REQUIRED"


@pytest.mark.parametrize("exit_code", [1, 2, 3, 4, 5, None])
def test_abnormal_exit_cannot_pass_with_positive_report(exit_code):
    report = {"tests": {"test_a.py::test_a": {"outcome": "passed"}}, "collect_errors": [], "exitstatus": exit_code}
    plan = Plan("FULL", "safe", [SelectedTest("test_a.py", "HIGH")], 1, [], [], True)
    findings, _ = _test_findings(SandboxResult(exit_code, "", "", 1), report, plan, Limits())
    assert aggregate(findings)[0] != "PASS"


def test_selected_file_omitted_by_pytest_cannot_pass():
    report = {"tests": {"test_a.py::test_a": {"outcome": "passed"}}, "collect_errors": [], "exitstatus": 0}
    plan = Plan("IMPACTED", "safe", [SelectedTest("test_a.py", "HIGH"), SelectedTest("test_b.py", "HIGH")], 2, [], [])
    findings, _ = _test_findings(SandboxResult(0, "", "", 1), report, plan, Limits())
    assert aggregate(findings)[0] != "PASS"


def test_setup_without_completed_call_cannot_hide_behind_a_pass():
    report = {"tests": {"test_a.py::test_a": {"outcome": "passed"},
                        "test_a.py::test_b": {"outcome": "incomplete"}}, "collect_errors": [], "exitstatus": 0}
    plan = Plan("FULL", "safe", [SelectedTest("test_a.py", "HIGH")], 1, [], [], True)
    findings, _ = _test_findings(SandboxResult(0, "", "", 1), report, plan, Limits())
    assert aggregate(findings)[0] == "REVIEW_REQUIRED"


@pytest.mark.parametrize("tamper", ["result", "truncate", "replace"])
def test_gate_never_reuses_unsigned_artifacts(demo_repo, tamper):
    opts = VerifyOptions(repo=demo_repo, base="main", head="pr/analytics-leak", sandbox="subprocess")
    first = verify(opts)
    directory = Path(first["run_dir"])
    if tamper == "result":
        payload = json.loads((directory / "result.json").read_text())
        payload["verdict"] = "PASS"
        (directory / "result.json").write_text(json.dumps(payload))
    elif tamper == "truncate":
        lines = (directory / "events.jsonl").read_text().splitlines()
        (directory / "events.jsonl").write_text(lines[0] + "\n")
    else:
        other = verify(replace(opts, head="pr/docs-only"))
        for name in ("result.json", "events.jsonl"):
            (directory / name).write_bytes((Path(other["run_dir"]) / name).read_bytes())
    before = (directory / "result.json").read_bytes()
    second = verify(opts)
    assert second["verdict"] == "BLOCK" and not second["cached"]
    assert first["run_id"] == second["run_id"]
    assert first["attempt_id"] != second["attempt_id"]
    assert (directory / "result.json").read_bytes() == before


def test_concurrent_equivalent_attempts_preserve_each_other(demo_repo):
    opts = VerifyOptions(repo=demo_repo, base="main", head="pr/safe-refactor", sandbox="subprocess")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: verify(opts), range(2)))
    assert results[0]["run_id"] == results[1]["run_id"]
    assert results[0]["run_dir"] != results[1]["run_dir"]
    for r in results:
        assert r["verdict"] == "PASS"
        assert json.loads((Path(r["run_dir"]) / "result.json").read_text())["attempt_id"] == r["attempt_id"]


@pytest.mark.parametrize("option", ["require_tests", "untrusted_code", "allow_insecure_sandbox", "trust_head_policy"])
def test_assurance_options_change_identity(demo_repo, option):
    opts = VerifyOptions(repo=demo_repo, base="main", head="pr/docs-only", sandbox="subprocess")
    a = verify(opts)
    b = verify(replace(opts, **{option: True}))
    assert a["run_id"] != b["run_id"] and not b["cached"]


def test_stricter_request_cannot_reuse_local_pass(demo_repo):
    opts = VerifyOptions(repo=demo_repo, base="main", head="pr/safe-refactor", sandbox="subprocess")
    assert verify(opts)["verdict"] == "PASS"
    r = verify(replace(opts, untrusted_code=True, require_tests=True))
    assert r["verdict"] != "PASS" and not r["cached"]


def test_action_contract_rejects_authority_injection():
    request = dict(schema_version=2, tenant_id="t", repository_id="r", session_id="s",
                   workspace_revision="sha256:" + "a" * 64,
                   action={"action_type": "RUN_TESTS", "test_paths": ["test_a.py"], "profile": "pytest"})
    assert ActionRequest.model_validate(request).action.profile == "pytest"
    for changes in ({"schema_version": 99}, {"approved": True}, {"policy": {}},
                    {"action": {"action_type": "SHELL", "argv": ["sh"]}}):
        with pytest.raises(ValidationError):
            ActionRequest.model_validate({**request, **changes})


def test_infrastructure_failure_cannot_have_pass_receipt():
    with pytest.raises(ValidationError):
        VerificationReceipt(schema_version=2, run_id="r", attempt_id="a", input_digest="a" * 64,
                            verdict="PASS", execution_state="failed-infrastructure", mode="VERIFICATION ONLY")


def test_unsigned_analysis_cache_cannot_erase_dependency_violation(demo_repo):
    from reposhield import ANALYZER_VERSION
    from reposhield.analyzer import ParseCache
    from reposhield.engine import state_dir_for
    from reposhield.gitutil import GitTree, resolve
    from reposhield.graph import Graph
    state = Path(state_dir_for(demo_repo))
    (state / "cache").mkdir(parents=True, exist_ok=True)
    base = resolve(demo_repo, "main")
    cache = ParseCache()
    graph = Graph.build(GitTree(demo_repo, base), cache)
    # A structurally valid, correctly versioned cache with false dependency data.
    # Removing payment imports hides its transitive route through common/money.py.
    for path, parsed in graph.files.items():
        if path.startswith("payments/"):
            parsed.imports = []
            cache.data[f"{parsed.cid}:0"] = parsed.payload()
    (state / "cache" / f"graph-{base}.json").write_text(
        json.dumps({"analyzer": ANALYZER_VERSION, "graph": graph.to_dict()}))
    (state / "parse_cache.json").write_text(json.dumps({"v": ANALYZER_VERSION, "entries": cache.data}))
    r = verify(VerifyOptions(repo=demo_repo, base="main", head="pr/transitive-leak", sandbox="subprocess"))
    assert r["verdict"] == "BLOCK" and not r["graph"]["base_graph_cached"]


@pytest.mark.parametrize("section,key,value", [
    ("sandbox", "image", "runner@sha256:" + "a" * 64),
    ("sandbox", "network", True), ("sandbox", "memory_mb", 512),
    ("verification", "test_command", ["python", "-m", "pytest", "-x"]),
    ("verification", "timeout_seconds", 42),
])
def test_runner_and_evidence_configuration_changes_fingerprint(section, key, value):
    from reposhield.engine import _input_context
    from reposhield.policy import load_config
    from reposhield.util import canonical_json
    cfg, errors = load_config("version: 1")
    def context():
        return _input_context(VerifyOptions(), ".", "head", "base", "merge", cfg,
                              "version: 1", "base:base", errors, SubprocessSandbox(), "safe")
    before = canonical_json(context())
    cfg[section][key] = value
    assert canonical_json(context()) != before
    if key == "image":
        assert context()["runner_image_digest"] == "sha256:" + "a" * 64


def test_legacy_gateway_cannot_execute_new_action_schema(tmp_path):
    from reposhield import actions
    from reposhield.policy import load_config
    cfg, _ = load_config("version: 1\nactions:\n  allow: ['pytest *']")
    action = actions.canonical_action("pytest test_a.py")
    for changes in ({"schema_version": 2}, {"type": "DATABASE_OPERATION"}):
        with pytest.raises(actions.Denied, match="schema or type"):
            actions.authorize({**action, **changes}, cfg, "policy", b"k" * 32, str(tmp_path))


def test_fingerprint_binds_environment_policy_without_disclosing_values(monkeypatch):
    from reposhield.engine import _input_context
    from reposhield.policy import load_config
    cfg, errors = load_config("version: 1")
    def context():
        return _input_context(VerifyOptions(), ".", "head", "base", "merge", cfg,
                              "version: 1", "base:base", errors, SubprocessSandbox(), "safe")
    before = context()
    monkeypatch.setenv("PATH", "sensitive-local-path")
    after = context()
    if os.name == "nt":
        assert before["environment_policy"] != after["environment_policy"]
    assert "sensitive-local-path" not in json.dumps(after)
