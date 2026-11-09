"""Reproducible benchmarks.  Run:  python benchmark/bench.py

A) incremental graph update vs full rebuild on a synthetic repo
B) test-selection strategies vs seeded regressions in the demo app (does the strategy still catch the bug?)
"""
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from reposhield import coverage_map                                    # noqa: E402
from reposhield.analyzer import ParseCache                              # noqa: E402
from reposhield.demo import DATA                                        # noqa: E402
from reposhield.gitutil import Change, DirTree                          # noqa: E402
from reposhield.graph import Graph                                      # noqa: E402
from reposhield.sandbox import Limits, SubprocessSandbox                # noqa: E402
from reposhield.selector import select_tests                            # noqa: E402


# ---------------------------------------------------------------- A
def bench_graph(n_files=2000, n_changed=5, seed=7):
    rng = random.Random(seed)
    root = tempfile.mkdtemp(prefix="rs-bench-")
    try:
        for i in range(n_files):
            pkg = f"p{i % 40}"
            deps = rng.sample(range(n_files), 5)
            body = "\n".join(f"from p{j % 40} import m{j}" for j in deps if j != i)
            body += "\n" + "\n".join(f"def f{k}(x):\n    return x + {k}\n" for k in range(12))
            os.makedirs(os.path.join(root, pkg), exist_ok=True)
            open(os.path.join(root, pkg, f"m{i}.py"), "w").write(body)
        tree = DirTree(root)
        t = time.perf_counter(); base = Graph.build(tree, ParseCache()); full_s = time.perf_counter() - t
        cache = ParseCache()
        Graph.build(tree, cache)                                          # warm content-addressed cache (what the base-graph cache provides)
        changed = {f"p{i % 40}/m{i}.py" for i in rng.sample(range(n_files), n_changed)}
        for p in changed:
            open(os.path.join(root, p), "a").write("\nCHANGED = True\n")
        inc = base.clone()
        t = time.perf_counter(); stats = inc.update(DirTree(root), changed, set(), cache); inc_s = time.perf_counter() - t
        t = time.perf_counter(); full2 = Graph.build(DirTree(root), ParseCache()); full2_s = time.perf_counter() - t
        assert inc.edge_set() == full2.edge_set(), "incremental graph differs from full rebuild!"
        return {"files": n_files, "edges": base.edge_count(), "changed": n_changed, "full_rebuild_s": round(full2_s, 3),
                "incremental_s": round(inc_s, 3), "speedup_x": round(full2_s / inc_s, 1), "parsed": stats["parsed"],
                "identical_to_full_rebuild": True}
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ---------------------------------------------------------------- B
MUTATIONS = [
    ("refund: drop over-refund guard", "payments/refund.py", '    if cents > remaining:\n        raise ValueError("cannot refund more than the original charge")\n', ""),
    ("refund: wrong ledger sign", "payments/refund.py", 'payment["account"], cents, "refund"', 'payment["account"], -cents, "refund"'),
    ("service: charge sign flipped", "payments/service.py", '-cents, "charge"', 'cents, "charge"'),
    ("money: float truncation", "common/money.py", "round(float(amount) * 100)", "int(float(amount) * 100)"),
    ("money: allow negatives", "common/money.py", '    if cents < 0:\n        raise ValueError("amount must not be negative")\n', ""),
    ("database: balance ignores credits", "payments/database.py", "if a == account)", "if a == account and c < 0)"),
    ("tokens: no expiry check", "auth/tokens.py", "    if (now if now is not None else time.time()) > int(exp):\n        return None\n", ""),
    ("tokens: signature not checked", "auth/tokens.py", "    if not hmac.compare_digest(expect, sig):\n        return None\n", ""),
    ("login: always true", "auth/login.py", "return hmac.compare_digest(hash_password(password, salt), expected)", "return True"),
    ("orders: ignores quantity", "orders/service.py", "price * qty for price, qty", "price for price, qty"),
    ("analytics: track is a no-op", "analytics/client.py", "    EVENTS.append({\"event\": event, **props})", "    pass"),
    ("routes: wrong status code", "api/routes.py", '"status": 201', '"status": 200'),
]


