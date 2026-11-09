"""Tests for the hardening pass: hostile test reports, cache integrity, git edge cases, module bans, doctor."""
import json
import os
import shutil
import subprocess

import pytest

from reposhield import gitutil
from reposhield.analyzer import MAX_PARSE_BYTES, parse_source
from reposhield.audit import verify_chain
from reposhield.cli import main
from reposhield.engine import MAX_REPORT_BYTES, VerifyOptions, load_test_report, verify
from reposhield.gitutil import Change, GitError
from reposhield.graph import Graph
from reposhield.policy import EvalContext, evaluate_policies, load_config
from tests.test_analyzer_graph import build

ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def sh(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=ENV)


# ---------- the sandbox's test report is hostile input ----------
def write_report(tmp_path, payload, raw=None):
    d = tmp_path / ".reposhield" / "out"; d.mkdir(parents=True, exist_ok=True)
    p = d / "results.json"
    p.write_text(raw if raw is not None else json.dumps(payload))
    return str(p)


GOOD = {"tests": {"tests/a.py::t": {"outcome": "passed", "duration": 0.1}}, "collect_errors": [], "exitstatus": 0}


def test_valid_report_is_accepted(tmp_path):
    assert load_test_report(write_report(tmp_path, GOOD), str(tmp_path))["exitstatus"] == 0


@pytest.mark.parametrize("bad", [
    [], "str", {"tests": []}, {"tests": {}, "collect_errors": {}, "exitstatus": 0},
    {"tests": {}, "collect_errors": [], "exitstatus": "0"}, {"tests": {}, "collect_errors": [], "exitstatus": True},
    {"tests": {"x": {"outcome": "totally-passed"}}, "collect_errors": [], "exitstatus": 0},
    {"tests": {"x": "passed"}, "collect_errors": [], "exitstatus": 0},
])
def test_malformed_report_is_rejected(tmp_path, bad):
    assert load_test_report(write_report(tmp_path, bad), str(tmp_path)) is None


def test_garbage_oversized_and_missing_reports_are_rejected(tmp_path):
    assert load_test_report(write_report(tmp_path, None, raw="{not json"), str(tmp_path)) is None
    assert load_test_report(write_report(tmp_path, None, raw=" " * (MAX_REPORT_BYTES + 1)), str(tmp_path)) is None
    assert load_test_report(str(tmp_path / "nope.json"), str(tmp_path)) is None


