import json
import os

import pytest

from reposhield.audit import verify_chain
from reposhield.engine import VerifyOptions, verify

EXPECTED = {
    "pr/safe-refactor": "PASS",
    "pr/analytics-leak": "BLOCK",
    "pr/transitive-leak": "BLOCK",
    "pr/secret-and-workflow": "BLOCK",
    "pr/weakened-tests": "REVIEW_REQUIRED",
    "pr/real-bug": "BLOCK",
    "pr/policy-tamper": "BLOCK",
    "pr/docs-only": "PASS",
    "pr/new-dependency": "REVIEW_REQUIRED",
    "pr/prod-config": "REVIEW_REQUIRED",
}


@pytest.mark.parametrize("branch,verdict", EXPECTED.items())
def test_scenario_verdicts(run, branch, verdict):
    r = run(branch)
    assert r["verdict"] == verdict, r["summary"]
    ok, msg = verify_chain(os.path.join(r["run_dir"], "events.jsonl"))
    assert ok, msg


def test_safe_change_uses_selective_tests_and_incremental_graph(run):
    r = run("pr/safe-refactor")
    assert r["plan"]["mode"] == "IMPACTED" and r["plan"]["selected"] < r["plan"]["total"]
    assert r["graph"]["updated"] == 1 and r["graph"]["reparsed"] <= 1 and r["graph"]["mode"] == "incremental"
    assert r["tests"]["status"] == "RAN" and r["tests"]["failed"] == 0


def test_blocking_static_finding_skips_test_execution(run):
    r = run("pr/analytics-leak")
    assert r["tests"]["status"] == "NOT_RUN"
    r2 = run("pr/analytics-leak", always_run_tests=True)
    assert r2["tests"]["status"] == "RAN"


def test_real_regression_is_caught_by_sandboxed_tests(run):
    r = run("pr/real-bug")
    assert r["tests"]["failed"] >= 1
    assert any(f["rule_id"] == "authentication-tests" and f["result"] == "FAIL" for f in r["findings"])


def test_policy_is_read_from_base_so_agent_cannot_delete_it(run):
    r = run("pr/policy-tamper")
    ids = {f["rule_id"] for f in r["findings"] if f["effect"] == "BLOCK"}
    assert "payment-isolation" in ids and r["fingerprint"]["policy_source"].startswith("base:")
    assert any(f["rule_id"] == "policy-file-changed" for f in r["findings"])


def test_weakened_tests_flagged_even_though_all_tests_pass(run):
    r = run("pr/weakened-tests")
    assert r["tests"]["failed"] == 0 and r["verdict"] == "REVIEW_REQUIRED"
    assert any(f["rule_id"] == "test-integrity" and f["result"] == "FAIL" for f in r["findings"])


def test_secret_is_redacted_in_evidence(run):
    r = run("pr/secret-and-workflow")
    blob = json.dumps(r)
    assert "AKIAIOSFODNN7EXAMPLE" not in blob


def test_runs_are_idempotent_and_reproducible(demo_repo):
    o = VerifyOptions(repo=demo_repo, base="main", head="pr/safe-refactor", sandbox="subprocess", force=True)
    a = verify(o)
    o.force = False
    b = verify(o)
    assert not b["cached"] and a["run_id"] == b["run_id"] and a["verdict"] == b["verdict"]
    assert a["attempt_id"] != b["attempt_id"] and a["run_dir"] != b["run_dir"]
    assert os.path.exists(os.path.join(a["run_dir"], "result.json"))
    c = verify(VerifyOptions(repo=demo_repo, base="main", head="pr/analytics-leak", sandbox="subprocess"))
    assert c["run_id"] != a["run_id"]


def test_tampering_with_stored_audit_log_is_detected(run):
    r = run("pr/docs-only")
    p = os.path.join(r["run_dir"], "events.jsonl")
    text = open(p).read().replace("PASS", "FAIL", 1).replace('"verdict": "PASS"', '"verdict": "BLOCK"')
    lines = open(p).read().splitlines()
    ev = json.loads(lines[-2]); ev["data"]["verdict"] = "BLOCK"
    lines[-2] = json.dumps(ev, sort_keys=True)
    open(p, "w").write("\n".join(lines) + "\n")
    assert not verify_chain(p)[0]


def test_untrusted_head_policy_requires_review(demo_repo, tmp_path):
    import shutil, subprocess
    repo = str(tmp_path / "r")
    shutil.copytree(demo_repo, repo)
    env = {**os.environ, "GIT_AUTHOR_NAME": "a", "GIT_AUTHOR_EMAIL": "a@a", "GIT_COMMITTER_NAME": "a", "GIT_COMMITTER_EMAIL": "a@a"}
    sh = lambda *a: subprocess.run(["git", "-C", repo, *a], check=True, capture_output=True, env=env)
    sh("checkout", "-q", "-b", "nopolicy", "main")
    sh("rm", "-q", ".reposhield.yml"); sh("commit", "-q", "-m", "drop policy")
    sh("checkout", "-q", "-b", "addpolicy", "nopolicy")
    sh("checkout", "-q", "main", "--", ".reposhield.yml"); sh("commit", "-q", "-m", "add policy back")
    r = verify(VerifyOptions(repo=repo, base="nopolicy", head="addpolicy", sandbox="subprocess", force=True, run_tests=False))
    assert r["verdict"] == "REVIEW_REQUIRED"
    assert any(f["rule_id"] == "policy-introduced" for f in r["findings"])
