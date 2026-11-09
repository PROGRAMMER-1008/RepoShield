from reposhield.gitutil import Change, DirTree
from reposhield.graph import Graph
from reposhield.policy import EvalContext, evaluate_policies, load_config, validate
from reposhield.selector import select_tests
from tests.test_analyzer_graph import build, write


def test_validate_catches_bad_policies():
    errs = validate({"version": 1, "policies": [
        {"id": "a", "severity": "nope", "rules": [{"type": "forbidden_import", "from": "x"}]},
        {"id": "a", "rules": [{"type": "mystery"}]}]})
    text = " ".join(errs)
    assert "severity" in text and "needs 'to'" in text and "duplicate" in text and "unknown type" in text


def _cfg(extra=""):
    return load_config("""
version: 1
policies:
  - id: iso
    severity: critical
    rules:
      - {type: forbidden_import, from: "pay/**", to: "ana/**", transitive: true}
""" + extra)[0]


def test_preexisting_violation_is_not_blamed_on_the_change(tmp_path):
    files = {"pay/a.py": "import ana.x\n", "ana/x.py": ""}
    base = build(tmp_path, files)
    ctx = EvalContext([Change("M", "pay/a.py")], base.clone(), base, {}, {})
    out = evaluate_policies(_cfg(), ctx)
    assert out.findings[0].result == "PASS" and "pre-existing" in out.findings[0].message


def test_new_transitive_violation_has_path_evidence(tmp_path):
    base = build(tmp_path / "b", {"pay/a.py": "import util.u\n", "util/u.py": "", "ana/x.py": ""})
    head = build(tmp_path / "h", {"pay/a.py": "import util.u\n", "util/u.py": "import ana.x\n", "ana/x.py": ""})
    out = evaluate_policies(_cfg(), EvalContext([Change("M", "util/u.py")], head, base, {}, {}))
    f = out.findings[0]
    assert f.result == "FAIL" and f.evidence[0]["path"] == ["pay/a.py", "util/u.py", "ana/x.py"]


def test_new_dynamic_import_in_guarded_package_is_unknown_not_pass(tmp_path):
    base = build(tmp_path / "b", {"pay/a.py": "X=1\n", "ana/x.py": ""})
    head = build(tmp_path / "h", {"pay/a.py": "import importlib\nimportlib.import_module(name)\n", "ana/x.py": ""})
    out = evaluate_policies(_cfg(), EvalContext([Change("M", "pay/a.py")], head, base, {}, {}))
    assert any(f.result == "UNKNOWN" for f in out.findings)


def test_selector_static_superset_and_conservative_fallbacks(tmp_path):
    g = build(tmp_path, {
        "lib/core.py": "", "lib/mid.py": "import lib.core\n", "app.py": "import lib.mid\n", "orphan.py": "",
        "tests/test_core.py": "import lib.core\n", "tests/test_app.py": "import app\n", "tests/test_other.py": "X=1\n",
        "data.json": "{}",
    })
    plan = select_tests(g, g, [Change("M", "lib/core.py")])
    assert {t.path for t in plan.tests} == {"tests/test_core.py", "tests/test_app.py"}      # transitive via lib.mid -> app
    assert plan.mode == "IMPACTED"
    assert select_tests(g, g, [Change("M", "orphan.py")]).mode == "FULL"                   # no mapping => run everything
    assert select_tests(g, g, [Change("M", "data.json")]).mode == "FULL"                   # unknown file type => run everything
    assert select_tests(g, g, [Change("M", "README.md")], ignore_paths=["**/*.md"]).mode == "NONE"
    assert select_tests(g, g, [Change("M", "lib/core.py")], force_full=["policy"]).mode == "FULL"


def test_selector_deleted_module_selects_former_dependents(tmp_path):
    base = build(tmp_path / "b", {"lib.py": "", "tests/test_lib.py": "import lib\n", "tests/test_x.py": ""})
    head = base.clone()
    head.files.pop("lib.py")
    head._rebuild()
    plan = select_tests(head, base, [Change("D", "lib.py")])
    assert [t.path for t in plan.tests] == ["tests/test_lib.py"]