def test_symlinked_report_is_rejected(tmp_path):
    secret = tmp_path / "outside.json"; secret.write_text(json.dumps(GOOD))
    ws = tmp_path / "ws"; (ws / ".reposhield" / "out").mkdir(parents=True)
    link = ws / ".reposhield" / "out" / "results.json"
    try:
        os.symlink(secret, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this platform")
    assert load_test_report(str(link), str(ws)) is None


# ---------- unsigned persisted gate results are never reused ----------
def test_tampered_cached_run_is_recomputed_not_trusted(demo_repo):
    o = VerifyOptions(repo=demo_repo, base="main", head="pr/docs-only", sandbox="subprocess")
    a = verify(VerifyOptions(**{**o.__dict__, "force": True}))
    fresh = verify(o)
    assert fresh["cached"] is False and fresh["run_dir"] != a["run_dir"]
    p = os.path.join(a["run_dir"], "events.jsonl")
    lines = open(p).read().splitlines()
    ev = json.loads(lines[1]); ev["data"]["source"] = "forged"; lines[1] = json.dumps(ev, sort_keys=True)
    open(p, "w").write("\n".join(lines) + "\n")
    b = verify(o)
    assert b["cached"] is False and verify_chain(os.path.join(b["run_dir"], "events.jsonl"))[0]


def test_cached_result_still_reports_where_its_report_lives(demo_repo):
    o = VerifyOptions(repo=demo_repo, base="main", head="pr/docs-only", sandbox="subprocess")
    verify(VerifyOptions(**{**o.__dict__, "force": True}))
    assert os.path.exists(os.path.join(verify(o)["run_dir"], "report.html"))


# ---------- git edge cases ----------
def test_shallow_clone_gives_actionable_error(demo_repo, tmp_path):
    clone = str(tmp_path / "shallow")
    subprocess.run(["git", "clone", "-q", "--depth=1", "--no-single-branch", "file://" + demo_repo.replace("\\", "/"), clone],
                   check=True, capture_output=True, env=ENV)
    with pytest.raises(GitError, match="shallow|fetch full history"):
        verify(VerifyOptions(repo=clone, base="main", head="origin/pr/safe-refactor", sandbox="subprocess", run_tests=False))


def test_no_changes_passes_cleanly(demo_repo):
    r = verify(VerifyOptions(repo=demo_repo, base="main", head="main", sandbox="subprocess", force=True))
    assert r["verdict"] == "PASS" and r["plan"]["mode"] == "NONE" and r["changes"] == []


def test_filenames_with_spaces_and_unicode_are_handled(tmp_path):
    repo = str(tmp_path / "r"); os.makedirs(repo)
    sh(repo, "init", "-q", "-b", "main")
    open(os.path.join(repo, "a.py"), "w").write("x = 1\n")
    sh(repo, "add", "-A"); sh(repo, "commit", "-q", "-m", "base")
    sh(repo, "checkout", "-q", "-b", "feat")
    for name in ("my file.py", "ünï.py"):
        open(os.path.join(repo, name), "w", encoding="utf-8").write("key = 'AKIAIOSFODNN7EXAMPLE'\n")
    sh(repo, "add", "-A"); sh(repo, "commit", "-q", "-m", "feat")
    added = gitutil.diff_added_lines(repo, "main", "feat")
    assert set(added) == {"my file.py", "ünï.py"} and added["my file.py"][0][0] == 1
    changes = {c.path for c in gitutil.diff_changes(repo, "main", "feat")}
    assert changes == {"my file.py", "ünï.py"}
    r = verify(VerifyOptions(repo=repo, base="main", head="feat", sandbox="subprocess", run_tests=False, force=True))
    assert r["verdict"] == "BLOCK" and any(f["rule_id"] == "secret-scan" and f["result"] == "FAIL" for f in r["findings"])


def test_c_style_quoted_paths_are_decoded():
    assert gitutil.unquote_c('"a\\"b\\\\c\\td"') == 'a"b\\c\td'
    assert gitutil.unquote_c('"\\303\\274.py"') == "ü.py"


# ---------- analyzer limits ----------
def test_huge_and_pathological_sources_do_not_crash_analysis():
    big = parse_source("big.py", b"x = 1\n" * (MAX_PARSE_BYTES // 6 + 10), "c")
    assert not big.ok and big.error.startswith("skipped")
    deep = parse_source("deep.py", ("(" * 5000 + "1" + ")" * 5000).encode(), "c")
    assert not deep.ok                                   # SyntaxError / RecursionError caught, never raised


def test_oversized_changed_file_is_unknown_not_pass_or_syntax_error(tmp_path):
    from reposhield.checks import syntax_check
    g = Graph(); g.files["big.py"] = parse_source("big.py", b"x=1\n" * (MAX_PARSE_BYTES // 4 + 10), "c")
    assert syntax_check(g, [Change("M", "big.py")]).result == "UNKNOWN"


# ---------- forbidden_import with module names ----------
CFG = load_config("""
version: 1
policies:
  - id: no-http
    severity: critical
    rules:
      - {type: forbidden_import, from: "pay/**", modules: [requests, "boto3.*"]}
""")[0]


def test_module_ban_flags_new_imports_only(tmp_path):
    base = build(tmp_path / "b", {"pay/a.py": "import requests\n", "pay/b.py": "x = 1\n"})
    head = build(tmp_path / "h", {"pay/a.py": "import requests\n", "pay/b.py": "from boto3.session import Session\nimport requests.adapters\n"})
    out = evaluate_policies(CFG, EvalContext([Change("M", "pay/b.py")], head, base, {}, {}))
    f = out.findings[0]
    assert f.result == "FAIL"
    assert {e["file"] for e in f.evidence} == {"pay/b.py"}          # pay/a.py's old import is pre-existing
    assert {e["target"] for e in f.evidence} == {"boto3.session", "requests.adapters"}


def test_module_ban_ignores_lookalikes_and_other_packages(tmp_path):
    g = build(tmp_path, {"pay/a.py": "import requests_toolbelt\nimport json\n", "other/x.py": "import requests\n"})
    out = evaluate_policies(CFG, EvalContext([Change("M", "pay/a.py")], g, g.clone(), {}, {}))
    assert out.findings[0].result == "PASS"


# ---------- doctor ----------
def test_doctor_runs_and_proves_isolation_properties(capsys):
    rc = main(["doctor", "--sandbox", "subprocess"])
    out = capsys.readouterr().out
    assert rc == 0
    for needle in ("host secrets hidden", "timeout kills runaway tests", "output flood is capped", "Security boundary: NO"):
        assert needle in out


# ---------------------------------------------------------------- presentation layer
def test_impact_map_draws_violation_path_changed_tag_and_test_badges(run):
    from reposhield.report import graph_svg
    svg = graph_svg(run("pr/transitive-leak"))
    assert svg.startswith("<svg") and 'class="e vi"' in svg and "CHANGED" in svg and "test" in svg
    assert "payments/" in svg and "analytics/" in svg and 'marker-end="url(#arv)"' in svg
    assert "<script" not in svg and "http://" not in svg.replace("http://www.w3.org/2000/svg", "")


def test_impact_map_is_skipped_when_there_is_nothing_to_draw(run):
    from reposhield.report import graph_svg
    assert graph_svg(run("pr/docs-only")) == ""


def test_report_html_has_plain_english_meaning_tiles_and_map(run):
    r = run("pr/transitive-leak")
    page = open(os.path.join(r["run_dir"], "report.html"), encoding="utf-8").read()
    assert "Do not merge" in page and "Impact map" in page and "file changed" in page and "<svg" in page


def test_gallery_summarises_all_scenarios_and_escapes_content(run):
    from reposhield.report import gallery_html
    rows = [{"branch": b, "story": "<b>x</b>", "expected": "-", "result": run(b), "report_uri": "file:///r.html"}
            for b in ("pr/safe-refactor", "pr/analytics-leak", "pr/weakened-tests")]
    page = gallery_html(rows, "9.9")
    assert "pr/analytics-leak" in page and "blocked before merge" in page and "sent to a human" in page
    assert "<b>x</b>" not in page and "&lt;b&gt;x&lt;/b&gt;" in page and "v9.9" in page