def failing_test_files(ws):
    coverage_map.install_plugin(ws)
    out = os.path.join(ws, ".reposhield", "out", "gt.json")
    SubprocessSandbox().run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "rs_pytest_plugin"], ws,
                            env={"RS_RESULT_PATH": ".reposhield/out/gt.json"}, limits=Limits(timeout_seconds=60))
    rep = json.load(open(out))
    return {n.split("::")[0] for n, r in rep["tests"].items() if r["outcome"] in ("failed", "error")}


def heuristic(changed_path, all_tests):
    stem = os.path.basename(changed_path)[:-3]
    return {t for t in all_tests if stem in os.path.basename(t)}


def bench_selection():
    work = tempfile.mkdtemp(prefix="rs-sel-")
    try:
        base_dir = os.path.join(work, "base")
        shutil.copytree(DATA, base_dir, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
        base = Graph.build(DirTree(base_dir))
        cov = coverage_map.collect(base_dir, SubprocessSandbox(), Limits(timeout_seconds=60))
        shutil.rmtree(os.path.join(base_dir, ".reposhield"), ignore_errors=True)
        all_tests = base.tests()
        rows, tot = [], {"full": [0, 0], "filename": [0, 0], "safe": [0, 0], "balanced": [0, 0]}
        for name, path, old, new in MUTATIONS:
            ws = os.path.join(work, "mut")
            shutil.rmtree(ws, ignore_errors=True)
            shutil.copytree(base_dir, ws)
            text = open(os.path.join(ws, path)).read()
            assert old in text, (name, "pattern missing")
            open(os.path.join(ws, path), "w").write(text.replace(old, new, 1))
            truth = failing_test_files(ws)
            assert truth, f"mutation '{name}' is not detectable by the suite"
            head = Graph.build(DirTree(ws))
            ch = [Change("M", path)]
            sel = {"full": set(all_tests), "filename": heuristic(path, all_tests),
                   "safe": {t.path for t in select_tests(head, base, ch, strategy="safe").tests},
                   "balanced": {t.path for t in select_tests(head, base, ch, strategy="balanced", coverage=cov).tests}}
            row = {"mutation": name}
            for k, v in sel.items():
                caught = bool(v & truth)
                tot[k][0] += len(v); tot[k][1] += caught
                row[k] = f"{len(v)}{'✓' if caught else '✗'}"
            rows.append(row)
        n = len(MUTATIONS)
        summary = {k: {"avg_tests": round(v[0] / n, 1), "caught": f"{v[1]}/{n}", "avg_reduction_pct": round(100 * (1 - v[0] / n / len(all_tests)), 1)} for k, v in tot.items()}
        return rows, summary, len(all_tests)
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    print("== A. graph: incremental vs full rebuild ==")
    a = bench_graph()
    print(json.dumps(a, indent=2))
    print("\n== B. test selection vs seeded regressions (✓ = bug caught by selected tests) ==")
    rows, summary, total = bench_selection()
    print(f"{'mutation':<36}{'full':>6}{'filename':>10}{'safe':>7}{'balanced':>10}   (tests selected of {total})")
    for r in rows:
        print(f"{r['mutation']:<36}{r['full']:>6}{r['filename']:>10}{r['safe']:>7}{r['balanced']:>10}")
    print(json.dumps(summary, indent=2))
    os.makedirs(os.path.join(os.path.dirname(__file__), "results"), exist_ok=True)
    json.dump({"graph": a, "selection": {"rows": rows, "summary": summary, "total_test_files": total}},
              open(os.path.join(os.path.dirname(__file__), "results", "latest.json"), "w"), indent=2)
