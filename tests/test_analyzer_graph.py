import os
import random
import shutil

from reposhield.analyzer import ParseCache, parse_source
from reposhield.gitutil import DirTree
from reposhield.graph import Graph


def write(root, files):
    for rel, text in files.items():
        full = os.path.join(root, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as fh:
            fh.write(text)


def build(tmp_path, files):
    write(str(tmp_path), files)
    return Graph.build(DirTree(str(tmp_path)))


def test_parse_tests_asserts_and_skips():
    pf = parse_source("tests/test_a.py", (
        b"import pytest\n"
        b"@pytest.mark.skip\ndef test_a():\n    assert 1\n"
        b"class TestB:\n    def test_c(self):\n        with pytest.raises(ValueError):\n            pass\n        assert True\n"), "x")
    names = {t.name: t for t in pf.tests}
    assert names["test_a"].skipped and names["test_a"].asserts == 1
    assert names["TestB::test_c"].asserts == 2 and not names["TestB::test_c"].skipped


def test_syntax_error_is_reported_not_raised():
    pf = parse_source("a.py", b"def (:\n", "x")
    assert not pf.ok and "SyntaxError" in pf.error


def test_import_resolution_relative_package_and_implicit(tmp_path):
    g = build(tmp_path, {
        "pkg/__init__.py": "", "pkg/a.py": "from . import b\nfrom .c import f\n", "pkg/b.py": "", "pkg/c.py": "def f(): pass\n",
        "top.py": "import pkg.b\nfrom pkg import a\n",
    })
    deps = {(e.dst, e.kind) for e in g.out["pkg/a.py"]}
    assert ("pkg/b.py", "import") in deps and ("pkg/c.py", "import") in deps
    top = {(e.dst, e.kind) for e in g.out["top.py"]}
    assert ("pkg/b.py", "import") in top and ("pkg/a.py", "import") in top
    assert ("pkg/__init__.py", "implicit") in top          # importing pkg.b runs pkg/__init__.py


def test_src_layout_roots(tmp_path):
    g = build(tmp_path, {"src/lib/__init__.py": "", "src/lib/x.py": "", "app.py": "import lib.x\n"})
    assert any(e.dst == "src/lib/x.py" for e in g.out["app.py"])


def test_dynamic_imports(tmp_path):
    g = build(tmp_path, {"a.py": "import importlib\nimportlib.import_module('b')\nimportlib.import_module(name)\n", "b.py": ""})
    assert any(e.dst == "b.py" and e.kind == "dynamic" and e.conf < 1 for e in g.out["a.py"])
    assert len(g.files["a.py"].dynamic) == 1               # the non-constant one stays UNKNOWN


def test_impact_is_reverse_reachability_with_paths(tmp_path):
    g = build(tmp_path, {"d.py": "", "c.py": "import d\n", "b.py": "import c\n", "a.py": "import b\n", "z.py": ""})
    imp = g.impact(["d.py"])
    assert set(imp) == {"d.py", "c.py", "b.py", "a.py"}
    assert imp["a.py"].via == ["d.py", "c.py", "b.py", "a.py"] and imp["a.py"].distance == 3


def _random_repo(rng, n):
    files = {}
    for i in range(n):
        deps = rng.sample(range(n), k=rng.randint(0, min(3, n)))
        lines = [f"import m{j}" if j != i else "" for j in deps]
        files[f"m{i}.py"] = "\n".join(lines) + f"\nVALUE = {i}\n"
    return files


def test_incremental_update_equals_full_rebuild_property(tmp_path):
    """For random edits (modify / add / delete), incremental == full rebuild, and only touched files are re-parsed."""
    for seed in range(15):
        rng = random.Random(seed)
        root = tmp_path / f"r{seed}"
        files = _random_repo(rng, 12)
        write(str(root), files)
        cache = ParseCache()
        g = Graph.build(DirTree(str(root)), cache)
        changed, removed = set(), set()
        for _ in range(rng.randint(1, 4)):
            op = rng.choice(["modify", "add", "delete"])
            live = sorted(set(files) - removed)
            if op == "modify" and live:
                p = rng.choice(live)
                write(str(root), {p: f"import m{rng.randint(0, 11)}\nX = {rng.random()}\n"})
                changed.add(p)
            elif op == "add" or not live:
                p = f"new{rng.randint(0, 99)}.py"
                write(str(root), {p: f"import m{rng.randint(0, 11)}\n"})
                changed.add(p)
            else:
                p = rng.choice(live)
                os.remove(root / p)
                removed.add(p)
                changed.discard(p)
        inc = g.clone()
        stats = inc.update(DirTree(str(root)), changed, removed, cache)
        full = Graph.build(DirTree(str(root)))
        assert inc.edge_set() == full.edge_set(), f"seed {seed}"
        assert set(inc.files) == set(full.files)
        assert stats["parsed"] <= len(changed)
